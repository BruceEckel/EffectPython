"""Milestone 2 acceptance: the static effect checker (plan 2.2, 4.2),
from Milestone 5 the handler class rules (plan 1.5), from Milestone 6
the exception rules (plan 1.6), from Milestone 7 the throw rules
(plan 1.7), from Milestone 8 the finally rules (plan 1.8), from
Milestone 9 the list and for rules (plan 1.9), from Milestone 10
the loop rule for break and continue (plan 1.10) and the type rules
for return values, loop and try merging, and [] aliasing, and from
Milestone 11 the bool rule for and, or, not, if, and while, and elif
(plan 1.11), from Milestone 12 the dict and in rules (plan 1.12),
from Milestone 13 the f-string field rule (plan 1.13), and from
Milestone 14 the augmented assignment rules (plan 1.14).

Run with:  pypy2 -m pytest
"""
import pytest

from effectpython.checker import check
from effectpython.errors import InvalidProgram, UnhandledEffectError
from effectpython.parser import parse
from support import read_program

EFFECTS = '''\
class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

class DBQuery(Effect):
    def execute(sql: str) -> str: ...

'''

def check_source(body):
    check(parse(EFFECTS + body))

def test_accepts_a_program_whose_main_handles_everything():
    check(parse(read_program('read_config.epy')))

def test_accepts_fibonacci():
    check(parse(read_program('fib.epy')))

def test_effects_performed_in_a_loop_count_for_the_function():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('def f() -> int:\n'
                     '    while 1 < 2:\n'
                     '        perform(FileIO.read("a"))\n'
                     '    return 0\n'
                     'def main() -> int / []:\n'
                     '    return 0\n')
    assert 'FileIO (line 10)' in info.value.msg

def test_rejects_perform_without_the_effect_in_the_row():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('def read_config(path: str) -> str:\n'
                     '    return perform(FileIO.read(path))\n'
                     'def main() -> int / []:\n'
                     '    return 0\n')
    assert info.value.msg == (
        "line 8: function 'read_config' performs FileIO (line 9) without "
        "declaring it in its effect row")

def test_rejects_handle_missing_a_clause():
    with pytest.raises(InvalidProgram) as info:
        check_source('def main() -> int / []:\n'
                     '    try:\n'
                     '        with handle(FileIO):\n'
                     '            pass\n'
                     '    except FileIO.read as eff:\n'
                     '        eff.resume("x")\n'
                     '    return 0\n')
    assert info.value.msg == (
        'line 9: handle(FileIO) is missing a clause for FileIO.write')

def test_callee_effects_flow_into_the_caller():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('def f() -> str / [FileIO]:\n'
                     '    return perform(FileIO.read("a"))\n'
                     'def g() -> str / [DBQuery]:\n'
                     '    perform(DBQuery.execute("q"))\n'
                     '    return f()\n'
                     'def main() -> int / []:\n'
                     '    return 0\n')
    assert info.value.msg == (
        "line 10: function 'g' performs FileIO (line 12) without declaring "
        "it in its effect row")

def test_effects_performed_in_a_clause_count_for_the_function():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('def main() -> int / []:\n'
                     '    try:\n'
                     '        with handle(FileIO):\n'
                     '            pass\n'
                     '    except FileIO.read as eff:\n'
                     '        eff.resume(perform(DBQuery.execute("q")))\n'
                     '    except FileIO.write as eff:\n'
                     '        pass\n'
                     '    return 0\n')
    assert 'DBQuery (line 13)' in info.value.msg

def test_nested_handles_discharge_their_own_effects():
    check_source('def both() -> str / [FileIO, DBQuery]:\n'
                 '    perform(FileIO.write("a", "b"))\n'
                 '    return perform(DBQuery.execute("q"))\n'
                 'def main() -> int / []:\n'
                 '    try:\n'
                 '        with handle(FileIO):\n'
                 '            try:\n'
                 '                with handle(DBQuery):\n'
                 '                    print(both())\n'
                 '            except DBQuery.execute as q:\n'
                 '                q.resume(q.sql)\n'
                 '    except FileIO.read as eff:\n'
                 '        eff.resume(eff.path)\n'
                 '    except FileIO.write as eff:\n'
                 '        eff.resume(1)\n'
                 '    return 0\n')

def test_recursion_uses_the_declared_row():
    check_source('def down(n: int) -> int / [FileIO]:\n'
                 '    if n == 0:\n'
                 '        return perform(FileIO.write("done", "x"))\n'
                 '    return down(n - 1)\n'
                 'def main() -> int / []:\n'
                 '    try:\n'
                 '        with handle(FileIO):\n'
                 '            down(3)\n'
                 '    except FileIO.read as eff:\n'
                 '        eff.resume("")\n'
                 '    except FileIO.write as eff:\n'
                 '        eff.resume(0)\n'
                 '    return 0\n')

MAIN = 'def main() -> int / []:\n    return 0\n'

@pytest.mark.parametrize('body, error, msg', [
    ('', InvalidProgram, 'no main() function defined'),
    ('def main(n: int) -> int / []:\n    return 0\n',
     InvalidProgram, 'line 8: main() takes no parameters'),
    ('def main() -> int / [FileIO]:\n    return 0\n',
     UnhandledEffectError,
     'line 8: main() must have an empty effect row, not [FileIO]'),
    ('def f() -> int / [Nope]:\n    return 0\n' + MAIN,
     InvalidProgram,
     "line 8: 'Nope' is not an effect or an exception class"),
    ('def f() -> int:\n    return perform(Nope.read("a"))\n' + MAIN,
     InvalidProgram, "line 9: unknown effect 'Nope'"),
    ('def f() -> int / [FileIO]:\n    return perform(FileIO.nope())\n'
     + MAIN, InvalidProgram,
     "line 9: effect 'FileIO' has no operation 'nope'"),
    ('def f() -> str / [FileIO]:\n    return perform(FileIO.read())\n'
     + MAIN, InvalidProgram,
     'line 9: FileIO.read takes 1 arguments (0 given)'),
    ('def f() -> str / [FileIO]:\n    return perform(FileIO.read(1))\n'
     + MAIN, InvalidProgram,
     'line 9: argument 1 of FileIO.read must be str, not int'),
    ('def f() -> int:\n    x = FileIO.read("a")\n    return 0\n' + MAIN,
     InvalidProgram,
     'line 9: FileIO.read(...) must be the argument of perform()'),
    ('def f() -> int:\n    return g(1)\n' + MAIN,
     InvalidProgram, "line 9: name 'g' is not defined"),
    ('def g(a: int, b: int) -> int:\n    return a\n'
     'def f() -> int:\n    return g(1)\n' + MAIN,
     InvalidProgram, 'line 11: g() takes 2 arguments (1 given)'),
    ('def g(a: int) -> int:\n    return a\n'
     'def f() -> int:\n    return g("s")\n' + MAIN,
     InvalidProgram, 'line 11: argument 1 of g() must be int, not str'),
    ('def g(a: int) -> int:\n    return a\n'
     'def f() -> int:\n    return g(True)\n' + MAIN,
     InvalidProgram, 'line 11: argument 1 of g() must be int, not bool'),
    ('def main() -> int / []:\n    try:\n        with handle(FileIO):\n'
     '            pass\n    except DBQuery.execute as e:\n        pass\n'
     '    except FileIO.read as e:\n        pass\n'
     '    except FileIO.write as e:\n        pass\n    return 0\n',
     InvalidProgram,
     'line 12: clause for DBQuery.execute, but handle(FileIO) does not '
     'name DBQuery'),
    ('def main() -> int / []:\n    try:\n        with handle(FileIO):\n'
     '            pass\n    except FileIO.read as e:\n        pass\n'
     '    except FileIO.read as e:\n        pass\n'
     '    except FileIO.write as e:\n        pass\n    return 0\n',
     InvalidProgram, 'line 14: duplicate clause for FileIO.read'),
    ('def main() -> int / []:\n    try:\n        with handle(FileIO):\n'
     '            pass\n    except FileIO.read as e:\n'
     '        e.resume(e.size)\n'
     '    except FileIO.write as e:\n        pass\n    return 0\n',
     InvalidProgram,
     "line 13: operation FileIO.read has no parameter 'size'"),
    ('def main() -> int / []:\n    try:\n        with handle(FileIO):\n'
     '            pass\n    except FileIO.read as e:\n'
     '        e.resume(1)\n'
     '    except FileIO.write as e:\n        pass\n    return 0\n',
     InvalidProgram,
     'line 13: e.resume() for FileIO.read must pass str, not int'),
    ('def f() -> int:\n    x = 1\n    return x.resume(1)\n' + MAIN,
     InvalidProgram,
     "line 10: 'x' is not an except binding or a handler instance"),
    ('def f() -> int:\n    return x.path\n' + MAIN,
     InvalidProgram, "line 9: name 'x' is not defined"),
    ('def f() -> int:\n    return x + 1\n' + MAIN,
     InvalidProgram, "line 9: name 'x' is not defined"),
    ('def f() -> int:\n    return 0\ndef f() -> int:\n    return 1\n'
     + MAIN, InvalidProgram, "line 10: function 'f' is defined twice"),
    ('class FileIO(Effect):\n    def read(path: str) -> str: ...\n' + MAIN,
     InvalidProgram, "line 8: effect 'FileIO' is declared twice"),
])
def test_rejected_programs(body, error, msg):
    with pytest.raises(error) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('expr, msg', [
    ('"a" + 1', 'str and int'),
    ('1 < "b"', 'int and str'),
    ('"a" - "b"', 'str and str'),
    ('"a" < "b"', 'str and str'),
    ('True < False', 'bool and bool'),
    ('(1 == 1) + 1', 'bool and int'),
])
def test_rejects_operands_of_the_wrong_types(expr, msg):
    op = expr.split(' ')[-2]
    with pytest.raises(InvalidProgram) as info:
        check_source('def f() -> int:\n    x = %s\n    return 0\n'
                     % expr + MAIN)
    assert info.value.msg == (
        'line 9: unsupported operand types for %s: %s' % (op, msg))

@pytest.mark.parametrize('expr', [
    '1 + 2 * 3 // 4 % 5', '1 < 2', '7 == 7', '"a" + "b"', '"a" != "b"',
    'True == False',
])
def test_accepts_operands_of_matching_types(expr):
    check_source('def f() -> int:\n    x = %s\n    return 0\n'
                 % expr + MAIN)

def test_accepts_a_name_bound_each_way():
    check_exceptions(
        'class Fake(Handler[FileIO]):\n    n: int = 0\n'
        '    def read(self, path: str) -> str:\n'
        '        return path\n'
        '    def write(self, path: str, content: str) -> int:\n'
        '        return self.n\n'
        'def f(a: int) -> int / []:\n    b = a + 1\n'
        '    fake = Fake()\n    with handle(fake):\n        pass\n'
        '    try:\n        with handle(DBQuery):\n            pass\n'
        '    except DBQuery.execute as eff:\n        print(eff.sql)\n'
        '    try:\n        raise NotFound("x")\n'
        '    except NotFound as e:\n        print(e)\n'
        '    return b + fake.n\n' + MAIN)

def test_rejects_a_read_before_the_assignment_in_source_order():
    with pytest.raises(InvalidProgram) as info:
        check_source('def f() -> int:\n    i = 0\n    while i < 2:\n'
                     '        print(x)\n        x = i\n'
                     '        i = i + 1\n    return 0\n' + MAIN)
    assert info.value.msg == "line 11: name 'x' is not defined"

