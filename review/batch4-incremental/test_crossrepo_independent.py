"""Independent cross-repository identity and exact-pin update controls."""

import json
import sqlite3
import subprocess

import pytest

import lct.extract as extraction
from lct.storage import build, manifest
from tests.synthetic_support import initialize


def records(config, version):
    folder, _ = manifest(config, version)
    out = {}
    for filename, tables in (
        ('catalog.sqlite', ('nodes', 'edges')),
        ('graph-sites.sqlite', ('sites', 'query_observations', 'import_dependencies', 'import_requests')),
    ):
        with sqlite3.connect(folder / filename) as db:
            for table in tables:
                out[table] = sorted(json.dumps(json.loads(row[0]), sort_keys=True)
                                    for row in db.execute(f'select data from {table}'))
    return out


def pair(tmp_path):
    config, left = initialize(tmp_path / 'left')
    other, right = initialize(tmp_path / 'right')
    for repo in (left, right):
        (repo / 'src/weights.py').unlink()
    config['repositories'][0]['name'] = 'left'
    second = dict(other['repositories'][0], name='right')
    config['repositories'].append(second)
    return config, left, right


def counted(monkeypatch):
    calls = []
    original = extraction.python_nodes
    def count(file):
        calls.append((file['repository'], file['path']))
        return original(file)
    monkeypatch.setattr(extraction, 'python_nodes', count)
    return calls


@pytest.mark.parametrize('noise', [0, 20])
def test_same_paths_in_other_repository_are_not_selected(tmp_path, monkeypatch, noise):
    config, left, right = pair(tmp_path)
    source = 'def first(): pass\ndef second(): pass\ndef use(): first()\n'
    for repo in (left, right):
        (repo / 'src/a.py').write_text(source)
        (repo / 'src/b.py').write_text('from a import use\ndef run(): use()\n')
    for i in range(noise):
        (right / 'src' / f'unrelated_{i}.py').write_text(source)
    old = build(config, offline=True, lexical_only=True)
    before = records(config, old['version'])
    (left / 'src/a.py').write_text(source.replace('use(): first()', 'use(): second()'))
    calls = counted(monkeypatch)
    update = build(config, offline=True, lexical_only=True)
    assert sorted(calls) == [('left', 'src/a.py'), ('left', 'src/b.py')]
    oracle_config = dict(config, data=str(tmp_path / 'oracle'))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert records(config, update['version']) == records(oracle_config, oracle['version'])
    assert records(config, old['version']) == before


def pinned_pair(tmp_path):
    config, consumer, provider = pair(tmp_path)
    config['repositories'][0]['name'] = 'sm'
    config['repositories'][1]['name'] = 'trpg-rules-engine'
    (provider / 'src/dnd5e_engine').mkdir()
    (provider / 'src/dnd5e_engine/exec.py').write_text('def execute(callback): callback()\n')
    for args in (['add', '-A'], ['-c', 'commit.gpgsign=false', 'commit', '-m', 'provider']):
        subprocess.run(['git', '-C', str(provider), *args], check=True, capture_output=True)
    head = subprocess.check_output(['git', '-C', str(provider), 'rev-parse', 'HEAD'], text=True).strip()
    (consumer / 'pyproject.toml').write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="' + head + '"}\n')
    source = ('from dnd5e_engine.exec import execute\ndef first(): pass\ndef second(): pass\n'
              'def use(): execute(first)\n')
    (consumer / 'src/b.py').write_text(source)
    (provider / 'src/b.py').write_text('def untouched(): pass\n')
    subprocess.run(['git', '-C', str(provider), 'add', '-A'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(provider), '-c', 'commit.gpgsign=false', 'commit', '-m', 'unrelated'], check=True, capture_output=True)
    head = subprocess.check_output(['git', '-C', str(provider), 'rev-parse', 'HEAD'], text=True).strip()
    (consumer / 'pyproject.toml').write_text(
        '[tool.uv.sources]\ndnd5e-engine={git="https://github.com/agentic-trpg/trpg-rules-engine.git",rev="' + head + '"}\n')
    return config, consumer, provider, source


def test_consumer_parameter_change_reanalyzes_bound_provider(tmp_path, monkeypatch):
    config, consumer, provider, source = pinned_pair(tmp_path)
    old = build(config, offline=True, lexical_only=True)
    assert old['graph']['dependency_bindings']['sm']['matched']
    (consumer / 'src/b.py').write_text(source.replace('execute(first)', 'execute(second)'))
    calls = counted(monkeypatch)
    update = build(config, offline=True, lexical_only=True)
    assert sorted(calls) == [('sm', 'src/b.py'), ('trpg-rules-engine', 'src/dnd5e_engine/exec.py')]
    oracle_config = dict(config, data=str(tmp_path / 'oracle'))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert records(config, update['version']) == records(oracle_config, oracle['version'])


def test_provider_dirty_transition_rejects_previous_binding(tmp_path):
    config, consumer, provider, source = pinned_pair(tmp_path)
    old = build(config, offline=True, lexical_only=True)
    assert old['graph']['dependency_bindings']['sm']['matched']
    (provider / 'src/dnd5e_engine/exec.py').write_text('def execute(callback): pass\n')
    update = build(config, offline=True, lexical_only=True)
    assert update['incremental']['analysis_scope']['mode'] == 'full-graph'
    assert not update['graph']['dependency_bindings']['sm']['matched']
    oracle_config = dict(config, data=str(tmp_path / 'oracle'))
    oracle = build(oracle_config, offline=True, lexical_only=True)
    assert records(config, update['version']) == records(oracle_config, oracle['version'])
