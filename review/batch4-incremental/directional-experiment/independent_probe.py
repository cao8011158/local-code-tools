"""Independent root cases for the bounded directional scheduling hypothesis."""
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('directional_probe_target', HERE/'run.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def cases():
    a='def first(): pass\ndef second(): pass\ndef invoke(cb): cb()\n'
    b='from callee import invoke,first,second\ndef run(): invoke(cb=first)\n'
    old={'src/callee.py':a,'src/caller.py':b}
    yield 'keyword_callback_changed',old,{**old,'src/caller.py':b.replace('cb=first','cb=second')}
    a='def first(): pass\ndef second(): pass\ndef factory():\n chosen=first\n return chosen\n'
    old={'src/a.py':a,'src/b.py':'from a import factory\ndef run(): factory()()\n'}
    yield 'return_binding_changed_not_return_expression',old,{**old,'src/a.py':a.replace('chosen=first','chosen=second')}
    a='def first(): pass\ndef second(): pass\ndef invoke(cb): cb()\n'
    b='from callee import invoke,first,second\ninvoke(first)\n'
    old={'src/callee.py':a,'src/caller.py':b}
    yield 'module_level_callback_changed',old,{**old,'src/caller.py':b.replace('invoke(first)','invoke(second)')}

if __name__=='__main__':
    result=[m.run_case(*c) for c in cases()]
    (HERE/'independent-results.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in result:
        print(json.dumps({'case':r['case'],'equal':r['equal'],'directional':r['directional'],'differences':r['differences']}))
