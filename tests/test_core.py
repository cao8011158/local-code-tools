"""AST/lexical unit checks; no network, project imports, or fabricated provider calls."""

import sqlite3

import pytest

from lct.common import ToolError, digest, lock
from lct.embedding import vector_key
from lct.extract import embedding_texts, markdown_nodes, python_nodes
from lct.graph import Graph
from lct.lexical import add_document, rank, tokenize
from lct.storage import DDL


def file(text, path="src/demo.py", repo="demo"):
    return dict(text=text, path=path, repository=repo, is_test=False, sha256=digest(text))


def graph(text, other=None):
    files = [file(text)] + ([file(other, "src/helper.py")] if other else [])
    nodes, asts = [], {}
    for f in files:
        ns, trees = python_nodes(f)
        nodes += ns
        asts.update(trees)
    g = Graph(nodes, asts, [dict(name="demo", path=".", head="test", status="")])
    edges, info = g.build()
    byid = {n["node_id"]: n["qualname"] for n in nodes}
    calls = [
        (byid[e["source"]], byid.get(e["target"], e["target"]), e["status"], e["expression"])
        for e in edges
        if e["kind"] == "CALLS"
    ]
    return calls, edges, info


def test_direct_and_alias():
    calls, _, _ = graph("def target(): pass\ndef caller():\n target()\n f=target\n f()\n")
    assert ("caller", "target", "resolved", "target") in calls
    assert ("caller", "target", "resolved", "f") in calls


def test_import_alias():
    calls, _, _ = graph(
        "from helper import work as alias\ndef caller(): alias()\n", "def work(): pass\n"
    )
    assert ("caller", "work", "resolved", "alias") in calls


def test_method_constructor_annotation():
    calls, _, _ = graph(
        "class A:\n def work(self): pass\ndef caller(x:A):\n a=A()\n a.work()\n x.work()\n"
    )
    assert ("caller", "A.work", "resolved", "a.work") in calls
    assert ("caller", "A.work", "resolved", "x.work") in calls


def test_callback_flow():
    calls, _, _ = graph("def target(): pass\ndef invoke(cb): cb()\ndef caller(): invoke(target)\n")
    assert ("invoke", "target", "resolved", "cb") in calls


def test_dict_possible_is_not_unknown():
    calls, _, _ = graph(
        "def a(): pass\ndef b(): pass\ntable={'a':a,'b':b}\ndef choose(k): table[k]()\n"
    )
    assert ("choose", "a", "possible", "table[k]") in calls
    assert ("choose", "b", "possible", "table[k]") in calls


def test_registry_flow():
    calls, _, _ = graph(
        "handlers={}\ndef register(name,cb): handlers[name]=cb\ndef target(): pass\nregister('go',target)\ndef dispatch(k): handlers[k]()\n"
    )
    assert ("dispatch", "target", "resolved", "handlers[k]") in calls


def test_unknown_is_retained_no_same_name_guess():
    calls, _, _ = graph("def target(): pass\ndef caller(x): x.target()\n")
    assert ("caller", None, "unresolved", "x.target") in calls


def test_inheritance():
    calls, edges, _ = graph(
        "class A:\n def work(self): pass\nclass B(A): pass\ndef caller(): B().work()\n"
    )
    assert any(e["kind"] == "INHERITS" and e["status"] == "resolved" for e in edges)
    assert ("caller", "A.work", "resolved", "B().work") in calls


def test_external_boundary():
    calls, _, _ = graph("import json as j\ndef f(): j.loads('{}')\n")
    assert any(c[2] == "boundary" and "json.loads" in c[1] for c in calls)


