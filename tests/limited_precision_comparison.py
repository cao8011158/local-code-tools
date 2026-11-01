"""Strict refinement oracle for a budget-limited cold analysis.

This deliberately does not change the general semantic comparison contract.
Additional facts must be independently supported by captured source and by an
existing propagated unknown-container read. Missing facts are never accepted.
"""

import ast
import json

from lct.common import canonical, digest
from tests.semantic_comparison import EXECUTION_LEDGER, _site


def _objects(rows):
    return {row[0]: json.loads(row[4]) for row in rows}


def _eager_annotation(edge, nodes, sources):
    if edge[3:5] != ("REFERENCES", "resolved"):
        return False
    fact = json.loads(edge[-1])
    source, target = nodes.get(edge[1]), nodes.get(edge[2])
    if not source or not target or fact.get("basis") != "AST value reference; never implies invocation":
        return False
    if fact.get("phase") != "annotation" or fact.get("expression") != target.get("name"):
        return False
    if (source.get("kind") != "class" or target.get("kind") != "class"
            or source.get("path") != target.get("path")
            or source.get("repository") != target.get("repository")):
        return False
    if fact.get("source_version_id") != source.get("version_id") or fact.get("target_version_id") != target.get("version_id"):
        return False
    content = sources.get((source["repository"], source["path"]))
    if content is None:
        return False
    tree = ast.parse(content)
    if any(isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
           and any(alias.name == "annotations" for alias in stmt.names) for stmt in tree.body):
        return False
    # This is an intentionally small proof for a directly bound module class.
    # A later same-name definition, import, or assignment cannot be treated as
    # the annotation's binding merely because it has matching source text.
    definitions = [stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)
                   and stmt.name == target["name"]]
    if (len(definitions) != 1 or definitions[0].lineno != target["definition_line"]
            or target["definition_line"] >= source["definition_line"]):
        return False
    for stmt in tree.body:
        if stmt.lineno >= source["definition_line"]:
            break
        if stmt is definitions[0]:
            continue
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if isinstance(stmt, ast.ImportFrom) and any(alias.name == "*" for alias in stmt.names):
                return False
            if any((alias.asname or alias.name.split(".")[0]) == target["name"]
                   for alias in stmt.names):
                return False
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == target["name"]:
            return False
        if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            if any(isinstance(name, ast.Name) and name.id == target["name"]
                   for assignment in targets for name in ast.walk(assignment)):
                return False
    owners = [stmt for stmt in tree.body if isinstance(stmt, ast.ClassDef)
              and stmt.name == source["name"] and stmt.lineno == source["definition_line"]]
    if len(owners) != 1:
        return False
    for statement in owners[0].body:
        annotation = statement.annotation if isinstance(statement, ast.AnnAssign) else None
        if (isinstance(annotation, ast.Name) and annotation.id == target["name"]
                and annotation.lineno == fact.get("line")
                and annotation.col_offset == fact.get("column")):
            return True
        # Only a docstring or pass is known to leave this class body's name
        # binding untouched. Refuse complex earlier statements conservatively.
        if not (isinstance(statement, ast.Pass) or
                (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                 and isinstance(statement.value.value, str))):
            return False
    return False


def _direct_open_input(subscription, existing, nodes, sources):
    fact = json.loads(subscription[-1])
    if (fact.get("origin") != "unknown-container-universe"
            or fact.get("key_kind") != "range" or fact.get("key") is not None
            or "open-project-input" not in fact.get("unknown_reasons", ())
            or fact.get("consumer_owner") != fact.get("read_owner")
            or fact.get("consumer_location") != fact.get("read_location")):
        return False
    location = fact["read_location"]
    if not any((other.get("origin") == fact["origin"]
                and other.get("key_kind") == fact["key_kind"]
                and other.get("read_owner") == fact["read_owner"]
                and other.get("read_site") == fact["read_site"]
                and other.get("read_location") == location
                and other.get("unknown_reasons") == fact["unknown_reasons"])
               for other in existing):
        return False
    content = sources.get((location["repository"], location["path"]))
    if content is None:
        return False
    owner = nodes.get(fact["read_owner"])
    if (not owner or owner.get("repository") != location["repository"]
            or owner.get("path") != location["path"]
            or not owner.get("definition_line", 0) <= location["line"]
            or location["line"] > owner.get("end", location["line"])):
        return False
    modules = [n for n in nodes.values() if n.get("kind") == "module"
               and n.get("repository") == location["repository"]
               and n.get("path") == location["path"]]
    if len(modules) != 1 or not modules[0].get("snapshot_id"):
        return False
    module = modules[0]
    def site(role):
        return digest(canonical([location["repository"], location["path"],
                                 module["snapshot_id"], location["line"], location["column"],
                                 location["end_line"], location["end_column"], role]))
    if (fact["read_owner"] not in nodes or fact["consumer_owner"] not in nodes
            or subscription[0] != digest(canonical(fact)) or subscription[1] != fact["origin"]
            or subscription[2] != fact["key_kind"] or subscription[3] != str(fact["key"])
            or subscription[4:8] != (
                fact["read_owner"], fact["read_site"], fact["consumer_owner"], fact["consumer_site"])
            or fact["read_site"] != site("container-read")
            or fact["consumer_site"] != site("read")):
        return False
    try:
        expected = ast.dump(ast.parse(location["expression"], mode="eval").body)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, ast.Subscript)
               and node.lineno == location["line"] and node.col_offset == location["column"]
               and ast.dump(node) == expected
               for node in ast.walk(ast.parse(content)))


def assert_limited_refinement(actual, fresh, sources):
    """Require all fresh facts; allow only proven additional annotation/read facts."""
    assert actual.keys() == fresh.keys()
    nodes = _objects(actual["nodes"])
    for table in actual:
        if table in EXECUTION_LEDGER:
            continue
        if table == "sites":
            a = {json.loads(row[-1])["site_id"]: _site(row[-1]) for row in actual[table]}
            b = {json.loads(row[-1])["site_id"]: _site(row[-1]) for row in fresh[table]}
            assert a == b, table
        elif table == "analysis_input_consumers":
            a = {row[:-1]: int(row[-1]) for row in actual[table]}
            b = {row[:-1]: int(row[-1]) for row in fresh[table]}
            assert a.keys() == b.keys() and all(a[key] > 0 and b[key] > 0 for key in a), table
        elif table == "edges":
            a, b = set(actual[table]), set(fresh[table])
            assert b <= a and all(_eager_annotation(row, nodes, sources) for row in a - b), table
        elif table == "unit_container_subscriptions":
            a, b = set(actual[table]), set(fresh[table])
            existing = [json.loads(row[-1]) for row in b]
            assert b <= a and all(_direct_open_input(row, existing, nodes, sources) for row in a - b), table
        else:
            assert actual[table] == fresh[table], table
