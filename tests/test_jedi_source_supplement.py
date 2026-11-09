"""Public behavior of the narrow, source-backed Jedi-empty call association."""

import pytest
from unittest.mock import patch
import json
import sqlite3
import subprocess
import sys

import jedi

from lct.storage import build, manifest
from lct.supplemental_calls import SupplementalCalls
from tests.synthetic_support import initialize, forbid_provider
from tests.test_batch3_actual_acceptance import semantic
from tests.semantic_comparison import assert_semantic_equal
from tests.test_python_pipeline import analyze, site


BASE = ("def first(): pass\ndef second(): pass\ndef execute(callback):callback()\n"
        "registry={}\ndef register(key,fn):registry[key]=fn\n"
        "register('a',first)\nregister('b',second)\n"
        "register('dispatch',execute)\n"
        "def run():registry['a']()\n"
        "def run_callback():registry['dispatch'](first)\n"
        "def unknown():unresolved()\n")


def test_exact_registered_key_and_composed_callback_preserve_raw_jedi_empty(tmp_path):
    result = analyze(tmp_path, {'demo.py': BASE}, closed=False)
    for expression, owner, name in (("registry['a']", 'run', 'first'),
                                    ("registry['dispatch']", 'run_callback', 'execute'),
                                    ('callback', 'execute', 'first')):
        row = site(result, expression, owner)
        assert row['names'] == {name}
        assert row['target_provider'] == 'jedi-source-supplement'
        assert row['evidence'][1]['raw'] == []
        assert row['unresolved_reasons'] == ['jedi-no-result']
        assert row['evidence'][2]['sources']
    plain = site(result, 'unresolved', 'unknown')
    assert not plain['targets'] and len(plain['evidence']) == 2
    assert result[2]['supplemental_calls'] == 3


@pytest.mark.parametrize('source', [
    "def first():pass\nregistry={}\nalias=registry\ndef never():alias['a']=first\ndef run():registry['a']()\n",
    "def first():pass\nregistry={}\nalias=registry\nalias['a']=first\nregistry=None\ndef run():registry['a']()\n",
    "def first():pass\nregistry={}\nalias=registry\nalias['a']=first\nregistry.clear()\ndef run():registry['a']()\n",
    "def first():pass\nregistry={}\ndef register(key,fn):registry[key]=fn\n"
    "if flag:register('a',first)\ndef run():registry['a']()\n",
    "def first():pass\nregistry={}\ndef register(key,fn):registry[key]=fn\n"
    "register(unknown_key,first)\nregister('a',first)\ndef run():registry['a']()\n",
    "def first():pass\nregistry={}\ndef register(key,fn):registry[key]=fn\n"
    "def alternate(key,fn):pass\nif flag:choose=register\n"
    "else:choose=alternate\nchoose('a',first)\ndef run():registry['a']()\n",
])
def test_unproved_write_or_receiver_does_not_supply_call_target(tmp_path, source):
    result = analyze(tmp_path, {'demo.py': source}, closed=False)
    row = site(result, "registry['a']", 'run')
    assert row['targets'] == []
    assert row['unresolved_reasons'] == ['jedi-no-result']
    assert len(row['evidence']) == 2


def test_nonempty_jedi_result_never_enters_source_lookup(tmp_path):
    result = analyze(tmp_path, {'demo.py':
        "def first():pass\nregistry={'a':first}\ndef run():registry['a']()\n"},
        closed=False)
    row = site(result, "registry['a']", 'run')
    assert row['names'] == {'first'}
    assert row['target_provider'] == 'jedi-get-signatures'
    assert result[2]['supplemental_source_query_entries'] == 0
    assert result[2]['supplemental_metadata_queries_executed'] == 0


