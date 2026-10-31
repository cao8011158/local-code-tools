"""Source-only Jedi input footprint; never builds the LCT graph or executes source."""
import argparse
import ast
import collections
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import jedi
from jedi import file_io
from jedi import inference
from jedi.inference import imports, references, dynamic_params
from jedi.inference.compiled import subprocess as compiled_subprocess

from lct.common import inventory
from lct.extract import extract
from lct.graph import Graph
from lct.python_analysis import Analyzer
from tests.synthetic_support import initialize


SOURCE = Path(__file__).parent / 'fixtures'
EVENTS = collections.defaultdict(list)
PHASE = ['setup']
ACTIVE_REGEX = []


def path_hint(path):
    if path is None:
        return None
    value = str(path)
    if '/lct-python-' in value:
        return value[value.index('/lct-python-') + 1:].split('/', 1)[-1]
    if '/source/' in value:
        return value.split('/source/', 1)[-1]
    return value if len(value) < 100 else value[-100:]


def record(kind, **values):
    EVENTS[PHASE[0]].append(dict(kind=kind, **values))


def hooks():
    original_parse = inference.InferenceState.parse_and_get_code
    def parse(self, code=None, path=None, **kwargs):
        record('parse', path=path_hint(path), supplied=code is not None,
               supplied_sha=hashlib.sha256(code if isinstance(code, bytes) else
                   code.encode()).hexdigest() if code is not None else None)
        return original_parse(self, code=code, path=path, **kwargs)
    inference.InferenceState.parse_and_get_code = parse

    original_read = file_io.FileIO.read
    def read(self):
        data = original_read(self)
        extra = {}
        if ACTIVE_REGEX:
            regex = ACTIVE_REGEX[-1]
            extra = dict(pattern=regex.pattern, regex_matched=bool(regex.search(
                references.python_bytes_to_unicode(data, errors='replace'))))
        record('file-read', path=path_hint(self.path), sha256=hashlib.sha256(data).hexdigest(),
               **extra)
        return data
    file_io.FileIO.read = read

    original_get = imports.ModuleCache.get
    def get(self, names):
        value = original_get(self, names)
        record('module-cache', name='.'.join(names) if names else '', hit=value is not None)
        return value
    imports.ModuleCache.get = get

    original_attr = compiled_subprocess.InferenceStateSubprocess.__getattr__
    def attr(self, name):
        callable_ = original_attr(self, name)
        if name != 'get_module_info':
            return callable_
        def wrapped(*args, **kwargs):
            value = callable_(*args, **kwargs)
            found = value[1] is not None if isinstance(value, tuple) and len(value) > 1 else None
            record('module-info', name=kwargs.get('full_name'), found=found,
                   global_search=kwargs.get('is_global_search'))
            return value
        return wrapped
    compiled_subprocess.InferenceStateSubprocess.__getattr__ = attr

    original_search = references.search_in_file_ios
    def search(state, iterator, name, **kwargs):
        candidates = []
        def traced():
            for file in iterator:
                candidates.append(path_hint(file.path))
                yield file
        result = original_search(state, traced(), name, **kwargs)
        for item in result:
            yield item
        record('name-search', name=name, checked=candidates, checked_count=len(candidates))
    references.search_in_file_ios = search

    original_check = references._check_fs
    def check(state, file, regex):
        ACTIVE_REGEX.append(regex)
        try:
            value = original_check(state, file, regex)
        finally:
            ACTIVE_REGEX.pop()
        record('name-file-check', path=path_hint(file.path), context_returned=value is not None,
               pattern=regex.pattern)
        return value
    references._check_fs = check

    original_dynamic = dynamic_params._search_function_arguments
    def dynamic(module, funcdef, string_name):
        values = original_dynamic(module, funcdef, string_name)
        record('dynamic-arguments', name=string_name, results=len(values))
        return values
    dynamic_params._search_function_arguments = dynamic


def run(noise, mutate):
    with tempfile.TemporaryDirectory(prefix='jedi-inputs-') as temporary:
        config, repo = initialize(Path(temporary) / 'capture')
        (repo / 'src/weights.py').unlink()
        (repo / 'docs/guide.md').unlink()
        package = repo / 'src/trpg_state_machine'
        package.mkdir()
        for name, fixture in (('item_units.py', SOURCE / 'actual-source-subset/src/trpg_state_machine/item_units.py'),
                              ('errors.py', SOURCE / 'actual-source-subset/src/trpg_state_machine/errors.py'),
                              ('_execution.py', SOURCE / 'actual-related-source/src/trpg_state_machine/_execution.py')):
            shutil.copyfile(fixture, package / name)
        if mutate:
            target = package / '_execution.py'
            original = target.read_bytes()
            assert b'"actor"' in original
            target.write_bytes(original.replace(b'"actor"', b'"actor_changed"', 1))
        for index in range(noise):
            (repo / f'src/idle_{index}.py').write_text(f'def idle_{index}():\n    return {index}\n')
        files, repos, _ = inventory(config)
        nodes, asts = extract(files)
        graph = Graph(nodes, asts, repos)
        hooks()
        PHASE[0] = 'initialize'
        analyzer = Analyzer(graph.nodes, asts, graph.repos, graph.imported)
        try:
            scope = next(ident for ident, node in graph.nodes.items()
                         if node['kind'] == 'function' and node['path'].endswith('/item_units.py')
                         and node['name'] == 'valid_item_unit')
            tree = asts[scope]
            data = next(expr for expr in ast.walk(tree) if isinstance(expr, ast.Name)
                        and expr.id == 'data' and isinstance(expr.ctx, ast.Load))
            re_call = next(expr for expr in ast.walk(tree) if isinstance(expr, ast.Attribute)
                           and expr.attr == 'fullmatch' and isinstance(expr.value, ast.Name)
                           and expr.value.id == 're')
            outcomes = {}
            for label, expr in (('data-cold', data), ('data-hot', data),
                                ('re-cold', re_call), ('re-hot', re_call)):
                PHASE[0] = label
                result = analyzer.query(scope, expr)
                outcomes[label] = dict(atoms=sorted((a.kind, a.target) for a in result.atoms),
                                       reasons=sorted(result.reasons),
                                       executed_queries=analyzer.executed_queries)
        finally:
            analyzer.close()
    print(json.dumps(dict(jedi=jedi.__version__, noise=noise, mutate=mutate,
                          outcomes=outcomes, events=EVENTS), sort_keys=True, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--noise', type=int, default=0)
    parser.add_argument('--mutate', action='store_true')
    args = parser.parse_args()
    run(args.noise, args.mutate)
