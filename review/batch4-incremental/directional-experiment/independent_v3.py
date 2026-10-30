"""Independent third-round probes; failures are evidence, not suppressed assertions."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("v3_root_probe", HERE / "v3.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.v1.schedule = m.schedule


def cases():
    source = ("def first(): pass\ndef second(): pass\nclass Box:\n"
              " def __init__(self, cb): self.cb=cb\ndef factory():\n"
              " value=Box(first)\n return value\n")
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\ndef callback():\n box=factory()\n return box.cb\n",
              "src/c.py": "from b import callback\ndef run(): callback()()\n"}
    yield "field_extracted_then_forwarded", before, {**before,
          "src/a.py": source.replace("Box(first)", "Box(second)")}
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\ndef discard():\n box=factory()\n return 7\n",
              "src/c.py": "from b import discard\ndef run(): discard()\n"}
    yield "discard_object_return_constant", before, {**before,
          "src/a.py": source.replace("Box(first)", "Box(second)")}
    source = ("def first(): pass\ndef second(): pass\nclass Box:\n"
              " def __init__(self): self.cb=first\ndef factory():\n"
              " value=Box()\n return value\n")
    before = {"src/a.py": source,
              "src/b.py": "from a import factory\ndef run(): factory().cb()\n"}
    yield "constructor_field_changes_factory_unchanged", before, {**before,
          "src/a.py": source.replace("self.cb=first", "self.cb=second")}


if __name__ == "__main__":
    results = [m.run_case(*case) for case in cases()]
    (HERE / "independent-v3-results.json").write_text(json.dumps(results, indent=2) + "\n")
    for r in results:
        print(json.dumps({"case": r["case"], "equal": r["equal"],
                          "directional": r["directional"], "differences": r["differences"]}))
