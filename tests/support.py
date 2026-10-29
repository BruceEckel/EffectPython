"""Helpers shared by the test modules."""
import os

from effectpython import ast_nodes as ast
from effectpython.interpreter import Output

PROGRAMS = os.path.join(os.path.dirname(__file__), 'programs')

def read_program(name):
    with open(os.path.join(PROGRAMS, name)) as f:
        return f.read()

def shape(x):
    """A node tree as nested tuples of class names and field values,
    without line numbers, so two ASTs compare by structure."""
    if isinstance(x, ast.Node):
        fields = tuple(shape(getattr(x, a)) for a in type(x)._attrs_)
        return (type(x).__name__,) + fields
    if isinstance(x, list):
        return [shape(item) for item in x]
    return x

class ListOutput(Output):
    def __init__(self):
        self.lines = []

    def write_line(self, text):
        self.lines.append(text)
