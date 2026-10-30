"""Independent public-build controls for partial container analysis dependencies."""
import json

import pytest

from lct.common import ToolError
from lct.storage import FileDependencies, build, current, manifest
from tests.synthetic_support import initialize


B = 'def target(): pass\nregistry={"go":target}\ndef run(): registry["go"]()\n'
ISOLATED = 'def writer():\n local={}\n local["x"]=1\n'
UNCERTAIN = 'def writer(key):\n local={}\n local[key]=1\n'


def make(tmp_path):
    config, repo = initialize(tmp_path / 'fixture')
    (repo / 'src/weights.py').unlink()
    (repo / 'docs/guide.md').unlink()
    return config, repo


def test_subscription_precedes_new_writer_and_failed_publish_keeps_old_reads(tmp_path):
    config, repo = make(tmp_path)
    (repo / 'src/b.py').write_text(B)
    first = build(config, offline=True, lexical_only=True)
    old_folder, old_meta = manifest(config, first['version'])
    consumer = ('synthetic-review', 'src/b.py')
    with FileDependencies(old_folder, old_meta) as deps:
        assert deps.analysis_watchers('slot-writer-universe') == {consumer}
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == set()
    (repo / 'src/a.py').write_text(UNCERTAIN)
    with pytest.raises(ToolError, match='Injected interruption'):
        build(config, offline=True, lexical_only=True, fail_at='before_publish')
    assert current(config) == first['version']
    with FileDependencies(old_folder, old_meta) as deps:
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == set()
    second = build(config, offline=True, lexical_only=True)
    folder, meta = manifest(config, second['version'])
    with FileDependencies(folder, meta) as deps:
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == {consumer}
        assert deps.adjacent('synthetic-review', 'src/a.py') == set()
    identical = build(config, offline=True, lexical_only=True)
    same_folder, same_meta = manifest(config, identical['version'])
    assert identical['incremental']['analysis_scope']['mode'] == 'identical-python-capture-reuse'
    with FileDependencies(same_folder, same_meta) as deps:
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == {consumer}
        assert deps.analysis_watchers('slot-writer-universe') == {consumer}
    (repo / 'src/a.py').write_text(ISOLATED)
    third = build(config, offline=True, lexical_only=True)
    new_folder, new_meta = manifest(config, third['version'])
    with FileDependencies(new_folder, new_meta) as deps:
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == set()
        assert deps.analysis_watchers('slot-writer-universe') == {consumer}
    with FileDependencies(folder, meta) as deps:
        assert deps.analysis_readers('synthetic-review', 'src/a.py') == {consumer}


def test_actual_index_lookup_is_scoped_under_unrelated_read_growth(tmp_path):
    rows = []
    for noise in (0, 40):
        config, repo = make(tmp_path / str(noise))
        (repo / 'src/a.py').write_text('def target(): pass\nregistry={"go":target}\n')
        (repo / 'src/b.py').write_text('from a import registry\ndef run(): registry["go"]()\n')
        for i in range(noise):
            (repo / f'src/noise_{i}.py').write_text(f'def target_{i}(): pass\nlocal={{"go":target_{i}}}\ndef run(): local["go"]()\n')
        snapshot = build(config, offline=True, lexical_only=True)
        folder, meta = manifest(config, snapshot['version'])
        with FileDependencies(folder, meta) as deps:
            sql = []; steps = [0]
            deps.db.set_trace_callback(sql.append)
            def tick():
                steps[0] += 1
                return 0
            deps.db.set_progress_handler(tick, 1)
            found = deps.analysis_readers('synthetic-review', 'src/a.py')
            assert found == {('synthetic-review', 'src/b.py')}
            assert deps.analysis_readers('foreign', 'src/a.py') == set()
            deps.db.set_trace_callback(None)
            deps.db.set_progress_handler(None, 0)
            plans = [r[3] for query in sql for r in deps.db.execute('explain query plan ' + query)]
            assert plans and all('SEARCH' in p and 'SCAN' not in p for p in plans), plans
            rows.append(dict(noise=noise, queries=len(sql), result_rows=len(found), vm_steps=steps[0], plans=plans))
        assert '_analysis_reads' not in meta['graph']
        assert '_analysis_watches' not in meta['graph']
    assert rows[0]['queries'] == rows[1]['queries']
    print(json.dumps(rows, sort_keys=True))


def test_recording_budget_does_not_change_analysis_results(tmp_path, monkeypatch):
    import lct.python_analysis as analysis
    from tests.test_python_pipeline import analyze

    sources = {'src/b.py': B, 'src/a.py': UNCERTAIN}
    before = analyze(tmp_path, sources)
    monkeypatch.setattr(analysis, 'ANALYSIS_DEPENDENCY_LIMIT', 1)
    limited = analyze(tmp_path, sources)
    assert before[0] == limited[0]
    assert before[1] == limited[1]
    assert before[2]['sites'] == limited[2]['sites']
    assert limited[2]['_analysis_dependency_truncated'] is True
    assert len(limited[2]['_analysis_reads']) + len(limited[2]['_analysis_watches']) <= 1