@pytest.mark.parametrize('expr', ['eff + 1', '"a" + eff', 'eff < eff'])
def test_accepts_an_operand_of_unknown_type(expr):
    check_source('def main() -> int / []:\n    try:\n'
                 '        with handle(DBQuery):\n            pass\n'
                 '    except DBQuery.execute as eff:\n        x = %s\n'
                 '    return 0\n' % expr)

# --- Handler classes (Milestone 5) -------------------------------------------

HANDLERS = EFFECTS + '''\
class Log(Effect):
    def note(text: str) -> int: ...

class FakeFileIO(Handler[FileIO]):
    def read(self, path: str) -> str:
        return "contents of " + path
    def write(self, path: str, content: str) -> int / [Log]:
        perform(Log.note("writing " + path))
        return 7

class CountingFileIO(Handler[FileIO]):
    writes: int = 0
    def read(self, path: str) -> str:
        return path
    def write(self, path: str, content: str) -> int:
        self.writes = self.writes + 1
        return self.writes

'''

def check_handlers(body):
    check(parse(HANDLERS + body))

def test_accepts_the_counting_handler_program():
    check(parse(read_program('counting_handler.epy')))

def test_accepts_the_plan_example_with_a_method_row_handled_outside():
    check_handlers('def load_app(name: str) -> int / [FileIO]:\n'
                   '    config = perform(FileIO.read(name + ".json"))\n'
                   '    return perform(FileIO.write(name, config))\n'
                   'def main() -> int / []:\n'
                   '    try:\n'
                   '        with handle(Log):\n'
                   '            with handle(FakeFileIO()):\n'
                   '                print(load_app("settings"))\n'
                   '    except Log.note as eff:\n'
                   '        print("log:", eff.text)\n'
                   '        eff.resume(0)\n'
                   '    return 0\n')

def test_accepts_a_construction_beside_an_inline_clause():
    check_handlers('def main() -> int / []:\n'
                   '    try:\n'
                   '        with handle(CountingFileIO(), DBQuery):\n'
                   '            perform(DBQuery.execute("q"))\n'
                   '            perform(FileIO.read("a"))\n'
                   '    except DBQuery.execute as eff:\n'
                   '        eff.resume(eff.sql)\n'
                   '    return 0\n')

def test_a_handler_discharges_its_effect_from_the_body():
    check_handlers('def f() -> str:\n'
                   '    with handle(CountingFileIO(5)):\n'
                   '        return perform(FileIO.read("a"))\n'
                   '    return ""\n' + MAIN)

def test_a_method_row_flows_to_the_enclosing_function():
    with pytest.raises(UnhandledEffectError) as info:
        check_handlers('def f() -> int:\n'
                       '    with handle(FakeFileIO()):\n'
                       '        return perform(FileIO.write("a", "b"))\n'
                       '    return 0\n' + MAIN)
    assert info.value.msg == (
        "line 26: function 'f' performs Log (line 27) without declaring "
        "it in its effect row")

def test_a_method_declares_what_it_performs():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('class Fake(Handler[FileIO]):\n'
                     '    def read(self, path: str) -> str:\n'
                     '        return perform(DBQuery.execute(path))\n'
                     '    def write(self, path: str, content: str) -> int:\n'
                     '        return 0\n' + MAIN)
    assert info.value.msg == (
        "line 9: method 'read' performs DBQuery (line 10) without "
        "declaring it in its effect row")

def test_instance_fields_are_typed_after_the_block():
    check_handlers('def main() -> int / []:\n'
                   '    fake = CountingFileIO()\n'
                   '    with handle(fake):\n'
                   '        perform(FileIO.write("a", "b"))\n'
                   '    return fake.writes\n')

FAKE = ('class Fake(Handler[FileIO]):\n'
        '    def read(self, path: str) -> str:\n'
        '        return path\n'
        '    def write(self, path: str, content: str) -> int:\n'
        '        return 0\n')

@pytest.mark.parametrize('body, error, msg', [
    ('class Fake(Handler[FileIO]):\n'
     '    def read(self, path: str) -> str:\n        return path\n' + MAIN,
     InvalidProgram,
     "line 8: handler class 'Fake' has no method for FileIO.write"),
    (FAKE + '    def nope(self) -> int:\n        return 0\n' + MAIN,
     InvalidProgram,
     "line 13: method 'nope' of handler class 'Fake' is not an operation "
     "of FileIO"),
    ('class Fake(Handler[FileIO]):\n'
     '    def read(self, name: str) -> str:\n        return name\n'
     '    def write(self, path: str, content: str) -> int:\n'
     '        return 0\n' + MAIN, InvalidProgram,
     "line 9: method 'read' of handler class 'Fake' must take "
     "(self, path: str), as FileIO.read does"),
    ('class Fake(Handler[FileIO]):\n'
     '    def read(self, path: int) -> str:\n        return ""\n'
     '    def write(self, path: str, content: str) -> int:\n'
     '        return 0\n' + MAIN, InvalidProgram,
     "line 9: method 'read' of handler class 'Fake' must take "
     "(self, path: str), as FileIO.read does"),
    ('class Fake(Handler[FileIO]):\n'
     '    def read(self, path: str) -> int:\n        return 0\n'
     '    def write(self, path: str, content: str) -> int:\n'
     '        return 0\n' + MAIN, InvalidProgram,
     "line 9: method 'read' of handler class 'Fake' must return str, "
     "as FileIO.read does"),
    ('class Fake(Handler[FileIO]):\n    items: Nope\n' + FAKE[29:] + MAIN,
     InvalidProgram,
     "line 9: field 'items' of handler class 'Fake' must be int, str, "
     "list[...], or dict[str, ...], not Nope"),
    ('class Fake(Handler[FileIO]):\n    writes: int = "x"\n' + FAKE[29:]
     + MAIN, InvalidProgram,
     "line 9: default of field 'writes' must be int, not str"),
    ('class Fake(Handler[FileIO]):\n    a: int = 0\n    b: int\n'
     + FAKE[29:] + MAIN, InvalidProgram,
     "line 10: field 'b' without a default follows a field with one"),
    ('class Fake(Handler[FileIO]):\n    a: int\n    a: str\n'
     + FAKE[29:] + MAIN, InvalidProgram,
     "line 10: field 'a' is declared twice in handler class 'Fake'"),
    (FAKE + '    def read(self, path: str) -> str:\n        return path\n'
     + MAIN, InvalidProgram,
     "line 13: method 'read' is declared twice in handler class 'Fake'"),
    (FAKE + FAKE + MAIN, InvalidProgram,
     "line 13: handler class 'Fake' is declared twice"),
    ('class FileIO(Handler[DBQuery]):\n'
     '    def execute(self, sql: str) -> str:\n        return sql\n'
     + MAIN, InvalidProgram,
     "line 8: handler class 'FileIO' is declared twice"),
    (FAKE + 'def Fake() -> int:\n    return 0\n' + MAIN,
     InvalidProgram, "line 13: function 'Fake' is defined twice"),
    ('class Fake(Handler[Nope]):\n    def read(self) -> str:\n'
     '        return ""\n' + MAIN,
     InvalidProgram, "line 8: unknown effect 'Nope'"),
    (FAKE + 'def f() -> int:\n    x = Fake(1)\n    return 0\n' + MAIN,
     InvalidProgram, 'line 14: Fake() takes 0 arguments (1 given)'),
    ('class Fake(Handler[FileIO]):\n    a: int\n    b: str = ""\n'
     + FAKE[29:] + 'def f() -> int:\n    x = Fake(1, "b", 3)\n'
     '    return 0\n' + MAIN,
     InvalidProgram, 'line 16: Fake() takes 1 to 2 arguments (3 given)'),
    ('class Fake(Handler[FileIO]):\n    a: int\n'
     + FAKE[29:] + 'def f() -> int:\n    x = Fake("s")\n'
     '    return 0\n' + MAIN,
     InvalidProgram, 'line 15: argument 1 of Fake() must be int, not str'),
    ('class Fake(Handler[FileIO]):\n    a: int\n'
     + FAKE[29:] + 'def f() -> int:\n    x = Fake(1)\n'
     '    return x.nope\n' + MAIN,
     InvalidProgram, "line 16: handler class 'Fake' has no field 'nope'"),
    ('class Fake(Handler[FileIO]):\n    a: int\n'
     '    def read(self, path: str) -> str:\n'
     '        self.a = path\n        return path\n'
     '    def write(self, path: str, content: str) -> int:\n'
     '        return 0\n' + MAIN, InvalidProgram,
     "line 11: field 'a' of handler class 'Fake' is int; cannot assign "
     "str"),
    ('def f() -> int:\n    x = 1\n    x.a = 1\n    return 0\n' + MAIN,
     InvalidProgram, "line 10: 'x' is not a handler instance"),
    ('def f() -> int:\n    x.a = 1\n    return 0\n' + MAIN,
     InvalidProgram, "line 9: name 'x' is not defined"),
    ('def main() -> int / []:\n    with handle(FileIO):\n'
     '        pass\n    return 0\n', InvalidProgram,
     'line 9: with handle(FileIO) outside try needs except clauses for '
     'FileIO'),
    (FAKE + 'def main() -> int / []:\n    try:\n'
     '        with handle(Fake()):\n            pass\n'
     '    except FileIO.read as e:\n        pass\n    return 0\n',
     InvalidProgram,
     'line 17: clause for FileIO.read, but Fake fulfills FileIO'),
    (FAKE + 'def main() -> int / []:\n'
     '    with handle(Fake(), Fake()):\n        pass\n    return 0\n',
     InvalidProgram, 'line 14: handle() has two handlers for FileIO'),
    (FAKE + 'def main() -> int / []:\n    try:\n'
     '        with handle(Fake(), FileIO):\n            pass\n'
     '    except FileIO.read as e:\n        pass\n'
     '    except FileIO.write as e:\n        pass\n    return 0\n',
     InvalidProgram,
     'line 14: handle() names FileIO and a handler class for it'),
    ('def main() -> int / []:\n    nope = 1\n    with handle(nope):\n'
     '        pass\n    return 0\n', InvalidProgram,
     "line 10: 'nope' is not an effect or a handler instance"),
    ('def main() -> int / []:\n    with handle(nope):\n'
     '        pass\n    return 0\n', InvalidProgram,
     "line 9: name 'nope' is not defined"),
    ('def f() -> int:\n    return 0\n'
     'def main() -> int / []:\n    with handle(f()):\n'
     '        pass\n    return 0\n', InvalidProgram,
     "line 11: 'f' is not a handler class"),
])
def test_rejected_handler_programs(body, error, msg):
    with pytest.raises(error) as info:
        check_source(body)
    assert info.value.msg == msg

# --- Exceptions (Milestone 6) ------------------------------------------------

EXCEPTIONS = EFFECTS + '''\
class NotFound(Exception): ...

class Denied(Exception): ...

class Failing(Handler[FileIO]):
    def read(self, path: str) -> str / [NotFound]:
        raise NotFound(path)
    def write(self, path: str, content: str) -> int:
        return 0

'''

FIND = ('def find(key: str) -> str / [NotFound]:\n'
        '    raise NotFound(key)\n')

def check_exceptions(body):
    check(parse(EXCEPTIONS + body))

@pytest.mark.parametrize('name', [
    'except_exception.epy', 'raise_again.epy', 'raise_caught.epy',
    'raise_in_body.epy', 'raise_in_clause.epy', 'raise_in_method.epy',
    'raise_in_nested_clause.epy', 'try_around_perform.epy',
])
def test_accepts_the_exception_programs(name):
    check(parse(read_program(name)))

