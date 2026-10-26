"""Chinese/identifier tokenizer and persistent posting-based BM25 (k1=1.2, b=.75)."""

import math
import re
from collections import Counter


def tokenize(text):
    """Split CamelCase/snake_case; Latin lower-case; Han unigrams and overlapping bigrams."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z])([A-Z][a-z])", r"\1 \2", text).lower().replace("_", " ")
    out = re.findall(r"[a-z0-9]+", text)
    for span in re.findall(r"[\u3400-\u9fff]+", text):
        out.extend(span)
        out.extend(span[i : i + 2] for i in range(len(span) - 1))
    return out


def add_document(db, n, text):
    """Update only a changed node's posting rows; df/length stats are derived in candidate."""
    terms = Counter(tokenize(text))
    db.execute("delete from postings where node_id=?", (n["node_id"],))
    db.execute("delete from lengths where node_id=?", (n["node_id"],))
    db.executemany(
        "insert into postings values(?,?,?)", [(t, n["node_id"], tf) for t, tf in terms.items()]
    )
    db.execute(
        "insert into lengths values(?,?,?,?)",
        (n["node_id"], n["repository"], n["kind"], sum(terms.values())),
    )


def rank(db, q, where, params, count):
    """Read matching postings only; filter candidates in SQL before ranking/limiting."""
    terms = set(tokenize(q))
    if not terms:
        return []
    total, avg = db.execute(
        "select count(*),avg(l.length) from lengths l join nodes n using(node_id) where " + where,
        params,
    ).fetchone()
    if not total:
        return []
    scores = {}
    # Corpus df is fixed per index version. Candidate filtering is exact before TopK.
    corpus = db.execute("select count(*) from lengths").fetchone()[0]
    for term in terms:
        df = db.execute("select df from terms where term=?", (term,)).fetchone()
        if not df:
            continue
        idf = math.log(1 + (corpus - df[0] + 0.5) / (df[0] + 0.5))
        for ident, tf, length in db.execute(
            "select p.node_id,p.tf,l.length from postings p join lengths l using(node_id) join nodes n using(node_id) where p.term=? and "
            + where,
            [term, *params],
        ):
            score = idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / (avg or 1)))
            scores[ident] = scores.get(ident, 0) + score
    return sorted(scores, key=lambda k: (-scores[k], k))[:count]
