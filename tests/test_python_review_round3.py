"""Third independent-review contracts. All parser cases use production open inputs."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from lct.common import ToolError, atomic, load
from lct.query import Query
from lct.storage import build, current, manifest, prune, recover
from tests.test_lifecycle import sandbox as sandbox
from tests.test_python_pipeline import analyze, expect

CASES = [
    (
        "annotated_field",
        """def target(): pass
class C:
 def __init__(self): self.run: object=target
 def run(self): pass
def caller(): C().run()
""",
        "C().run",
        {"target"},
        {"C.run"},
    ),
    (
        "method_write",
        """def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 def change(self): self.run=b
def caller():
 obj=C()
 obj.change()
 obj.run()
""",
        "obj.run",
        {"b"},
        {"a"},
    ),
    (
        "field_delete",
        """def a(): pass
class C:
 def __init__(self): self.run=a
 def run(self): pass
def caller():
 obj=C()
 del obj.run
 obj.run()
""",
        "obj.run",
        {"C.run"},
        {"a"},
    ),
    (
        "annotated_slot",
        """def a(): pass
def b(): pass
def caller():
 table={"go":a}
 table["go"]: object=b
 table["go"]()
""",
        "table['go']",
        {"b"},
        {"a"},
    ),
    (
        "dict_unpack",
        """def a(): pass
def caller():
 original={"go":a}
 copied={**original}
 copied["go"]()
""",
        "copied['go']",
        {"a"},
        set(),
    ),
]


def check(result, expression, targets, forbidden=(), unknown=False):
    s = expect(
        result,
        expression,
        "caller",
        targets,
        forbidden=forbidden,
        unknown=unknown,
        complete=not unknown,
    )
    nodes = {n["node_id"]: n for n in result[0]}
    assert nodes[s["lexical_owner"]]["qualname"] == "caller" and s["phase"] == "body"
    edges = [e for e in result[1] if e["kind"] == "CALLS" and e.get("site_id") == s["site_id"]]
    assert {nodes[e["target"]]["qualname"] for e in edges if e["target"] in nodes} == targets
    assert all(
        e["source"] == s["execution_owner"]
        and e["line"] == s["line"]
        and e["unknown_origin"] == unknown
        and e["complete"] is (not unknown)
        for e in edges
    )
    assert bool(s["unresolved_reasons"]) is unknown
    decision = s["resolution_decision"]
    assert decision["selected_targets"] == s["targets"]
    if decision["excluded_jedi_targets"]:
        assert decision["reason"] == "tested-semantic-rule"
        assert decision.get("write_source_coverage", {}).get("complete")
    return s


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_review_calls(tmp_path, case):
    _, source, expression, targets, forbidden = case
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = check(r, expression, targets, forbidden)
    assert s["line"] == len(source.splitlines())


@pytest.mark.parametrize("asynchronous,alias", [(False, False), (False, True), (True, True)])
def test_context_factory_create_and_enter(tmp_path, asynchronous, alias):
    deco = "asynccontextmanager" if asynchronous else "contextmanager"
    binding = "cm" if alias else deco
    source = (
        f"from contextlib import {deco}"
        + (" as cm" if alias else "")
        + "\nclass C:\n def work(self): pass\n@"
        + binding
        + "\n"
        + ("async " if asynchronous else "")
        + "def acquire():\n yield C()\n"
        + ("async " if asynchronous else "")
        + "def caller():\n "
        + ("async " if asynchronous else "")
        + "with acquire() as obj: obj.work()\n"
    )
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = check(r, "acquire", {"acquire"})
    check(r, "obj.work", {"C.work"})
    byid = {n["node_id"]: n for n in r[0]}
    calls = [e for e in r[1] if e["kind"] == "CALLS" and e.get("site_id") == s["site_id"]]
    assert all(
        e["invocation_phase"] == "context-manager-create"
        and e["executes_body"] is False
        and e["target_role"] == "decorated-factory"
        for e in calls
    )
    wrapped = next(n["node_id"] for n in r[0] if n["qualname"] == "acquire")
    assert any(
        e["kind"] == "WRAPS"
        and e["target"] == wrapped
        and e["wrapper_origin"] == "contextlib." + deco
        for e in r[1]
    )
    assert any(
        e["kind"] == "CONTEXT_ENTERS"
        and e["source"] == s["execution_owner"]
        and e["target"] == wrapped
        and e["invocation_phase"] == "generator-resume"
        for e in r[1]
    )
    assert not any(
        e["kind"] == "CALLS"
        and e["source"] == s["execution_owner"]
        and byid.get(e["target"], {}).get("qualname") == "C"
        for e in r[1]
    )


def fixed_versions(monkeypatch, values):
    import time

    import lct.storage as storage

    ids = iter(values)
    monkeypatch.setattr(
        storage, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(ids) * 32))
    )
    monkeypatch.setattr(
        storage,
        "time",
        SimpleNamespace(
            monotonic=time.monotonic, gmtime=time.gmtime, strftime=lambda *args: "20261027T120000"
        ),
    )


def test_same_second_order_and_cursor_expiry(sandbox, monkeypatch):
    c, _ = sandbox
    fixed_versions(monkeypatch, ["f", "e", "0"])
    build(c, lexical_only=True)
    query = Query(c)
    cursor = query.search_code("weight", mode="bm25", candidates=10, limit=1)["next_cursor"]
    second = build(c, lexical_only=True)
    third = build(c, lexical_only=True)
    assert current(c) == third["version"]
    folders = {p.name for p in (Path(c["data"]) / "versions").iterdir() if p.is_dir()}
    assert folders == {second["version"], third["version"]}
    with pytest.raises(ToolError, match="expired"):
        query.search_code("weight", mode="bm25", candidates=10, limit=1, cursor=cursor)
    manifest(c, second["version"])


def test_recover_then_publish_and_failed_candidate(sandbox, monkeypatch):
    c, _ = sandbox
    fixed_versions(monkeypatch, ["f", "e", "d", "0"])
    first = build(c, lexical_only=True)
    second = build(c, lexical_only=True)
    with pytest.raises(ToolError, match="Injected"):
        build(c, lexical_only=True, fail_at="before_publish")
    recover(c, first["version"])
    third = build(c, lexical_only=True)
    assert current(c) == third["version"]
    assert load(Path(c["data"]) / "current.json")["previous"] == first["version"]
    folders = {p.name for p in (Path(c["data"]) / "versions").iterdir() if p.is_dir()}
    assert folders == {first["version"], third["version"]}
    with pytest.raises(ToolError, match="expired"):
        manifest(c, second["version"])


def test_legacy_pointer_uses_previous_not_uuid(sandbox, monkeypatch):
    c, _ = sandbox
    c["retained_versions"] = 4
    fixed_versions(monkeypatch, ["f", "e", "0"])
    versions = [build(c, lexical_only=True)["version"] for _ in range(3)]
    atomic(Path(c["data"]) / "current.json", dict(version=versions[2], previous=versions[1]))
    c["retained_versions"] = 2
    prune(c)
    assert {p.name for p in (Path(c["data"]) / "versions").iterdir() if p.is_dir()} == set(
        versions[1:]
    )


@pytest.mark.parametrize(
    "initial,change,targets,unknown",
    [
        ("self.run: object", "", {"C.run"}, False),
        ("self.run=a", "obj.run: object", {"a"}, False),
        ("self.run=a", "obj.run: object=b", {"b"}, False),
        ("self.run=a", "if flag: obj.run: object=b", {"a", "b"}, True),
        ("self.run=a", "if flag: del obj.run", {"a", "C.run"}, True),
        ("self.run=a", "del obj.run\n obj.run=b", {"b"}, False),
    ],
)
def test_field_event_controls(tmp_path, initial, change, targets, unknown):
    source = f"""def a(): pass