def test_cross_version_boundary(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="old"}'
    )
    nodes, asts = python_nodes(
        file("from dnd5e_engine.evaluation import evaluate\ndef f(): evaluate()\n", repo="sm")
    )
    other, oa = python_nodes(
        file(
            "def evaluate(): pass\n",
            "packages/x/src/dnd5e_engine/evaluation.py",
            "trpg-rules-engine",
        )
    )
    g = Graph(
        nodes + other,
        asts | oa,
        [
            dict(name="sm", path=str(tmp_path), head="sm", status=""),
            dict(name="trpg-rules-engine", path="none", head="new", status=""),
        ],
    )
    edges, info = g.build()
    assert not info["dependency_bindings"]["sm"]["matched"]
    assert all(
        e["target"] not in {n["node_id"] for n in other}
        for e in edges
        if e["kind"] in ("IMPORTS", "CALLS")
    )


def test_nested_duplicates_unique_and_line_shift():
    text = "def f():\n def x(): pass\n return x\ndef f():\n def x(): pass\n return x\n"
    nodes, _ = python_nodes(file(text))
    shifted, _ = python_nodes(file("\n\n" + text))
    assert len({n["node_id"] for n in nodes}) == len(nodes)
    assert [n["node_id"] for n in nodes] == [n["node_id"] for n in shifted]


def test_does_not_execute_source(tmp_path):
    target = tmp_path / "should-not-exist"
    text = (
        f"raise RuntimeError('index must not run this')\nopen({str(target)!r},'w')\ndef f(): pass\n"
    )
    python_nodes(file(text))
    assert not target.exists()


def test_templates_no_repeated_function_docstring():
    f = file(
        '"""module explanation"""\nclass C:\n """class explanation"""\n def f(self):\n  """function explanation"""\n  return 1\n'
    )
    nodes, _ = python_nodes(f)
    texts = embedding_texts(nodes, [f])
    function = next(t for t in texts if ":function:" in t["node_id"])
    assert function["text"].count("function explanation") == 1
    cls = next(t for t in texts if ":class:" in t["node_id"])
    assert "return 1" not in cls["text"]


def test_long_function_chunks_keep_node():
    f = file("def f():\n" + "    x=12345 # long preserved comments\n" * 2000)
    nodes, _ = python_nodes(f)
    ts = [t for t in embedding_texts(nodes, [f]) if ":function:" in t["node_id"]]
    assert len(ts) > 1 and len({t["node_id"] for t in ts}) == 1
    assert all(len(t["text"].encode()) + 64 < 32000 for t in ts)


def test_markdown_fences_tables_and_categories():
    f = file(
        "# Top\nintro\n\n```python\n# not-heading\n```\n\n|a|b|\n|---|---|\n|1|2|\n\n## Child\nbody\n",
        "docs/CONTRACT.md",
        "agentic-trpg",
    )
    ns = markdown_nodes(f)
    assert len(ns) == 2
    assert ns[1]["heading_path"] == ["Top", "Child"]
    assert ns[1]["parent"] == ns[0]["node_id"]
    assert all(n["category"] == "contract" for n in ns)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("容器重量", ["容", "器", "重量"]),
        ("SessionMemory.resolve_field", ["session", "memory", "resolve", "field"]),
        ("OCC回滚", ["occ", "回滚"]),
    ],
)
def test_tokenizer(query, expected):
    assert set(expected) <= set(tokenize(query))


def test_postings_filter_before_limit():
    db = sqlite3.connect(":memory:")
    db.executescript(DDL)
    for i in range(100):
        n = dict(node_id=str(i), repository="target" if i == 99 else "other", kind="function")
        db.execute(
            "insert into nodes values(?,?,?,?,?,?)",
            (str(i), n["repository"], "a.py", "function", "{}", ""),
        )
        add_document(db, n, "needle " * (100 - i))
    db.execute("insert into terms select term,count(*) from postings group by term")
    assert rank(db, "needle", "n.repository=?", ["target"], 1) == ["99"]


def test_historical_cache_key():
    import json

    e = dict(model="voyage-code-4", dimension=1024, dtype="float")
    text = "def x(): pass\n"
    expected = digest(json.dumps(["voyage-code-4", 1024, "float", "document", False, digest(text)]))
    assert vector_key(e, text, "document") == expected
    assert vector_key(e, text, "query") != expected


