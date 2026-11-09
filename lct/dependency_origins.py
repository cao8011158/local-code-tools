"""Private, source-located observations for future owner invalidation.

Rows retain candidates and uncertainty from the current analyzer. They are not
a proof that every Jedi or dynamic Python input has been enumerated.
"""

import json
from fractions import Fraction

from .common import canonical, digest

SCHEMA = 2
COVERAGE = "jedi-source-sites-partial"
# Source facts, not callable-target search work. The pinned 83-file capture
# produced 24,822 distinct facts; keep a bounded capacity above that measured
# inventory while retaining explicit truncation and failed update semantics.
LIMIT = 32768
_UNSET = object()


def key_identity(value):
    """Canonicalize only primitive keys whose equality is known without code."""
    if isinstance(value, str):
        return "string:" + value
    if value is None:
        return "none"
    if isinstance(value, (bool, int, float)):
        try:
            number = Fraction(value)
        except (ValueError, OverflowError, ZeroDivisionError):
            return None
        return f"number:{number.numerator}/{number.denominator}"
    return None


def save(db, supports, subscriptions, writes, nodes, *, available=True,
         truncated=False):
    """Validate endpoints before publishing immutable, indexed observations."""
    db.execute("create table unit_source_supports(id text primary key,producer_owner text not null,producer_site text not null,consumer_owner text not null,consumer_site text not null,kind text not null,status text not null,data text not null)")
    db.execute("create index unit_source_producer on unit_source_supports(producer_owner,producer_site,consumer_owner)")
    db.execute("create index unit_source_consumer on unit_source_supports(consumer_owner,consumer_site,kind)")
    db.execute("create table unit_container_subscriptions(id text primary key,origin text not null,key_kind text not null,key text,read_owner text not null,read_site text not null,consumer_owner text not null,consumer_site text not null,data text not null)")
    db.execute("create index unit_container_reader on unit_container_subscriptions(origin,key_kind,key,consumer_owner,consumer_site)")
    db.execute("create index unit_container_consumer on unit_container_subscriptions(consumer_owner,consumer_site)")
    db.execute("create table unit_container_writes(id text primary key,origin text not null,key_kind text not null,key text,producer_owner text not null,producer_site text not null,data text not null)")
    db.execute("create index unit_container_writer on unit_container_writes(origin,key_kind,key,producer_owner,producer_site)")
    if not available or truncated:
        return dict(schema=SCHEMA, coverage="unavailable", truncated=bool(truncated),
                    support_count=0, subscription_count=0, write_count=0)
    byid = {n["node_id"] for n in nodes}
    if len(supports) + len(subscriptions) + len(writes) > LIMIT:
        return dict(schema=SCHEMA, coverage="unavailable", truncated=True,
                    support_count=0, subscription_count=0, write_count=0)
    for record in supports:
        if (record["producer_owner"] not in byid or record["consumer_owner"] not in byid
                or record["status"] not in {"observed", "candidate", "unknown"}):
            raise ValueError("Invalid source support endpoint")
        raw = canonical(record)
        db.execute("insert or ignore into unit_source_supports values(?,?,?,?,?,?,?,?)", (
            digest(raw), record["producer_owner"], record["producer_site"],
            record["consumer_owner"], record["consumer_site"], record["kind"],
            record["status"], raw))
    for record in subscriptions:
        if (record["read_owner"] not in byid or record["consumer_owner"] not in byid
                or record["key_kind"] not in {"exact", "range"}):
            raise ValueError("Invalid container subscription endpoint")
        raw = canonical(record)
        db.execute("insert or ignore into unit_container_subscriptions values(?,?,?,?,?,?,?,?,?)", (
            digest(raw), record["origin"], record["key_kind"], record["key"],
            record["read_owner"], record["read_site"], record["consumer_owner"],
            record["consumer_site"], raw))
    for record in writes:
        if (record["producer_owner"] not in byid or
                record["key_kind"] not in {"exact", "range"}):
            raise ValueError("Invalid container write endpoint")
        raw = canonical(record)
        db.execute("insert or ignore into unit_container_writes values(?,?,?,?,?,?,?)", (
            digest(raw), record["origin"], record["key_kind"], record["key"],
            record["producer_owner"], record["producer_site"], raw))
    return dict(schema=SCHEMA, coverage=COVERAGE, truncated=False,
                support_count=db.execute("select count(*) from unit_source_supports").fetchone()[0],
                subscription_count=db.execute("select count(*) from unit_container_subscriptions").fetchone()[0],
                write_count=db.execute("select count(*) from unit_container_writes").fetchone()[0])