def b(): pass
class C:
 def __init__(self): {initial}
 def run(self): pass
def caller(flag):
 obj=C()
 {change}
 obj.run()
"""
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    check(r, "obj.run", targets, {"a", "b", "C.run"} - targets, unknown)


@pytest.mark.parametrize(
    "body,call,targets,unknown",
    [
        ("self.other=b", "first.change()", {"a"}, False),
        ("self.run=b", "second.change()", {"a"}, False),
        ("self.run=b", "first.change()", {"b"}, False),
        ("unknown(self)", "first.change()", {"a"}, True),
    ],
)
def test_method_effect_receiver_isolation(tmp_path, body, call, targets, unknown):
    source = f"""def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
 def change(self): {body}
def caller():
 first=C()
 second=C()
 {call}
 first.run()
"""
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    check(r, "first.run", targets, {"a", "b"} - targets, unknown)


@pytest.mark.parametrize(
    "setup,copy,after,targets,unknown",
    [
        ('original={"go":a}', '{"go":b,**original}', "", {"a"}, False),
        ('original={"go":a}', '{**original,"go":b}', "", {"b"}, False),
        ('original={"go":a}\n original["go"]: object=b', "{**original}", "", {"b"}, False),
        ('original={"go":a}', "{**original}", 'original["go"]=b', {"a"}, False),
        ('original={"go":a}', '{"go":a,**unknown}', "", {"a"}, True),
        ('original={"go":a}', '{**unknown,"go":b}', "", {"b"}, False),
        ('original={"go":a}', "{**unknown}", "", set(), True),
        ('original={}\n original["go"]=a', "{**original}", "", {"a"}, False),
    ],
)
def test_dictionary_expansion_order(tmp_path, setup, copy, after, targets, unknown):
    source = f"""def a(): pass
def b(): pass
def caller(unknown):
 {setup}
 copied={copy}
 {after}
 copied["go"]()