def test_a_declared_exception_reaches_a_caller_that_catches_it():
    check_exceptions(FIND +
                     'def main() -> int / []:\n'
                     '    try:\n'
                     '        print(find("a"))\n'
                     '    except NotFound as e:\n'
                     '        print(e)\n'
                     '    return 0\n')

def test_a_try_discharges_what_the_callee_declares():
    check_exceptions(FIND +
                     'def lookup(key: str) -> str:\n'
                     '    try:\n'
                     '        return find(key)\n'
                     '    except NotFound as e:\n'
                     '        return "missing"\n'
                     '    return ""\n' + MAIN)

def test_except_exception_catches_every_class_the_suite_raises():
    check_exceptions('def find(key: str) -> str / [NotFound, Denied]:\n'
                     '    if key == "x":\n'
                     '        raise Denied(key)\n'
                     '    raise NotFound(key)\n'
                     'def lookup(key: str) -> str:\n'
                     '    try:\n'
                     '        return find(key)\n'
                     '    except Exception as e:\n'
                     '        return "failed"\n'
                     '    return ""\n' + MAIN)

def test_an_except_clause_may_omit_the_binding():
    check_exceptions(FIND +
                     'def lookup(key: str) -> str:\n'
                     '    try:\n'
                     '        return find(key)\n'
                     '    except NotFound:\n'
                     '        return "missing"\n'
                     '    return ""\n' + MAIN)

def test_an_exception_may_be_raised_without_a_message():
    check_exceptions('def f() -> int / [NotFound]:\n'
                     '    raise NotFound()\n' + MAIN)

def test_a_clause_may_raise_the_name_it_bound():
    check_exceptions(FIND +
                     'def lookup(key: str) -> str / [NotFound]:\n'
                     '    try:\n'
                     '        return find(key)\n'
                     '    except NotFound as e:\n'
                     '        raise e\n' + MAIN)

def test_a_try_around_handle_catches_a_method_exception():
    check_exceptions('def f() -> str:\n'
                     '    try:\n'
                     '        with handle(Failing()):\n'
                     '            return perform(FileIO.read("a"))\n'
                     '    except NotFound as e:\n'
                     '        return "missing"\n'
                     '    return ""\n' + MAIN)

@pytest.mark.parametrize('body, msg', [
    ('def find(key: str) -> str:\n    raise NotFound(key)\n' + MAIN,
     "line 18: function 'find' raises NotFound (line 19) without "
     "declaring it in its effect row"),
    (FIND + 'def lookup(key: str) -> str:\n    return find(key)\n' + MAIN,
     "line 20: function 'lookup' raises NotFound (line 21) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    perform(FileIO.write("a", "b"))\n'
     '    raise NotFound("a")\n' + MAIN,
     "line 18: function 'f' performs FileIO (line 19), raises NotFound "
     "(line 20) without declaring it in its effect row"),
    ('def f() -> str:\n    with handle(Failing()):\n'
     '        return perform(FileIO.read("a"))\n    return ""\n' + MAIN,
     "line 18: function 'f' raises NotFound (line 19) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    with handle(Failing()):\n        try:\n'
     '            return perform(FileIO.read("a"))\n'
     '        except NotFound as e:\n            return "missing"\n'
     '    return ""\n' + MAIN,
     "line 18: function 'f' raises NotFound (line 19) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    try:\n        raise NotFound("a")\n'
     '    except NotFound as e:\n        raise Denied("b")\n'
     '    return ""\n' + MAIN,
     "line 18: function 'f' raises Denied (line 22) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    try:\n        raise Denied("b")\n'
     '    except NotFound as e:\n        return "missing"\n'
     '    return ""\n' + MAIN,
     "line 18: function 'f' raises Denied (line 20) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    try:\n'
     '        return perform(FileIO.read("a"))\n'
     '    except Exception as e:\n        return ""\n'
     '    return ""\n' + MAIN,
     "line 18: function 'f' performs FileIO (line 20) without "
     "declaring it in its effect row"),
    (FIND + 'def main() -> int / []:\n    print(find("a"))\n'
     '    return 0\n',
     "line 20: function 'main' raises NotFound (line 21) without "
     "declaring it in its effect row"),
    (FIND + 'def lookup(key: str) -> str:\n    try:\n'
     '        return find(key)\n    except NotFound as e:\n'
     '        raise e\n' + MAIN,
     "line 20: function 'lookup' raises NotFound (line 24) without "
     "declaring it in its effect row"),
])
def test_unhandled_exceptions(body, msg):
    with pytest.raises(UnhandledEffectError) as info:
        check_exceptions(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body, error, msg', [
    ('def f() -> int:\n    raise 1\n' + MAIN,
     InvalidProgram, 'line 19: raise needs an exception, not int'),
    ('def f() -> int:\n    raise FileIO.read("a")\n' + MAIN,
     InvalidProgram,
     'line 19: raise needs an exception, not FileIO.read(...)'),
    ('def f() -> int:\n    raise Exception("a")\n' + MAIN,
     InvalidProgram,
     'line 19: raise needs a declared exception class, not Exception'),
    ('def f() -> int:\n    try:\n        pass\n'
     '    except Exception as e:\n        raise e\n    return 0\n' + MAIN,
     InvalidProgram,
     'line 22: raise needs a declared exception class, not Exception'),
    ('def f() -> int:\n    raise x\n' + MAIN, InvalidProgram,
     "line 19: name 'x' is not defined"),
    ('def f() -> int / [NotFound]:\n    raise NotFound(1)\n' + MAIN,
     InvalidProgram,
     'line 19: argument 1 of NotFound() must be str, not int'),
    ('def f() -> int / [NotFound]:\n    raise NotFound("a", "b")\n'
     + MAIN, InvalidProgram,
     'line 19: NotFound() takes 0 to 1 arguments (2 given)'),
    ('def f() -> int:\n    try:\n        pass\n'
     '    except FileIO as e:\n        pass\n    return 0\n' + MAIN,
     InvalidProgram, "line 21: 'FileIO' is not an exception class"),
    ('def f() -> int:\n    try:\n        pass\n'
     '    except Nope as e:\n        pass\n    return 0\n' + MAIN,
     InvalidProgram, "line 21: 'Nope' is not an exception class"),
    ('class NotFound(Exception): ...\n' + MAIN, InvalidProgram,
     "line 18: exception class 'NotFound' is declared twice"),
    ('class FileIO(Exception): ...\n' + MAIN, InvalidProgram,
     "line 18: exception class 'FileIO' is declared twice"),
    ('def NotFound() -> int:\n    return 0\n' + MAIN, InvalidProgram,
     "line 18: function 'NotFound' is defined twice"),
    ('def f() -> int / [Exception]:\n    return 0\n' + MAIN,
     InvalidProgram,
     'line 18: an effect row names exception classes, not Exception'),
    ('class Bad(Handler[DBQuery]):\n'
     '    def execute(self, sql: str) -> str / [Nope]:\n'
     '        return sql\n' + MAIN, InvalidProgram,
     "line 19: 'Nope' is not an effect or an exception class"),
    ('def g(s: str) -> int:\n    return 0\n'
     'def f() -> int:\n    try:\n        pass\n'
     '    except NotFound as e:\n        return g(e)\n'
     '    return 0\n' + MAIN, InvalidProgram,
     'line 24: argument 1 of g() must be str, not NotFound'),
])
def test_rejected_exception_programs(body, error, msg):
    with pytest.raises(error) as info:
        check_exceptions(body)
    assert info.value.msg == msg

CAUGHT = ('    try:\n        raise NotFound("a")\n'
          '    except NotFound as e:\n        print(e)\n')

@pytest.mark.parametrize('body, lineno', [
    ('def main() -> int / []:\n' + CAUGHT +
     '    print(e)\n    return 0\n', 23),
    ('def main() -> int / []:\n    e = 7\n' + CAUGHT +
     '    return e\n', 24),
    ('def main() -> int / []:\n    try:\n        raise NotFound("a")\n'
     '    except NotFound as e:\n        try:\n'
     '            raise NotFound("b")\n'
     '        except NotFound as e:\n            print(e)\n'
     '        print(e)\n    return 0\n', 26),
    ('def f() -> int / [NotFound]:\n' + CAUGHT +
     '    raise e\n' + MAIN, 23),
    ('def f() -> int:\n' + CAUGHT + '    raise e\n' + MAIN, 23),
    ('def main() -> int / []:\n' + CAUGHT +
     '    x = e\n    return 0\n', 23),
    ('def main() -> int / []:\n' + CAUGHT +
     '    e.resume(1)\n    return 0\n', 23),
    ('def main() -> int / []:\n' + CAUGHT +
     '    print(e.path)\n    return 0\n', 23),
    ('def main() -> int / []:\n    e = 7\n    try:\n        try:\n'
     '            raise NotFound("a")\n'
     '        except NotFound as e:\n            raise e\n'
     '    except NotFound:\n        print("caught")\n'
     '    return e\n', 27),
    ('def main() -> int / []:\n    e = 7\n'
     '    try:\n        raise NotFound("a")\n'
     '    except NotFound as e:\n        if 1 == 1:\n'
     '            return 1\n    return e\n', 25),
    ('def main() -> int / []:\n' + CAUGHT +
     '    try:\n        raise NotFound("b")\n'
     '    except NotFound as e:\n        return 1\n'
     '    print(e)\n    return 0\n', 27),
    ('def f() -> int / [NotFound, Denied]:\n    return 0\n'
     'def main() -> int / []:\n    e = 7\n    try:\n        print(f())\n'
     '    except NotFound as e:\n        return 1\n'
     '    except Denied as e:\n        print(e)\n    return e\n', 28),
    ('def f() -> int / [NotFound, Denied]:\n    return 0\n'
     'def main() -> int / []:\n    e = 7\n    try:\n        print(f())\n'
     '    except NotFound as e:\n        print(e)\n'
     '    except Denied as e:\n        return 1\n    return e\n', 28),
], ids=['fresh', 'assigned-before', 'nested', 'raise-declared',
        'raise-undeclared', 'assignment', 'resume', 'field',
        'clause-raises', 'return-in-if', 'deleted-earlier',
        'other-clause-falls-through', 'earlier-clause-falls-through'])
def test_rejects_a_read_of_a_name_its_clause_deleted(body, lineno):
    with pytest.raises(InvalidProgram) as info:
        check_exceptions(body)
    assert info.value.msg == (
        "line %d: name 'e' is unbound after the except clause "
        "that bound it" % lineno)

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n' + CAUGHT +
    '    e = 7\n    return e\n',
    'def f() -> int / [NotFound, Denied]:\n    return 0\n'
    'def main() -> int / []:\n    try:\n        print(f())\n'
    '    except NotFound as e:\n        print(e)\n'
    '    except Exception as e:\n        print(e)\n    return 0\n',
    'def main() -> int / []:\n' + CAUGHT + CAUGHT +
    '    return 0\n',
    'def main() -> int / []:\n    try:\n        raise NotFound("a")\n'
    '    except NotFound as e:\n        try:\n'
    '            raise NotFound("b")\n'
    '        except NotFound as e:\n            print(e)\n'
    '        print("done")\n    return 0\n',
], ids=['assigned-after', 'second-clause', 'later-try', 'nested'])
def test_accepts_a_name_bound_again_after_its_clause(body):
    check_exceptions(body)

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    e = 7\n'
    '    try:\n        raise NotFound("a")\n'
    '    except NotFound as e:\n        print(e)\n        return 1\n'
    '    return e\n',
    'def f() -> int / [NotFound, Denied]:\n    return 0\n'
    'def main() -> int / []:\n    e = 7\n    try:\n        print(f())\n'
    '    except NotFound as e:\n        return 1\n'
    '    except Denied as e:\n        return 2\n    return e\n',
    'def f() -> int / [NotFound]:\n    raise NotFound("a")\n'
    'def main() -> int / []:\n    try:\n        with handle(FileIO):\n'
    '            print(perform(FileIO.read("a")))\n'
    '    except FileIO.read as eff:\n        try:\n            print(f())\n'
    '        except NotFound as eff:\n            return 1\n'
    '        eff.resume("x")\n'
    '    except FileIO.write as eff:\n        eff.resume(0)\n    return 0\n',
], ids=['one-clause', 'every-clause', 'eff-binding'])
def test_a_clause_ending_in_return_leaves_its_name_bound(body):
    check_exceptions(body)

