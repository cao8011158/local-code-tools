"""Fixture command dispatch and calculation."""


def target():
    """Calculate target command."""
    return 1


def other():
    """Calculate alternative command."""
    return 2


handlers = {"a": target, "b": other}


def dispatch(key):
    """Dispatch a registered command."""
    return handlers[key]()


class A:
    """Command service."""

    @classmethod
    def construct(cls):
        return cls()

    def work(self):
        return target()


def factory():
    return lambda: target()


a, b = (lambda: target()), (lambda: other())
