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
    assert s["target_provider"] == "jedi-get-signatures"
    assert s["evidence"][1]["api"] == "get_signatures"
    assert "resolution_decision" not in s
    return s


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0])
def test_review_calls(tmp_path, case):
    label, source, expression, _, _ = case
    # Fixed independent Jedi 0.20.1 get_signatures probes for each source.
    expected = {
        "annotated_field": set(), "method_write": {"a", "b"},
        "field_delete": {"a"}, "annotated_slot": {"b"},
        "dict_unpack": set(),
    }[label]
    r = analyze(tmp_path, {"demo.py": source}, closed=False)
    s = check(r, expression, expected, unknown=not expected)
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
    factory = check(r, "acquire", {"acquire"})
    work = check(r, "obj.work", {"C.work"})
    assert factory["phase"] == "body" and work["phase"] == "body"
    assert any(e["kind"] == "CONTEXT_ENTERS" and
               e["source"] == factory["execution_owner"] for e in r[1])


def fixed_versions(monkeypatch, values):
    import time
    import lct.storage as storage

    ids = iter(values)
    monkeypatch.setattr(
        storage, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(ids) * 32))
    )
    monkeypatch.setattr(
        storage, "time",
        SimpleNamespace(monotonic=time.monotonic, gmtime=time.gmtime,
                        strftime=lambda *args: "20261027T120000"),
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
        ("self.run: object", "", set(), True),
        ("self.run=a", "obj.run: object", {"a"}, False),
        ("self.run=a", "obj.run: object=b", {"a"}, False),
        ("self.run=a", "if flag: obj.run: object=b", {"a"}, False),
        ("self.run=a", "if flag: del obj.run", {"a"}, False),
        ("self.run=a", "del obj.run\n obj.run=b", {"a"}, False),
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
        ("self.run=b", "second.change()", {"a", "b"}, False),
        ("self.run=b", "first.change()", {"a", "b"}, False),
        ("unknown(self)", "first.change()", {"a"}, False),
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
        ('original={"go":a}', '{"go":b,**original}', "", {"b"}, False),
        ('original={"go":a}', '{**original,"go":b}', "", {"b"}, False),
        ('original={"go":a}\n original["go"]: object=b', "{**original}", "", set(), True),
        ('original={"go":a}', "{**original}", 'original["go"]=b', set(), True),
        ('original={"go":a}', '{"go":a,**unknown}', "", {"a"}, False),
        ('original={"go":a}', '{**unknown,"go":b}', "", {"b"}, False),
        ('original={"go":a}', "{**unknown}", "", set(), True),
        ('original={}\n original["go"]=a', "{**original}", "", set(), True),
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
    work = check(r, "obj.work", {"C.work"})
    assert work["execution_owner"] == s["execution_owner"]
    assert any(e["kind"] == "CONTEXT_ENTERS" and
               e["source"] == s["execution_owner"] for e in r[1])


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
    check(r, "C().run", {"a", "b"})


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
    s = check(r, "obj.run", {"a", "b"})
    assert s["target_provider"] == "jedi-get-signatures"
