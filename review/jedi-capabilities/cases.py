"""Synthetic inputs for direct public Jedi API observations, independent of LCT."""

HEADER = "def first(): pass\ndef second(): pass\n"
CASES = []


def add(ident, family, body="", *, files=None, note="", docs=None, **options):
    CASES.append(dict(id=ident, family=family,
                      files=files or {"demo.py": HEADER + body},
                      note=note, docs=docs or ["features", "api"], **options))


add("direct", "binding", "def run(): first«value»(«call»)\n")
add("alias", "binding", "alias=first«source»\ndef run():alias«value»(«call»)\n")
add("conditional", "binding",
    "if flag: fn=first\nelse: fn=second\ndef run():fn«value»(«call»)\n",
    note="Unknown flag: preserve all tool observations; no runtime ordering oracle.")
add("walrus_header", "binding",
    "handlers={'go':first}\nold=handlers\n"
    "def sentinel(x=(handlers:={'go':second})):pass\n"
    "handlers['go']=second\ndef run():old['go']«value»(«call»)\n")
add("unbound", "binding", "def run(callback):callback«value»(«call»)\n")
add("tuple_unpack", "binding", "fn,other=(first,second)\ndef run():fn«value»(«call»)\n")
add("callback_positional", "callback",
    "def execute(cb):cb«value»(«call»)\nexecute(first«argument»)\n",
    docs=["features", "api", "dynamic"])
add("callback_keyword", "callback",
    "def execute(cb):cb«value»(«call»)\nexecute(cb=first«argument»)\n")
add("callback_default", "callback",
    "def execute(cb=first«source»):cb«value»(«call»)\nexecute()\n")
add("callback_star", "callback",
    "def execute(cb):cb«value»(«call»)\nexecute(*(first«argument»,))\n")
add("callback_kwargs", "callback",
    "def execute(cb):cb«value»(«call»)\nexecute(**{'cb':first«argument»})\n")
add("callback_multiple_inputs", "callback",
    "def execute(cb):cb«value»(«call»)\nexecute(first)\nexecute(second)\n",
    note="Two static call inputs, not a promise of one context-specific target.")
add("callback_two_hops", "callback",
    "def execute(cb):cb«value»(«call»)\n"
    "def relay(cb):execute(cb«argument»)\nrelay(first«source»)\n")
add("callback_cross_module", "callback", files={
    "provider.py": HEADER,
    "worker.py": "def execute(cb):cb«value»(«call»)\n",
    "client.py": "from provider import first\nfrom worker import execute\nexecute(first«argument»)\n",
}, docs=["features", "api", "dynamic", "settings"])
add("callback_lambda", "callback",
    "execute=lambda cb:cb«value»(«call»)\nexecute(first«argument»)\n")
add("callback_partial", "callback",
    "from functools import partial\n"
    "def execute(cb):cb«value»(«call»)\nrun=partial(execute,first«argument»)\nrun()\n")
add("returned_function", "return",
    "def factory():return first«source»\ndef run():factory()«value»(«call»)\n")
add("returned_callback", "return",
    "def identity(cb):return cb«source»\ndef run():identity(first«argument»)«value»(«call»)\n")
add("closure", "return",
    "def factory(cb):\n def inner():cb«value»(«call»)\n return inner\nfactory(first«argument»)()\n")
add("nonlocal", "return",
    "def outer():\n fn=first\n def change():\n  nonlocal fn\n  fn=second\n change()\n fn«value»(«call»)\nouter()\n")
add("global_rebind", "return",
    "fn=first\ndef change():\n global fn\n fn=second\nchange()\ndef run():fn«value»(«call»)\n")
add("dict_literal", "dictionary",
    "registry={'go':first«source»}\ndef run():registry['go']«value»(«call»)\n")
add("dict_assign", "dictionary",
    "registry={}\nregistry['go']=first«source»\ndef run():registry['go']«value»(«call»)\n")
add("dict_alias_write", "dictionary",
    "registry={}\nalias=registry\nalias['go']=first«source»\n"
    "def run():registry['go']«value»(«call»)\n")
add("dict_update", "dictionary",
    "registry={}\nregistry.update({'go':first«source»})\n"
    "def run():registry['go']«value»(«call»)\n")
add("dict_get", "dictionary",
    "registry={'go':first«source»}\ndef run():registry.get('go')«value»(«call»)\n")
