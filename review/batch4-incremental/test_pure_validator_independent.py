"""Independent negative guards for the real-source validator certificate."""

import pytest

from lct.extract import python_nodes
from lct.simple_python import certify


@pytest.mark.parametrize("source", [
    "def f(x): return type(x) is int or x > 0\n",
    "def f(x): return x > 0 and type(x) is int\n",
    "def f(x, type): return type(x) is int and x > 0\n",
    "def f(x, int): return type(x) is int and x > 0\n",
    "def f(x, y): return type(x) is int and type(y) is int and x ** y <= 3\n",
    "def f(x): return (type(x) is int) is False and x <= 0\n",
    "def f(x): return (type(x) is int) == False and x <= 0\n",
    "def mutate(x): pass\ndef f(data): return type(data) is dict and type(data['x']) is int and mutate(data) is None and data['x'] <= 0\n",
    "def mutate(x): pass\ndef f(data): return type(data) is dict and type(data['x']) is int and mutate(data) is None is (data['x'] <= 3)\n",
    'import re\ndef f(data): return type(data) is dict and re.fullmatch("x", data["x"])\n',
    'import re\ndef f(data): return type(data) is dict and re.fullmatch(data["pattern"], "x")\n',
    'import re\ndef f(data): return type(data) is dict and re.compile("x")\n',
    'import re\ndef f(x):\n match = re.fullmatch\n return match(x)\n',
    'import re\ndef f(): return re.fullmatch\n',
    'def f(x):\n convert = set\n return convert(x)\n',
])
def test_unsafe_guard_does_not_authorize_local_reuse(source):
    file = dict(repository="review", path="src/validator.py", text=source,
                sha256="review", snapshot_id="review", is_test=False)
    _, trees = python_nodes(file)
    assert certify([file], trees) is None


@pytest.mark.parametrize("noise", [0, 20])
def test_real_validator_measured_parse_scope(tmp_path, monkeypatch, noise):
    import lct.extract as extraction
    from lct.storage import build
    from tests.test_actual_item_unit_incremental import oracle, records, setup

    config, repo, module = setup(tmp_path)
    if noise == 0:
        for path in (repo / "src").glob("unrelated_*.py"):
            path.unlink()
    first = build(config, offline=True, lexical_only=True)
    before = records(config, first["version"])
    module.write_bytes(module.read_bytes().replace(b"2**63 - 1", b"2**62 - 1"))
    parsed = []
    original = extraction.python_nodes
    def counted(file):
        parsed.append((file["repository"], file["path"]))
        return original(file)
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "python_nodes", counted)
        result = build(config, offline=True, lexical_only=True)
    assert [path for _, path in parsed] == ["src/trpg_state_machine/item_units.py"]
    scope = result["incremental"]["analysis_scope"]
    if noise:
        assert scope["mode"] == "certified-simple-python-component"
        assert scope["reused_python_files"] == noise
    else:
        assert scope["mode"] == "full-graph"
        assert scope["reason"] == "no-unchanged-python-modules"
        assert scope["total_python_files_parsed"] == 1
    assert records(config, first["version"]) == before
    oracle(tmp_path, config, result)
    print({"unrelated_files": noise, "actual_parse_calls": len(parsed),
           "scope": result["incremental"]["analysis_scope"]})
