"""Independent import receiver identity and conservative effect controls."""
import pytest

from tests.test_python_pipeline import analyze, site


@pytest.mark.parametrize('alias', ['registry', 'renamed'])
def test_imported_mutated_dictionary_has_real_receiver_and_target(tmp_path, alias):
    a = 'def first(): pass\ndef second(): pass\nregistry={"go":first}\nregistry["go"]=second\n'
    imported = 'registry' if alias == 'registry' else 'registry as renamed'
    result = analyze(tmp_path, {'a.py': a, 'b.py': f'from a import {imported}\ndef run(): {alias}["go"]()\n'})
    found = site(result, f"{alias}['go']", 'run')
    assert found['names'] == {'second'}, found
    assert found['complete'] is True
    assert found['unknown_origin'] is False


def test_unicode_receiver_and_separate_dictionary_do_not_merge(tmp_path):
    a = ('def first(): pass\ndef second(): pass\n'
         '名字={"go":first}; 名字["go"]=second\n'
         'other={"go":first}\n')
    result = analyze(tmp_path, {'a.py': a, 'b.py':
        'from a import 名字 as registry, other\n'
        'def run():\n    registry["go"]()\n    other["go"]()\n'})
    assert site(result, "registry['go']", 'run')['names'] == {'second'}
    assert site(result, "other['go']", 'run')['names'] == {'first'}


def test_conditional_mutation_keeps_both_candidates_and_uncertainty(tmp_path):
    a = ('def first(): pass\ndef second(): pass\nregistry={"go":first}\n'
         'if flag:\n    registry["go"]=second\n')
    result = analyze(tmp_path, {'a.py': a, 'b.py': 'from a import registry\ndef run(): registry["go"]()\n'})
    found = site(result, "registry['go']", 'run')
    assert found['names'] == {'first', 'second'}, found
    assert found['unknown_origin'] is True and found['complete'] is False


def test_custom_subscript_is_not_treated_as_plain_dictionary(tmp_path):
    a = ('def first(): pass\ndef second(): pass\n'
         'class Custom:\n'
         '    def __getitem__(self, key): return first\n'
         '    def __setitem__(self, key, value): pass\n'
         'registry=Custom()\nregistry["go"]=second\n')
    result = analyze(tmp_path, {'a.py': a, 'b.py': 'from a import registry\ndef run(): registry["go"]()\n'})
    found = site(result, "registry['go']", 'run')
    assert found['unknown_origin'] is True and found['complete'] is False
    assert found['names'] != {'second'}, found
