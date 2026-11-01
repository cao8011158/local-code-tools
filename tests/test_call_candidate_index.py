"""Caller admission follows explicit target or spelling evidence."""

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph
from lct.python_analysis import Analyzer, known, unknown


def analyzer(tmp_path, extras=0):
    text = ("def target(x): pass\ndef other(x): pass\n"
            "class C:\n def run(self,x): pass\n"
            "def caller(obj,callback):\n"
            " alias=target\n alias(1)\n obj.run(2)\n callback(3)\n"
            " target(4)\n other(5)\n" +
            ''.join(f' other({i})\n' for i in range(extras)))
    ns, trees = python_nodes(dict(repository='fixture', path='demo.py', text=text,
                                  sha256=digest(text), is_test=False))
    graph = Graph(ns, trees, [dict(name='fixture', path=str(tmp_path),
                                   head='captured', closed_world=False)])
    a = Analyzer(graph.nodes, trees, graph.repos, graph.imported)
    return a, next(n['node_id'] for n in ns if n['qualname'] == 'target')


def key(a, site):
    expr = site['_expr']
    return (a.module_for[site['execution_owner']], expr.end_lineno,
            expr.end_col_offset, False)


def admitted(a, function, sites):
    return [site for site in sites if site['_call'] is not None and a.may_call(function, site)]


def test_cold_and_warm_admission_avoids_unrelated_unknowns(tmp_path):
    a, target = analyzer(tmp_path, extras=300)
    try:
        cold = list(a.candidate_sites(target))
        assert [s['expression'] for s in cold] == ['alias', 'target']
        # Model cached observations produced in normal site order: a different
            # spelling may be an alias; failed observations stay on their site.
        aliases = {'alias', 'run'}
        for site in a.sites:
            if site['_call'] is None:
                continue
            spelling = site['_expr'].id if hasattr(site['_expr'], 'id') else site['_expr'].attr
            if spelling in aliases:
                result = known('callable', target)
            elif spelling == 'callback':
                result = unknown('jedi-error:RuntimeError')
            else:
                result = known('callable', 'another-node')
            observation = key(a, site)
            a.queries[observation] = result, []
            a._observe_query(observation, result)
        candidates = list(a.candidate_sites(target))
        assert [s['expression'] for s in candidates] == ['alias', 'obj.run']
        assert admitted(a, target, candidates) == candidates
        assert len(candidates) == 2
        a._query_inflight = 1
        assert list(a.candidate_sites(target)) == candidates
        a._query_inflight = 0
        a.sites.append(dict(_call=None))
        assert list(a.candidate_sites(target)) == candidates
        assert a.candidate_unknown_bucket_visits == 0
    finally:
        a.close()


def test_actual_failed_query_is_preserved_without_unrelated_admission(tmp_path):
    a, target = analyzer(tmp_path)
    try:
        site = next(s for s in a.sites if s['expression'] == 'callback')
        module = a.module_for[site['execution_owner']]
        class FailedScript:
            def infer(self, *_):
                raise RuntimeError('synthetic Jedi failure')
        a.scripts[module] = FailedScript()
        result = a.query(site['execution_owner'], site['_expr'])
        assert not result.atoms and 'jedi-error:RuntimeError' in result.reasons
        assert site not in a.candidate_sites(target)
    finally:
        a.close()


def test_graph_prepares_each_site_once_without_function_times_unknown_visits(tmp_path):
    observations = []
    for noise in (0, 20):
        source = ('def first(): pass\ndef target(cb): cb()\n'
                  'def driver(): target(first)\n' +
                  ''.join(f'def idle_{i}(opaque): opaque()\n' for i in range(noise)))
        ns, trees = python_nodes(dict(repository='fixture', path='demo.py',
                                      text=source, sha256=digest(source), is_test=False))
        graph = Graph(ns, trees, [dict(name='fixture', path=str(tmp_path),
                                       head='captured', closed_world=False)])
        _, info = graph.build()
        observations.append(info)
        assert info['candidate_site_queries_prepared'] == noise + 2
        assert info['candidate_unknown_bucket_visits'] == 0
        assert info['jedi_raw_result_counts'].get('empty', 0) == noise
        assert info['jedi_queries_executed'] == noise + 2
    assert observations[1]['candidate_calls'] > observations[0]['candidate_calls']
    assert observations[1]['candidate_visits'] == observations[0]['candidate_visits'] == 1


def test_same_spelling_unknown_methods_do_not_scale_with_method_count(tmp_path):
    for noise in (0, 20, 100):
        source = (''.join(f'class C{i}:\n def work(self): pass\n' for i in range(8)) +
                  ''.join(f'def caller{i}(obj): obj.work()\n' for i in range(noise)))
        ns, trees = python_nodes(dict(repository='fixture', path='demo.py',
                                      text=source, sha256=digest(source), is_test=False))
        graph = Graph(ns, trees, [dict(name='fixture', path=str(tmp_path),
                                       head='captured', closed_world=False)])
        _, info = graph.build()
        assert info['candidate_site_queries_prepared'] == noise
        assert info['jedi_raw_result_counts'].get('empty', 0) == noise
        assert info['candidate_visits'] == 0
        assert info['candidate_unknown_bucket_visits'] == 0


def test_expanded_selected_owners_prepare_new_sites_on_shared_analyzer(tmp_path):
    source = ('def first(): pass\ndef second(): pass\n'
              'def a(): first()\ndef b(): second()\n')
    ns, trees = python_nodes(dict(repository='fixture', path='demo.py',
                                  text=source, sha256=digest(source), is_test=False))
    graph = Graph(ns, trees, [dict(name='fixture', path=str(tmp_path),
                                   head='captured', closed_world=False)])
    owners = {n['qualname']: n['node_id'] for n in ns}
    first = {owners['a']}
    _, info = graph.build(selected_owners=first, retain_analyzer=True)
    analyzer = info.pop('_analyzer')
    try:
        assert info['candidate_site_queries_prepared'] == 1
        second = first | {owners['b']}
        _, expanded = graph.build(selected_owners=second, analyzer=analyzer,
                                  retain_analyzer=True)
        assert expanded.pop('_analyzer') is analyzer
        assert expanded['candidate_site_queries_prepared'] == 2
        assert expanded['jedi_queries_executed'] >= 2
        assert [s['expression'] for s in analyzer.candidate_sites(owners['second'])] == ['second']
        assert expanded['candidate_unknown_bucket_visits'] == 0
    finally:
        analyzer.close()


def test_frontend_mapping_reentry_does_not_scan_or_hide_later_target(tmp_path, monkeypatch):
    source = 'def target(): pass\ndef caller(): target()\n'
    ns, trees = python_nodes(dict(repository='fixture', path='demo.py',
                                  text=source, sha256=digest(source), is_test=False))
    graph = Graph(ns, trees, [dict(name='fixture', path=str(tmp_path),
                                   head='captured', closed_world=False)])
    target = next(n['node_id'] for n in ns if n['qualname'] == 'target')
    original = Analyzer.map_name
    def mapping_with_caller_lookup(self, name):
        if name.name == 'target':
            assert list(self.candidate_sites(target)) == []
        return original(self, name)
    monkeypatch.setattr(Analyzer, 'map_name', mapping_with_caller_lookup)
    _, info = graph.build()
    assert info['candidate_preparation_reentries'] >= 1
    assert info['candidate_unknown_bucket_visits'] == 0
    assert info['candidate_visits'] == 0
    assert any(s['expression'] == 'target' and target in s['targets'] for s in info['sites'])