def test_a_clause_ending_in_return_leaves_its_name_typed():
    body = ('def show(text: str) -> int:\n    print(text)\n'
            '    return 0\n'
            'def main() -> int / []:\n    e = 7\n'
            '    try:\n        raise NotFound("a")\n'
            '    except NotFound as e:\n        return 1\n'
            '    return show(e)\n')
    with pytest.raises(InvalidProgram) as info:
        check_exceptions(body)
    assert info.value.msg == (
        'line 27: argument 1 of show() must be str, not int')

# --- Throwing into the body (Milestone 7) ------------------------------------

THROWING = '''\
class FileIO(Effect):
    def read(path: str) -> str / [NotFound]: ...

class Plain(Effect):
    def get(key: str) -> str: ...

class NotFound(Exception): ...

class Denied(Exception): ...

class Missing(Handler[FileIO]):
    def read(self, path: str) -> str / [NotFound]:
        raise NotFound(path)

'''

CATCHING = ('def main() -> int / []:\n    try:\n'
            '        with handle(FileIO):\n            try:\n'
            '                print(perform(FileIO.read("a")))\n'
            '            except NotFound as e:\n                print(e)\n'
            '    except FileIO.read as eff:\n')

def check_throwing(body):
    check(parse(THROWING + body))

@pytest.mark.parametrize('name', [
    'throw_caught.epy', 'throw_through_body.epy',
    'throw_then_statements.epy', 'throw_in_method.epy',
    'many_throws.epy', 'throw_twice.epy',
])
def test_accepts_the_throw_programs(name):
    check(parse(read_program(name)))

@pytest.mark.parametrize('body', [
    CATCHING + '        eff.throw(NotFound(eff.path))\n    return 0\n',
    'def main() -> int / []:\n    try:\n        try:\n'
    '            with handle(FileIO):\n'
    '                print(perform(FileIO.read("a")))\n'
    '        except FileIO.read as eff:\n'
    '            eff.throw(NotFound(eff.path))\n'
    '    except NotFound as e:\n        print(e)\n    return 0\n',
    'def load(p: str) -> str / [FileIO, NotFound]:\n'
    '    return perform(FileIO.read(p))\n' + MAIN,
    'def main() -> int / []:\n    with handle(Missing()):\n'
    '        try:\n            print(perform(FileIO.read("a")))\n'
    '        except NotFound as e:\n            print(e)\n'
    '    return 0\n',
    CATCHING + '        eff.throw(NotFound(eff.path))\n'
    '        print("after")\n    return 0\n',
    CATCHING + '        try:\n            raise NotFound(eff.path)\n'
    '        except NotFound as e:\n            eff.throw(e)\n'
    '    return 0\n',
], ids=['caught-in-body', 'caught-around-handle', 'declared',
        'method-caught-in-body', 'statement-after', 'caught-name'])
def test_accepts_a_throw_the_program_accounts_for(body):
    check_throwing(body)

@pytest.mark.parametrize('row, msg', [
    ('DBQuery', "the row of Bad.get names exception classes; "
     "'DBQuery' is an effect"),
    ('Nope', "the row of Bad.get names exception classes; "
     "'Nope' is not an exception class"),
    ('Exception', 'the row of Bad.get names exception classes, '
     'not Exception'),
])
def test_rejected_operation_rows(row, msg):
    with pytest.raises(InvalidProgram) as info:
        check_exceptions('class Bad(Effect):\n'
                         '    def get(key: str) -> str / [%s]: ...\n'
                         % row + MAIN)
    assert info.value.msg == 'line 19: ' + msg

@pytest.mark.parametrize('body, msg', [
    (CATCHING + '        eff.throw(1)\n    return 0\n',
     'line 23: eff.throw() needs an exception, not int'),
    (CATCHING + '        eff.throw(Exception("x"))\n    return 0\n',
     'line 23: eff.throw() needs a declared exception class, '
     'not Exception'),
    (CATCHING + '        eff.throw(Denied())\n    return 0\n',
     'line 23: FileIO.read does not declare Denied, so eff.throw() '
     'cannot deliver it'),
    ('def main() -> int / []:\n    try:\n        with handle(Plain):\n'
     '            print(perform(Plain.get("a")))\n'
     '    except Plain.get as eff:\n        eff.throw(NotFound())\n'
     '    return 0\n',
     'line 20: Plain.get does not declare NotFound, so eff.throw() '
     'cannot deliver it'),
    (CATCHING + '        x = 1\n        x.throw(NotFound())\n'
     '    return 0\n',
     "line 24: 'x' is not an except binding or a handler instance"),
    (CATCHING + '        try:\n            raise NotFound("a")\n'
     '        except Exception as e:\n            eff.throw(e)\n'
     '    return 0\n',
     'line 26: eff.throw() needs a declared exception class, '
     'not Exception'),
], ids=['int', 'exception', 'undeclared', 'no-row', 'not-a-binding',
        'caught-as-exception'])
def test_rejected_throws(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_throwing(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body, msg', [
    ('def load(p: str) -> str / [FileIO]:\n'
     '    return perform(FileIO.read(p))\n' + MAIN,
     "line 15: function 'load' raises NotFound (line 16) without "
     "declaring it in its effect row"),
    ('def f() -> str:\n    try:\n        with handle(FileIO):\n'
     '            return perform(FileIO.read("a"))\n'
     '    except FileIO.read as eff:\n'
     '        eff.throw(NotFound(eff.path))\n    return ""\n' + MAIN,
     "line 15: function 'f' raises NotFound (line 18) without "
     "declaring it in its effect row"),
], ids=['performer', 'installer'])
def test_unhandled_throws(body, msg):
    with pytest.raises(UnhandledEffectError) as info:
        check_throwing(body)
    assert info.value.msg == msg

def test_rejects_the_undeclared_throw_program():
    with pytest.raises(InvalidProgram) as info:
        check(parse(read_program('rejected_undeclared_throw.epy')))
    assert info.value.msg == (
        'line 23: FileIO.read does not declare Denied, so eff.throw() '
        'cannot deliver it')

# --- Finally (Milestone 8) ---------------------------------------------------

HANDLED = ('    try:\n        with handle(FileIO):\n'
           '            print(perform(FileIO.read("a")))\n'
           '    except FileIO.read as eff:\n        eff.resume("x")\n'
           '    except FileIO.write as eff:\n        eff.resume(0)\n'
           '    finally:\n'
           '        print(perform(DBQuery.execute("q")))\n'
           '    return 0\n')

@pytest.mark.parametrize('name', [
    'try_finally.epy', 'finally_in_body.epy', 'finally_performs.epy',
    'finally_in_nested_body.epy', 'finally_on_return_in_clause.epy',
    'finally_on_raise_in_clause.epy', 'finally_raises.epy',
    'handle_with_finally.epy',
])
def test_accepts_the_finally_programs(name):
    check(parse(read_program(name)))

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    try:\n        with handle(DBQuery):\n'
    '            try:\n'
    '                print(perform(DBQuery.execute("q")))\n'
    '            finally:\n                print("done")\n'
    '    except DBQuery.execute as eff:\n        eff.resume(eff.sql)\n'
    '    return 0\n',
    'def main() -> int / []:\n    try:\n        with handle(DBQuery):\n'
    '            print(perform(DBQuery.execute("q")))\n'
    '    except DBQuery.execute as eff:\n        try:\n'
    '            raise NotFound(eff.sql)\n'
    '        except NotFound as e:\n            print(e)\n'
    '        finally:\n            print("done")\n'
    '        eff.resume(eff.sql)\n    return 0\n',
    'class Tidy(Handler[FileIO]):\n'
    '    def read(self, path: str) -> str:\n        try:\n'
    '            print(path)\n        finally:\n'
    '            print("read")\n        return path\n'
    '    def write(self, path: str, content: str) -> int:\n'
    '        return 0\n' + MAIN,
    'def f() -> int / [DBQuery]:\n' + HANDLED + MAIN,
], ids=['in-body', 'in-clause', 'in-method', 'on-handle-declared'])
def test_accepts_a_finally_the_program_accounts_for(body):
    check_exceptions(body)

@pytest.mark.parametrize('body, msg', [
    ('def f() -> str:\n    try:\n        pass\n    finally:\n'
     '        print(perform(FileIO.read("a")))\n    return ""\n' + MAIN,
     "line 18: function 'f' performs FileIO (line 22) without "
     "declaring it in its effect row"),
    ('def f() -> int:\n    try:\n        pass\n    finally:\n'
     '        raise NotFound()\n    return 0\n' + MAIN,
     "line 18: function 'f' raises NotFound (line 22) without "
     "declaring it in its effect row"),
    ('def f() -> int:\n    try:\n        raise NotFound("a")\n'
     '    except NotFound as e:\n        print(e)\n    finally:\n'
     '        raise Denied()\n    return 0\n' + MAIN,
     "line 18: function 'f' raises Denied (line 24) without "
     "declaring it in its effect row"),
    ('def f() -> int / []:\n' + HANDLED + MAIN,
     "line 18: function 'f' performs DBQuery (line 27) without "
     "declaring it in its effect row"),
], ids=['performs', 'raises', 'not-caught-by-own-clauses', 'on-handle'])
def test_unhandled_finally_effects(body, msg):
    with pytest.raises(UnhandledEffectError) as info:
        check_exceptions(body)
    assert info.value.msg == msg

def test_rejects_a_read_of_the_clause_name_in_its_finally():
    with pytest.raises(InvalidProgram) as info:
        check_exceptions('def main() -> int / []:\n' + CAUGHT +
                         '    finally:\n        print(e)\n'
                         '    return 0\n')
    assert info.value.msg == (
        "line 24: name 'e' is unbound after the except clause "
        "that bound it")

# --- Lists and the for loop (Milestone 9) ------------------------------------

COLLECTOR = ('class Log(Effect):\n    def note(text: str) -> int: ...\n'
             'class Collector(Handler[Log]):\n'
             '    entries: list[str] = []\n'
             '    def note(self, text: str) -> int:\n'
             '        self.entries.append(text)\n'
             '        return len(self.entries)\n')

LISTED = ('def names() -> list[str]:\n    return ["a", "b"]\n'
          'def f() -> int:\n    for x in names():\n')

@pytest.mark.parametrize('name', [
    'collector.epy', 'for_list.epy', 'for_range.epy', 'list_ops.epy',
    'list_shared.epy', 'perform_in_for.epy', 'list_index_error.epy',
])
def test_accepts_the_list_programs(name):
    check(parse(read_program(name)))

def test_rejects_the_range_value_program():
    with pytest.raises(InvalidProgram) as info:
        check(parse(read_program('rejected_range_value.epy')))
    assert info.value.msg == (
        'line 5: range() is allowed only as the iterable of a for '
        'statement')

