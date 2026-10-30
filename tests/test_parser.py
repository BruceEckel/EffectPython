"""Milestone 2, first slice: the lexer and the parser read the
Milestone 1 subset.

Run with:  pypy2 -m pytest
"""
import os

import pytest

from effectpython import ast_nodes as ast
from effectpython.errors import InvalidSyntax
from effectpython.interpreter import Interpreter, Output
from effectpython.lexer import tokenize
from effectpython.parser import parse
from effectpython.samples import build_fib_module

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

def kinds(source):
    return [tok.gettokentype() for tok in tokenize(source)]

# --- Lexer -------------------------------------------------------------------

def test_tokens_of_one_line():
    assert kinds('x = fib(n - 1) // 2') == [
        'NAME', 'EQUALS', 'NAME', 'LPAREN', 'NAME', 'MINUS', 'INT',
        'RPAREN', 'DOUBLESLASH', 'INT', 'NEWLINE']

def test_keywords_are_renamed_and_names_are_not():
    assert kinds('if defn else') == ['IF', 'NAME', 'ELSE', 'NEWLINE']

def test_indentation_becomes_indent_and_dedent():
    source = 'def f() -> int:\n    if x:\n        return 1\n    return 2\n'
    assert kinds(source) == [
        'DEF', 'NAME', 'LPAREN', 'RPAREN', 'ARROW', 'NAME', 'COLON',
        'NEWLINE', 'INDENT',
        'IF', 'NAME', 'COLON', 'NEWLINE', 'INDENT',
        'RETURN', 'INT', 'NEWLINE', 'DEDENT',
        'RETURN', 'INT', 'NEWLINE', 'DEDENT']

def test_blank_and_comment_lines_produce_no_tokens():
    source = '# header\n\nx = 1\n   \n  # indented comment\ny = 2\n'
    assert kinds(source) == [
        'NAME', 'EQUALS', 'INT', 'NEWLINE',
        'NAME', 'EQUALS', 'INT', 'NEWLINE']

def test_newline_inside_brackets_is_ignored():
    assert kinds('f(1,\n  2)\n') == [
        'NAME', 'LPAREN', 'INT', 'COMMA', 'INT', 'RPAREN', 'NEWLINE']

def test_missing_final_newline_is_supplied():
    assert kinds('x = 1') == ['NAME', 'EQUALS', 'INT', 'NEWLINE']

def test_unexpected_character_reports_line_and_column():
    with pytest.raises(InvalidSyntax) as info:
        tokenize('x = 1\ny = 2 $ 3\n')
    assert info.value.msg == "line 2, column 7: unexpected character '$'"
    assert (info.value.lineno, info.value.colno) == (2, 7)

def test_inconsistent_dedent_is_an_error():
    with pytest.raises(InvalidSyntax) as info:
        tokenize('if x:\n        a\n    b\n')
    assert info.value.msg.startswith('line 3, column 5: unindent')

# --- Parser ------------------------------------------------------------------

def test_fib_program_matches_the_hand_built_ast():
    module = parse(read_program('fib.epy'))
    assert shape(module) == shape(build_fib_module(20))

def test_fib_program_runs():
    out = ListOutput()
    exit_code = Interpreter(parse(read_program('fib.epy')), out).run_main()
    assert (exit_code, out.lines) == (0, ['6765'])

def test_signature_with_params_and_effect_row():
    fn = parse('def f(a: int, b: str) -> str / [IO, Log]:\n    return\n'
               ).functions[0]
    assert shape(fn) == ('FunctionDef', 'f', ['a', 'b'], ['int', 'str'],
                         'str', ['IO', 'Log'], [('Return', None)])

def test_line_numbers_come_from_the_source():
    module = parse('\ndef f() -> int:\n\n    x = 1\n    return x\n')
    fn = module.functions[0]
    assert (fn.lineno, fn.body[0].lineno, fn.body[1].lineno) == (2, 4, 5)

def test_empty_module():
    assert parse('# nothing here\n').functions == []

@pytest.mark.parametrize('source, expected', [
    ('1 + 2 * 3',
     ('BinOp', '+', ('IntLiteral', 1),
      ('BinOp', '*', ('IntLiteral', 2), ('IntLiteral', 3)))),
    ('(1 + 2) * 3',
     ('BinOp', '*', ('BinOp', '+', ('IntLiteral', 1), ('IntLiteral', 2)),
      ('IntLiteral', 3))),
    ('a - b - c',
     ('BinOp', '-', ('BinOp', '-', ('Name', 'a'), ('Name', 'b')),
      ('Name', 'c'))),
    ('a % 2 == 0',
     ('Compare', '==', ('BinOp', '%', ('Name', 'a'), ('IntLiteral', 2)),
      ('IntLiteral', 0))),
    ('x <= y + 1',
     ('Compare', '<=', ('Name', 'x'),
      ('BinOp', '+', ('Name', 'y'), ('IntLiteral', 1)))),
    ('"a" + \'b\'',
     ('BinOp', '+', ('StrLiteral', 'a'), ('StrLiteral', 'b'))),
    ('print(7, "x", 1 != 2)',
     ('Call', 'print', [('IntLiteral', 7), ('StrLiteral', 'x'),
                        ('Compare', '!=', ('IntLiteral', 1),
                         ('IntLiteral', 2))])),
    ('f()', ('Call', 'f', [])),
])
def test_expression_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

def test_if_else_and_assignment():
    module = parse('def main() -> int:\n'
                   '    if a > b:\n'
                   '        c = a\n'
                   '    else:\n'
                   '        c = b\n'
                   '    return c\n')
    assert shape(module.functions[0].body) == [
        ('If', ('Compare', '>', ('Name', 'a'), ('Name', 'b')),
         [('Assign', 'c', ('Name', 'a'))],
         [('Assign', 'c', ('Name', 'b'))]),
        ('Return', ('Name', 'c'))]

