# Reuse HEADER + DECORATOR from test_python_implicit_effects.py verbatim.
def a(): pass
def b(): pass
class C:
 def __init__(self): self.run=a
def caller():
 obj=C()
 def decorate(fn):
  obj.run=b
  return fn
 @decorate
 def unused(): pass
 obj.run()
