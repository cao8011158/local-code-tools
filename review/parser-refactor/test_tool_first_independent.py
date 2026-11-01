"""Independent tool consumption and source support controls for parser refactor."""
from unittest.mock import patch

import pytest

from lct.python_analysis import Analyzer
from tests.test_python_pipeline import analyze, site


@pytest.mark.parametrize("source,callee,line", [(
    "def first(): pass\ndef run():\n first()\n", "first", 3),
    ("def first(): pass\nalias=first\ndef run():\n alias()\n", "alias", 4),
])
def test_plain_alias_callee_is_not_reinferred_by_name_resolver(tmp_path, source, callee, line):
    original = Analyzer.name
    calls = []
    def watch(a, scope, name, before, anchor):
        if anchor.lineno == line and name == callee:
            calls.append((scope, name))
        return original(a, scope, name, before, anchor)
    with patch.object(Analyzer, 'name', watch):
        result = analyze(tmp_path, {'src/demo.py': source}, closed=False)
    assert site(result, callee, 'run')['names'] == {'first'}
    assert not calls, 'Jedi-covered callee re-entered custom name target inference'


def test_callback_same_name_as_global_keeps_argument_support(tmp_path):
    source = 'def first(): pass\ndef execute(first): first()\ndef driver(): execute(first)\n'
    r = analyze(tmp_path, {'src/demo.py': source}, closed=False)
    assert site(r, 'first', 'execute')['names'] == {'first'}
    nodes = {n['node_id']: n['qualname'] for n in r[0]}
    supports = r[2].get('_unit_supports', [])
    assert any(s['kind'] == 'actual-parameter'
               and nodes[s['producer_owner']] == 'driver'
               and nodes[s['consumer_owner']] == 'execute' for s in supports)


def test_local_unbound_rule_remains_a_specific_exception(tmp_path):
    r = analyze(tmp_path, {'src/demo.py': 'def first(): pass\ndef run():\n first()\n first=1\n'}, closed=False)
    s = site(r, 'first', 'run')
    assert not s['names']
    assert 'unbound-local-before-assignment' in s['resolution_decision']['semantic_rules']


def test_registered_container_gap_is_preserved(tmp_path):
    source = 'def first(): pass\nregistry={}\ndef register(key, value): registry[key]=value\nregister("go",first)\ndef run(): registry["go"]()\n'
    r = analyze(tmp_path, {'src/demo.py': source}, closed=False)
    assert site(r, "registry['go']", 'run')['names'] == {'first'}
