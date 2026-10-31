"""Exact captured receiver mapping for an imported dictionary mutation."""

from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze, site


def test_import_mapping_uses_subscript_receiver_binding(tmp_path, monkeypatch):
    seen = []
    original = Analyzer.map_name

    def collect(self, name):
        value, raw = original(self, name)
        if raw.get("mapping") == "exact-captured-subscript-receiver":
            seen.append((raw, value))
        return value, raw

    monkeypatch.setattr(Analyzer, "map_name", collect)
    result = analyze(tmp_path, {
        "a.py": ("def first(): pass\ndef second(): pass\n"
                 "registry={'go':first}\nregistry['go']=second\n"),
        "b.py": "from a import registry as alias\ndef run(): alias['go']()\n",
    })
    found = site(result, "alias['go']", "run")
    assert found["names"] == {"second"} and found["complete"]
    assert seen
    assert any(raw["name"] == "registry" and raw["line"] == 4
               and {a.kind for a in value.atoms} == {"container"}
               and not value.unknown for raw, value in seen)


def test_later_rebinding_does_not_pretend_subscript_target_is_container(tmp_path):
    result = analyze(tmp_path, {
        "a.py": ("def first(): pass\ndef second(): pass\n"
                 "registry={'go':first}\nregistry=object()\nregistry['go']=second\n"),
        "b.py": "from a import registry\ndef run(): registry['go']()\n",
    })
    found = site(result, "registry['go']", "run")
    assert not found["complete"] and found["unknown_origin"]
    assert found["names"] != {"second"}


def test_sequence_receiver_is_outside_dictionary_mapping(tmp_path, monkeypatch):
    mapped = []
    original = Analyzer.map_name

    def collect(self, name):
        value, raw = original(self, name)
        if raw.get("mapping") == "exact-captured-subscript-receiver":
            mapped.append(raw)
        return value, raw

    monkeypatch.setattr(Analyzer, "map_name", collect)
    analyze(tmp_path, {
        "a.py": "def first(): pass\ndef second(): pass\nitems=[first]\nitems[0]=second\n",
        "b.py": "from a import items\ndef run(): items[0]()\n",
    })
    assert mapped == []
