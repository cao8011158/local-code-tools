"""Source-only synthetic corpus. Never import or execute this intentionally invalid driver."""
import json as external_json
from helpers import work as imported_work
from registry import register, handlers

def target():
    return 1

def other():
    return 2

def direct():
    return target()  # case:direct

def alias():
    cb = target
    return cb()  # case:alias

def string_value():
    cb = "target"
    return cb()  # case:string

def invoke(cb):
    return cb()  # case:callback_known

def known_driver():
    return invoke(target)  # case:known_driver

def mixed(cb):
    return cb()  # case:callback_mixed

def mixed_driver(unknown):
    mixed(target)  # case:mixed_known_driver
    return mixed(unknown)  # case:mixed_unknown_driver

def dispatch_fixed():
    table = {"a": target, "b": other}
    return table["a"]()  # case:dict_fixed

def dispatch_dynamic(key):
    table = {"a": target, "b": other}
    return table[key]()  # case:dict_dynamic

register("go", target)  # case:register

def registered():
    return handlers["go"]()  # case:registry

def imported():
    return imported_work()  # case:import_alias

def shadow(imported_work):
    return imported_work()  # case:shadow

class A:
    def work(self):
        return 3

    def bare(self):
        return work()  # case:bare

    @staticmethod
    def invoke(cb):
        return cb()  # case:staticmethod_callback

    @classmethod
    def construct(cls):
        return target()  # case:classmethod_body

def method_driver():
    obj = A()
    obj.work()  # case:instance
    A.work(obj)  # case:class_attribute
    A.invoke(target)  # case:staticmethod_driver
    return A.construct()  # case:classmethod_driver

class Base:
    def run(self):
        return 4

class Child(Base):
    def run(self):
        return super().run()  # case:super

def inherited():
    return Child().run()  # case:inherited

def outer():
    def inner():
        return target()  # case:closure_body
    return inner()  # case:nested

def factory():
    return target  # reference:factory_return

def returned():
    cb = factory()  # case:factory
    return cb()  # case:returned

def lambda_factory():
    return lambda: target()  # case:lambda_body

def lambda_driver():
    cb = lambda_factory()  # case:lambda_factory
    return cb()  # case:lambda_call

def decorate(fn):
    return fn

def make():
    return 7

@decorate  # case:decorator_implicit
def decorated(value=make()):  # case:default
    return target()  # case:decorated_body

def branch(flag):
    if flag:
        cb = target
    else:
        cb = other
    return cb()  # case:branch

def reassignment():
    cb = target
    cb = other
    return cb()  # case:reassignment

def boundary():
    return external_json.loads("{}")  # case:external

def references():
    cb = target  # reference:assignment
    values = [target, other]  # reference:container
    return cb, values