def test_concurrent_writer_lock(tmp_path):
    with lock(tmp_path / "writer.lock"):
        with pytest.raises(ToolError, match="Concurrent"):
            with lock(tmp_path / "writer.lock"):
                pass
    with lock(tmp_path / "writer.lock"):
        pass


def test_unknown_local_shadows_global():
    calls, _, _ = graph("def cb(): pass\ndef invoke(cb): cb()\n")
    assert ("invoke", None, "unresolved", "cb") in calls


def test_registry_via_method():
    calls, _, _ = graph(
        "class Registry:\n def __init__(self): self.handlers={}\n def register(self,name,cb): self.handlers[name]=cb\n def dispatch(self,k): self.handlers[k]()\ndef target(): pass\nr=Registry()\nr.register('go',target)\n"
    )
    assert any(c[0] == "Registry.dispatch" and c[1] == "target" for c in calls)


def test_real_compatible_cache_reuse_without_network(tmp_path):
    import copy
    from pathlib import Path

    from lct.common import config, load
    from lct.embedding import Embeddings

    c = copy.deepcopy(config())
    cache = Path(c["embedding"].get("historical_cache", "none"))
    if not cache.is_dir():
        pytest.skip("optional real historical vector cache not present on this machine")
    questions = load(cache.parent.parent / "questions.json")
    c["data"] = str(tmp_path / "real-cache")
    e = Embeddings(c)
    try:
        text = questions[0]["zh"]
        first = e.get_many([text], "query", offline=True)[0]
        second = e.get_many([text], "query", offline=True)[0]
        assert first.shape == (1024,) and (first == second).all()
        assert e.historical_hits == 1 and e.hits == 1 and e.requests == 0
        with pytest.raises(ToolError, match="offline"):
            e.get_many(["def entirely_new_uncached_fixture(): pass"], "document", offline=True)
        assert e.requests == 0
    finally:
        e.close()


def test_per_package_pin_and_untracked_python_are_fail_closed(tmp_path):
    import subprocess

    from lct.common import git

    sm = tmp_path / "sm"
    re = tmp_path / "re"
    sm.mkdir()
    re.mkdir()
    for args in (
        ["init", str(re)],
        ["-C", str(re), "config", "user.name", "Local"],
        ["-C", str(re), "config", "user.email", "local@example.invalid"],
    ):
        subprocess.run(["git", *args], check=True, capture_output=True)
    (re / "tracked.py").write_text("def tracked(): pass\n")
    subprocess.run(["git", "-C", str(re), "add", "tracked.py"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(re), "commit", "-m", "fixture"], check=True, capture_output=True
    )
    head = git(re, "rev-parse", "HEAD")
    (sm / "pyproject.toml").write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="wrong"}\ndnd5e-srd-data={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="'
        + head
        + '"}\n'
    )
    nodes, asts = python_nodes(
        file("def work(): pass\n", "packages/x/src/dnd5e_engine/evaluation.py", "trpg-rules-engine")
    )
    data, da = python_nodes(
        file("def load(): pass\n", "packages/y/src/dnd5e_srd_data/loader.py", "trpg-rules-engine")
    )
    repos = [
        dict(name="sm", path=str(sm), head="sm", status=""),
        dict(name="trpg-rules-engine", path=str(re), head=head, status=""),
    ]
    graph = Graph(nodes + data, asts | da, repos)
    assert all(v.startswith("boundary:") for v in graph.imported("sm", "dnd5e_engine.evaluation"))
    assert graph.imported("sm", "dnd5e_srd_data.loader") == {data[0]["node_id"]}
    (re / "untracked.py").write_text("def new(): pass\n")
    dirty = Graph(nodes + data, asts | da, repos)
    assert all(v.startswith("boundary:") for v in dirty.imported("sm", "dnd5e_srd_data.loader"))
