"""Real Voyage embeddings with compatible content keys, durable budget and finite retries."""

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from .common import ToolError, atomic, digest, load, lock


def vector_key(e, text, kind):
    """Preserve historical key serialization exactly; templates are already in text hash."""
    return digest(json.dumps([e["model"], e["dimension"], e["dtype"], kind, False, digest(text)]))


def bound(text):
    """Conservative UTF-8 byte bound plus input-type prefix; not exact tokenizer usage."""
    return len(text.encode()) + 64


class Embeddings:
    """SQLite cache is shared across versions; network reservations survive unknown outcomes."""

    def __init__(self, c):
        self.e = c["embedding"]
        self.data = Path(c["data"])
        self.data.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data / "vectors.sqlite", timeout=30)
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute(
            "create table if not exists vectors (key text primary key, kind text, vector blob, origin text, used_at real)"
        )
        self.db.commit()
        self.hits = 0
        self.historical_hits = 0
        self.new_vectors = 0
        self.requests = 0

    def close(self):
        self.db.close()

    def valid(self, values):
        """Reject invalid provider/cache payloads; never fabricate replacement vectors."""
        a = np.asarray(values, dtype=np.float32)
        if a.shape != (self.e["dimension"],) or not np.isfinite(a).all() or np.linalg.norm(a) == 0:
            raise ToolError("Invalid embedding vector")
        return a

    def lookup(self, text, kind):
        """Reuse only identical model/dimension/dtype/input_type/truncation/text content."""
        key = vector_key(self.e, text, kind)
        row = self.db.execute("select vector from vectors where key=?", (key,)).fetchone()
        if row:
            self.hits += 1
            return self.valid(np.frombuffer(row[0], dtype=np.float32))
        old = Path(self.e.get("historical_cache", "__no_cache__")) / (key + ".json")
        if old.is_file():
            a = self.valid(load(old))
            self.db.execute(
                "insert or ignore into vectors values(?,?,?,?,?)",
                (key, kind, a.tobytes(), "historical-compatible", time.time()),
            )
            self.db.commit()
            self.historical_hits += 1
            return a
        return None

    def ledger(self):
        """A single tool-wide ledger covers document and query API usage."""
        p = self.data / "ledger.json"
        return (
            load(p)
            if p.exists()
            else {
                "attempts": 0,
                "reserved_tokens": 0,
                "usage_tokens": 0,
                "successes": 0,
                "errors": [],
            }
        )

    def call(self, texts, kind):
        """Only 429/5xx are retried, with budget reserved before every HTTP attempt."""
        secret = os.environ.get("VOYAGE_API_KEY")
        if not secret:
            raise ToolError(
                "VOYAGE_API_KEY unavailable; set it in process environment, never in config"
            )
        if any(bound(t) > 32000 for t in texts):
            raise ToolError("Input exceeds explicit conservative 32K byte budget")
        payload = json.dumps(
            dict(
                input=texts,
                model=self.e["model"],
                input_type=kind,
                output_dimension=self.e["dimension"],
                output_dtype=self.e["dtype"],
                truncation=False,
            )
        ).encode()
        for attempt in range(self.e["retries"] + 1):
            ledger = self.ledger()
            reservation = sum(bound(t) for t in texts)
            nxt = ledger["reserved_tokens"] + reservation
            if (
                ledger["attempts"] >= self.e["max_requests"]
                or nxt > self.e["max_estimated_tokens"]
                or nxt * self.e["price_per_million_usd"] / 1e6 > self.e["max_cost_usd"]
            ):
                raise ToolError(
                    "Inherited API request/token/cost ceiling reached; completed cache remains resumable"
                )
            delay = self.e["min_interval_seconds"] - (
                time.time() - ledger.get("last_attempt_epoch", 0)
            )
            if delay > 0:
                time.sleep(delay)
            ledger["attempts"] += 1
            ledger["reserved_tokens"] = nxt
            ledger["last_attempt_epoch"] = time.time()
            atomic(self.data / "ledger.json", ledger)
            self.requests += 1
            req = urllib.request.Request(
                self.e["endpoint"],
                data=payload,
                headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    raw = json.loads(response.read())
            except urllib.error.HTTPError as exc:
                code = exc.code
                body = exc.read().decode(errors="replace").lower()
                billing = any(
                    s in body
                    for s in (
                        "insufficient credit",
                        "insufficient balance",
                        "payment required",
                        "billing_error",
                        "quota exhausted",
                        "credits exhausted",
                    )
                )
                ledger["errors"].append(
                    {"http_status": code, "billing": billing, "outcome_unknown": code >= 500}
                )
                atomic(self.data / "ledger.json", ledger)
                if billing or code not in (429, 500, 502, 503, 504) or attempt == self.e["retries"]:
                    raise ToolError(
                        f"Voyage HTTP {code}; stopped, budget reservation retained"
                    ) from None
                time.sleep(min(2 ** (attempt + 1), 16))
                continue
            except (urllib.error.URLError, TimeoutError, OSError):
                ledger["errors"].append({"transport_error": True, "outcome_unknown": True})
                atomic(self.data / "ledger.json", ledger)
                raise ToolError(
                    "Embedding transport failed; outcome unknown and reservation retained"
                ) from None
            if raw.get("model") != self.e["model"]:
                raise ToolError("Embedding response model mismatch")
            rows = sorted(raw.get("data", []), key=lambda r: r["index"])
            if [r["index"] for r in rows] != list(range(len(texts))):
                raise ToolError("Incomplete embedding response")
            vectors = [self.valid(r["embedding"]) for r in rows]
            ledger["usage_tokens"] += int(raw["usage"]["total_tokens"])
            ledger["successes"] += 1
            atomic(self.data / "ledger.json", ledger)
            for text, a in zip(texts, vectors):
                self.db.execute(
                    "insert or replace into vectors values(?,?,?,?,?)",
                    (vector_key(self.e, text, kind), kind, a.tobytes(), "voyage-api", time.time()),
                )
            self.db.commit()
            self.new_vectors += len(texts)
            return vectors

    def get_many(self, texts, kind="document", offline=False):
        """Deduplicate inputs; persist each completed batch before requesting the next."""
        with lock(self.data / "embedding.lock"):
            found = {}
            for text in dict.fromkeys(texts):
                v = self.lookup(text, kind)
                if v is not None:
                    found[text] = v
            missing = [t for t in dict.fromkeys(texts) if t not in found]
            if missing and offline:
                raise ToolError("Dense cache missing in offline mode")
            ledger = self.ledger()
            total = ledger["reserved_tokens"] + sum(bound(t) for t in missing)
            if (
                total > self.e["max_estimated_tokens"]
                or total * self.e["price_per_million_usd"] / 1e6 > self.e["max_cost_usd"]
            ):
                raise ToolError("Preflight missing-input estimate exceeds inherited budget")
            batch, size = [], 0
            for text in missing + [None]:
                if batch and (
                    text is None
                    or size + bound(text) > self.e["batch_bytes"]
                    or len(batch) >= self.e["batch_items"]
                ):
                    vectors = self.call(batch, kind)
                    found.update(zip(batch, vectors))
                    print(
                        f"Embedding cached: {self.new_vectors} new vectors, {self.requests} requests",
                        file=__import__("sys").stderr,
                        flush=True,
                    )
                    batch, size = [], 0
                if text is not None:
                    batch.append(text)
                    size += bound(text)
            return [found[t] for t in texts]
