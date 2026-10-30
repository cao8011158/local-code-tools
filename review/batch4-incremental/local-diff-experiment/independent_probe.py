"""Root-authored independent differential cases; no production changes."""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('local_diff', HERE / 'run.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def cases():
    before = {'src/common.py': 'def helper(): pass\n'}
    for i in range(20):
        before[f'src/client_{i}.py'] = f'from common import helper\ndef f{i}(): helper()\n'
    after = dict(before)
    after['src/client_0.py'] = 'from common import helper\ndef f0():\n helper()\n helper()\n'
    yield 'shared_hub_conservative_expansion', before, after
    before = {
        'src/entry.py': 'def run(): pass\n',
        'src/middle.py': 'from leaf import handler\ndef invoke(): handler()\n',
        'src/leaf.py': 'def handler(): pass\n',
        'src/noise.py': 'def unrelated(): pass\n',
    }
    yield 'new_import_transitive_chain', before, {**before, 'src/entry.py': 'from middle import invoke\ndef run(): invoke()\n'}
    before = {'src/caller.py': 'from absent import callback\ndef invoke(): callback()\n', 'src/noise.py': 'pass\n'}
    yield 'absent_namespace_creation', before, {**before, 'src/absent.py': 'def callback(): pass\n'}


if __name__ == '__main__':
    results = [m.run_case(*c) for c in cases()]
    (HERE / 'independent-results.json').write_text(json.dumps(results, indent=2)+'\n')
    for r in results:
        print(json.dumps({'case': r['case'], 'equal': r['equal'], 'candidate': r['candidate'], 'full': r['full']}))

    # Diagnostic variant: capture syntactic import-name reverse records once from
    # OLD source, then match newly added module names. No new full graph consulted.
    name, before, after = list(cases())[-1]
    old_reverse = {}
    for path, source in before.items():
        for imported in m.imports(source, path):
            old_reverse.setdefault(imported, set()).add(path)
    original = m.file_index
    def supplemented_index(old_graph):
        db = original(old_graph)
        for path in after.keys() - before.keys():
            for importer in old_reverse.get(m.module_name(path), ()):
                db.execute('insert into adjacency values(?,?,?)', (importer, path, 'EXPERIMENT_NEGATIVE_IMPORT'))
        return db
    m.file_index = supplemented_index
    try:
        supplement = m.run_case('absent_namespace_with_old_import_name_index', before, after)
    finally:
        m.file_index = original
    supplement['additional_preparation'] = {'old_import_name_records': sum(map(len, old_reverse.values())), 'old_files_parsed_once_for_index': len(before)}
    (HERE / 'supplement-results.json').write_text(json.dumps(supplement, indent=2)+'\n')
    print(json.dumps({'case': supplement['case'], 'equal': supplement['equal'], 'candidate': supplement['candidate'], 'additional_preparation': supplement['additional_preparation']}))
