"""Read-only acceptance adapter: use existing vectors, refuse missing inputs and all APIs.

This does not change stored data, normalization, ranking, filters or paging. It
replaces cache I/O only in the validation process, not in production source files.
"""

import contextlib
import sqlite3
from pathlib import Path

import numpy as np

from lct.common import ToolError
from lct.embedding import Embeddings, vector_key


@contextlib.contextmanager
def readonly_embeddings():
    """Give CLI/MCP test processes a SQLite mode=ro cache and no network fallback."""
    original = (Embeddings.__init__, Embeddings.get_many, Embeddings.call)

    def init(self, c):
        self.e = c["embedding"]
        self.data = Path(c["data"])
        self.db = sqlite3.connect((self.data / "vectors.sqlite").as_uri() + "?mode=ro", uri=True)
        self.hits = self.historical_hits = self.new_vectors = self.requests = 0

    def many(self, texts, kind="document", offline=False):
        values = []
        for text in texts:
            row = self.db.execute(
                "select vector from vectors where key=?", (vector_key(self.e, text, kind),)
            ).fetchone()
            if row is None:
                raise ToolError(
                    "Read-only validation: required cached vector missing; no API allowed"
                )
            values.append(self.valid(np.frombuffer(row[0], dtype=np.float32)))
            self.hits += 1
        return values

    def denied(*args, **kwargs):
        raise AssertionError("Embedding API forbidden during source-only publication")

    Embeddings.__init__, Embeddings.get_many, Embeddings.call = init, many, denied
    try:
        yield
    finally:
        Embeddings.__init__, Embeddings.get_many, Embeddings.call = original