def test_while():
    module = parse('def main() -> int:\n'
                   '    while i < 3:\n'
                   '        i = i + 1\n'
                   '    return i\n')
    assert shape(module.functions[0].body) == [
        ('While', ('Compare', '<', ('Name', 'i'), ('IntLiteral', 3)),
         [('Assign', 'i', ('BinOp', '+', ('Name', 'i'), ('IntLiteral', 1)))]),
        ('Return', ('Name', 'i'))]

@pytest.mark.parametrize('source, msg', [
    ('def f() -> int:\n    return 1 +\n',
     'line 2, column 15: unexpected end of line'),
    ('def f() -> int:\nreturn 1\n',
     "line 2, column 1: unexpected 'return'"),
    ('def f() -> int:\n    x = (1\n',
     "line 2, column 9: '(' was never closed"),
    ('def f() -> int:\n', 'unexpected end of input'),
    ('x = 1\n', "line 1, column 1: unexpected 'x'"),
])
def test_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- Effect syntax -----------------------------------------------------------

PLAN_EXAMPLE = '''\
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

def read_config(path: str) -> str / [FileIO]:
    return perform(FileIO.read(path))

def main() -> int / []:
    try:
        with handle(FileIO):
            config = read_config("settings.json")
            print(config)
    except FileIO.read as eff:
        path = eff.path
        eff.resume(path + "!")
    except FileIO.write as eff:
        pass
    return 0
'''

def test_import_line_leaves_no_node():
    module = parse('from effectpython import Effect, perform\n')
    assert (module.effects, module.functions) == ([], [])

def test_effect_class_with_operation_stubs():
    module = parse(PLAN_EXAMPLE)
    assert shape(module.effects) == [
        ('EffectDef', 'FileIO', [
            ('OperationDef', 'read', ['path'], ['str'], 'str'),
            ('OperationDef', 'write', ['path', 'content'],
             ['str', 'str'], 'int')])]

def test_perform_folds_the_operation_call():
    fn = parse(PLAN_EXAMPLE).functions[0]
    assert shape(fn.body) == [
        ('Return', ('Perform', 'FileIO', 'read', [('Name', 'path')]))]

def test_handle_block_with_two_clauses():
    main = parse(PLAN_EXAMPLE).functions[1]
    assert shape(main.body) == [
        ('Handle', ['FileIO'],
         [('Assign', 'config',
           ('Call', 'read_config', [('StrLiteral', 'settings.json')])),
          ('ExprStmt', ('Call', 'print', [('Name', 'config')]))],
         [('Clause', 'FileIO', 'read', 'eff',
           [('Assign', 'path', ('AttrRead', 'eff', 'path')),
            ('ExprStmt', ('Resume', 'eff',
                          ('BinOp', '+', ('Name', 'path'),
                           ('StrLiteral', '!'))))]),
          ('Clause', 'FileIO', 'write', 'eff', [('Pass',)])]),
        ('Return', ('IntLiteral', 0))]

def test_handle_several_effects_and_nested_handle():
    source = ('def main() -> int:\n'
              '    try:\n'
              '        with handle(FileIO, DBQuery):\n'
              '            try:\n'
              '                with handle(Log):\n'
              '                    pass\n'
              '            except Log.write as e:\n'
              '                e.resume(0)\n'
              '    except FileIO.read as eff:\n'
              '        pass\n'
              '    except DBQuery.execute as eff:\n'
              '        pass\n')
    outer = parse(source).functions[0].body[0]
    inner = outer.body[0]
    assert (outer.effects, inner.effects) == (['FileIO', 'DBQuery'], ['Log'])
    assert [c.op for c in outer.clauses] == ['read', 'execute']
    assert shape(inner.clauses[0].body) == [
        ('ExprStmt', ('Resume', 'e', ('IntLiteral', 0)))]

def test_operation_call_outside_perform_is_an_opcall():
    stmt = parse('def main() -> int:\n    x = FileIO.read("a", 1)\n'
                 ).functions[0].body[0]
    assert shape(stmt) == ('Assign', 'x', ('OpCall', 'FileIO', 'read',
                                          [('StrLiteral', 'a'),
                                           ('IntLiteral', 1)]))

def test_line_numbers_of_effect_nodes():
    module = parse(PLAN_EXAMPLE)
    effect = module.effects[0]
    handle = module.functions[1].body[0]
    assert (effect.lineno, effect.operations[1].lineno) == (3, 5)
    assert (handle.lineno, handle.clauses[1].lineno) == (11, 18)
    assert handle.clauses[0].body[1].expr.lineno == 17

@pytest.mark.parametrize('source, msg', [
    ('class FileIO(Thing):\n    def read() -> str: ...\n',
     'line 1, column 14: a class must derive from Effect'),
    ('def main() -> int:\n    try:\n        with open(f):\n'
     '            pass\n    except IO.read as e:\n        pass\n',
     'line 3, column 14: a with statement must use handle(...)'),
    ('def main() -> int:\n    perform(x)\n',
     'line 2, column 5: perform() takes one Effect.op(...) argument'),
    ('def main() -> int:\n    perform(IO.read(), 1)\n',
     'line 2, column 5: perform() takes one Effect.op(...) argument'),
    ('def main() -> int:\n    eff.resume()\n',
     'line 2, column 9: resume() takes one argument'),
    ('class FileIO(Effect):\n    def read() -> str:\n        pass\n',
     'line 2, column 23: unexpected end of line'),
    ('def main() -> int:\n    try:\n        with handle(IO):\n'
     '            pass\n    return 0\n',
     "line 5, column 5: unexpected 'return'"),
])
def test_effect_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg
