"""Root-authored v2 boundaries beyond the developer selection fixtures."""
import importlib.util,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('directional_v2_probe',HERE/'v2.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.v1.schedule=m.schedule

def cases():
    a='def first(): pass\ndef second(): pass\ndef factory():\n chosen=first\n return chosen\n'
    before={'src/a.py':a,'src/b.py':'from a import factory\ndef forward():\n value=factory()\n return value\n','src/c.py':'from b import forward\ndef run(): forward()()\n'}
    yield 'forward_return_through_local',before,{**before,'src/a.py':a.replace('chosen=first','chosen=second')}
    a='def first(): pass\ndef second(): pass\nclass Box:\n def __init__(self, cb): self.cb=cb\ndef factory():\n value=Box(first)\n return value\n'
    before={'src/a.py':a,'src/b.py':'from a import factory\ndef run(): factory().cb()\n'}
    yield 'returned_same_class_different_field',before,{**before,'src/a.py':a.replace('value=Box(first)','value=Box(second)')}

if __name__=='__main__':
    results=[m.run_case(*case) for case in cases()]
    (HERE/'independent-v2-results.json').write_text(json.dumps(results,indent=2)+'\n')
    for r in results: print(json.dumps({'case':r['case'],'equal':r['equal'],'directional':r['directional'],'differences':r['differences']}))
