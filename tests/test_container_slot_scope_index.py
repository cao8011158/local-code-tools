"""Public-build evidence for local literal writer scope exclusion."""

import json
import sqlite3

from lct.storage import build, manifest
from tests.synthetic_support import initialize


def _caller_site(config, version):
    folder, _ = manifest(config, version)
    with sqlite3.connect(folder / "graph-sites.sqlite") as db:
        return next(json.loads(raw) for (raw,) in db.execute("select data from sites")
                    if '"expression":"registry[\'go\']"' in raw)


def test_unrelated_local_alias_writers_do_not_grow_consumer_checks(tmp_path):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run():\n    return registry['go']()\n")
    evidence = []
    for count in (0, 20, 100):
        for number in range(count):
            path = repo / f"src/a_{number}.py"
            if not path.exists():
                path.write_text(f"def writer_{number}():\n"
                                "    slot={}\n    alias=slot\n    alias['x']=1\n")
        result = build(config, offline=True, lexical_only=True)
        site = _caller_site(config, result["version"])
        coverage = site["resolution_decision"]["write_source_coverage"]
        evidence.append((result["graph"], site, coverage))
        # The AST effect index currently prepares all known writer scopes;
        # caller candidate checks below must still stay bounded.
        assert result["graph"]["slot_scope_index_build_scopes"] == count
        assert result["graph"]["slot_scope_fallback_scopes"] == 0
        if count == 0:
            identical = build(config, offline=True, lexical_only=True)
            assert identical["incremental"]["analysis_scope"]["mode"] == (
                "identical-python-capture-reuse")
            assert _caller_site(config, identical["version"]) == site
            assert all(identical["graph"][key] == 0 for key in (
                "slot_scope_index_build_scopes", "slot_scope_fallback_scopes",
                "slot_scope_candidates_checked", "slot_events_checked"))
    first_graph, first_site, first_coverage = evidence[0]
    for graph, site, coverage in evidence[1:]:
        assert site["targets"] == first_site["targets"]
        assert site["complete"] == first_site["complete"]
        assert site["unresolved_reasons"] == first_site["unresolved_reasons"]
        assert coverage == first_coverage
        assert graph["slot_scope_candidates_checked"] <= first_graph[
            "slot_scope_candidates_checked"]
        assert graph["slot_events_checked"] <= first_graph["slot_events_checked"]


def test_only_source_related_receivers_are_read_candidates(tmp_path):
    config, repo = initialize(tmp_path / "uncertain")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run():\n    return registry['go']()\n")
    sources = (
        "def parameter(registry):\n    registry['x']=1\n",
        "from b import registry\ndef imported():\n    registry['x']=1\n",
        "def escaped():\n    slot={}\n    slot['x']=1\n    return slot\n",
        "def called(f):\n    slot={}\n    slot['x']=1\n    f(slot)\n",
        "def rebound(registry):\n    slot={}\n    slot=registry\n    slot['x']=1\n",
        "from b import registry as remote\n"
        "def imported_rebound():\n    slot={}\n    alias=slot\n"
        "    alias=remote\n    alias['x']=1\n",
    )
    for number, source in enumerate(sources):
        (repo / f"src/uncertain_{number}.py").write_text(source)
    result = build(config, offline=True, lexical_only=True)
    graph = result["graph"]
    assert graph["slot_scope_index_build_scopes"] == len(sources)
    assert graph["slot_writer_index_receivers"] == len(sources)
    # Two unlocated parameter receivers retain a boundary/watch, without
    # becoming candidate writers for every unrelated known container.
    assert graph["slot_scope_fallback_scopes"] == 2
    coverage = _caller_site(config, result["version"])["resolution_decision"][
        "write_source_coverage"]
    assert any("uncertain_1.py" in ident for ident in coverage["required_events"])
    assert any("uncertain_5.py" in ident for ident in coverage["required_events"])
    assert not any(f"uncertain_{i}.py" in ident for ident in coverage["required_events"]
                   for i in (0, 2, 3, 4))


def test_alias_rebound_between_two_fresh_local_origins_stays_isolated(tmp_path):
    config, repo = initialize(tmp_path / "aliases")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    (repo / "src/b.py").write_text(
        "def target(): pass\nregistry={'go':target}\n"
        "def run():\n    return registry['go']()\n")
    (repo / "src/a.py").write_text(
        "def writer():\n    first={}\n    alias=first\n    alias['x']=1\n"
        "    second={}\n    alias=second\n    alias['x']=2\n")
    result = build(config, offline=True, lexical_only=True)
    assert result["graph"]["slot_scope_index_build_scopes"] == 1
    assert result["graph"]["slot_scope_fallback_scopes"] == 0
    assert not any("src/a.py" in ident for ident in _caller_site(
        config, result["version"])["resolution_decision"]["write_source_coverage"][
            "required_events"])