def test_jedi_error_is_not_misread_as_an_empty_observation(tmp_path):
    original = jedi.Script.get_signatures

    def failing(script, line, column):
        if script.path.name == 'demo.py' and line == 6:
            raise RuntimeError('injected final query error')
        return original(script, line, column)

    source = "def first():pass\nregistry={}\nalias=registry\nalias['a']=first\n\ndef run():registry['a']()\n"
    with patch.object(jedi.Script, 'get_signatures', failing):
        result = analyze(tmp_path, {'demo.py': source}, closed=False)
    row = site(result, "registry['a']", 'run')
    assert row['targets'] == []
    assert row['unresolved_reasons'] == ['jedi-error:RuntimeError']
    assert row['evidence'][1]['raw'][0]['mapping'] == 'jedi-error'
    assert result[2]['supplemental_source_query_entries'] == 0


@pytest.mark.parametrize('noise', [0, 20, 100])
def test_exact_key_source_queries_do_not_grow_with_unrelated_calls(tmp_path, noise):
    sources = {'demo.py':
        "def first():pass\nregistry={}\ndef register(key,fn):registry[key]=fn\n"
        "register('a',first)\ndef run():registry['a']()\n"}
    sources.update({f'idle_{n}.py': 'def idle(opaque):opaque()\n'
                    for n in range(noise)})
    result = analyze(tmp_path, sources, closed=False)
    assert site(result, "registry['a']", 'run')['names'] == {'first'}
    assert result[2]['supplemental_source_query_entries'] == 1
    assert result[2]['supplemental_metadata_queries_executed'] == 0


def test_cross_file_source_survives_consumer_edit_and_restart(tmp_path):
    config, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    config['retained_versions'] = 8
    provider = repo / 'src/provider.py'
    consumer = repo / 'src/consumer.py'
    provider.write_text("def first():pass\ndef second():pass\nregistry={}\n"
                        "def register(k,f):registry[k]=f\nregister('a',first)\n")
    consumer.write_text("from provider import registry\ndef run():registry['a']()\n")

    def row(version):
        folder, _ = manifest(config, version)
        with sqlite3.connect(folder / 'graph-sites.sqlite') as db:
            return next(json.loads(raw) for (raw,) in db.execute('select data from sites')
                        if json.loads(raw)['expression'] == "registry['a']")

    with forbid_provider():
        cold = build(config, offline=True, lexical_only=True)
    original = row(cold['version'])
    assert original['targets'] and original['evidence'][1]['raw'] == []
    consumer.write_text("from provider import registry\ndef run():return registry['a']()\n")
    with forbid_provider():
        updated = build(config, offline=True, lexical_only=True)
    assert row(updated['version'])['targets'] == original['targets']
    assert row(cold['version']) == original
    provider.write_text(provider.read_text().replace("register('a',first)",
                                                      "register('a',second)"))
    command = ('import json,sys; from lct.storage import build; '
               'print(json.dumps(build(json.load(sys.stdin),offline=True,lexical_only=True)))')
    with forbid_provider():
        child = subprocess.run([sys.executable, '-c', command], input=json.dumps(config),
                               text=True, capture_output=True, check=True)
    changed = json.loads(child.stdout)
    assert row(changed['version'])['targets'] != original['targets']
    assert row(cold['version']) == original
    fresh_config = dict(config, data=str(tmp_path / 'fresh'))
    with forbid_provider():
        fresh = build(fresh_config, offline=True, lexical_only=True)
    assert_semantic_equal(semantic(config, changed['version']),
                          semantic(fresh_config, fresh['version']))


@pytest.mark.parametrize('noise', [0, 20, 100])
def test_plain_unknown_does_not_prepare_unrelated_container_writes(tmp_path, noise):
    source = ("def first():pass\ndef run():unknown()\n" +
              "\n".join(f"registry_{n}={{'a':first}}" for n in range(noise)) + "\n")

    def forbidden(*args, **kwargs):
        raise AssertionError('unrelated supplement write preparation')

    with patch.object(SupplementalCalls, '_append_write', forbidden):
        result = analyze(tmp_path, {'demo.py': source}, closed=False)
    row = site(result, 'unknown', 'run')
    assert row['target_provider'] == 'jedi-get-signatures'
    assert result[2]['supplemental_calls'] == 0
    assert result[2]['supplemental_source_query_entries'] == 0
