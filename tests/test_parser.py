"""Milestone 2, first slice: the lexer and the parser read the
Milestone 1 subset; from Milestone 5, handler classes too; from
Milestone 6, exceptions; from Milestone 7, operation rows and throw;
from Milestone 8, finally; from Milestone 9, lists and the
for loop; from Milestone 10, break and continue; from Milestone 11,
the boolean operators and elif (plan 1.11); from Milestone 12, dicts
and in (plan 1.12); from Milestone 13, f-strings (plan 1.13);
from Milestone 14, augmented assignment (plan 1.14); from
Milestone 16, None and optional types (plan 1.16); from Milestone
17, tuples (plan 1.17).

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

def test_raise_is_a_keyword():
    assert kinds('raise NotFound(x)') == [
        'RAISE', 'NAME', 'LPAREN', 'NAME', 'RPAREN', 'NEWLINE']

def test_true_and_false_are_keywords():
    assert kinds('x = True != False') == [
        'NAME', 'EQUALS', 'TRUE', 'NE', 'FALSE', 'NEWLINE']

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
    ('True == False',
     ('Compare', '==', ('BoolLiteral', True), ('BoolLiteral', False))),
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
            ('OperationDef', 'read', ['path'], ['str'], 'str', []),
            ('OperationDef', 'write', ['path', 'content'],
             ['str', 'str'], 'int', [])])]

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
          ('Clause', 'FileIO', 'write', 'eff', [('Pass',)])],
         [], []),
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
     'line 1, column 14: a class must derive from Effect, Handler[...], '
     'or Exception'),
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

# --- Handler classes (Milestone 5) -------------------------------------------

HANDLER_EXAMPLE = '''\
from effectpython import Effect, Handler, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

class CountingFileIO(Handler[FileIO]):
    writes: int = 0
    prefix: str
    def read(self, path: str) -> str:
        return self.prefix + path
    def write(self, path: str, content: str) -> int / [Log]:
        self.writes = self.writes + 1
        return self.writes

def main() -> int / []:
    fake = CountingFileIO(0, "contents of ")
    with handle(fake, FakeLog(3)):
        print(perform(FileIO.read("a")))
    print(fake.writes)
    return 0
'''

def test_handler_class_shape():
    module = parse(HANDLER_EXAMPLE)
    assert shape(module.handlers) == [
        ('HandlerDef', 'CountingFileIO', 'FileIO',
         [('FieldDef', 'writes', 'int', ('IntLiteral', 0)),
          ('FieldDef', 'prefix', 'str', None)],
         [('FunctionDef', 'read', ['self', 'path'],
           ['CountingFileIO', 'str'], 'str', [],
           [('Return', ('BinOp', '+', ('AttrRead', 'self', 'prefix'),
                        ('Name', 'path')))]),
          ('FunctionDef', 'write', ['self', 'path', 'content'],
           ['CountingFileIO', 'str', 'str'], 'int', ['Log'],
           [('AttrAssign', 'self', 'writes',
             ('BinOp', '+', ('AttrRead', 'self', 'writes'),
              ('IntLiteral', 1))),
            ('Return', ('AttrRead', 'self', 'writes'))])])]

def test_with_handle_outside_try_has_no_clauses():
    main = parse(HANDLER_EXAMPLE).functions[0]
    assert shape(main.body) == [
        ('Assign', 'fake', ('Call', 'CountingFileIO',
                            [('IntLiteral', 0),
                             ('StrLiteral', 'contents of ')])),
        ('Handle', ['fake'],
         [('ExprStmt', ('Call', 'print',
                        [('Perform', 'FileIO', 'read',
                          [('StrLiteral', 'a')])]))],
         [], [('Call', 'FakeLog', [('IntLiteral', 3)])], []),
        ('ExprStmt', ('Call', 'print', [('AttrRead', 'fake', 'writes')])),
        ('Return', ('IntLiteral', 0))]

def test_try_handle_mixes_a_construction_with_an_effect_name():
    source = ('def main() -> int:\n'
              '    try:\n'
              '        with handle(FakeFileIO(), DBQuery):\n'
              '            pass\n'
              '    except DBQuery.execute as eff:\n'
              '        eff.resume("")\n')
    handle = parse(source).functions[0].body[0]
    assert (handle.effects, shape(handle.constructions)) == (
        ['DBQuery'], [('Call', 'FakeFileIO', [])])
    assert [c.op for c in handle.clauses] == ['execute']

def test_line_numbers_of_handler_nodes():
    handler = parse(HANDLER_EXAMPLE).handlers[0]
    assert (handler.lineno, handler.fields[1].lineno,
            handler.methods[1].lineno) == (7, 9, 12)

@pytest.mark.parametrize('source, msg', [
    ('class Fake(Other[FileIO]):\n    def read(self) -> str:\n'
     '        pass\n',
     'line 1, column 12: a class must derive from Effect, Handler[...], '
     'or Exception'),
    ('class Fake(Handler[FileIO]):\n    def read(path: str) -> str:\n'
     '        pass\n',
     "line 2, column 13: a handler method's first parameter must be self"),
    ('class Fake(Handler[FileIO]):\n    def read() -> str:\n'
     '        pass\n',
     "line 2, column 13: a handler method's first parameter must be self"),
    ('class Fake(Handler[FileIO]):\n    def read(me, path: str) -> str:\n'
     '        pass\n',
     "line 2, column 14: a handler method's first parameter must be self"),
    ('class Fake(Handler[FileIO]):\n    writes: int = 1 + 2\n',
     'line 2, column 17: a field default must be an int, str, or bool '
     'literal, [], or {}'),
    ('def main() -> int:\n    with open(f):\n        pass\n',
     'line 2, column 10: a with statement must use handle(...)'),
    ('class Fake(Handler[FileIO]):\n    def read(self) -> str: ...\n',
     "line 2, column 28: unexpected '...'"),
])
def test_handler_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- Exceptions (Milestone 6) ------------------------------------------------

EXCEPTION_EXAMPLE = '''\
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

class NotFound(Exception): ...

def read_config(path: str) -> str / [FileIO, NotFound]:
    config = perform(FileIO.read(path))
    if config == "":
        raise NotFound(path)
    return config

def main() -> int / []:
    try:
        try:
            with handle(FileIO):
                print(read_config("settings.json"))
        except FileIO.read as eff:
            eff.resume("")
    except NotFound as e:
        print("missing:", e)
    return 0
'''

@pytest.mark.parametrize('source', [
    'class NotFound(Exception): ...\n',
    'class NotFound(Exception): pass\n',
    'class NotFound(Exception):\n    ...\n',
    'class NotFound(Exception):\n    pass\n',
])
def test_exception_class_body_forms(source):
    module = parse(source)
    assert shape(module.exceptions) == [('ExceptionDef', 'NotFound')]

def test_raise_in_a_function_with_an_exception_in_its_row():
    fn = parse(EXCEPTION_EXAMPLE).functions[0]
    assert fn.effect_row == ['FileIO', 'NotFound']
    assert shape(fn.body[1].body) == [
        ('Raise', ('Call', 'NotFound', [('Name', 'path')]))]

def test_try_except_around_a_handle_block():
    main = parse(EXCEPTION_EXAMPLE).functions[1]
    assert shape(main.body[0]) == (
        'Try',
        [('Handle', ['FileIO'],
          [('ExprStmt', ('Call', 'print',
                         [('Call', 'read_config',
                           [('StrLiteral', 'settings.json')])]))],
          [('Clause', 'FileIO', 'read', 'eff',
            [('ExprStmt', ('Resume', 'eff', ('StrLiteral', '')))])],
          [], [])],
        [('ExceptClause', 'NotFound', 'e',
          [('ExprStmt', ('Call', 'print',
                         [('StrLiteral', 'missing:'), ('Name', 'e')]))])],
        [])

def test_except_without_as_has_no_binding():
    source = ('def main() -> int:\n'
              '    try:\n'
              '        pass\n'
              '    except NotFound as e:\n'
              '        pass\n'
              '    except Exception:\n'
              '        pass\n')
    stmt = parse(source).functions[0].body[0]
    assert shape(stmt.clauses) == [
        ('ExceptClause', 'NotFound', 'e', [('Pass',)]),
        ('ExceptClause', 'Exception', None, [('Pass',)])]

def test_line_numbers_of_exception_nodes():
    module = parse(EXCEPTION_EXAMPLE)
    raise_stmt = module.functions[0].body[1].body[0]
    outer = module.functions[1].body[0]
    assert (module.exceptions[0].lineno, raise_stmt.lineno) == (6, 11)
    assert (outer.lineno, outer.body[0].lineno,
            outer.clauses[0].lineno) == (15, 16, 21)

@pytest.mark.parametrize('source, msg', [
    ('def main() -> int:\n    try:\n        with handle(IO):\n'
     '            pass\n    except IO.read as e:\n        pass\n'
     '    except NotFound:\n        pass\n',
     'line 7, column 5: a try statement cannot mix effect clauses and '
     'exception clauses'),
    ('def main() -> int:\n    try:\n        pass\n'
     '    except NotFound as e:\n        pass\n'
     '    except IO.read as e:\n        pass\n',
     'line 6, column 5: a try statement cannot mix effect clauses and '
     'exception clauses'),
    ('def main() -> int:\n    try:\n        pass\n'
     '    except IO.read as e:\n        pass\n',
     'line 2, column 5: effect clauses need a with handle(...) statement'),
    ('def main() -> int:\n    try:\n        with handle(IO):\n'
     '            pass\n        pass\n    except IO.read as e:\n'
     '        pass\n',
     'line 2, column 5: effect clauses need a with handle(...) statement'),
    ('def main() -> int:\n    try:\n        try:\n'
     '            with handle(IO):\n                pass\n'
     '        except IO.read as e:\n            pass\n'
     '    except Log.write as e:\n        pass\n',
     'line 2, column 5: effect clauses need a with handle(...) statement'),
    ('class NotFound(Thing): ...\n',
     'line 1, column 16: a class must derive from Effect, Handler[...], '
     'or Exception'),
    ('class FileIO(Effect): ...\n',
     'line 1, column 14: an effect class declares at least one operation'),
    ('class NotFound(Exception):\n    def read() -> str: ...\n',
     'line 1, column 16: an exception class has no body beyond ... or pass'),
    ('def main() -> int:\n    raise\n',
     'line 2, column 10: unexpected end of line'),
    ('def main() -> int:\n    try:\n        pass\n    except:\n'
     '        pass\n',
     "line 4, column 11: unexpected ':'"),
    ('class NotFound(Exception):\n    count: int\n',
     "line 2, column 5: unexpected 'count'"),
])
def test_exception_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- Throwing into the body (Milestone 7) ------------------------------------

THROW_EXAMPLE = '''\
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str / [NotFound]: ...
    def write(path: str, content: str) -> int / [NotFound, Denied]: ...
    def close() -> int: ...

class NotFound(Exception): ...

class Denied(Exception): ...

def main() -> int / []:
    try:
        with handle(FileIO):
            print(perform(FileIO.read("settings.json")))
    except FileIO.read as eff:
        eff.throw(NotFound(eff.path))
    except FileIO.write as eff:
        x = eff.throw(Denied(eff.path))
    except FileIO.close as eff:
        eff.resume(0)
    return 0
'''

def test_operation_stubs_with_and_without_a_row():
    module = parse(THROW_EXAMPLE)
    assert shape(module.effects[0].operations) == [
        ('OperationDef', 'read', ['path'], ['str'], 'str', ['NotFound']),
        ('OperationDef', 'write', ['path', 'content'], ['str', 'str'],
         'int', ['NotFound', 'Denied']),
        ('OperationDef', 'close', [], [], 'int', [])]

def test_throw_as_a_statement_in_a_clause():
    clause = parse(THROW_EXAMPLE).functions[0].body[0].clauses[0]
    assert shape(clause.body) == [
        ('ExprStmt', ('Throw', 'eff',
                      ('Call', 'NotFound', [('AttrRead', 'eff', 'path')])))]

def test_throw_as_an_assigned_value():
    clause = parse(THROW_EXAMPLE).functions[0].body[0].clauses[1]
    assert shape(clause.body) == [
        ('Assign', 'x', ('Throw', 'eff',
                         ('Call', 'Denied', [('AttrRead', 'eff', 'path')])))]

def test_throw_on_an_effect_name_is_a_throw_node():
    stmt = parse('def main() -> int:\n    FileIO.throw(x)\n'
                 ).functions[0].body[0]
    assert shape(stmt) == ('ExprStmt', ('Throw', 'FileIO', ('Name', 'x')))

def test_line_numbers_of_throw_nodes():
    handle = parse(THROW_EXAMPLE).functions[0].body[0]
    assert (handle.clauses[0].body[0].expr.lineno,
            handle.clauses[1].body[0].value.lineno) == (17, 19)

@pytest.mark.parametrize('source, msg', [
    ('def main() -> int:\n    eff.throw()\n',
     'line 2, column 9: throw() takes one argument'),
    ('def main() -> int:\n    eff.throw(1, 2)\n',
     'line 2, column 9: throw() takes one argument'),
])
def test_throw_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

@pytest.mark.parametrize('source', [
    'class FileIO(Effect):\n    def read() -> str / [NotFound,]: ...\n',
    'class FileIO(Effect):\n    def read() -> str / [NotFound: ...\n',
])
def test_malformed_operation_row_is_a_syntax_error(source):
    with pytest.raises(InvalidSyntax):
        parse(source)

# --- Finally (Milestone 8) ---------------------------------------------------

FINALLY_EXAMPLE = '''\
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

class NotFound(Exception): ...

def main() -> int / []:
    try:
        print("body")
    finally:
        print("cleanup")
    try:
        raise NotFound("x")
    except NotFound as e:
        print("caught")
    finally:
        print("after")
    try:
        with handle(FileIO):
            print(perform(FileIO.read("a")))
    except FileIO.read as eff:
        eff.resume("")
    finally:
        print("closed")
    return 0
'''

def test_finally_is_a_keyword():
    assert kinds('finally:') == ['FINALLY', 'COLON', 'NEWLINE']

def test_try_finally_without_clauses():
    main = parse(FINALLY_EXAMPLE).functions[0]
    assert shape(main.body[0]) == (
        'Try',
        [('ExprStmt', ('Call', 'print', [('StrLiteral', 'body')]))],
        [],
        [('ExprStmt', ('Call', 'print', [('StrLiteral', 'cleanup')]))])

def test_try_except_finally():
    main = parse(FINALLY_EXAMPLE).functions[0]
    assert shape(main.body[1]) == (
        'Try',
        [('Raise', ('Call', 'NotFound', [('StrLiteral', 'x')]))],
        [('ExceptClause', 'NotFound', 'e',
          [('ExprStmt', ('Call', 'print', [('StrLiteral', 'caught')]))])],
        [('ExprStmt', ('Call', 'print', [('StrLiteral', 'after')]))])

def test_finally_wraps_a_handle_block_in_a_try():
    main = parse(FINALLY_EXAMPLE).functions[0]
    assert shape(main.body[2]) == (
        'Try',
        [('Handle', ['FileIO'],
          [('ExprStmt', ('Call', 'print',
                         [('Perform', 'FileIO', 'read',
                           [('StrLiteral', 'a')])]))],
          [('Clause', 'FileIO', 'read', 'eff',
            [('ExprStmt', ('Resume', 'eff', ('StrLiteral', '')))])],
          [], [])],
        [],
        [('ExprStmt', ('Call', 'print', [('StrLiteral', 'closed')]))])

def test_try_except_without_finally_has_an_empty_finalbody():
    source = ('def main() -> int:\n'
              '    try:\n'
              '        pass\n'
              '    except NotFound as e:\n'
              '        pass\n')
    stmt = parse(source).functions[0].body[0]
    assert stmt.finalbody == []

def test_line_numbers_of_finally_nodes():
    first = parse(FINALLY_EXAMPLE).functions[0].body[0]
    assert (first.lineno, first.finalbody[0].lineno) == (9, 12)

@pytest.mark.parametrize('source, msg', [
    ('def main() -> int:\n    try:\n        pass\n'
     '    except IO.read as e:\n        pass\n'
     '    finally:\n        pass\n',
     'line 2, column 5: effect clauses need a with handle(...) statement'),
    ('def main() -> int:\n    try:\n        with handle(IO):\n'
     '            pass\n    except IO.read as e:\n        pass\n'
     '    except NotFound:\n        pass\n    finally:\n        pass\n',
     'line 7, column 5: a try statement cannot mix effect clauses and '
     'exception clauses'),
])
def test_finally_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

@pytest.mark.parametrize('source', [
    'def main() -> int:\n    try:\n        pass\n',
    'def main() -> int:\n    try:\n        pass\n    return 0\n',
])
def test_try_without_clauses_or_finally_is_a_syntax_error(source):
    with pytest.raises(InvalidSyntax):
        parse(source)

# --- Lists and the for loop (Milestone 9) ------------------------------------

def test_for_and_in_are_keywords():
    assert kinds('for x in xs:') == [
        'FOR', 'NAME', 'IN', 'NAME', 'COLON', 'NEWLINE']

@pytest.mark.parametrize('element', ['int', 'str', 'bool'])
def test_list_parameter_type(element):
    fn = parse('def f(xs: list[%s]) -> int:\n    return 0\n' % element
               ).functions[0]
    assert fn.param_types == ['list[%s]' % element]

def test_list_function_return_type():
    fn = parse('def f() -> list[str]:\n    return []\n').functions[0]
    assert fn.return_type == 'list[str]'

def test_list_operation_return_type():
    effect = parse('class Store(Effect):\n'
                   '    def all() -> list[bool]: ...\n').effects[0]
    assert effect.operations[0].return_type == 'list[bool]'

def test_list_handler_field_type():
    handler = parse('class Collector(Handler[Log]):\n'
                    '    entries: list[str] = []\n').handlers[0]
    assert shape(handler.fields) == [
        ('FieldDef', 'entries', 'list[str]', ('ListLiteral', []))]

@pytest.mark.parametrize('source, msg', [
    ('def f(xs: set[int]) -> int:\n    return 0\n',
     "line 1, column 11: 'set' takes no type parameter; list[...] does"),
    ('def f(xs: list) -> int:\n    return 0\n',
     'line 1, column 11: list needs an element type: list[int], '
     'list[str], or list[bool]'),
], ids=['other-generic', 'bare-list'])
def test_type_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

@pytest.mark.parametrize('source, expected', [
    ('self.entries.append(t)',
     ('MethodCall', ('AttrRead', 'self', 'entries'), 'append',
      [('Name', 't')])),
    ('xs[i]', ('Index', ('Name', 'xs'), ('Name', 'i'))),
    ('collector.entries[0]',
     ('Index', ('AttrRead', 'collector', 'entries'), ('IntLiteral', 0))),
    ('[1, 2][0]',
     ('Index', ('ListLiteral', [('IntLiteral', 1), ('IntLiteral', 2)]),
      ('IntLiteral', 0))),
    ('xs[0][1]',
     ('Index', ('Index', ('Name', 'xs'), ('IntLiteral', 0)),
      ('IntLiteral', 1))),
    ('xs.append(1)', ('OpCall', 'xs', 'append', [('IntLiteral', 1)])),
    ('[]', ('ListLiteral', [])),
    ('[1, 2]', ('ListLiteral', [('IntLiteral', 1), ('IntLiteral', 2)])),
], ids=['method-call', 'index', 'index-attr', 'index-literal',
        'nested-index', 'name-append', 'empty-list', 'list'])
def test_postfix_and_list_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

@pytest.mark.parametrize('source, expected', [
    ('x = 1', ('Assign', 'x', ('IntLiteral', 1))),
    ('x.f = 1', ('AttrAssign', 'x', 'f', ('IntLiteral', 1))),
    ('xs[i] = 1',
     ('IndexAssign', ('Name', 'xs'), ('Name', 'i'), ('IntLiteral', 1))),
], ids=['name', 'attribute', 'index'])
def test_assignment_targets(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    assert shape(module.functions[0].body[0]) == expected

@pytest.mark.parametrize('source, expected', [
    ('for x in xs:',
     ('For', 'x', ('Name', 'xs'), [('Pass',)])),
    ('for i in range(3):',
     ('ForRange', 'i', [('IntLiteral', 3)], [('Pass',)])),
    ('for i in range(1, n):',
     ('ForRange', 'i', [('IntLiteral', 1), ('Name', 'n')], [('Pass',)])),
    ('for x in f():',
     ('For', 'x', ('Call', 'f', []), [('Pass',)])),
], ids=['list', 'range-one', 'range-two', 'other-call'])
def test_for_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n        pass\n' % source)
    assert shape(module.functions[0].body[0]) == expected

@pytest.mark.parametrize('source, expected', [
    ('-1', ('IntLiteral', -1)),
    ('-x', ('BinOp', '-', ('IntLiteral', 0), ('Name', 'x'))),
    ('3 - -1', ('BinOp', '-', ('IntLiteral', 3), ('IntLiteral', -1))),
    ('-x * 2',
     ('BinOp', '*', ('BinOp', '-', ('IntLiteral', 0), ('Name', 'x')),
      ('IntLiteral', 2))),
], ids=['literal', 'name', 'after-minus', 'before-star'])
def test_unary_minus(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

@pytest.mark.parametrize('source, msg', [
    ('def main() -> int:\n    f(1) = 2\n',
     'line 2, column 10: cannot assign to this expression'),
    ('class Fake(Handler[Log]):\n    entries: list[int] = [1]\n',
     "line 2, column 24: a list field's default must be []"),
], ids=['assign-call', 'list-default'])
def test_list_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- break and continue (Milestone 10) ---------------------------------------

@pytest.mark.parametrize('keyword, node', [
    ('break', ast.Break),
    ('continue', ast.Continue),
], ids=['break', 'continue'])
def test_loop_exit_statement(keyword, node):
    source = 'def main() -> int:\n    while True:\n        %s\n' % keyword
    loop = parse(source).functions[0].body[0]
    statement = loop.body[0]
    assert (type(statement), statement.lineno) == (node, 3)

@pytest.mark.parametrize('keyword, msg', [
    ('break', "line 2, column 11: unexpected '='"),
    ('continue', "line 2, column 14: unexpected '='"),
], ids=['break', 'continue'])
def test_loop_exit_keyword_cannot_be_assigned(keyword, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    %s = 1\n' % keyword)
    assert info.value.msg == msg

# --- and, or, not, and elif (Milestone 11) -----------------------------------

def test_boolean_operators_and_elif_are_keywords():
    assert kinds('a and not b or c elif') == [
        'NAME', 'AND', 'NOT', 'NAME', 'OR', 'NAME', 'ELIF', 'NEWLINE']

@pytest.mark.parametrize('source, expected', [
    ('a and b or c',
     ('BoolOp', 'or', ('BoolOp', 'and', ('Name', 'a'), ('Name', 'b')),
      ('Name', 'c'))),
    ('a or b and c',
     ('BoolOp', 'or', ('Name', 'a'),
      ('BoolOp', 'and', ('Name', 'b'), ('Name', 'c')))),
    ('not a == b',
     ('Not', ('Compare', '==', ('Name', 'a'), ('Name', 'b')))),
    ('a and not b',
     ('BoolOp', 'and', ('Name', 'a'), ('Not', ('Name', 'b')))),
    ('(a or b) and c',
     ('BoolOp', 'and', ('BoolOp', 'or', ('Name', 'a'), ('Name', 'b')),
      ('Name', 'c'))),
    ('not not a', ('Not', ('Not', ('Name', 'a')))),
], ids=['and-before-or', 'or-after-and', 'not-over-compare',
        'not-in-and', 'parentheses', 'not-not'])
def test_boolean_operator_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

def print_body(text):
    return [('ExprStmt', ('Call', 'print', [('StrLiteral', text)]))]

@pytest.mark.parametrize('source, expected', [
    ('if a:\n        print("1")\n'
     '    elif b:\n        print("2")\n'
     '    else:\n        print("3")\n',
     ('If', ('Name', 'a'), print_body('1'),
      [('If', ('Name', 'b'), print_body('2'), print_body('3'))])),
    ('if a:\n        print("1")\n'
     '    elif b:\n        print("2")\n'
     '    elif c:\n        print("3")\n',
     ('If', ('Name', 'a'), print_body('1'),
      [('If', ('Name', 'b'), print_body('2'),
        [('If', ('Name', 'c'), print_body('3'), [])])])),
], ids=['elif-else', 'two-elifs'])
def test_elif_nests_an_if_in_the_else(source, expected):
    module = parse('def main() -> int:\n    %s' % source)
    assert shape(module.functions[0].body[0]) == expected

def test_an_elif_carries_its_own_line():
    statement = parse('def main() -> int:\n    if a:\n        pass\n'
                      '    elif b:\n        pass\n').functions[0].body[0]
    assert (statement.lineno, statement.orelse[0].lineno) == (2, 4)

@pytest.mark.parametrize('source, msg', [
    ('    print(a < b < c)\n', "line 2, column 17: unexpected '<'"),
    ('    and = 1\n', "line 2, column 5: unexpected 'and'"),
], ids=['chained-compare', 'and-as-name'])
def test_boolean_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n' + source)
    assert info.value.msg == msg

# --- dict[str, T] and in (Milestone 12) --------------------------------------

def test_braces_are_tokens():
    assert kinds('{"a": 1}') == [
        'LBRACE', 'STRING', 'COLON', 'INT', 'RBRACE', 'NEWLINE']

@pytest.mark.parametrize('source, expected', [
    ('{}', ('DictLiteral', [], [])),
    ('{"a": 1, "b": 2}',
     ('DictLiteral', [('StrLiteral', 'a'), ('StrLiteral', 'b')],
      [('IntLiteral', 1), ('IntLiteral', 2)])),
    ('{"a": 1,\n        "b": 2}',
     ('DictLiteral', [('StrLiteral', 'a'), ('StrLiteral', 'b')],
      [('IntLiteral', 1), ('IntLiteral', 2)])),
], ids=['empty', 'two-entries', 'newline-inside'])
def test_dict_literal_shapes(source, expected):
    module = parse('def main() -> int:\n    print(%s)\n' % source)
    call = module.functions[0].body[0].expr
    assert shape(call.args[0]) == expected

@pytest.mark.parametrize('source, expected', [
    ('a in b', ('In', ('Name', 'a'), ('Name', 'b'), False)),
    ('a not in b', ('In', ('Name', 'a'), ('Name', 'b'), True)),
    ('not a in b',
     ('Not', ('In', ('Name', 'a'), ('Name', 'b'), False))),
], ids=['in', 'not-in', 'not-over-in'])
def test_membership_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

def test_dict_type_on_a_parameter():
    fn = parse('def f(d: dict[str, int]) -> int:\n    return 0\n'
               ).functions[0]
    assert fn.param_types == ['dict[str, int]']

@pytest.mark.parametrize('source, msg', [
    ('def f(d: dict[int, str]) -> int:\n    return 0\n',
     'line 1, column 15: dict keys are str, not int'),
    ('def f(d: dict) -> int:\n    return 0\n',
     'line 1, column 10: dict needs a key and a value type: '
     'dict[str, int], dict[str, str], or dict[str, bool]'),
    ('class H(Handler[E]):\n    d: dict[str, int] = {"a": 1}\n',
     "line 2, column 23: a dict field's default must be {}"),
], ids=['int-key', 'bare-dict', 'field-default'])
def test_dict_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- f-strings (Milestone 13) ------------------------------------------------

@pytest.mark.parametrize('source, expected', [
    ('f"x"', ['FSTRING_START', 'FSTRING_MIDDLE', 'FSTRING_END']),
    ('f""', ['FSTRING_START', 'FSTRING_END']),
    ('f"a{n}b"',
     ['FSTRING_START', 'FSTRING_MIDDLE', 'LBRACE', 'NAME', 'RBRACE',
      'FSTRING_MIDDLE', 'FSTRING_END']),
    ('f"{a}{b}"',
     ['FSTRING_START', 'LBRACE', 'NAME', 'RBRACE', 'LBRACE', 'NAME',
      'RBRACE', 'FSTRING_END']),
    ('f\'{d["k"]}\'',
     ['FSTRING_START', 'LBRACE', 'NAME', 'LBRACKET', 'STRING',
      'RBRACKET', 'RBRACE', 'FSTRING_END']),
    ('f"{a and not b}"',
     ['FSTRING_START', 'LBRACE', 'NAME', 'AND', 'NOT', 'NAME', 'RBRACE',
      'FSTRING_END']),
], ids=['text', 'empty', 'field-between-text', 'adjacent-fields',
        'string-in-field', 'keywords-in-field'])
def test_fstring_tokens(source, expected):
    assert kinds(source) == expected + ['NEWLINE']

def test_fstring_middle_holds_the_literal_text():
    middle = tokenize('f"ab{n}"\n')[1]
    assert (middle.gettokentype(), middle.getstr()) == (
        'FSTRING_MIDDLE', 'ab')

def test_a_name_in_a_field_has_its_source_position():
    name = tokenize('x = f"ab{name}"\n')[5]
    pos = name.getsourcepos()
    assert (name.getstr(), pos.lineno, pos.colno) == ('name', 1, 10)

@pytest.mark.parametrize('source, msg', [
    ('f"{"', "line 1, column 3: f-string: expecting '}'"),
    ('    print(f"{")', "line 1, column 13: f-string: expecting '}'"),
    ('f"}"', "line 1, column 3: f-string: single '}' is not allowed"),
    ('f"{}"',
     "line 1, column 3: f-string: valid expression required before '}'"),
    ('f"a{ }b"',
     "line 1, column 4: f-string: valid expression required before '}'"),
    ('f"{{x}}"', "line 1, column 4: f-string: nested '{' is not allowed"),
    ('f"{$}"', "line 1, column 4: unexpected character '$'"),
], ids=['unclosed', 'unclosed-indented', 'single-close', 'empty-field',
        'blank-field', 'nested-open', 'bad-character'])
def test_fstring_lexing_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        tokenize(source)
    assert info.value.msg == msg

@pytest.mark.parametrize('source, expected', [
    ('f"a{n}b{m}"',
     ('FString', ['a', 'b', ''], [('Name', 'n'), ('Name', 'm')])),
    ('f""', ('FString', [''], [])),
    ('f"{a}{b}"',
     ('FString', ['', '', ''], [('Name', 'a'), ('Name', 'b')])),
    ('f"text"', ('FString', ['text'], [])),
    ('f"{n + 1}"',
     ('FString', ['', ''],
      [('BinOp', '+', ('Name', 'n'), ('IntLiteral', 1))])),
    ('f"{d[\'k\']}"',
     ('FString', ['', ''], [('Index', ('Name', 'd'), ('StrLiteral', 'k'))])),
    ('f"{a < b}"',
     ('FString', ['', ''], [('Compare', '<', ('Name', 'a'), ('Name', 'b'))])),
    ('f"{n}" + "s"',
     ('BinOp', '+', ('FString', ['', ''], [('Name', 'n')]),
      ('StrLiteral', 's'))),
    ('xs[f"{n}"]',
     ('Index', ('Name', 'xs'), ('FString', ['', ''], [('Name', 'n')]))),
    ('print(f"{n}", f"{m}")',
     ('Call', 'print', [('FString', ['', ''], [('Name', 'n')]),
                        ('FString', ['', ''], [('Name', 'm')])])),
], ids=['two-fields', 'empty', 'adjacent-fields', 'text-only',
        'binop-field', 'index-field', 'compare-field', 'left-of-plus',
        'index-key', 'two-arguments'])
def test_fstring_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    statement = module.functions[0].body[0]
    assert shape(statement) == ('ExprStmt', expected)

def test_an_fstring_carries_the_line_of_its_start():
    statement = parse('def main() -> int:\n    x = (1 +\n'
                      '        f"{n}")\n').functions[0].body[0]
    assert statement.value.right.lineno == 3

@pytest.mark.parametrize('source, msg', [
    ('f"{n=}"', "line 2, column 9: unexpected '='"),
    ('f"{n +}"', "line 2, column 11: unexpected '}'"),
], ids=['self-documenting', 'incomplete-expr'])
def test_fstring_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    %s\n' % source)
    assert info.value.msg == msg

# --- augmented assignment (Milestone 14) -------------------------------------

@pytest.mark.parametrize('source, expected', [
    ('x += 1', ['NAME', 'PLUSEQUALS', 'INT']),
    ('x -= 1', ['NAME', 'MINUSEQUALS', 'INT']),
    ('x *= 1', ['NAME', 'STAREQUALS', 'INT']),
    ('x //= 1', ['NAME', 'DOUBLESLASHEQUALS', 'INT']),
    ('x %= 1', ['NAME', 'PERCENTEQUALS', 'INT']),
    ('x // y', ['NAME', 'DOUBLESLASH', 'NAME']),
    ('a -> b', ['NAME', 'ARROW', 'NAME']),
    ('x == y', ['NAME', 'EQ', 'NAME']),
], ids=['plus', 'minus', 'star', 'doubleslash', 'percent',
        'floor-divide', 'arrow', 'equality'])
def test_augmented_tokens(source, expected):
    assert kinds(source) == expected + ['NEWLINE']

@pytest.mark.parametrize('op', ['+', '-', '*', '//', '%'])
def test_a_name_target_builds_an_assign_over_a_binop(op):
    module = parse('def main() -> int:\n    x %s= v\n' % op)
    assert shape(module.functions[0].body[0]) == (
        'Assign', 'x', ('BinOp', op, ('Name', 'x'), ('Name', 'v')))

def test_a_field_target_builds_an_attr_assign_over_a_binop():
    module = parse('def main() -> int:\n    self.n += 1\n')
    assert shape(module.functions[0].body[0]) == (
        'AttrAssign', 'self', 'n',
        ('BinOp', '+', ('AttrRead', 'self', 'n'), ('IntLiteral', 1)))

@pytest.mark.parametrize('source, expected', [
    ('xs[i] += v',
     ('IndexAugAssign', '+', ('Name', 'xs'), ('Name', 'i'),
      ('Name', 'v'))),
    ('d["k"] //= 2',
     ('IndexAugAssign', '//', ('Name', 'd'), ('StrLiteral', 'k'),
      ('IntLiteral', 2))),
], ids=['list', 'dict'])
def test_a_subscript_target_builds_an_index_aug_assign(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    assert shape(module.functions[0].body[0]) == expected

@pytest.mark.parametrize('source', [
    'x += 1', 'self.n += 1', 'xs[i] += 1',
], ids=['name', 'field', 'subscript'])
def test_an_augmented_assignment_carries_its_line(source):
    module = parse('def main() -> int:\n    pass\n    %s\n' % source)
    assert module.functions[0].body[1].lineno == 3

@pytest.mark.parametrize('source, msg', [
    ('f() += 1', 'line 2, column 9: cannot assign to this expression'),
    ('1 += 1', 'line 2, column 7: cannot assign to this expression'),
    ('x + = 1', "line 2, column 9: unexpected '='"),
], ids=['call', 'literal', 'split-operator'])
def test_augmented_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    %s\n' % source)
    assert info.value.msg == msg

# --- None and optional types (Milestone 16) ----------------------------------

def test_none_and_is_are_keywords_and_the_bar_is_a_token():
    assert kinds('x: int | None = y is not None') == [
        'NAME', 'COLON', 'NAME', 'PIPE', 'NONE', 'EQUALS', 'NAME', 'IS',
        'NOT', 'NONE', 'NEWLINE']

@pytest.mark.parametrize('source, expected', [
    ('x = None', ('Assign', 'x', ('NoneLiteral',))),
    ('x = y is None', ('Assign', 'x', ('IsNone', ('Name', 'y'), False))),
    ('x = y is not None',
     ('Assign', 'x', ('IsNone', ('Name', 'y'), True))),
    ('x = not y is None',
     ('Assign', 'x', ('Not', ('IsNone', ('Name', 'y'), False)))),
    ('x = f() is None and z',
     ('Assign', 'x',
      ('BoolOp', 'and', ('IsNone', ('Call', 'f', []), False),
       ('Name', 'z')))),
], ids=['literal', 'is', 'is-not', 'not-is', 'and'])
def test_none_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    assert shape(module.functions[0].body[0]) == expected

@pytest.mark.parametrize('written', [
    'None', 'int | None', 'str | None', 'bool | None'])
def test_a_type_may_be_none_or_optional(written):
    module = parse('def f(x: %s) -> %s:\n    return x\n'
                   % (written, written))
    fn = module.functions[0]
    assert (fn.param_types, fn.return_type) == ([written], written)

def test_an_operation_may_return_an_optional_with_a_row():
    module = parse('class A(Effect):\n'
                   '    def get(key: str) -> str | None / [E]: ...\n')
    op = module.effects[0].operations[0]
    assert (op.return_type, op.row) == ('str | None', ['E'])

@pytest.mark.parametrize('source, msg', [
    ('    None = 1\n',
     'line 2, column 10: cannot assign to this expression'),
    ('    x = y is z\n', "line 2, column 14: unexpected 'z'"),
    ('    x = y is not 1\n', "line 2, column 18: unexpected '1'"),
    ('    x = 1 | 2\n', "line 2, column 11: unexpected '|'"),
    ('    x = y is None == True\n',
     "line 2, column 19: unexpected '=='"),
], ids=['assign-none', 'is-name', 'is-not-literal', 'bar', 'chain'])
def test_none_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n' + source)
    assert info.value.msg == msg

@pytest.mark.parametrize('written, msg', [
    ('int | str', "line 1, column 16: unexpected 'str'"),
    ('None | int', "line 1, column 15: unexpected '|'"),
    ('list[int] | None', "line 1, column 20: unexpected '|'"),
    ('list | None',
     'line 1, column 10: list | None is not a type; the optional types '
     'are int | None, str | None, bool | None, tuple[...] | None, and '
     'a data class | None'),
], ids=['union', 'none-first', 'list', 'bare-list'])
def test_optional_type_errors(written, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def f(x: %s) -> int:\n    return 0\n' % written)
    assert info.value.msg == msg

# --- Tuples (Milestone 17) ---------------------------------------------------

@pytest.mark.parametrize('source, expected', [
    ('t = (1, "a")',
     ('Assign', 't',
      ('TupleLiteral', [('IntLiteral', 1), ('StrLiteral', 'a')]))),
    ('t = (a, b, c)',
     ('Assign', 't',
      ('TupleLiteral', [('Name', 'a'), ('Name', 'b'), ('Name', 'c')]))),
    ('t = (a)', ('Assign', 't', ('Name', 'a'))),
    ('a, b = t', ('Unpack', ['a', 'b'], ('Name', 't'))),
    ('a, b, c = f()', ('Unpack', ['a', 'b', 'c'], ('Call', 'f', []))),
    ('b, a = (a, b)',
     ('Unpack', ['b', 'a'],
      ('TupleLiteral', [('Name', 'a'), ('Name', 'b')]))),
], ids=['pair', 'triple', 'parenthesized', 'unpack', 'unpack-three',
        'swap'])
def test_tuple_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    assert shape(module.functions[0].body[0]) == expected

def test_an_unpack_carries_its_line():
    module = parse('def main() -> int:\n    pass\n    a, b = t\n')
    assert module.functions[0].body[1].lineno == 3

@pytest.mark.parametrize('written', [
    'tuple[int, str]', 'tuple[str, str, bool]',
    'tuple[int, int, int, int]', 'tuple[str, str] | None',
    'tuple[int, str, bool] | None'])
def test_a_type_may_be_a_tuple_or_its_optional(written):
    module = parse('def f(x: %s) -> %s:\n    return x\n'
                   % (written, written))
    fn = module.functions[0]
    assert (fn.param_types, fn.return_type) == ([written], written)

@pytest.mark.parametrize('source, msg', [
    ('    t = (1,)\n', "line 2, column 12: unexpected ')'"),
    ('    t = ()\n', "line 2, column 10: unexpected ')'"),
    ('    t = 1, 2\n', "line 2, column 10: unexpected ','"),
    ('    return 1, 2\n', "line 2, column 13: unexpected ','"),
    ('    a, b.c = t\n',
     'line 2, column 12: cannot assign to this expression'),
    ('    a, 1 = t\n',
     'line 2, column 10: cannot assign to this expression'),
], ids=['one-element', 'empty', 'bare', 'bare-return', 'field-target',
        'literal-target'])
def test_tuple_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n' + source)
    assert info.value.msg == msg

@pytest.mark.parametrize('written, msg', [
    ('tuple', 'line 1, column 10: tuple needs element types: '
     'tuple[int, str]'),
    ('tuple[int]', 'line 1, column 10: a tuple has two or more element '
     'types: tuple[int, str]'),
    ('tuple[int, list]',
     'line 1, column 10: tuple[..., list] is not a type; an element '
     'type is int, str, or bool'),
    ('dict[str, int, int]',
     "line 1, column 10: 'dict' takes no list of element types; "
     "tuple[...] does"),
    ('dict[str, int] | None',
     'line 1, column 10: dict[...] | None is not a type; the optional '
     'types are int | None, str | None, bool | None, '
     'tuple[...] | None, and a data class | None'),
], ids=['bare', 'one', 'element', 'dict-three', 'dict-optional'])
def test_tuple_type_errors(written, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def f(x: %s) -> int:\n    return 0\n' % written)
    assert info.value.msg == msg

# --- Data classes (Milestone 19) ---------------------------------------------

TASK = ('@dataclass\nclass Task:\n    name: str\n'
        '    needs: list[str] = []\n    done: bool = False\n')

def test_a_data_class_is_a_datadef_of_fields():
    module = parse('from dataclasses import dataclass\n' + TASK)
    assert shape(module.records) == [
        ('DataDef', 'Task',
         [('FieldDef', 'name', 'str', None),
          ('FieldDef', 'needs', 'list[str]', ('ListLiteral', [])),
          ('FieldDef', 'done', 'bool', ('BoolLiteral', False))])]

@pytest.mark.parametrize('written', [
    'Task', 'list[Task]', 'dict[str, Task]', 'Task | None',
])
def test_a_type_may_name_a_class(written):
    fn = parse('def f(x: %s) -> %s:\n    return x\n'
               % (written, written)).functions[0]
    assert (fn.param_types, fn.return_type) == ([written], written)

@pytest.mark.parametrize('source, msg', [
    ('class Task:\n    name: str\n',
     'line 1, column 1: a class with no base needs @dataclass on the '
     'line above it'),
    ('@other\nclass Task:\n    name: str\n',
     'line 1, column 2: the one decorator is @dataclass, above a class'),
    ('@dataclass(frozen=True)\nclass Task:\n    name: str\n',
     "line 1, column 11: unexpected '('"),
    ('@dataclass\nclass Task:\n    name: str\n'
     '    def run(self) -> int:\n        return 0\n',
     'line 2, column 1: a data class has fields and no methods'),
    ('@dataclass\nclass Task(Effect):\n    name: str\n',
     "line 2, column 11: unexpected '('"),
    ('@dataclass\ndef f() -> int:\n    return 0\n',
     "line 2, column 1: unexpected 'def'"),
    ('@dataclass\nclass Task:\n    pass\n',
     "line 3, column 5: unexpected 'pass'"),
], ids=['no-decorator', 'other-decorator', 'decorator-arguments',
        'method', 'base', 'function', 'no-fields'])
def test_data_class_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse(source)
    assert info.value.msg == msg

# --- A field through any expression (Milestone 20) ---------------------------

FIRST = ('Index', ('Name', 'ts'), ('IntLiteral', 0))

@pytest.mark.parametrize('source, expected', [
    ('x = ts[0].name', ('Assign', 'x', ('FieldRead', FIRST, 'name'))),
    ('x = make().name',
     ('Assign', 'x', ('FieldRead', ('Call', 'make', []), 'name'))),
    ('x = t.name', ('Assign', 'x', ('AttrRead', 't', 'name'))),
    ('ts[0].n = 4',
     ('FieldAssign', '', FIRST, 'n', ('IntLiteral', 4))),
    ('ts[0].n += 4',
     ('FieldAssign', '+', FIRST, 'n', ('IntLiteral', 4))),
    ('ts[0].needs.append(1)',
     ('ExprStmt', ('MethodCall', ('FieldRead', FIRST, 'needs'),
                   'append', [('IntLiteral', 1)]))),
    ('x = p.ts[0].name',
     ('Assign', 'x',
      ('FieldRead', ('Index', ('AttrRead', 'p', 'ts'),
                     ('IntLiteral', 0)), 'name'))),
], ids=['index', 'call', 'name', 'store', 'augmented', 'method',
        'through-a-field'])
def test_field_shapes(source, expected):
    module = parse('def main() -> int:\n    %s\n' % source)
    assert shape(module.functions[0].body[0]) == expected

# --- join(), get(), and ** (Milestone 21) ------------------------------------

TWO = ('IntLiteral', 2)
THREE = ('IntLiteral', 3)

@pytest.mark.parametrize('source, expected', [
    ('2 ** 3', ('BinOp', '**', TWO, THREE)),
    ('2 ** 3 ** 2', ('BinOp', '**', TWO, ('BinOp', '**', THREE, TWO))),
    ('-2 ** 3',
     ('BinOp', '-', ('IntLiteral', 0), ('BinOp', '**', TWO, THREE))),
    ('2 ** -3', ('BinOp', '**', TWO, ('IntLiteral', -3))),
    ('2 * 3 ** 2',
     ('BinOp', '*', TWO, ('BinOp', '**', THREE, TWO))),
    ('2 ** 3 * 2',
     ('BinOp', '*', ('BinOp', '**', TWO, THREE), TWO)),
    ('-2', ('IntLiteral', -2)),
], ids=['power', 'right-to-left', 'minus-on-the-left',
        'minus-on-the-right', 'under-times', 'before-times', 'literal'])
def test_power_shapes(source, expected):
    module = parse('def main() -> int:\n    return %s\n' % source)
    assert shape(module.functions[0].body[0]) == ('Return', expected)

def test_an_augmented_power_is_the_assignment_it_means():
    module = parse('def main() -> int:\n    x **= 2\n')
    assert shape(module.functions[0].body[0]) == (
        'Assign', 'x', ('BinOp', '**', ('Name', 'x'), TWO))

@pytest.mark.parametrize('source, expected', [
    ('", ".join(ws)',
     ('MethodCall', ('StrLiteral', ', '), 'join', [('Name', 'ws')])),
    ('d.get("a", 0)',
     ('OpCall', 'd', 'get', [('StrLiteral', 'a'), ('IntLiteral', 0)])),
], ids=['join-on-a-literal', 'get-on-a-name'])
def test_method_shapes(source, expected):
    module = parse('def main() -> int:\n    return %s\n' % source)
    assert shape(module.functions[0].body[0]) == ('Return', expected)

# --- for k, v in d.items() (Milestone 22) ------------------------------------

@pytest.mark.parametrize('iterable, target', [
    ('d.items()', ('Name', 'd')),
    ('self.d.items()', ('AttrRead', 'self', 'd')),
    ('make().items()', ('Call', 'make', [])),
], ids=['name', 'field', 'call'])
def test_a_for_with_two_names_is_a_foritems(iterable, target):
    module = parse('def main() -> int:\n    for k, v in %s:\n'
                   '        pass\n' % iterable)
    assert shape(module.functions[0].body[0]) == (
        'ForItems', 'k', 'v', target, [('Pass',)])

@pytest.mark.parametrize('header, msg', [
    ('for k, v in d:',
     'line 2, column 10: a for with two names walks a dict: '
     'for k, v in d.items()'),
    ('for k, v in d.items(1):',
     'line 2, column 10: a for with two names walks a dict: '
     'for k, v in d.items()'),
    ('for k, v in d.keys():',
     'line 2, column 10: a for with two names walks a dict: '
     'for k, v in d.items()'),
    ('for k, k in d.items():',
     'line 2, column 12: the two names of a for must differ'),
    ('for a, b, c in d.items():', "line 2, column 13: unexpected ','"),
], ids=['no-call', 'arguments', 'other-method', 'same-name', 'three'])
def test_for_items_syntax_errors(header, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    %s\n        pass\n' % header)
    assert info.value.msg == msg

# --- Keyword arguments (Milestone 23) ----------------------------------------

ONE = ('IntLiteral', 1)

@pytest.mark.parametrize('source, expected', [
    ('f(a=1)', ('KeywordCall', 'f', [ONE], ['a'])),
    ('f(2, a=1, b=x)',
     ('KeywordCall', 'f', [TWO, ONE, ('Name', 'x')], ['a', 'b'])),
    ('f(a == 1)',
     ('Call', 'f', [('Compare', '==', ('Name', 'a'), ONE)])),
    ('f(2)', ('Call', 'f', [TWO])),
], ids=['keyword', 'after-positional', 'comparison', 'positional'])
def test_keyword_call_shapes(source, expected):
    module = parse('def main() -> int:\n    return %s\n' % source)
    assert shape(module.functions[0].body[0]) == ('Return', expected)

@pytest.mark.parametrize('source, msg', [
    ('f(a=1, a=2)', 'line 2, column 19: keyword argument repeated: a'),
    ('f(a=1, 2)',
     'line 2, column 17: positional argument follows keyword argument'),
    ('perform(E.op(a=1))', "line 2, column 26: unexpected '='"),
    ('perform(x=E.op())',
     'line 2, column 12: perform() takes one Effect.op(...) argument'),
    ('xs.append(value=1)', "line 2, column 27: unexpected '='"),
    ('f(1=2)', "line 2, column 15: unexpected '='"),
], ids=['repeated', 'positional-after', 'operation', 'perform',
        'method', 'literal-name'])
def test_keyword_syntax_errors(source, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    return %s\n' % source)
    assert info.value.msg == msg

def test_a_constructor_inside_handle_takes_no_keywords():
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    with handle(Fake(n=1)):\n'
              '        pass\n')
    assert info.value.msg == "line 2, column 23: unexpected '='"

# --- Format specs (Milestone 24) ---------------------------------------------

N = ('Name', 'n')

@pytest.mark.parametrize('spec, parts', [
    ('8', ('', '', False, 8, '')),
    ('>8', ('', '>', False, 8, '')),
    ('*<5', ('*', '<', False, 5, '')),
    ('05', ('', '', True, 5, '')),
    ('^6d', ('', '^', False, 6, 'd')),
    ('0<5', ('0', '<', False, 5, '')),
    ('<05', ('', '<', True, 5, '')),
    ('s', ('', '', False, 0, 's')),
    ('<<3', ('<', '<', False, 3, '')),
], ids=['width', 'align', 'fill', 'zero', 'kind', 'zero-fill',
        'align-then-zero', 'kind-alone', 'fill-is-an-alignment'])
def test_a_format_spec_is_read_into_its_parts(spec, parts):
    module = parse('def main() -> int:\n    x = f"a{n:%s}b"\n' % spec)
    assert shape(module.functions[0].body[0]) == (
        'Assign', 'x',
        ('FString', ['a', 'b'], [('Formatted', N) + parts]))

def test_a_colon_in_a_string_is_no_spec():
    module = parse('def main() -> int:\n'
                   '    x = f"{d[\'a:b\']:3}{d[\'c:d\']}"\n')
    key = ('Index', ('Name', 'd'), ('StrLiteral', 'a:b'))
    assert shape(module.functions[0].body[0]) == (
        'Assign', 'x',
        ('FString', ['', '', ''],
         [('Formatted', key, '', '', False, 3, ''),
          ('Index', ('Name', 'd'), ('StrLiteral', 'c:d'))]))

SPEC_FORM = ('f-string: a format spec is [[fill]align][0][width]'
             "[d or s], not '%s'")

@pytest.mark.parametrize('field, msg', [
    ('n:', 'line 2, column 13: ' + SPEC_FORM % ''),
    ('n:8.2', 'line 2, column 13: ' + SPEC_FORM % '8.2'),
    ('n:,', 'line 2, column 13: ' + SPEC_FORM % ','),
    ('n:=5', 'line 2, column 13: ' + SPEC_FORM % '=5'),
    ('n:5x', 'line 2, column 13: ' + SPEC_FORM % '5x'),
    ('n:{w}', "line 2, column 14: f-string: nested '{' is not allowed"),
    (':8', "line 2, column 11: f-string: valid expression required "
     "before ':'"),
    ('', "line 2, column 11: f-string: valid expression required "
     "before '}'"),
    ('n!r', "line 2, column 13: unexpected character '!'"),
], ids=['empty', 'precision', 'comma', 'equals', 'other-letter',
        'nested', 'no-expression', 'empty-field', 'conversion'])
def test_format_spec_syntax_errors(field, msg):
    with pytest.raises(InvalidSyntax) as info:
        parse('def main() -> int:\n    x = f"{%s}"\n' % field)
    assert info.value.msg == msg