"""
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    check(r, "copied['go']", targets, {"a", "b"} - targets, unknown)


def test_rule_label_without_coverage_cannot_exclude_jedi(tmp_path, monkeypatch):
    import ast

    from lct.python_analysis import Analyzer, certified, known

    original = Analyzer._resolve

    def incomplete(self, scope, expr, before):
        if isinstance(expr, ast.Subscript):
            wrong = next(i for i, n in self.nodes.items() if n["qualname"] == "a")
            return certified(known("callable", wrong), "literal-slot-state")
        return original(self, scope, expr, before)

    monkeypatch.setattr(Analyzer, "_resolve", incomplete)
    r = analyze(tmp_path, {"demo.py": CASES[3][1]}, closed=False)
    s = check(r, "table['go']", set(), {"a", "b"}, True)
    assert s["resolution_decision"]["jedi_targets"]
    assert not s["resolution_decision"]["excluded_jedi_targets"]
    assert s["resolution_decision"]["write_source_coverage"] is None


def test_recover_current_does_not_lose_previous(sandbox, monkeypatch):
    c, _ = sandbox
    fixed_versions(monkeypatch, ["f", "0"])
    build(c, lexical_only=True)
    latest = build(c, lexical_only=True)
    before = load(Path(c["data"]) / "current.json")
    recover(c, latest["version"])
    assert load(Path(c["data"]) / "current.json") == before


def test_legacy_unknown_order_preserved_until_history_suffices(sandbox, monkeypatch):
    c, _ = sandbox
    c["retained_versions"] = 4
    fixed_versions(monkeypatch, ["f", "e", "d", "1", "0"])
    first, second, third = [build(c, lexical_only=True)["version"] for _ in range(3)]
    atomic(Path(c["data"]) / "current.json", dict(version=third, previous=second))
    prune(c)
    manifest(c, first)
    build(c, lexical_only=True)
    manifest(c, first)
    build(c, lexical_only=True)
    with pytest.raises(ToolError, match="expired"):
        manifest(c, first)


def test_pointer_publication_survives_stale_failed_marker(sandbox, monkeypatch):
    c, _ = sandbox
    fixed_versions(monkeypatch, ["f", "e", "0"])
    first = build(c, lexical_only=True)["version"]
    second = build(c, lexical_only=True)["version"]
    atomic(
        Path(c["data"]) / "versions" / second / "build-state.json",
        dict(state="failed-or-interrupted"),
    )
    prune(c)
    manifest(c, second)
    third = build(c, lexical_only=True)["version"]
    manifest(c, second)
    assert current(c) == third
    with pytest.raises(ToolError, match="expired"):
        manifest(c, first)


def test_imported_context_factory_alias(tmp_path):
    r = analyze(
        tmp_path,
        {
            "helper.py": """from contextlib import contextmanager as cm
class C:
 def work(self): pass
@cm
def acquire(): yield C()
""",
            "demo.py": """from helper import acquire as alias
def caller():
 with alias() as obj: obj.work()
""",
        },
        closed=False,
    )
    s = check(r, "alias", {"acquire"})
    check(r, "obj.work", {"C.work"})
    assert r[2]["schema"] == 3
    assert any(e.get("site_id") == s["site_id"] and e.get("executes_body") is False for e in r[1])


def test_complete_legacy_failed_marker_is_not_age_proof(sandbox, monkeypatch):
    c, _ = sandbox
    c["retained_versions"] = 4
    fixed_versions(monkeypatch, ["f", "e", "0"])
    first, second, third = [build(c, lexical_only=True)["version"] for _ in range(3)]
    atomic(
        Path(c["data"]) / "versions" / first / "build-state.json",
        dict(state="failed-or-interrupted"),
    )
    atomic(Path(c["data"]) / "current.json", dict(version=third, previous=second))
    prune(c)
    manifest(c, first)


def test_constructor_method_effect_is_finite(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
class C:
 def __init__(self):
  self.run=a
  self.change()
 def change(self): self.run=b
def caller(): C().run()
"""
        },
        closed=False,
    )
    check(r, "C().run", {"b"}, {"a"})


def test_shadowed_method_effect_is_not_class_body_execution(tmp_path):
    r = analyze(
        tmp_path,
        {
            "demo.py": """def a(): pass
def b(): pass
def unknown(): pass
class C:
 def __init__(self):
  self.run=a
  self.change=unknown
 def change(self): self.run=b
def caller():
 obj=C()
 obj.change()
 obj.run()
"""
        },
        closed=False,
    )
    check(r, "obj.run", {"a"}, {"b"}, True)


def test_rule_label_without_coverage_is_not_complete_even_when_jedi_agrees(tmp_path, monkeypatch):
    import ast

    from lct.python_analysis import Analyzer, certified, known

    original = Analyzer._resolve

    def incomplete(self, scope, expr, before):
        if isinstance(expr, ast.Subscript):
            target = next(i for i, n in self.nodes.items() if n["qualname"] == "a")
            return certified(known("callable", target), "literal-slot-state")
        return original(self, scope, expr, before)

    monkeypatch.setattr(Analyzer, "_resolve", incomplete)
    source = 'def a(): pass\ndef caller():\n table={"go":a}\n table["go"]()\n'
    s = check(
        analyze(tmp_path, {"demo.py": source}, closed=False), "table['go']", {"a"}, unknown=True
    )
    assert "missing-write-source-coverage" in s["unresolved_reasons"]
    assert not s["resolution_decision"]["conflict"]
