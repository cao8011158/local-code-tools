"""Private, capture-bound AST evidence for owner-level graph updates.

The SQLite artifact is verified against its immutable manifest before this cache
is opened.  The digest of each captured source is checked again before an AST is
used.  An incompatible cache is never an incremental admission certificate.
"""

import ast
import base64
import json
import zlib

from .common import canonical, digest

SCHEMA = 1


def _encode_asts(asts):
    """Serialize syntax trees without executable object deserialization."""
    seen, objects = {}, []
    def encode(value):
        if isinstance(value, ast.AST):
            existing = seen.get(id(value))
            if existing is not None:
                return {"ref": existing}
            index = len(objects)
            seen[id(value)] = index
            objects.append(None)
            objects[index] = dict(type=type(value).__name__,
                                  fields={key: encode(item) for key, item in vars(value).items()})
            return {"ref": index}
        if isinstance(value, list):
            return {"list": [encode(item) for item in value]}
        if isinstance(value, tuple):
            return {"tuple": [encode(item) for item in value]}
        if isinstance(value, bytes):
            return {"bytes": base64.b64encode(value).decode("ascii")}
        if isinstance(value, complex):
            return {"complex": [value.real, value.imag]}
        if value is Ellipsis:
            return {"ellipsis": True}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise ValueError("unsupported AST constant")
    roots = {ident: encode(tree) for ident, tree in asts.items()}
    return zlib.compress(canonical(dict(roots=roots, objects=objects)).encode("utf-8"), 6)


def _decode_asts(payload):
    try:
        data = json.loads(zlib.decompress(payload))
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("previous-unit-ast-payload-invalid") from exc
    objects = data["objects"]
    if not isinstance(objects, list) or len(objects) > 1_000_000:
        raise ValueError("previous-unit-ast-size-invalid")
    cache = {}
    def decode(value):
        if not isinstance(value, dict):
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            raise ValueError("previous-unit-ast-value-invalid")
        if len(value) != 1:
            raise ValueError("previous-unit-ast-tag-invalid")
        if "ref" in value:
            index = value["ref"]
            if type(index) is not int or index < 0 or index >= len(objects):
                raise ValueError("previous-unit-ast-reference-invalid")
            if index in cache:
                return cache[index]
            entry = objects[index]
            cls = getattr(ast, entry["type"], None)
            if not isinstance(cls, type) or not issubclass(cls, ast.AST):
                raise ValueError("previous-unit-ast-type-invalid")
            obj = cls.__new__(cls)
            cache[index] = obj
            for key, item in entry["fields"].items():
                if not isinstance(key, str) or key.startswith("__"):
                    raise ValueError("previous-unit-ast-field-invalid")
                setattr(obj, key, decode(item))
            return obj
        if "list" in value:
            return [decode(item) for item in value["list"]]
        if "tuple" in value:
            return tuple(decode(item) for item in value["tuple"])
        if "bytes" in value:
            return base64.b64decode(value["bytes"], validate=True)
        if "complex" in value:
            return complex(*value["complex"])
        if "ellipsis" in value and value["ellipsis"] is True:
            return Ellipsis
        raise ValueError("previous-unit-ast-tag-invalid")
    if not isinstance(data["roots"], dict):
        raise ValueError("previous-unit-ast-roots-invalid")
    return {ident: decode(ref) for ident, ref in data["roots"].items()}


def save(db, asts, nodes):
    """Persist the complete AST map, including shared module/definition objects."""
    db.execute("create table unit_ast_cache(schema integer not null, payload blob not null)")
    if asts is None:
        return False
    sources = {(n["repository"], n["path"]): n["source_sha256"] for n in nodes
               if n["kind"] == "module" and n["path"].endswith(".py")}
    modules = {k: t for k, t in asts.items() if isinstance(t, ast.Module)}
    byid = {n["node_id"]: n for n in nodes}
    if len(modules) != len(sources) or any(
            k not in byid or (byid[k]["repository"], byid[k]["path"]) not in sources
            for k in modules):
        return False
    try:
        payload = _encode_asts(asts)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False  # full graph still publishes; this capture is not reusable
    db.execute("insert into unit_ast_cache values(?,?)", (SCHEMA, payload))
    return True


def load(db, old_nodes, old_sources):
    """Return the old AST map only after source and definition identity checks."""
    row = db.execute("select schema,payload from unit_ast_cache").fetchone()
    if row is None or row[0] != SCHEMA:
        raise ValueError("previous-unit-ast-schema-unavailable")
    trees = _decode_asts(row[1])
    if not isinstance(trees, dict) or set(trees) != {
            ident for ident, n in old_nodes.items() if n["kind"] in ("module", "class", "function")
            and n["path"].endswith(".py")}:
        raise ValueError("previous-unit-ast-catalog-mismatch")
    children = {}
    for ident, n in old_nodes.items():
        if ident in trees and n["kind"] != "module":
            children.setdefault(n["module"], []).append(trees[ident])
    for ident, tree in trees.items():
        if not isinstance(tree, ast.AST):
            raise ValueError("previous-unit-ast-invalid")
        n = old_nodes[ident]
        if n["kind"] != "module":
            continue
        key = n["repository"], n["path"]
        source = old_sources.get(key)
        if (source is None or n["source_sha256"] != digest(source)
                or getattr(tree, "_lct_source", None) != source):
            raise ValueError("previous-unit-ast-source-mismatch")
        members = {id(obj) for obj in ast.walk(tree)}
        if any(id(candidate) not in members for candidate in children.get(ident, ())):
            raise ValueError("previous-unit-ast-shared-identity-mismatch")
    return trees


def has_parameters(tree):
    """Inspect the actual definition, including default calls and kw-only args."""
    if not isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return True  # missing evidence must never exclude a parameter source
    args = tree.args
    return bool(args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg)


def save_owner_observations(db, reads, watches, inputs):
    """Actual owner-specific analysis inputs; no inferred dependency closure."""
    db.execute("create table unit_analysis_reads(owner text not null,consumer text not null,producer text not null,kind text not null,primary key(owner,consumer,producer,kind))")
    db.execute("create index unit_analysis_read_producer on unit_analysis_reads(producer,owner)")
    db.execute("create table unit_analysis_watches(owner text not null,consumer text not null,kind text not null,universe text not null,primary key(owner,consumer,kind,universe))")
    db.execute("create index unit_analysis_watch_kind on unit_analysis_watches(kind,owner)")
    db.execute("create table unit_input_events(owner text not null,consumer text not null,component text not null,purpose text not null,primary key(owner,consumer,component,purpose))")
    db.executemany("insert into unit_analysis_reads values(?,?,?,?)", sorted(reads))
    db.executemany("insert into unit_analysis_watches values(?,?,?,?)", sorted(watches))
    db.executemany("insert into unit_input_events values(?,?,?,?)", (
        (owner, consumer, canonical(component), purpose)
        for owner, consumer, component, purpose in sorted(inputs)))


def load_owner_observations(db):
    reads = set(db.execute("select owner,consumer,producer,kind from unit_analysis_reads"))
    watches = set(db.execute("select owner,consumer,kind,universe from unit_analysis_watches"))
    inputs = {(owner, consumer, tuple(json.loads(component)), purpose)
              for owner, consumer, component, purpose in db.execute(
                  "select owner,consumer,component,purpose from unit_input_events")}
    return reads, watches, inputs

