"""Unchanged package layout is still part of a selected import's context."""

import pytest

from lct.storage import build
from tests.test_cross_repository_python_incremental import fixture, records


@pytest.mark.parametrize('layout', ['initializer', 'module'])
def test_unchanged_import_prefix_context_matches_full(tmp_path, layout):
    config, consumer, provider = fixture(tmp_path, pinned=True)
    if layout == 'initializer':
        package = consumer / 'src/dnd5e_engine'
        package.mkdir()
        (package / '__init__.py').write_text('')
    else:
        (consumer / 'src/dnd5e_engine.py').write_text('def unrelated(): pass\n')
    caller = consumer / 'src/caller.py'
    caller.write_text('from dnd5e_engine.evaluation import target\ndef run(): target()\n')
    old = build(config, offline=True, lexical_only=True)
    before = records(config, old['version'])
    caller.write_text(caller.read_text() + 'def extra(): target()\n')
    update = build(config, offline=True, lexical_only=True)
    oracle_config = dict(config, data=str(tmp_path / 'oracle'))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert records(config, update['version']) == records(oracle_config, oracle['version'])
    assert records(config, old['version']) == before
