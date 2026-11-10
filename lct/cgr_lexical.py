"""Incremental local BM25 indexes for graph nodes and Markdown sections."""

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

from markdown_it import MarkdownIt

CATEGORIES = ("contract", "implementation", "history", "experiment")
MARKDOWN = MarkdownIt("commonmark")


def digest(data):
    """Return a content fingerprint for bytes or UTF-8 text."""
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def tokens(value):
    """Split identifiers and emit Chinese characters and adjacent pairs."""
    value = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).lower()
    for word in re.findall(r"[\u3400-\u9fff]+|[^\W_\u3400-\u9fff]+", value):
        if "\u3400" <= word[0] <= "\u9fff":
            yield from word
            yield from (a + b for a, b in zip(word, word[1:]))
        else:
            yield word


def connect(path):
    """Open the supplement database and ensure its tables exist."""
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS publication (
            project TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entry (
            rowid INTEGER PRIMARY KEY,
            project TEXT NOT NULL, key TEXT NOT NULL, node_id INTEGER,
            path TEXT NOT NULL, fingerprint TEXT NOT NULL, metadata TEXT NOT NULL,
            UNIQUE(project, key), UNIQUE(project, node_id)
        );
        CREATE INDEX IF NOT EXISTS entry_path ON entry(project, path);
        CREATE VIRTUAL TABLE IF NOT EXISTS terms USING fts5(words);
        CREATE TABLE IF NOT EXISTS doc_file (
            path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL
        );
    """)
    return db


def publish(db, project, state, detail):
    """Persist readiness with the caller's transaction."""
    db.execute(
        "INSERT OR REPLACE INTO publication VALUES (?, ?, ?)",
        (project, state, json.dumps(detail, ensure_ascii=False)),
    )


def require_ready(db, projects):
    """Return publication details or reject unpublished refresh batches."""
    published = []
    for project in projects:
        row = db.execute(
            "SELECT state, detail FROM publication WHERE project=?", (project,)
        ).fetchone()
        if row is None or row["state"] != "ready":
            detail = row["detail"] if row else "run refresh_index"
            raise RuntimeError(f"{project} unavailable: {detail}")
        published.append(json.loads(row["detail"]))
    return published


def sync_entries(db, project, records, path=None):
    """Update only inserted, changed, relocated and deleted entries."""
    scope = "project=?" if path is None else "project=? AND path=?"
    params = (project,) if path is None else (project, path)
    previous = {row["key"]: row for row in db.execute(f"SELECT * FROM entry WHERE {scope}", params)}
    counts = dict(inserted=0, replaced=0, relocated=0, deleted=0)
    for key, old in previous.items():
        if key not in records:
            db.execute("DELETE FROM terms WHERE rowid=?", (old["rowid"],))
            db.execute("DELETE FROM entry WHERE rowid=?", (old["rowid"],))
            counts["deleted"] += 1
        elif old["node_id"] != records[key][0]:
            db.execute("UPDATE entry SET node_id=NULL WHERE rowid=?", (old["rowid"],))
    for key, (node_id, file, content, metadata) in records.items():
        fingerprint = digest(content)
        encoded = json.dumps(metadata, ensure_ascii=False)
        old = previous.get(key)
        fields = (node_id, file, fingerprint, encoded)
        if old is None:
            rowid = db.execute(
                "INSERT INTO entry(project,key,node_id,path,fingerprint,metadata) VALUES (?,?,?,?,?,?)",
                (project, key, *fields),
            ).lastrowid
            db.execute(
                "INSERT INTO terms(rowid, words) VALUES (?,?)",
                (rowid, " ".join(tokens(content))),
            )
            counts["inserted"] += 1
        elif fields != (old["node_id"], old["path"], old["fingerprint"], old["metadata"]):
            db.execute(
                "UPDATE entry SET node_id=?,path=?,fingerprint=?,metadata=? WHERE rowid=?",
                (*fields, old["rowid"]),
            )
            if old["fingerprint"] != fingerprint:
                db.execute(
                    "UPDATE terms SET words=? WHERE rowid=?",
                    (" ".join(tokens(content)), old["rowid"]),
                )
                counts["replaced"] += 1
            else:
                counts["relocated"] += 1
    return counts


def candidates(db, query, limit, projects, category=None):
    """Rank matching terms within the allowed projects and optional category."""
    match = " OR ".join(f'"{token}"' for token in dict.fromkeys(tokens(query)))
    if not match:
        return []
    params = [match, *projects]
    placeholders = ",".join("?" for _ in projects)
    where = f"terms MATCH ? AND e.project IN ({placeholders})"
    if category is not None:
        where += " AND json_extract(e.metadata, '$.category')=?"
        params.append(category)
    return db.execute(
        f"""SELECT e.project, e.node_id, e.metadata, bm25(terms) AS score
            FROM terms JOIN entry e ON e.rowid=terms.rowid WHERE {where}
            ORDER BY score, e.rowid LIMIT ?""",
        (*params, limit),
    ).fetchall()


def category_for(path):
    """Match the previous local tool's category precedence for DOC."""
    lower = path.lower()
    if any(word in lower for word in ("experiment", "ablation")):
        return "experiment"
    if any(word in lower for word in ("review", "progress", "acceptance", "changelog")):
        return "history"
    return "contract" if path.startswith("docs/") else "implementation"


def sections(path, source):
    """Split Markdown by CommonMark headings, preserving source line ranges."""
    lines = source.splitlines(keepends=True)
    headings = [(0, 0, 0, "(preamble)")]
    parsed = MARKDOWN.parse(source)
    for index, token in enumerate(parsed):
        if token.type == "heading_open" and token.level == 0:
            headings.append((*token.map, int(token.tag[1]), parsed[index + 1].content))
    stack = []
    counts = Counter()
    records = {}
    for index, (start, excerpt_start, level, title) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(lines)
        if start == end:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        hierarchy = tuple(heading for _, heading in stack) + (title,)
        counts[hierarchy] += 1
        key = json.dumps([path, hierarchy, counts[hierarchy]], ensure_ascii=False)
        body = "".join(lines[start:end]).strip()
        excerpt = "".join(lines[excerpt_start:end]).strip()[:700]
        records[key] = (
            None,
            path,
            " ".join(hierarchy) + "\n" + body,
            {
                "file": path,
                "heading_path": hierarchy,
                "category": category_for(path),
                "start_line": start + 1,
                "end_line": end,
                "excerpt": excerpt,
            },
        )
        if level:
            stack.append((level, title))
    return records


def markdown_files(repo):
    """Read the DOC root and docs/ scope, including uncommitted files."""
    root = repo.path
    for path in sorted(root.glob("*.md")):
        if path.is_file() and not path.is_symlink() and path.name not in repo.exclude:
            yield path
    if not (root / "docs").is_dir() or (root / "docs").is_symlink():
        return
    for parent, dirs, names in os.walk(root / "docs", onerror=_raise):
        dirs[:] = sorted(
            d for d in dirs if d not in repo.exclude_dirs and not (Path(parent) / d).is_symlink()
        )
        for name in sorted(names):
            path = Path(parent) / name
            if (
                name.endswith(".md")
                and not path.is_symlink()
                and path.relative_to(root).as_posix() not in repo.exclude
            ):
                yield path


def _raise(error):
    """Stop a refresh if walking an indexed directory fails."""
    raise error


def refresh_docs(db, project, repo):
    """Replace only records belonging to changed Markdown files."""
    old = dict(db.execute("SELECT path, fingerprint FROM doc_file"))
    seen = set()
    changed = Counter()
    files = Counter()
    for file in markdown_files(repo):
        path = file.relative_to(repo.path).as_posix()
        data = file.read_bytes()
        fingerprint = digest(data)
        seen.add(path)
        if old.get(path) == fingerprint:
            continue
        files["modified" if path in old else "added"] += 1
        changed.update(sync_entries(db, project, sections(path, data.decode("utf-8-sig")), path))
        db.execute("INSERT OR REPLACE INTO doc_file VALUES (?,?)", (path, fingerprint))
    for path in old.keys() - seen:
        files["deleted"] += 1
        changed.update(sync_entries(db, project, {}, path))
        db.execute("DELETE FROM doc_file WHERE path=?", (path,))
    return {
        "files": len(seen),
        "sections": db.execute("SELECT count(*) FROM entry WHERE project=?", (project,)).fetchone()[
            0
        ],
        "file_changes": dict(files),
        "section_changes": dict(changed),
    }
