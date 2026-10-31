"""Full package names and aliases resolve inside the requesting repository."""

import pytest

from lct.common import digest
from lct.extract import python_nodes
from lct.graph import Graph


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('shared_package', [False, True])
def test_package_qualified_function_and_class_aliases(tmp_path, reverse, shared_package):
    repositories = ['left', 'right']
    if reverse:
        repositories.reverse()
    nodes, trees = [], {}
    for repo in repositories:
        package = 'shared_package' if shared_package else repo + '_package'
        sources = {
            f'src/{package}/__init__.py': '',
            f'src/{package}/tools.py': 'def work(): pass\nclass Box:\n    def run(self): pass\n',
            'src/caller.py': (
                f'from {package}.tools import work as action, Box as LocalBox\n'
                'def use():\n    action()\n    value = LocalBox()\n    value.run()\n'
            ),
        }
        for path, text in sources.items():
            ns, ts = python_nodes(dict(repository=repo, path=path, text=text,
                                       is_test=False, sha256=digest(text)))
            nodes.extend(ns)
            trees.update(ts)
    g = Graph(nodes, trees, [dict(name=r, path=str(tmp_path / r), head='test',
                                 status='', closed_world=True) for r in repositories])
    _, info = g.build()
    byid = {n['node_id']: n for n in nodes}
    for repo in repositories:
        for expression, qualname in [('action', 'work'), ('value.run', 'Box.run')]:
            site, = [s for s in info['sites']
                     if byid[s['execution_owner']]['repository'] == repo
                     and s['expression'] == expression]
            expected = {n['node_id'] for n in nodes
                        if n['repository'] == repo and n['qualname'] == qualname}
            assert set(site['targets']) == expected, site
            assert not site['unknown_origin'], site
            assert site['complete'], site
