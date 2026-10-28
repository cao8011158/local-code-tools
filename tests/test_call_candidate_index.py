"""The locality index must retain the old may_call predicate and site order."""

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


def test_cold_and_warm_admission_exactly_matches_old_scan(tmp_path):
    a, target = analyzer(tmp_path, extras=300)
    try:
        cold = list(a.candidate_sites(target))
        assert cold == [s for s in a.sites if s['_call'] is not None]
        # Model cached observations produced in normal site order: a different
        # spelling may be an alias, while missing/failed Jedi atoms are admitted.
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
        old = admitted(a, target, a.sites)
        candidates = list(a.candidate_sites(target))
        assert admitted(a, target, candidates) == old
        assert [s['expression'] for s in old[:4]] == ['alias', 'obj.run', 'callback', 'target']
        assert len(candidates) < 10  # 300 unrelated cached observations are skipped.
        a._query_inflight = 1
        assert a.candidate_sites(target) is a.sites
        a._query_inflight = 0
        a.sites.append(dict(_call=None))
        assert a.candidate_sites(target) is a.sites
    finally:
        a.close()


def test_actual_failed_query_is_an_unknown_candidate(tmp_path):
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
        assert site in a.candidate_sites(target)
    finally:
        a.close()
