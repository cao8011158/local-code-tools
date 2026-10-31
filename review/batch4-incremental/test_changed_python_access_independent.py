"""Trace actual indexed dependency queries from public local builds."""

import json

import lct.extract as extraction
from lct.storage import FileDependencies, build
from tests.synthetic_support import initialize


def test_public_component_queries_use_indexes_with_unrelated_relation_growth(tmp_path, monkeypatch):
    actual_parse = extraction.python_nodes
    actual_importers = FileDependencies.importers
    active, comparisons = {}, []

    def counted(file):
        if active:
            active["parsed"].append(file["path"])
        return actual_parse(file)

    def wrapped(method, label):
        def run(self, *args):
            if not active:
                return method(self, *args)
            statements, ticks = [], [0]
            self.db.set_trace_callback(statements.append)
            def step():
                ticks[0] += 1
                return 0
            self.db.set_progress_handler(step, 1)
            try:
                result = method(self, *args)
            finally:
                self.db.set_trace_callback(None)
                self.db.set_progress_handler(None, 0)
            plans = []
            for statement in statements:
                if statement.lstrip().lower().startswith("select"):
                    plans.extend(row[3] for row in self.db.execute("explain query plan " + statement))
            assert plans and any("SEARCH" in p for p in plans), plans
            assert not any("SCAN file_adjacency" in p or "SCAN import_requests" in p for p in plans), plans
            active["queries"].append(dict(method=label, target=list(args), rows=len(result),
                                           vm_steps=ticks[0], plans=plans))
            return result
        return run

    monkeypatch.setattr(extraction, "python_nodes", counted)
    monkeypatch.setattr(FileDependencies, "unit_readers", wrapped(FileDependencies.unit_readers, "unit_readers"))
    monkeypatch.setattr(FileDependencies, "importers", wrapped(actual_importers, "importers"))
    for noise in (0, 20):
        c, repo = initialize(tmp_path / f"fixture-{noise}")
        (repo / "src/weights.py").unlink()
        a = "from b import execute\ndef first(): pass\ndef second(): pass\ndef run(): execute(first)\n"
        (repo / "src/a.py").write_text(a)
        (repo / "src/b.py").write_text("def execute(callback): callback()\n")
        (repo / "src/u.py").write_text("def unrelated(): pass\n")
        for i in range(noise):
            (repo / "src" / f"base_{i}.py").write_text(f"def leaf_{i}(): pass\n")
            (repo / "src" / f"noise_{i}.py").write_text(
                f"from base_{i} import leaf_{i}\ndef caller_{i}(): leaf_{i}()\n")
        build(c, offline=True, lexical_only=True)
        (repo / "src/a.py").write_text(a.replace("execute(first)", "execute(second)"))
        active.update(parsed=[], queries=[])
        result = build(c, offline=True, lexical_only=True)
        assert result["incremental"]["analysis_scope"]["mode"] == "incremental-owners"
        assert sorted(active["parsed"]) == ["src/a.py"]
        comparisons.append(dict(unrelated_pairs=noise, parsed=active["parsed"], queries=active["queries"]))
        active.clear()
    shape = lambda group: sorted((q["method"], tuple(q["target"]), q["rows"]) for q in group["queries"])
    assert shape(comparisons[0]) == shape(comparisons[1])
    assert len(comparisons[0]["queries"]) == len(comparisons[1]["queries"]) > 0
    print(json.dumps(comparisons, ensure_ascii=False, sort_keys=True))
