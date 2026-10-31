"""Bounded analysis of captured business bytes, with complete graph oracle."""

import json
import shutil
import sqlite3
from pathlib import Path

from lct.simple_python import CERTIFICATE
from lct.storage import build, manifest
from tests.synthetic_support import initialize

SOURCE = (Path(__file__).parents[1] / "review/batch4-incremental/fixtures"
          / "actual-source-subset/src/trpg_state_machine/item_units.py")


def records(config, version):
    folder, _ = manifest(config, version)
    output = {}
    for filename, tables in (("catalog.sqlite", ("nodes", "edges")),
                             ("graph-sites.sqlite", ("sites", "query_observations",
                                                     "import_dependencies", "import_requests"))):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                output[table] = sorted(json.dumps(json.loads(raw), sort_keys=True)
                                       for (raw,) in db.execute(f"select data from {table}"))
    return output


def setup(tmp_path, *, caller=False):
    config, repo = initialize(tmp_path / "isolated")
    (repo / "src/weights.py").unlink()
    (repo / "docs/guide.md").unlink()
    module = repo / "src/trpg_state_machine/item_units.py"
    module.parent.mkdir()
    shutil.copyfile(SOURCE, module)
    for number in range(20):
        (repo / f"src/unrelated_{number}.py").write_text(
            f"def unrelated_{number}():\n    return {number}\n")
    if caller:
        (repo / "src/caller.py").write_text(
            "from trpg_state_machine.item_units import valid_item_unit\n"
            "def use(data):\n    return valid_item_unit(data)\n")
    return config, repo, module


def oracle(tmp_path, config, updated):
    fresh_config = dict(config, data=str(tmp_path / "full-oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, updated["version"]) == records(fresh_config, fresh["version"])


def test_actual_item_unit_local_with_unrelated_growth(tmp_path):
    config, repo, module = setup(tmp_path)
    baseline = build(config, offline=True, lexical_only=True)
    assert baseline["simple_python_certificate"] == CERTIFICATE
    old = records(config, baseline["version"])
    source = module.read_bytes()
    assert source == SOURCE.read_bytes()
    module.write_bytes(source.replace(b"2**63 - 1", b"2**63 - 2"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["python_files_parsed"] == 1
    assert scope["python_ast_context_files"] == 1
    assert scope["reused_python_files"] == 20
    assert records(config, baseline["version"]) == old
    oracle(tmp_path, config, updated)


def test_actual_item_unit_importer_reanalyzed_and_shadow_falls_back(tmp_path):
    config, repo, module = setup(tmp_path, caller=True)
    baseline = build(config, offline=True, lexical_only=True)
    before = records(config, baseline["version"])
    module.write_bytes(module.read_bytes().replace(b"2**63 - 1", b"2**63 - 2"))
    updated = build(config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners"
    assert scope["python_files_parsed"] == 1
    assert scope["reused_python_files"] == 21
    assert records(config, baseline["version"]) == before
    oracle(tmp_path, config, updated)

    # A newly captured local module can change where `import re` resolves.
    (repo / "src/re.py").write_text("def fullmatch(pattern, value):\n    return None\n")
    shadow = build(config, offline=True, lexical_only=True)
    assert shadow["incremental"]["analysis_scope"]["mode"] == "full-graph"
    fresh_config = dict(config, data=str(tmp_path / "shadow-oracle"))
    fresh = build(fresh_config, offline=True, lexical_only=True)
    assert records(config, shadow["version"]) == records(fresh_config, fresh["version"])


def test_builtin_shadow_or_ordered_guard_rejects_certificate(tmp_path):
    config, repo, module = setup(tmp_path)
    raw = module.read_text()
    assert "type(data) is dict" in raw
    assert "data[\"quantity\"] == 1" in raw
    for changed in (raw.replace("type(data) is dict", "data[\"quantity\"] == 1", 1),
                    raw + "\ndef type(value):\n    return int\n",
                    raw.replace("def valid_item_unit(data):", "def valid_item_unit(data, type):"),
                    'def f(x):\n    return (type(x) is int) is False and x <= 0\n',
                    'def f(x):\n    return (type(x) is int) == False and x <= 0\n',
                    'def f(x):\n    return type(x) is int and 1 ** x <= 1\n',
                    'def mutate(x):\n    return None\n'
                    'def f(data):\n    return type(data) is dict and '
                    'type(data["x"]) is int and mutate(data) is None and data["x"] <= 0\n',
                    'def mutate(x):\n    return None\n'
                    'def f(data):\n    return type(data) is dict and '
                    'type(data["x"]) is int and mutate(data) is None is (data["x"] <= 3)\n',
                    'from helper import f as type\ndef f(x):\n    return type(x) is int and x <= 0\n'):
        module.write_text(changed)
        result = build(config, offline=True, lexical_only=True)
        assert result["simple_python_certificate"] is None


def test_new_helper_bindings_cannot_escape_or_impersonate_stdlib(tmp_path):
    config, _, module = setup(tmp_path)
    raw = module.read_text()
    for changed in (raw + "\ndef escape():\n    return re.fullmatch\n",
                    raw + "\ndef escape():\n    return re\n",
                    raw + "\ndef escape():\n    return type\n",
                    raw + "\ndef escape(data):\n    cb = re.fullmatch\n    return cb(data)\n",
                    raw + "\ndef escape(data):\n    cb = set\n    return cb(data)\n",
                    raw.replace("import re", "from helper import f as re")):
        module.write_text(changed)
        result = build(config, offline=True, lexical_only=True)
        assert result["simple_python_certificate"] is None
