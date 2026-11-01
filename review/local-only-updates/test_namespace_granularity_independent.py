"""External reviewer harness: namespace invalidation stays at consuming owners."""
import runpy
from pathlib import Path

import pytest

flows = runpy.run_path(str(Path(__file__).with_name("test_local_only_flow_independent.py")))


@pytest.mark.parametrize("missing_module", [False, True])
def test_new_import_target_keeps_unrelated_sibling_function_unselected(tmp_path, missing_module):
    sources = {
        "consumer.py": "from provider import later\nfrom other import leaf\n"
                       "def run(): later()\ndef unrelated(): leaf()\n",
        "other.py": "def leaf(): return 1\n"}
    if not missing_module:
        sources["provider.py"] = "def existing(): return 1\n"
    c, repo = flows["setup_sources"](tmp_path, sources)
    (repo / "src/provider.py").write_text("def existing(): return 1\ndef later(): return 2\n")
    updated = flows["local_update"](c)
    assert flows["call_targets"](c, updated, "run", "later") == {"later"}
    assert not any(":function:unrelated#" in name
                   for name in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-namespace")


def test_missing_module_appearing_updates_module_alias_consumer_only(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import later\nalias=later\nfrom other import leaf\n"
                       "def run(): alias()\ndef unrelated(): leaf()\n",
        "other.py": "def leaf(): return 1\n"})
    (repo / "src/provider.py").write_text("def later(): return 2\n")
    updated = flows["local_update"](c)
    assert flows["call_targets"](c, updated, "run", "alias") == {"later"}
    assert not any(":function:unrelated#" in name
                   for name in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-alias")


def test_metadata_import_refresh_does_not_invalidate_other_default_callback(tmp_path):
    c, repo = flows["setup_sources"](tmp_path, {
        "consumer.py": "from provider import work\nfrom other import leaf\n"
                       "def run(): work()\ndef unrelated(fn=leaf): fn()\n",
        "provider.py": "def work(): return 1\n", "other.py": "def leaf(): return 1\n"})
    (repo / "src/provider.py").write_text("def work(): return 2\n")
    updated = flows["local_update"](c)
    assert not any(":function:unrelated#" in name
                   for name in updated["incremental"]["analysis_scope"]["selected_owner_ids"])
    flows["compare_fresh"](c, updated, tmp_path, "fresh-default")
