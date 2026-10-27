"""Source-only fixture: contextlib wrappers are not executed by the analyzer."""

from contextlib import contextmanager


class Resource:
    def work(self):
        pass


@contextmanager
def acquire():
    yield Resource()


def caller():
    with acquire() as resource:
        resource.work()
