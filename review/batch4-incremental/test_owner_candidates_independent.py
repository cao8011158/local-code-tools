"""Keep new higher-order callees correct across shared-analyser iterations."""
from pathlib import Path
import runpy

import pytest

helpers = runpy.run_path(str(Path(__file__).with_name("test_owner_update_independent.py")))


@pytest.mark.parametrize("closed", [False, True])
def test_retargeted_returned_callback_matches_full_after_two_passes(tmp_path, closed):
    sources = {
        "functions.py": "def first(cb): return cb\ndef second(cb): return cb\n"
                        "def alpha(): return 1\ndef beta(): return 2\n",
        "worker.py": "def apply(callback, value): return callback(value)\n"
                     "def other(callback, value): return callback(value)\n",
        "existing.py": "from functions import first, alpha\nfrom worker import apply\n"
                       "def old(): return apply(first, alpha)\n",
        "changed.py": "from functions import second, beta\nfrom worker import apply, other\n"
                      "def run():\n    fn = other(second, beta)\n    return fn()\n",
    }
    config, repo = helpers["fixture"](tmp_path, sources)
    config["repositories"][0]["closed_world"] = closed
    helpers["build"](config, offline=True, lexical_only=True)
    (repo / "src/changed.py").write_text(
        sources["changed.py"].replace("fn = other", "fn = apply"))
    updated = helpers["build"](config, offline=True, lexical_only=True)
    scope = updated["incremental"]["analysis_scope"]
    assert scope["mode"] == "incremental-owners", scope
    assert scope["total_python_files_parsed"] == 1
    assert scope["owner_analysis_iterations"] >= 2
    helpers["oracle"](config, updated["version"], tmp_path)