@pytest.mark.parametrize('body', [
    'def f() -> list[int]:\n    result = []\n    result.append(1)\n'
    '    return result\n' + MAIN,
    'class Fake(Handler[FileIO]):\n    flags: list[bool] = []\n'
    + FAKE[29:] + MAIN,
    'def main() -> int / []:\n    try:\n        with handle(DBQuery):\n'
    '            print(perform(DBQuery.execute("q")))\n'
    '    except DBQuery.execute as eff:\n        for i in range(2):\n'
    '            print(i)\n        eff.resume(eff.sql)\n    return 0\n',
    'class Fake(Handler[FileIO]):\n'
    '    def read(self, path: str) -> str:\n'
    '        for part in [path, path]:\n            print(part)\n'
    '        return path\n'
    '    def write(self, path: str, content: str) -> int:\n'
    '        return 0\n' + MAIN,
    'def f() -> int:\n    try:\n        pass\n    finally:\n'
    '        for i in range(1, 3):\n            print(i)\n'
    '    return 0\n' + MAIN,
], ids=['built-from-empty', 'empty-field-default', 'for-in-clause',
        'for-in-method', 'for-in-finally'])
def test_accepts_a_list_program(body):
    check_source(body)

@pytest.mark.parametrize('stmt', [
    'print(xs[-1])', 'print(xs == [])', 'print([] == [])',
    'print(len("ab"))', 'print(str(1) + str(True))', 'print(xs[i])',
    'xs[i] = v',
])
def test_accepts_a_list_operation(stmt):
    check_source('def f(xs: list[int], i: int, v: int) -> int:\n'
                 '    %s\n    return 0\n' % stmt + MAIN)

def test_a_for_binds_its_name_to_the_element_type():
    check_source(LISTED + '        print(x + "!")\n    return 0\n' + MAIN)

def test_a_for_name_of_element_type_rejects_a_mismatched_operand():
    with pytest.raises(InvalidProgram) as info:
        check_source(LISTED + '        print(x + 1)\n    return 0\n' + MAIN)
    assert info.value.msg == (
        'line 12: unsupported operand types for +: str and int')

def test_a_for_over_an_empty_list_leaves_its_name_untyped():
    check_source('def f() -> int:\n    xs = []\n    for x in xs:\n'
                 '        print(x + 1, x + "a")\n    return 0\n' + MAIN)

@pytest.mark.parametrize('body, msg', [
    ('def f() -> int:\n    xs = [1, "a"]\n    return 0\n' + MAIN,
     'line 9: list elements must share a type: int and str'),
    ('def f() -> int:\n    xs = range(3)\n    return 0\n' + MAIN,
     'line 9: range() is allowed only as the iterable of a for '
     'statement'),
    ('def f() -> int:\n    for x in 5:\n        pass\n    return 0\n'
     + MAIN, 'line 9: for needs a list, a dict, or range(), not int'),
    ('def f() -> int:\n    print(len(5))\n    return 0\n' + MAIN,
     'line 9: len() needs a list, dict, or str, not int'),
    ('def f() -> int:\n    print(len("a", "b"))\n    return 0\n' + MAIN,
     'line 9: len() takes 1 arguments (2 given)'),
    ('def f() -> int:\n    n = 1\n    return n[0]\n' + MAIN,
     "line 10: 'n' is not a list"),
    ('def f() -> int:\n    n = 1\n    n[0] = 1\n    return 0\n' + MAIN,
     "line 10: 'n' is not a list"),
    ('def f() -> int:\n    n = 1\n    n.append(1)\n    return 0\n' + MAIN,
     "line 10: 'n' is not a list"),
    ('def f() -> int:\n    xs = [1]\n    xs.append("a")\n    return 0\n'
     + MAIN, 'line 10: argument 1 of append() must be int, not str'),
    ('def f() -> int:\n    xs = [1]\n    xs[0] = "a"\n    return 0\n'
     + MAIN, 'line 10: the list holds int; cannot assign str'),
    ('def f() -> int:\n    xs = [1]\n    print(xs["a"])\n    return 0\n'
     + MAIN, 'line 10: a list index must be int, not str'),
    ('def f() -> int:\n    xs = [1]\n    xs.pop(1)\n    return 0\n'
     + MAIN, "line 10: a list has no method 'pop'"),
    ('def f() -> int:\n    print(x)\n    for x in [1]:\n        pass\n'
     '    return 0\n' + MAIN, "line 9: name 'x' is not defined"),
    ('def f() -> int:\n    for i in range():\n        pass\n'
     '    return 0\n' + MAIN,
     'line 9: range() takes 1 to 2 arguments (0 given)'),
    ('def f() -> int:\n    for i in range(1, 2, 3):\n        pass\n'
     '    return 0\n' + MAIN,
     'line 9: range() takes 1 to 2 arguments (3 given)'),
    ('def f() -> int:\n    for i in range("a"):\n        pass\n'
     '    return 0\n' + MAIN,
     'line 9: argument 1 of range() must be int, not str'),
    ('def f() -> int:\n    print(str([1]))\n    return 0\n' + MAIN,
     'line 9: str() needs an int, str, or bool, not list[int]'),
    ('def f() -> int:\n    print([1] == ["a"])\n    return 0\n' + MAIN,
     'line 9: unsupported operand types for ==: list[int] and list[str]'),
    ('def f() -> int:\n    print([1] + [2])\n    return 0\n' + MAIN,
     'line 9: unsupported operand types for +: list[int] and list[int]'),
    ('def f() -> int:\n    r = []\n    r.append(1)\n    r.append("a")\n'
     '    return 0\n' + MAIN,
     'line 11: argument 1 of append() must be int, not str'),
    ('def f(xs: list[str]) -> int:\n    return 0\n'
     'def g() -> int:\n    r = []\n    r.append(1)\n    return f(r)\n'
     + MAIN, 'line 13: argument 1 of f() must be list[str], not list[int]'),
    ('class Fake(Handler[FileIO]):\n    xs: list[int] = 1\n' + FAKE[29:]
     + MAIN, "line 9: default of field 'xs' must be list[int], not int"),
    ('class Fake(Handler[FileIO]):\n    xs: int = []\n' + FAKE[29:]
     + MAIN, "line 9: default of field 'xs' must be int, not list"),
    (COLLECTOR + 'def f() -> int:\n    c = Collector()\n'
     '    c.entries = 1\n    return 0\n' + MAIN,
     "line 17: field 'entries' of handler class 'Collector' is "
     "list[str]; cannot assign int"),
], ids=['mixed-elements', 'range-value', 'for-over-int', 'len-of-int',
        'len-two-arguments', 'index-not-a-list', 'index-assign-not-a-list',
        'append-not-a-list', 'append-mismatch', 'index-assign-mismatch',
        'str-index', 'no-method', 'read-before-for', 'range-no-arguments',
        'range-three-arguments', 'range-str', 'str-of-list',
        'compare-mismatch', 'list-plus', 'append-fixes-element',
        'argument-list-type', 'list-field-int-default',
        'int-field-list-default', 'list-field-assign'])
def test_rejected_list_programs(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('name', ['len', 'str', 'range'])
def test_a_function_cannot_take_a_built_in_name(name):
    with pytest.raises(InvalidProgram) as info:
        check_source('def %s(x: int) -> int:\n    return x\n' % name + MAIN)
    assert info.value.msg == "line 8: '%s' is a built-in" % name

# --- break and continue (Milestone 10) ---------------------------------------

ONE_OP = 'class E(Effect):\n    def op() -> int: ...\n'

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    break\n    return 0\n',
     "line 9: 'break' outside loop"),
    ('def main() -> int / []:\n    if True:\n        continue\n'
     '    return 0\n',
     "line 10: 'continue' not properly in loop"),
    (ONE_OP + 'class H(Handler[E]):\n    def op(self) -> int:\n'
     '        break\n        return 0\n'
     'def main() -> int / []:\n    while True:\n'
     '        with handle(H()):\n            perform(E.op())\n'
     '    return 0\n',
     "line 12: 'break' outside loop"),
], ids=['break-in-main', 'continue-in-if', 'break-in-method'])
def test_rejects_a_loop_exit_outside_a_loop(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    while True:\n        break\n'
    '    return 0\n',
    'def main() -> int / []:\n    for x in [1, 2]:\n        continue\n'
    '    return 0\n',
    'def main() -> int / []:\n    if True:\n'
    '        for i in range(3):\n            break\n    return 0\n',
    'def main() -> int / []:\n    while True:\n        try:\n'
    '            break\n        finally:\n            print("x")\n'
    '    return 0\n',
    'def main() -> int / []:\n    for i in range(2):\n'
    '        for j in range(2):\n            continue\n    return 0\n',
    ONE_OP + 'def main() -> int / []:\n    for i in range(2):\n'
    '        try:\n            with handle(E):\n'
    '                perform(E.op())\n'
    '        except E.op as eff:\n            if True:\n'
    '                break\n            eff.resume(1)\n    return 0\n',
], ids=['while', 'for-list', 'for-in-if', 'in-try-finally',
        'inner-loop', 'in-effect-clause'])
def test_accepts_a_loop_exit_inside_a_loop(body):
    check_source(body)

# --- if branches and effect clause bindings (Milestone 10) -------------------

HX = ('class X(Effect):\n    def a() -> int: ...\n'
      'class HX(Handler[X]):\n    def a(self) -> int:\n        return 1\n')

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    x = "s"\n    if 1 == 1:\n'
    '        x = "s"\n    else:\n        x = 1\n    print(x + 1)\n'
    '    return 0\n',
    'def main() -> int / []:\n    if True:\n        x = 1\n    else:\n'
    '        x = 2\n    print(x + 1)\n    return 0\n',
    'def main() -> int / []:\n    xs = []\n    if True:\n'
    '        xs.append(1)\n    xs.append(2)\n    return 0\n',
    'def main() -> int / []:\n    if True:\n        y = 5\n'
    '    print(y)\n    return 0\n',
], ids=['branches-differ', 'branches-agree', 'empty-list-refined',
        'one-branch-binds'])
def test_accepts_a_name_merged_after_an_if(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    if 1 == 1:\n        x = 1\n    else:\n'
     '        x = 2\n    print(x + "a")\n    return 0\n',
     'line 13: unsupported operand types for +: int and str'),
    ('class E(Exception): ...\nclass F(Exception): ...\n'
     'def main() -> int / []:\n    x = E()\n    if 1 == 1:\n'
     '        x = E()\n    else:\n        x = F()\n    try:\n'
     '        raise x\n    except F as e:\n        pass\n    return 0\n',
     'line 17: raise needs an exception, not a value of unknown type'),
    (HX + 'def main() -> int / []:\n    h = 1\n    if 1 == 1:\n'
     '        h = 1\n    else:\n        h = HX()\n'
     '    with handle(h):\n        print(perform(X.a()))\n'
     '    return 0\n',
     "line 19: 'h' is not an effect or a handler instance"),
    ('def main() -> int / []:\n    xs = []\n    if True:\n'
     '        xs.append(1)\n    xs.append("a")\n    return 0\n',
     'line 12: argument 1 of append() must be int, not str'),
], ids=['branches-agree', 'raise-unknown', 'handle-unknown',
        'empty-list-refined'])
