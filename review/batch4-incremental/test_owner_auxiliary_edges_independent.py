"""Shared import lookup edges must retain only surviving import supports."""
from pathlib import Path
import runpy

import pytest

helpers = runpy.run_path(str(Path(__file__).with_name("test_owner_update_independent.py")))


@pytest.mark.parametrize("other_importer", [False, True])
def test_missing_name_lookup_retarget_preserves_other_import_support(tmp_path, other_importer):
    sources = {"a.py": "from b import missing\n",
               "b.py": "def foo(): pass\n", "c.py": "def foo(): pass\n"}
    if other_importer:
        sources["other.py"] = "from b import missing\n"
    config, repo = helpers["fixture"](tmp_path, sources)
    config["retained_versions"] = 4
    first = helpers["build"](config, offline=True, lexical_only=True)
    before = helpers["records"](config, first["version"])
    for index, module in enumerate(("c", "b")):
        (repo / "src/a.py").write_text(f"from {module} import missing\n")
        updated = helpers["build"](config, offline=True, lexical_only=True)
        scope = updated["incremental"]["analysis_scope"]
        assert scope["mode"] == "incremental-owners", scope
        assert scope["total_python_files_parsed"] == 1
        helpers["oracle"](config, updated["version"], tmp_path, f"oracle-{index}")
    assert helpers["records"](config, first["version"]) == before
