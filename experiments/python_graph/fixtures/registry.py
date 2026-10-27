"""Project-local registration without executing the module in the evaluator."""
handlers = {}
def register(key, cb):
    handlers[key] = cb