def test_rejects_a_name_merged_after_an_if(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

ASK = ('class Ask(Effect):\n    def ask(n: int) -> int: ...\n'
       'def main() -> int / []:\n')

ASKED = ('    try:\n        with handle(Ask):\n'
         '            print(perform(Ask.ask(1)))\n'
         '    except Ask.ask as eff:\n')

@pytest.mark.parametrize('body', [
    ASK + '    eff = 3\n' + ASKED + '        eff.resume(1)\n'
    '    print(eff + 1)\n    return 0\n',
    ASK + ASKED + '        eff.resume(1)\n    eff = 2\n'
    '    print(eff)\n    return 0\n',
    ASK + ASKED + '        print(eff.n)\n        eff.resume(1)\n'
    '    return 0\n',
], ids=['bound-before', 'assigned-after', 'read-in-clause'])
def test_accepts_an_effect_clause_name_as_the_runtime_leaves_it(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    (ASK + ASKED + '        eff.resume(1)\n    print(eff)\n    return 0\n',
     "line 16: name 'eff' is unbound after the except clause that "
     "bound it"),
    (ASK + '    eff = "s"\n' + ASKED + '        eff.resume(1)\n'
     '    print(eff + 1)\n    return 0\n',
     'line 17: unsupported operand types for +: str and int'),
], ids=['fresh', 'bound-before'])
def test_rejects_an_effect_clause_name_as_the_runtime_leaves_it(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

# --- return types and merged paths (Milestone 10) ----------------------------

HY = ('class Y(Effect):\n    def b() -> int: ...\n'
      'class HY(Handler[Y]):\n    def b(self) -> int:\n        return 2\n')

@pytest.mark.parametrize('body', [
    'def f() -> int:\n    return 1\n' + MAIN,
    'def f() -> str:\n    return "a"\n' + MAIN,
    HX + 'def f() -> HX:\n    return HX()\n' + MAIN,
    'class E(Exception): ...\ndef f() -> E:\n    return E()\n' + MAIN,
    'def f() -> None:\n    return\n' + MAIN,
    'def f() -> list[int]:\n    return []\n' + MAIN,
], ids=['int', 'str', 'handler-class', 'exception-class', 'bare-none',
        'empty-list'])
def test_accepts_a_return_of_the_declared_type(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def f() -> int:\n    return "a"\n' + MAIN,
     "line 9: function 'f' must return int, not str"),
    (HX + HY + 'def f() -> HX:\n    return HY()\n' + MAIN,
     "line 19: function 'f' must return HX, not HY"),
    ('def f() -> int:\n    return\n' + MAIN,
     "line 9: function 'f' must return int, not None"),
    ('class X(Effect):\n    def a() -> int: ...\n'
     'class HX(Handler[X]):\n    def a(self) -> int:\n'
     '        return "a"\n' + MAIN,
     "line 12: method 'a' must return int, not str"),
], ids=['str-for-int', 'other-handler', 'bare-for-int', 'method'])
def test_rejects_a_return_of_another_type(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body', [
    'def f(n: int) -> int:\n    if n == 0:\n        return 1\n'
    '    else:\n        return 2\n' + MAIN,
    'class E(Exception): ...\ndef f() -> int:\n    try:\n'
    '        return 1\n    except E:\n        return 2\n' + MAIN,
    'def f() -> int:\n    try:\n        print(1)\n    finally:\n'
    '        return 0\n' + MAIN,
    ONE_OP + 'def f() -> int:\n    try:\n        with handle(E):\n'
    '            return perform(E.op())\n    except E.op as eff:\n'
    '        eff.resume(1)\n' + MAIN,
    'class E(Exception): ...\ndef f() -> int / [E]:\n    raise E()\n'
    + MAIN,
    'def f() -> None:\n    print(1)\n' + MAIN,
], ids=['if-else', 'try-except', 'try-finally', 'handle-resumes',
        'raise', 'none-falls-off'])
def test_accepts_a_body_that_always_returns(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def f(n: int) -> int:\n    if n == 0:\n        return 1\n' + MAIN,
     "line 8: function 'f' can reach its end without returning int"),
    ('def f() -> int:\n    for i in range(3):\n        return i\n' + MAIN,
     "line 8: function 'f' can reach its end without returning int"),
    (ONE_OP + 'def f() -> int:\n    try:\n        with handle(E):\n'
     '            return perform(E.op())\n    except E.op as eff:\n'
     '        print(1)\n' + MAIN,
     "line 10: function 'f' can reach its end without returning int"),
], ids=['if-without-else', 'for', 'handle-abandons'])
def test_rejects_a_body_that_can_reach_its_end(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

GET = 'class Ask(Effect):\n    def get() -> int: ...\n'

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    x = "a"\n    for i in range(0):\n'
    '        x = 1\n    print(x + "b")\n    return 0\n',
    'def main() -> int / []:\n    x = "a"\n    while x == "a":\n'
    '        x = 1\n    print(x + "b")\n    return 0\n',
    'class Boom(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
    '    try:\n        print("b")\n    except Boom:\n        x = "a"\n'
    '    print(x + 1)\n    return 0\n',
    GET + 'def main() -> int / []:\n    x = "a"\n    try:\n'
    '        with handle(Ask):\n            perform(Ask.get())\n'
    '            print(x + "!")\n    except Ask.get as eff:\n'
    '        x = 1\n        eff.resume(0)\n    print(x - 1)\n'
    '    return 0\n',
], ids=['for', 'while', 'try', 'handle'])
def test_accepts_a_name_merged_after_a_loop_try_or_handle(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    xs = []\n    for i in range(2):\n'
     '        print(xs[0] + 1)\n        xs.append("a")\n    return 0\n',
     'line 11: unsupported operand types for +: str and int'),
    ('class Boom(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
     '    try:\n        print("b")\n    except Boom:\n        x = "a"\n'
     '        return 0\n    print(x + "a")\n    return 0\n',
     'line 16: unsupported operand types for +: int and str'),
    (GET + 'def main() -> int / []:\n    xs = []\n    try:\n'
     '        with handle(Ask):\n            perform(Ask.get())\n'
     '            print(xs[0] + "s")\n    except Ask.get as eff:\n'
     '        xs.append(1)\n        eff.resume(0)\n    return 0\n',
     'line 15: unsupported operand types for +: int and str'),
], ids=['for-second-pass', 'try-clause-returns', 'handle-widened'])
def test_rejects_a_name_merged_after_a_loop_try_or_handle(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body, msg', [
    ('def add(a: list[str]) -> int:\n    return 0\n'
     'def main() -> int / []:\n    xs = []\n    add(xs)\n'
     '    xs.append(1)\n    return 0\n',
     'line 13: argument 1 of append() must be str, not int'),
    ('def mk() -> list[int]:\n    xs = []\n    xs.append("a")\n'
     '    return xs\n' + MAIN,
     "line 11: function 'mk' must return list[int], not list[str]"),
], ids=['parameter', 'return'])
def test_rejects_an_empty_list_refined_by_its_receiver(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

def test_an_empty_list_assigned_to_another_name_loses_its_type():
    check_source('def main() -> int / []:\n    xs = []\n    ys = xs\n'
                 '    ys.append(1)\n    xs.append("a")\n'
                 '    print(ys[0] + ys[1])\n    return 0\n')

def test_accepts_an_append_to_a_name_of_unknown_type():
    check_source('def main() -> int / []:\n    if True:\n'
                 '        xs = [1]\n    xs.append(2)\n    return 0\n')

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
    '        x = "s"\n        if i == 0:\n            break\n'
    '        x = 1\n    print(x + 1)\n    return 0\n',
    'def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
    '        x = "s"\n        if i == 0:\n            break\n'
    '        x = 1\n    print(x + "a")\n    return 0\n',
    'def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
    '        x = "s"\n        if i == 0:\n            continue\n'
    '        x = 1\n    print(x + "a")\n    return 0\n',
    'class E(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
    '    try:\n        x = "s"\n        raise E()\n        x = 1\n'
    '    except E:\n        print(x + "a")\n    return 0\n',
    ASK + '    x = 1\n    try:\n        with handle(Ask):\n'
    '            print(perform(Ask.ask(1)))\n            print(x + 1)\n'
    '    except Ask.ask as eff:\n        x = "s"\n'
    '        eff.resume(1)\n        x = 1\n    return 0\n',
    ASK + '    x = 1\n    try:\n        with handle(Ask):\n'
    '            x = "s"\n            print(perform(Ask.ask(1)))\n'
    '            x = 1\n    except Ask.ask as eff:\n'
    '        print(x + "a")\n        eff.resume(1)\n    return 0\n',
    'def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
    '        x = "s"\n        print(x)\n        x = 2\n'
    '    print(x + 1)\n    return 0\n',
], ids=['break', 'break-str-read', 'continue', 'try-midsuite',
        'clause-before-resume', 'body-before-perform', 'loop-restores'])
def test_accepts_a_name_unknown_at_a_statement_boundary(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
     '        x = 2\n    print(x + "a")\n    return 0\n',
     'line 12: unsupported operand types for +: int and str'),
    ('def main() -> int / []:\n    x = 1\n    for i in range(3):\n'
     '        x = "s"\n        print(x)\n        x = 2\n'
     '    print(x + "a")\n    return 0\n',
     'line 14: unsupported operand types for +: int and str'),
], ids=['loop-same-type', 'loop-restores'])
def test_rejects_a_name_whose_type_survives_every_boundary(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    x = "s"\n    for x in range(0):\n'
    '        pass\n    print(x + 1)\n    return 0\n',
    'def main() -> int / []:\n    for x in range(2):\n        pass\n'
    '    print(x + 1)\n    return 0\n',
    'class E(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
    '    try:\n        x = "s"\n        raise E()\n        x = 1\n'
    '    except E:\n        pass\n    finally:\n        print(x + 1)\n'
    '    return 0\n',
    'class E(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
    '    try:\n        raise E()\n    except E:\n        x = "s"\n'
    '        return 0\n    finally:\n        print(x + 1)\n'
    '    return 0\n',
    'def main() -> int / []:\n    if 1 == 1:\n        v = "a"\n'
    '    else:\n        v = 1\n    xs = [v]\n    xs.append(1)\n'
    '    print(xs[0] + 1)\n    return 0\n',
    'def main() -> int / []:\n    if 1 == 1:\n        v = "a"\n'
    '    else:\n        v = 1\n    xs = [v, 1]\n'
    '    print(xs[0] + "a")\n    return 0\n',
], ids=['for-zero-trips', 'for-unbound-before', 'finally-midsuite',
        'finally-clause-returns', 'unknown-element-append',
        'unknown-element-mixed'])
def test_accepts_a_name_widened_by_a_loop_finally_or_literal(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    x = 1\n    for x in range(2):\n'
     '        pass\n    print(x + "a")\n    return 0\n',
     'line 12: unsupported operand types for +: int and str'),
    ('class E(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
     '    try:\n        print("s")\n    except E:\n        pass\n'
     '    finally:\n        print(x + "a")\n    return 0\n',
     'line 16: unsupported operand types for +: int and str'),
    ('class E(Exception): ...\ndef main() -> int / []:\n    x = 1\n'
     '    try:\n        raise E()\n    except E as x:\n'
     '        return 0\n    finally:\n        print(x)\n',
     "line 16: name 'x' is unbound after the except clause that "
     "bound it"),
    ('def main() -> int / []:\n    xs = [[]]\n    return 0\n',
     'line 9: list elements must be int, str, or bool, not a list'),
    ('def main() -> int / []:\n    ys = [1]\n    zs = [ys]\n'
     '    return 0\n',
     'line 10: list elements must be int, str, or bool, not a list'),
    ('def main() -> int / []:\n    ys = [1]\n    zs = []\n'
     '    zs.append(ys)\n    return 0\n',
     'line 11: list elements must be int, str, or bool, not a list'),
], ids=['for-same-type', 'finally-every-path', 'finally-clause-name',
        'nested-empty', 'nested-name', 'nested-append'])