add("dict_unpack", "dictionary",
    "original={'go':first«source»}\nregistry={**original}\n"
    "def run():registry['go']«value»(«call»)\n")
add("dict_dynamic_key", "dictionary",
    "registry={'a':first,'b':second}\ndef run(key):registry[key]«value»(«call»)\n")
add("dict_delete", "dictionary",
    "registry={'go':first}\ndel registry['go']\n"
    "def run():registry['go']«value»(«call»)\n",
    note="Static observations need not model statement execution as a runtime trace.")
add("dict_register", "dictionary",
    "registry={}\ndef register(key,fn):registry[key]=fn«source»\n"
    "register('go',first«argument»)\ndef run():registry['go']«value»(«call»)\n",
    docs=["features", "api", "dynamic"])
add("dict_parameter_writer", "dictionary",
    "registry={}\ndef add(bucket):bucket['go']=first«source»\n"
    "add(registry)\ndef run():registry['go']«value»(«call»)\n")
add("dict_cross_module_write", "dictionary", files={
    "provider.py": HEADER + "registry={}\n",
    "writer.py": "from provider import registry,first\nregistry['go']=first«source»\n",
    "client.py": "from provider import registry\ndef run():registry['go']«value»(«call»)\n",
}, docs=["features", "api", "dynamic"])
add("dict_cross_module_imported_literal", "dictionary", files={
    "provider.py": HEADER + "registry={'go':first«source»}\n",
    "client.py": "from provider import registry\ndef run():registry['go']«value»(«call»)\n",
})
add("dict_getter", "dictionary", files={
    "provider.py": HEADER + "registry={'go':first«source»}\n"
    "def get_callback():return registry['go']«read»\n",
    "client.py": "from provider import get_callback\n"
    "def run():\n fn=get_callback()\n fn«value»(«call»)\n",
})
add("dict_getter_cross_writer", "dictionary", files={
    "provider.py": HEADER + "registry={}\ndef get_callback():return registry['go']«read»\n",
    "writer.py": "from provider import registry,first\nregistry['go']=first«source»\n",
    "client.py": "from provider import get_callback\n"
    "def run():\n fn=get_callback()\n fn«value»(«call»)\n",
}, docs=["features", "api", "dynamic"])
add("registered_callback_composition", "dictionary",
    "registry={}\ndef execute(cb):cb«callback_value»(«call_callback»)\n"
    "def register(key,fn):registry[key]=fn«source»\nregister('go',execute«argument»)\n"
    "def run():registry['go']«value»(«call»first«callback_argument»)\n",
    docs=["features", "api", "dynamic"])
add("list_literal", "sequence", "items=[first«source»]\ndef run():items[0]«value»(«call»)\n")
add("list_append", "sequence",
    "items=[]\nitems.append(first«source»)\ndef run():items[0]«value»(«call»)\n",
    docs=["features", "api", "dynamic", "settings"])
add("list_extend", "sequence",
    "items=[]\nitems.extend([first«source»])\ndef run():items[0]«value»(«call»)\n")
add("list_cross_module_append", "sequence", files={
    "provider.py": HEADER + "items=[]\n",
    "writer.py": "from provider import items,first\nitems.append(first«source»)\n",
    "client.py": "from provider import items\ndef run():items[0]«value»(«call»)\n",
}, docs=["features", "api", "dynamic"])
add("tuple_index", "sequence", "items=(first,second)\ndef run():items[-1]«value»(«call»)\n")
add("list_comprehension", "sequence",
    "items=[fn for fn in [first]]\ndef run():items[0]«value»(«call»)\n")
add("generator_yield", "sequence",
    "def callbacks():yield first«source»\n"
    "def run():\n for fn in callbacks():fn«value»(«call»)\n")
add("generator_yield_from", "sequence",
    "def callbacks():yield from [first«source»]\n"
    "def run():\n for fn in callbacks():fn«value»(«call»)\n")
add("bound_method", "object",
    "class C:\n def method(self):pass\nobj=C()\ndef run():obj.method«value»(«call»)\n")
add("classmethod", "object",
    "class C:\n @classmethod\n def build(cls):pass\ndef run():C.build«value»(«call»)\n")
add("staticmethod", "object",
    "class C:\n @staticmethod\n def work():pass\ndef run():C.work«value»(«call»)\n")
