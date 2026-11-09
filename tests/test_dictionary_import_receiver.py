"""Imported mutable receiver forms consume Jedi's call-site signatures."""

import pytest

from tests.test_python_pipeline import analyze, expect


@pytest.mark.parametrize("source,expression,expected,unknown", [
    ("registry={'go':first}\nregistry['go']=second\n", "alias['go']", {"second"}, False),
    ("registry={'go':first}\nregistry=object()\nregistry['go']=second\n", "alias['go']", set(), True),
    ("items=[first]\nitems[0]=second\n", "alias[0]", {"second"}, False),
])
def test_imported_receiver_variants(tmp_path, source, expression, expected, unknown):
    name = "items" if source.startswith("items") else "registry"
    result = analyze(tmp_path, {
        "a.py": "def first(): pass\ndef second(): pass\n" + source,
        "b.py": f"from a import {name} as alias\ndef run(): {expression}()\n",
    })
    observed = expect(result, expression, "run", expected, unknown=unknown,
                      complete=not unknown)
    assert observed["target_provider"] == "jedi-get-signatures"
    assert observed["unresolved_reasons"] == (["jedi-no-result"] if unknown else [])