def test_rejects_a_loop_name_finally_read_or_nested_list(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

UNSURE = ('    if 1 == 1:\n        x = 1\n    else:\n        x = "s"\n')

HN = ('class X(Effect):\n    def a() -> int: ...\n'
      'class H(Handler[X]):\n    n: int = 0\n'
      '    def a(self) -> int:\n        return 1\n')

@pytest.mark.parametrize('body, msg', [
    ('def f(n: int) -> int:\n    return n\n'
     'def main() -> int / []:\n' + UNSURE + '    f(x)\n    return 0\n',
     "line 15: argument 1 of f() must be int, but 'x' has no known type"),
    (ASK + UNSURE + '    try:\n        with handle(Ask):\n'
     '            print(perform(Ask.ask(x)))\n'
     '    except Ask.ask as eff:\n        eff.resume(1)\n    return 0\n',
     "line 17: argument 1 of Ask.ask must be int, but 'x' has no known "
     "type"),
    (HN + 'def main() -> int / []:\n' + UNSURE + '    h = H(x)\n'
     '    return 0\n',
     "line 19: argument 1 of H() must be int, but 'x' has no known type"),
    ('class Boom(Exception): ...\ndef main() -> int / []:\n' + UNSURE
     + '    e = Boom(x)\n    return 0\n',
     "line 14: argument 1 of Boom() must be str, but 'x' has no known "
     "type"),
    ('def main() -> int / []:\n' + UNSURE
     + '    for i in range(x):\n        pass\n    return 0\n',
     "line 13: argument 1 of range() must be int, but 'x' has no known "
     "type"),
    ('def main() -> int / []:\n' + UNSURE
     + '    xs = [1]\n    xs.append(x)\n    return 0\n',
     "line 14: argument 1 of append() must be int, but 'x' has no known "
     "type"),
    ('def f() -> int:\n' + UNSURE + '    return x\n' + MAIN,
     "line 13: function 'f' must return int, but 'x' has no known type"),
    (GET + 'class H(Handler[Ask]):\n    def get(self) -> int:\n'
     '        if 1 == 1:\n            v = 1\n        else:\n'
     '            v = "s"\n        return v\n' + MAIN,
     "line 16: method 'get' must return int, but 'v' has no known type"),
    (HN + 'def main() -> int / []:\n' + UNSURE
     + '    h = H()\n    h.n = x\n    return 0\n',
     "line 20: field 'n' of handler class 'H' must be int, but 'x' has no "
     "known type"),
    ('def main() -> int / []:\n' + UNSURE
     + '    xs = [1]\n    xs[0] = x\n    return 0\n',
     "line 14: an element of the list must be int, but 'x' has no known "
     "type"),
    (ASK + UNSURE + ASKED + '        eff.resume(x)\n    return 0\n',
     "line 19: eff.resume() for Ask.ask must pass int, but 'x' has no "
     "known type"),
    ('def main() -> int / []:\n' + UNSURE
     + '    ys = [x, 1]\n    for i in range(ys[0]):\n        pass\n'
     '    return 0\n',
     "line 14: argument 1 of range() must be int, but the value has no "
     "known type"),
], ids=['function', 'operation', 'handler-class', 'exception-class',
        'range', 'append', 'return', 'method', 'field', 'index',
        'resume', 'element'])
def test_rejects_a_value_of_unknown_type_at_a_typed_slot(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n' + UNSURE + '    print(x)\n    return 0\n',
    'def main() -> int / []:\n' + UNSURE + '    xs = []\n'
    '    xs.append(x)\n    xs.append(1)\n    return 0\n',
    'def main() -> int / []:\n' + UNSURE + '    print(len(x))\n'
    '    print(str(x))\n    return 0\n',
    'def main() -> int / []:\n' + UNSURE + '    print(x + 1)\n'
    '    return 0\n',
], ids=['print', 'empty-list', 'len-and-str', 'operator'])
def test_accepts_a_value_of_unknown_type_where_no_slot_is_typed(body):
    check_source(body)

# --- and, or, not, and elif (Milestone 11) -----------------------------------

BOOLS = ('def main() -> int / []:\n'
         '    a = True\n    b = False\n    c = True\n')

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    print(True and False)\n    return 0\n',
    'def main() -> int / []:\n    print(not 1 == 2)\n    return 0\n',
    BOOLS + '    print(a and not b or c)\n    return 0\n',
    'def main() -> int / []:\n    i = 0\n'
    '    while i < 3 and i != 5:\n        i = i + 1\n    return 0\n',
    'def f(a: bool, b: bool) -> bool:\n    return a and b\n' + MAIN,
    'def main() -> int / []:\n    n = 1\n    if n == 0:\n        x = 1\n'
    '    elif n == 1:\n        x = "s"\n    else:\n        x = 2\n'
    '    print(x + 1)\n    print(x + "a")\n    return 0\n',
    'def f() -> bool / [FileIO]:\n'
    '    return True and perform(FileIO.read("a")) == "x"\n' + MAIN,
], ids=['literals', 'not-compare', 'names', 'while-test', 'return-bool',
        'elif-merges', 'perform-in-right-operand'])
def test_accepts_bool_operands_and_tests(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    print(1 and True)\n    return 0\n',
     'line 9: and needs a bool, not int'),
    ('def main() -> int / []:\n    print(True or "s")\n    return 0\n',
     'line 9: or needs a bool, not str'),
    ('def main() -> int / []:\n    print(not "s")\n    return 0\n',
     'line 9: not needs a bool, not str'),
    ('def main() -> int / []:\n    n = 1\n    if n:\n        pass\n'
     '    return 0\n',
     'line 10: if needs a bool, not int'),
    ('def main() -> int / []:\n    n = 1\n    while n:\n        n = 0\n'
     '    return 0\n',
     'line 10: while needs a bool, not int'),
    ('def main() -> int / []:\n    n = 1\n    if n == 0:\n        pass\n'
     '    elif n:\n        pass\n    return 0\n',
     'line 12: if needs a bool, not int'),
], ids=['and-int', 'or-str', 'not-str', 'if-int', 'while-int', 'elif-int'])
def test_rejects_a_non_bool_operand_or_test(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

def test_an_effect_in_a_right_operand_counts_for_the_function():
    with pytest.raises(UnhandledEffectError) as info:
        check_source('def f() -> bool:\n'
                     '    return False and perform(FileIO.read("a")) == "x"\n'
                     + MAIN)
    assert info.value.msg == (
        "line 8: function 'f' performs FileIO (line 9) without "
        "declaring it in its effect row")

def test_a_pass_that_unbinds_a_name_is_followed_by_another():
    body = ('class E(Exception): ...\n'
            'def main() -> int / []:\n    if 1 == 1:\n        e = "s"\n'
            '    else:\n        e = 1\n    for i in range(2):\n'
            '        print(e)\n        try:\n            raise E()\n'
            '        except E as e:\n            pass\n    return 0\n')
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == ("line 15: name 'e' is unbound after the "
                              "except clause that bound it")

# --- dict[str, T] and in (Milestone 12) --------------------------------------

TOTAL = ('def total(d: dict[str, int]) -> int:\n    n = 0\n'
         '    for k in d:\n        n = n + d[k] + 1\n    return n\n')

@pytest.mark.parametrize('body', [
    TOTAL + 'def main() -> int / []:\n    d = {}\n    d["a"] = 1\n'
    '    print(total(d))\n    return 0\n',
    TOTAL + 'def main() -> int / []:\n    print(total({}))\n    return 0\n',
    'def main() -> int / []:\n    d = {"a": 1}\n    k = "a"\n'
    '    print(k in d, k not in d, len(d) + 1)\n    return 0\n',
    'def main() -> int / []:\n    print(1 in [1, 2], 3 not in [1, 2])\n'
    '    return 0\n',
    'def main() -> int / []:\n    b = "a" in {"a": "x"}\n'
    '    if b:\n        pass\n    return 0\n',
    'class Files(Handler[FileIO]):\n    files: dict[str, str] = {}\n'
    '    def read(self, path: str) -> str:\n'
    '        return self.files[path]\n'
    '    def write(self, path: str, content: str) -> int:\n'
    '        self.files[path] = content\n        return len(self.files)\n'
    + MAIN,
], ids=['refined-then-passed', 'empty-passed', 'dict-membership-len',
        'list-membership', 'in-gives-bool', 'dict-field'])
def test_accepts_dict_and_membership(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    d = {"a": 1}\n    print(d[1])\n'
     '    return 0\n',
     'line 10: a dict key must be str, not int'),
    ('def main() -> int / []:\n    d = {"a": 1}\n    d["b"] = "s"\n'
     '    return 0\n',
     'line 10: the dict holds int; cannot assign str'),
    ('def main() -> int / []:\n    d = {"a": "x"}\n    print(1 in d)\n'
     '    return 0\n',
     "line 10: 'd' holds str; cannot test int"),
    ('def main() -> int / []:\n    print(1 in 2)\n    return 0\n',
     'line 9: in needs a list or dict, not int'),
    ('def main() -> int / []:\n    print({1: 2})\n    return 0\n',
     'line 9: dict keys must be str, not int'),
    ('def main() -> int / []:\n    print({"a": 1, "b": "s"})\n'
     '    return 0\n',
     'line 9: dict values must share a type: int and str'),
    ('def main() -> int / []:\n    print({"a": [1]})\n    return 0\n',
     'line 9: dict values must be int, str, or bool, not a list'),
    ('def main() -> int / []:\n    print(str({"a": 1}))\n    return 0\n',
     'line 9: str() needs an int, str, or bool, not dict[str, int]'),
    ('def main() -> int / []:\n    print({"a": 1} == {"a": 1})\n'
     '    return 0\n',
     'line 9: unsupported operand types for ==: '
     'dict[str, int] and dict[str, int]'),
    ('def f(n: int) -> int:\n    return n\n'
     'def main() -> int / []:\n    print(f({}))\n    return 0\n',
     'line 11: argument 1 of f() must be int, not dict'),
], ids=['int-key', 'wrong-value', 'in-wrong-key', 'in-int',
        'literal-int-key', 'mixed-values', 'list-value', 'str-of-dict',
        'dict-equality', 'empty-to-int'])
def test_rejects_a_dict_or_membership_type_error(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

def test_an_instance_name_survives_a_second_pass_over_its_suite():
    body = (HX + 'def main() -> int / []:\n    x = 1\n'
            '    try:\n        with handle(X):\n            h = HX()\n'
            '            with handle(h):\n'
            '                print(perform(X.a()))\n'
            '    except X.a as eff:\n        eff.resume(2)\n'
            '    return 0\n')
    check_source(body)

# --- second passes over a suite (verification pass of 2026-11-08) -----------

PASSES = ('class Log(Effect):\n    def note(text: str) -> int: ...\n'
          'class Boom(Exception): ...\n'
          'def take_int(n: int) -> int:\n    return n\n')

def rebound(pad):
    return (pad + 'try:\n' + pad + '    raise Boom()\n' +
            pad + 'except Boom as x:\n' + pad + '    pass\n')

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    for v in [1, 2]:\n'
    '        take_int(v)\n        v = "s"\n    return 0\n',
    'def take_str(s: str) -> int:\n    return 0\n'
    'def main() -> int / []:\n    d = {"a": 1}\n    for k in d:\n'
    '        take_str(k)\n        k = 3\n    return 0\n',
    'def main() -> int / []:\n    for i in range(3):\n'
    '        take_int(i)\n        i = "s"\n    return 0\n',
    'def main() -> int / []:\n    for e in [1, 2]:\n'
    '        take_int(e)\n        try:\n            raise Boom()\n'
    '        except Boom as e:\n            pass\n    return 0\n',
], ids=['list-retyped', 'dict-retyped', 'range-retyped', 'except-rebound'])
def test_accepts_a_for_name_bound_afresh_on_every_pass(body):
    check_source(PASSES + body)