add("super_method", "object",
    "class Base:\n def work(self):pass\n"
    "class Child(Base):\n def run(self):super().work«value»(«call»)\nChild().run()\n")
add("instance_field", "object",
    "class C:\n def __init__(self):self.callback=first«source»\n"
    " def run(self):self.callback«value»(«call»)\nC().run()\n")
add("instance_dict", "object",
    "class C:\n def __init__(self):self.registry={'go':first«source»}\n"
    " def run(self):self.registry['go']«value»(«call»)\nC().run()\n")
add("outside_instance_write", "object",
    "class C:pass\nobj=C()\nobj.callback=first«source»\n"
    "def run():obj.callback«value»(«call»)\n")
add("callable_instance", "object",
    "class C:\n def __call__(self):pass\nobj=C()\ndef run():obj«value»(«call»)\n",
    note="A returned Name of type instance is not automatically a class or __call__ declaration.")
add("noncallable_instance", "object", "class C:pass\nobj=C()\ndef run():obj«value»(«call»)\n")
add("property_callable", "object",
    "class C:\n @property\n def callback(self):return first«source»\n"
    "def run():C().callback«value»(«call»)\n")
add("custom_descriptor", "object",
    "class Descriptor:\n def __get__(self,obj,owner):return first«source»\n"
    "class C:callback=Descriptor()\ndef run():C().callback«value»(«call»)\n")
add("custom_getattr", "dynamic",
    "class C:\n def __getattr__(self,name):return first«source»\n"
    "def run():C().callback«value»(«call»)\n")
add("getattr_literal", "dynamic",
    "class C:\n def method(self):pass\n"
    "def run():getattr(C(),'method')«value»(«call»)\n")
add("setattr", "dynamic",
    "class C:pass\nobj=C()\nsetattr(obj,'callback',first«source»)\n"
    "def run():obj.callback«value»(«call»)\n")
add("globals_write", "dynamic",
    "globals()['callback']=first«source»\ndef run():callback«value»(«call»)\n")
add("object_dict_write", "dynamic",
    "class C:pass\nobj=C()\nobj.__dict__['callback']=first«source»\n"
    "def run():obj.callback«value»(«call»)\n")
add("dynamic_import", "dynamic", files={
    "provider.py": HEADER,
    "demo.py": "mod=__import__('provider')\ndef run():mod.first«value»(«call»)\n",
})
add("decorator", "decorator",
    "def decorate(fn):return first«source»\n@decorate\n"
    "def target():pass\ndef run():target«value»(«call»)\n")
add("decorator_factory", "decorator",
    "def factory():\n def decorate(fn):return first«source»\n return decorate\n"
    "@factory()\ndef target():pass\ndef run():target«value»(«call»)\n")
add("contextmanager_factory", "decorator",
    "from contextlib import contextmanager\n@contextmanager\n"
    "def manager():yield first\n"
    "def run():\n with manager«value»(«call») as cb:cb«callback_value»(«call_callback»)\n",
    note="Query factory and as-bound callable separately. This does not certify an implicit enter/resume edge.")
add("async_return", "async",
    "async def factory():return first«source»\n"
    "async def run():\n fn=await factory()\n fn«value»(«call»)\n")
add("relative_import", "import", files={
    "pkg/__init__.py": "",
    "pkg/provider.py": HEADER,
    "pkg/client.py": "from .provider import first as alias\n"
    "def run():alias«value»(«call»)\n",
})
add("reexport", "import", files={
    "provider.py": HEADER,
    "bridge.py": "from provider import first as alias\n",
    "client.py": "from bridge import alias\ndef run():alias«value»(«call»)\n",
})
add("namespace_package", "import", files={
    "pkg/provider.py": HEADER,
    "client.py": "from pkg.provider import first\ndef run():first«value»(«call»)\n",
})
add("stub", "typing", files={
    "provider.pyi": "def first() -> None: ...\n",
    "client.py": "from provider import first\ndef run():first«value»(«call»)\n",
})
add("callable_annotation", "typing",
    "from typing import Callable\n"
    "def execute(cb:Callable[[],None]):cb«value»(«call»)\nexecute(first«argument»)\n",
    note="A Callable annotation may yield an abstract signature rather than a concrete passed definition.")
add("type_comment", "typing",
    "fn=first  # type: object\ndef run():fn«value»(«call»)\n")
