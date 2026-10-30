"""Independent root checks of real container processing and retained unknowns."""
from collections import Counter

from lct.python_analysis import Analyzer
from lct.python_effects import EffectCatalog
from tests.test_python_pipeline import analyze, site


B = 'def target(): pass\nregistry={"go": target}\ndef run(): return registry["go"]()\n'


def test_target_processing_and_evidence_ignore_unrelated_local_writers(tmp_path, monkeypatch):
    actual_slots, actual_before = Analyzer.container_slots, EffectCatalog.before
    active = [0]
    visited = []
    def slots(self, atom, *args, **kwargs):
        target = ':src/b.py:' in atom.target
        active[0] += int(target)
        try:
            return actual_slots(self, atom, *args, **kwargs)
        finally:
            active[0] -= int(target)
    def before(self, scope, *args, **kwargs):
        events = actual_before(self, scope, *args, **kwargs)
        if active[0]:
            visited.append((scope, len(events)))
        return events
    monkeypatch.setattr(Analyzer, 'container_slots', slots)
    monkeypatch.setattr(EffectCatalog, 'before', before)
    results = []
    evidence = []
    for noise in (0, 30):
        sources = {'src/b.py': B}
        for i in range(noise):
            sources[f'src/noise_{i}.py'] = 'def write_local():\n values={}\n alias=values\n alias["x"]=1\n'
        visited.clear()
        result = analyze(tmp_path / str(noise), sources)
        selected = site(result, 'registry[\'go\']', 'run')
        assert selected['names'] == {'target'} and selected['complete']
        assert all(':src/b.py:' in scope for scope, _ in visited), visited
        assert all(':src/b.py:' in check['scope'] for check in selected['resolution_decision']['write_source_coverage']['checks'])
        results.append(selected)
        evidence.append(dict(noise=noise, scopes=len(visited), events=sum(count for _, count in visited), visits=dict(Counter(scope for scope, _ in visited))))
    assert results[0] == results[1]
    assert evidence[0]['scopes'] == evidence[1]['scopes']
    assert evidence[0]['events'] == evidence[1]['events']
    print(evidence)


def test_alias_of_imported_container_still_changes_candidates(tmp_path):
    result = analyze(tmp_path, {
        'src/b.py': B,
        'src/writer.py': 'from b import registry\ndef other(): pass\ndef mutate():\n alias=registry\n alias["go"]=other\n',
    })
    selected = site(result, 'registry[\'go\']', 'run')
    assert 'other' in selected['names']
    assert selected['unknown_origin'] and not selected['complete']
    assert any('writer.py' in check['scope'] for check in selected['resolution_decision']['write_source_coverage']['checks'])


def test_local_rebind_to_parameter_is_not_isolated(tmp_path):
    result = analyze(tmp_path, {
        'src/b.py': B,
        'src/writer.py': 'from b import registry\ndef other(): pass\ndef mutate(values):\n local={}\n local=values\n local["go"]=other\ndef run_writer(): mutate(registry)\n',
    })
    selected = site(result, 'registry[\'go\']', 'run')
    assert 'other' in selected['names']
    assert selected['unknown_origin'] and not selected['complete']


def test_dynamic_key_and_nested_scope_are_not_proven_isolated(tmp_path):
    result = analyze(tmp_path, {
        'src/b.py': B,
        'src/keys.py': 'def write_key(key):\n local={}\n local[key]=1\n',
        'src/closure.py': 'def writer():\n local={}\n def nested(): return local\n local["x"]=1\n',
    })
    selected = site(result, 'registry[\'go\']', 'run')
    checks = selected['resolution_decision']['write_source_coverage']['checks']
    assert any(':src/keys.py:' in c['scope'] for c in checks)
    assert any(':src/closure.py:' in c['scope'] for c in checks)