def test_a_second_check_of_finally_starts_from_the_continuing_paths():
    body = ('def main() -> int / []:\n    x = 0\n    try:\n'
            '        print(1)\n    finally:\n        take_int(x)\n'
            '        try:\n            raise Boom()\n'
            '        except Boom as x:\n            pass\n'
            '    return 0\n')
    check_source(PASSES + body)

def test_a_finally_may_rebind_the_name_of_a_clause_that_returned():
    body = ('def f() -> int:\n    try:\n        raise Boom()\n'
            '    except Boom as e:\n        return 0\n'
            '    finally:\n        e = 1\n    return 1\n'
            'def main() -> int / []:\n    print(f())\n    return 0\n')
    check_source(PASSES + body)

def handled(body, clause):
    return ('def main() -> int / []:\n    x = 0\n    try:\n'
            '        with handle(Log):\n' + body +
            '    except Log.note as eff:\n' + clause +
            '        eff.resume(0)\n    return 0\n')

NOTED = '            perform(Log.note("a"))\n            take_int(x)\n'

NESTED = ('        try:\n            with handle(Ask):\n'
          '                perform(Ask.get())\n'
          '        except Ask.get as e:\n            x = "s"\n'
          '            e.resume(1)\n')

@pytest.mark.parametrize('body', [
    PASSES + handled(NOTED + rebound(' ' * 12), ''),
    PASSES + handled('            take_int(x)\n            x = "s"\n'
                     '            perform(Log.note(x))\n', ''),
    PASSES + handled(NOTED, '        x = 5\n'),
], ids=['body-unbinds', 'body-retypes', 'clause-keeps-type'])
def test_accepts_a_handled_body_whose_own_end_state_differs(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    (PASSES + handled(NOTED, '        x = "s"\n'),
     "line 18: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
    (PASSES + handled(NOTED + '            x = "s"\n', '        x = "t"\n'),
     "line 18: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
    (PASSES + handled(NOTED, rebound(' ' * 8)),
     "line 18: name 'x' is unbound after the except clause that bound it"),
    (PASSES + GET + handled(NOTED, NESTED),
     "line 20: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
], ids=['clause-retypes', 'both-retype', 'clause-unbinds', 'nested-retypes'])
def test_rejects_a_clause_change_fed_back_into_the_body(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

# --- retyping at the performs (2026-11-09) -----------------------------------

NOTES = 'def notes() -> int / [Log]:\n    return perform(Log.note("a"))\n'

@pytest.mark.parametrize('body', [
    PASSES + handled('            take_int(x)\n'
                     '            perform(Log.note("a"))\n', '        x = "s"\n'),
    PASSES + 'def take_list(xs: list[int]) -> int:\n    return 0\n'
    'def main() -> int / []:\n    xs = []\n    xs.append(1)\n    try:\n'
    '        with handle(Log):\n            take_list(xs)\n'
    '            perform(Log.note("a"))\n            print(len(xs))\n'
    '    except Log.note as eff:\n        xs = ["s"]\n        eff.resume(0)\n'
    '    return 0\n',
    PASSES + 'def f() -> int / [Boom]:\n    return 0\n'
    'def g() -> int / [Boom]:\n    x = 0\n    try:\n'
    '        with handle(Log):\n            x = 1\n            f()\n'
    '            take_int(x)\n            perform(Log.note("a"))\n'
    '    except Log.note as eff:\n        x = "s"\n        eff.resume(0)\n'
    '    return 0\n'
    'def main() -> int / []:\n    return 0\n',
], ids=['read-before-perform', 'list-before-perform', 'exception-row'])
def test_accepts_a_read_before_the_first_perform_point(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    (PASSES + handled('            x = 1\n            take_int(x)\n'
                      '            perform(Log.note("a"))\n'
                      '            take_int(x)\n', '        x = "s"\n'),
     "line 20: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
    (PASSES + NOTES + handled('            x = 1\n            notes()\n'
                              '            take_int(x)\n', '        x = "s"\n'),
     "line 21: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
    (PASSES + GET + 'def main() -> int / []:\n    x = 0\n    try:\n'
     '        with handle(Log, Ask):\n            perform(Log.note("a"))\n'
     '            perform(Ask.get())\n    except Log.note as eff:\n'
     '        x = 1\n        eff.resume(0)\n        take_int(x)\n'
     '    except Ask.get as eff:\n        x = "s"\n        eff.resume(0)\n'
     '    return 0\n',
     "line 24: argument 1 of take_int() must be int, "
     "but 'x' has no known type"),
], ids=['after-body-assign', 'call-with-row', 'after-resume'])
def test_rejects_a_read_after_a_perform_point_a_clause_retypes(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

# --- f-strings (Milestone 13) ------------------------------------------------

LOG = 'class Log(Effect):\n    def note(text: str) -> int: ...\n'

@pytest.mark.parametrize('body', [
    'def main() -> int / []:\n    n = 1\n    s = "a"\n    b = n > 0\n'
    '    print(f"{n} {s} {b} {n + 1} {not b}")\n    return 0\n',
    'def main() -> int / []:\n    print(f"")\n    print(f"text")\n'
    '    return 0\n',
    'def main() -> int / []:\n    d = {"k": 1}\n'
    '    print(f"{d[\'k\']}")\n    return 0\n',
    'def take(s: str) -> int:\n    return 0\n'
    'def main() -> int / []:\n    n = 1\n    take(f"{n}")\n    return 0\n',
    'def main() -> int / []:\n    n = 1\n    d = {"a": 1}\n'
    '    d[f"row{n}"] = 1\n    return 0\n',
    'def name(n: int) -> str:\n    return f"#{n}"\n' + MAIN,
    'def main() -> int / []:\n    if 1 == 1:\n        v = 1\n'
    '    else:\n        v = "s"\n    print(f"{v}")\n    return 0\n',
], ids=['scalar-fields', 'no-fields', 'dict-item', 'str-argument',
        'dict-key', 'str-return', 'unknown-field'])
def test_accepts_an_fstring_of_scalar_or_unknown_fields(body):
    check_source(body)

@pytest.mark.parametrize('body, msg', [
    ('def main() -> int / []:\n    xs = [1]\n    print(f"{xs}")\n'
     '    return 0\n',
     'line 10: an f-string field needs an int, str, or bool, '
     'not list[int]'),
    ('def main() -> int / []:\n    d = {"a": 1}\n    print(f"{d}")\n'
     '    return 0\n',
     'line 10: an f-string field needs an int, str, or bool, '
     'not dict[str, int]'),
    ('def main() -> int / []:\n    print(f"{print(1)}")\n    return 0\n',
     'line 9: an f-string field needs an int, str, or bool, not None'),
], ids=['list-field', 'dict-field', 'none-field'])
def test_rejects_an_fstring_field_of_another_type(body, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == msg

def test_an_fstring_field_that_performs_counts_for_the_row():
    body = (LOG + 'def f() -> str:\n'
            '    return f"{perform(Log.note(\'x\'))}"\n' + MAIN)
    with pytest.raises(UnhandledEffectError) as info:
        check_source(body)
    assert info.value.msg == (
        "line 10: function 'f' performs Log (line 11) without declaring "
        "it in its effect row")

def test_accepts_an_fstring_field_that_performs_a_declared_effect():
    body = (LOG + 'def f() -> str / [Log]:\n'
            '    return f"{perform(Log.note(\'x\'))}"\n' + MAIN)
    check_source(body)

# --- augmented assignment (Milestone 14) ------------------------------------

def aug_main(lines):
    return 'def main() -> int / []:\n' + lines + '    return 0\n'

@pytest.mark.parametrize('lines', [
    '    x = 1\n    x += 1\n',
    '    x = 1\n    x -= 1\n',
    '    x = 1\n    x *= 2\n',
    '    x = 5\n    x //= 2\n',
    '    x = 5\n    x %= 2\n',
    '    s = "a"\n    s += "b"\n',
    '    xs = [1]\n    xs[0] += 1\n',
    '    d = {"k": 1}\n    d["k"] += 1\n',
    '    for i in range(3):\n        i += 1\n',
    '    i = 0\n    while i < 3:\n        i += 1\n',
], ids=['int-add', 'int-sub', 'int-mul', 'int-floordiv', 'int-mod',
        'str-add', 'list-item', 'dict-value', 'for-variable',
        'while-counter'])
def test_accepts_an_augmented_assignment_of_matching_types(lines):
    check_source(aug_main(lines))

def test_accepts_an_augmented_assignment_to_a_handler_field():
    body = (LOG + 'class Tally(Handler[Log]):\n    n: int = 0\n'
            '    def note(self, text: str) -> int:\n'
            '        self.n += 1\n        return self.n\n' + MAIN)
    check_source(body)

def test_an_augmented_floor_division_leaves_the_name_an_int():
    body = aug_main('    x = 5\n    x //= 2\n    y = x + "a"\n')
    with pytest.raises(InvalidProgram) as info:
        check_source(body)
    assert info.value.msg == (
        'line 11: unsupported operand types for +: int and str')

@pytest.mark.parametrize('lines, msg', [
    ('    x += 1\n', "line 9: name 'x' is not defined"),
    ('    s = "a"\n    s += 1\n',
     'line 10: unsupported operand types for +: str and int'),
    ('    s = "a"\n    s -= "a"\n',
     'line 10: unsupported operand types for -: str and str'),
    ('    xs = [1]\n    xs += [1]\n',
     'line 10: unsupported operand types for +: list[int] and list[int]'),
    ('    flag = True\n    flag += True\n',
     'line 10: unsupported operand types for +: bool and bool'),
    ('    d = {"a": "x"}\n    d["a"] += 1\n',
     'line 10: unsupported operand types for +: str and int'),
    ('    d = {"a": 1}\n    d[1] += 1\n',
     'line 10: a dict key must be str, not int'),
    ('    xs = [1]\n    xs["a"] += 1\n',
     'line 10: a list index must be int, not str'),
    ('    n = 1\n    n[0] += 1\n', "line 10: 'n' is not a list"),
], ids=['unbound-name', 'str-plus-int', 'str-minus', 'list-plus',
        'bool-plus', 'dict-value-type', 'dict-key-type', 'list-index-type',
        'not-a-list'])
def test_rejects_an_augmented_assignment_the_runtime_would_refuse(lines, msg):
    with pytest.raises(InvalidProgram) as info:
        check_source(aug_main(lines))
    assert info.value.msg == msg

def test_an_augmented_value_that_performs_counts_for_the_row():
    body = (LOG + 'def f() -> int:\n    xs = [1]\n'
            '    xs[0] += perform(Log.note("x"))\n    return 0\n' + MAIN)
    with pytest.raises(UnhandledEffectError) as info:
        check_source(body)
    assert info.value.msg == (
        "line 10: function 'f' performs Log (line 12) without declaring "
        "it in its effect row")

def test_accepts_an_augmented_value_that_performs_a_declared_effect():
    body = (LOG + 'def f() -> int / [Log]:\n    xs = [1]\n'
            '    xs[0] += perform(Log.note("x"))\n    return 0\n' + MAIN)
    check_source(body)