add("recursive_parameters", "metadata", files={"demo.py":
    "def forward(*args,**kwargs):return forward(*args,**kwargs)\nforward«value»(«call»1)\n"},
    note="Read Signature.params separately after retaining signature identity.",
    docs=["api", "dynamic"])
add("mutual_recursive_parameters", "metadata", files={"demo.py":
    "def first(*args,**kwargs):return second(*args,**kwargs)\n"
    "def second(*args,**kwargs):return first(*args,**kwargs)\nfirst«value»(«call»1)\n"},
    docs=["api", "dynamic"])
add("utf8_split_call", "position", files={"demo.py":
    "def café():pass\ndef run():\n café«value»(\n «call»)\n"})
add("wrong_cursor_end", "position", "def run():first«value»(«call»)«end»\n",
    note="get_signatures after the closing parenthesis is a documented empty result, not a capability gap.")
add("syntax_recovery", "syntax", "def run():first«value»(«call»)\nbroken = (\n",
    note="Syntax diagnostics are retained; partial recovery is not an all-syntax guarantee.")
add("missing_context", "integration", files={
    "provider.py": HEADER,
    "client.py": "from provider import first\ndef run():first«value»(«call»)\n",
}, omit=["provider.py"], note="Deliberately missing captured module: integration negative control, not an upstream limitation.")
add("restored_context", "integration", files={
    "provider.py": HEADER,
    "client.py": "from provider import first\ndef run():first«value»(«call»)\n",
}, note="Positive control for missing_context with identical client bytes.")

add("custom_metaclass", "dynamic",
    "class Meta(type):\n def __new__(meta,name,bases,namespace):\n"
    "  namespace['callback']=staticmethod(first«source»)\n"
    "  return super().__new__(meta,name,bases,namespace)\n"
    "class C(metaclass=Meta):pass\ndef run():C.callback«value»(«call»)\n")
add("dataclass", "typing",
    "from dataclasses import dataclass\nfrom typing import Callable\n"
    "@dataclass\nclass C:\n callback:Callable[[],None]=first«source»\n"
    "def run():C().callback«value»(«call»)\n")
add("dict_setdefault", "dictionary",
    "registry={}\nregistry.setdefault('go',first«source»)\n"
    "def run():registry['go']«value»(«call»)\n")
add("dict_overwrite", "dictionary",
    "registry={'go':first}\nregistry['go']=second«source»\n"
    "def run():registry['go']«value»(«call»)\n",
    note="Compare the actual tool observation with the initial literal; do not invent a latest-write arbiter.")
add("dict_clear", "dictionary",
    "registry={'go':first}\nregistry.clear()\ndef run():registry['go']«value»(«call»)\n",
    note="Retain any static observation; this probe does not execute clear or the fixture.")
add("dict_equal_keys", "dictionary",
    "registry={True:first«source»}\ndef run():registry[1]«value»(«call»)\n")
add("try_except", "flow",
    "try:fn=first\nexcept Exception:fn=second\ndef run():fn«value»(«call»)\n")
add("dict_returned_allocation", "dictionary",
    "def make():return {}\nregistry=make()\nregistry['go']=first«source»\n"
    "def run():registry['go']«value»(«call»)\n")
add("dict_register_two_keys", "dictionary",
    "registry={}\ndef register(key,fn):registry[key]=fn«source»\n"
    "register('a',first«argument_a»)\nregister('b',second«argument_b»)\n"
    "def run():registry['a']«value»(«call»)\n",
    note="Inferring a source parameter can return both functions; it does not prove key-specific final targets.",
    docs=["features", "api", "dynamic"])
add("callback_container_parameter", "callback",
    "def execute(callbacks):callbacks['go']«value»(«call»)\n"
    "execute({'go':first«argument»})\n")
add("callback_getter_argument", "callback",
    "registry={'go':first«source»}\ndef getter():return registry['go']\n"
    "def execute(cb):cb«value»(«call»)\nexecute(getter())\n")
add("references_inventory", "source", files={
    "provider.py": HEADER + "registry«ref_registry»={}\n",
    "writer.py": "from provider import registry,first\nregistry['go']=first«source»\n",
    "client.py": "from provider import registry\ndef run():registry['go']«value»(«call»)\n",
}, note="References locate symbol occurrences; their existence alone does not establish key-specific call targets.")

BY_ID = {case["id"]: case for case in CASES}
assert len(BY_ID) == len(CASES)
