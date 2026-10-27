"""Source-only fixture: distinct instance registries must not share callback origins."""


class Registry:
    def __init__(self):
        self.handlers = {}

    def register(self, key, cb):
        self.handlers[key] = cb

    def dispatch(self):
        self.handlers["go"]()


def a():
    pass


def b():
    pass


first = Registry()
second = Registry()
first.register("go", a)
second.register("go", b)
first.dispatch()