def verify(db, manifest):
    if (manifest.get("origin_dependency_schema") != SCHEMA or
            manifest.get("origin_dependency_coverage") != COVERAGE or
            manifest.get("origin_dependency_truncated")):
        return False
    for table, indexes, columns, count in (
            ("unit_source_supports", {"unit_source_producer", "unit_source_consumer"},
             {"id", "producer_owner", "producer_site", "consumer_owner", "consumer_site",
              "kind", "status", "data"}, "origin_support_count"),
            ("unit_container_subscriptions", {"unit_container_reader", "unit_container_consumer"},
             {"id", "origin", "key_kind", "key", "read_owner", "read_site",
              "consumer_owner", "consumer_site", "data"}, "origin_subscription_count"),
            ("unit_container_writes", {"unit_container_writer"},
             {"id", "origin", "key_kind", "key", "producer_owner", "producer_site", "data"},
             "origin_write_count")):
        if (type(manifest.get(count)) is not int or
                not indexes <= {r[1] for r in db.execute(f"pragma index_list('{table}')")} or
                not columns <= {r[1] for r in db.execute(f"pragma table_info('{table}')")} or
                db.execute(f"select count(*) from {table}").fetchone()[0] != manifest[count]):
            return False
    return True


def sources(db, consumer_owner, consumer_site=None, limit=100, max_bytes=100000):
    if not 1 <= limit <= 100:
        raise ValueError("source limit outside 1..100")
    if not 1 <= max_bytes <= 1_000_000:
        raise ValueError("source evidence byte budget exceeded")
    where = "consumer_owner=?" + (" and consumer_site=?" if consumer_site is not None else "")
    args = (consumer_owner,) if consumer_site is None else (consumer_owner, consumer_site)
    identified = db.execute("select id,length(cast(data as blob)) "
                      "from unit_source_supports where " + where +
                      " order by consumer_site,kind,producer_owner,producer_site,id limit ?",
                      (*args, limit + 1)).fetchall()
    if sum(size for _, size in identified[:limit]) > max_bytes:
        raise ValueError("source evidence byte budget exceeded")
    ids = [ident for ident, _ in identified[:limit]]
    if not ids:
        return dict(supports=[], has_more=False)
    rows = db.execute("select id,producer_owner,producer_site,consumer_owner,consumer_site,"
                      "kind,status,data from unit_source_supports where id in (" +
                      ",".join("?" for _ in ids) + ")", ids).fetchall()
    by_id = {row[0]: row[1:] for row in rows}
    decoded = []
    for ident in ids:
        row = by_id[ident]
        record = json.loads(row[-1])
        if tuple(record.get(k) for k in ("producer_owner", "producer_site", "consumer_owner",
                                          "consumer_site", "kind", "status")) != row[:-1]:
            raise ValueError("Source support row mismatch")
        decoded.append(record)
    return dict(supports=decoded, has_more=len(identified) > limit)


def readers(db, producer_owner, producer_site=None):
    if producer_site is None:
        rows = db.execute("select distinct consumer_owner,consumer_site from unit_source_supports "
                          "where producer_owner=?", (producer_owner,))
    else:
        rows = db.execute("select distinct consumer_owner,consumer_site from unit_source_supports "
                          "where producer_owner=? and producer_site=?",
                          (producer_owner, producer_site))
    return {tuple(row) for row in rows}


def container_readers(db, origin, key=_UNSET):
    """Return every consumer of the same origin; key relation is explanatory.

    The current analyzer does not prove exclusion of another key's conditional
    or dynamic writer, so a scheduler must not use an exact key to drop readers.
    """
    identity = key_identity(key) if key is not _UNSET else None
    rows = db.execute("select origin,key_kind,key,read_owner,read_site,consumer_owner,consumer_site,data "
                      "from unit_container_subscriptions where origin=?",
                      (origin,))
    result = []
    for row in rows:
        record = json.loads(row[-1])
        if tuple(record.get(k) for k in ("origin", "key_kind", "key", "read_owner", "read_site",
                                          "consumer_owner", "consumer_site")) != row[:-1]:
            raise ValueError("Container subscription row mismatch")
        if key is not _UNSET:
            record["key_relation"] = ("same" if identity is not None and
                                      record["key_kind"] == "exact" and
                                      record["key"] == identity else
                                      "range" if record["key_kind"] == "range" else
                                      "other-conservative")
        result.append(record)
    return result


def container_writes(db, origin, key=_UNSET):
    if key is _UNSET:
        rows = db.execute("select origin,key_kind,key,producer_owner,producer_site,data "
                          "from unit_container_writes where origin=?", (origin,))
    else:
        identity = key_identity(key)
        if identity is None:
            raise ValueError("Unsupported exact container key")
        rows = db.execute("select origin,key_kind,key,producer_owner,producer_site,data "
                          "from unit_container_writes where origin=? "
                          "and ((key_kind='exact' and key=?) or key_kind='range')",
                          (origin, identity))
    result = []
    for row in rows:
        record = json.loads(row[-1])
        if tuple(record.get(k) for k in ("origin", "key_kind", "key", "producer_owner",
                                          "producer_site")) != row[:-1]:
            raise ValueError("Container writer row mismatch")
        result.append(record)
    return result
