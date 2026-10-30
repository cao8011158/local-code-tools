"""Root probes for the approved constructor-impact repair, not general certification."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v4_root_probe", HERE / "v4.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.v1.schedule = m.schedule


def cases():
    source = ("def first(): pass\ndef second(): pass\nclass Box:\n"
              " def __init__(self): self.cb=first\ndef factory():\n"
              " value=Box()\n return value\n")
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\nclass Bridge:\n def forward(self):\n  value=factory()\n  return value\n",
              "src/c.py": "from b import Bridge\ndef run(): Bridge().forward().cb()\n"}
    yield "constructor_through_method_return", before, {**before,
          "src/a.py": source.replace("self.cb=first", "self.cb=second")}
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\ndef run(): factory().cb()\n"}
    for i in range(30):
        before[f"src/noise_{i}.py"] = f"def noise_{i}(): return 7\n"
    yield "constructor_with_30_unrelated_files", before, {**before,
          "src/a.py": source.replace("self.cb=first", "self.cb=second")}


if __name__ == "__main__":
    results = [m.run_case(*case) for case in cases()]
    (HERE / "independent-v4-results.json").write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        print(json.dumps({"case": r["case"], "equal": r["equal"],
                          "directional": r["directional"], "differences": r["differences"]}))
    assert all(r["equal"] for r in results), "Incremental/fresh semantic mismatch"
    assert results[1]["directional"]["selected"] == ["src/a.py", "src/b.py"]
