"""Independent review: unknown argument values still have a known providing site."""
import runpy
from pathlib import Path
import pytest

helpers = runpy.run_path(str(Path(__file__).parent / 'test_dependency_origins_independent.py'))
fixture, owner, at, sources = (helpers[k] for k in ('fixture', 'owner', 'at', 'sources'))
from lct.storage import FileDependencies

@pytest.mark.parametrize('argument,reason', [('*values','argument-unpacking'), ('**values','argument-unpacking'), ('','missing-required-argument')])
def test_known_callback_providing_call_is_not_lost_on_unpacking(tmp_path, argument, reason):
    _, _, _, folder, meta, nodes, sites = fixture(tmp_path, {
        'provider.py': 'from worker import execute\ndef provide(values): execute(' + argument + ')\n',
        'worker.py': 'def execute(callback): callback()\n'})
    providing = owner(nodes, 'provider.py', 'provide')
    consumer = owner(nodes, 'worker.py', 'execute')
    call = at(sites, consumer, 'callback')
    assert call['unknown_origin']
    with FileDependencies(folder, meta) as deps:
        rows = sources(deps, consumer, call['site_id'], 'actual-parameter')
        assert any(r['producer_owner'] == providing and r['status'] == 'unknown'
                   and reason in r['detail']['unknown_reasons'] for r in rows), rows
        assert (consumer, call['site_id']) in deps.unit_readers(providing)
