"""Milestone 2 acceptance: the static effect checker (plan 2.2, 4.2),
from Milestone 5 the handler class rules (plan 1.5), from Milestone 6
the exception rules (plan 1.6), and from Milestone 7 the throw rules
(plan 1.7).

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
    ('def f() -> int:\n    return x.resume(1)\n' + MAIN,
     InvalidProgram,
     "line 9: 'x' is not an except binding or a handler instance"),
    ('def f() -> int:\n    return x.path\n' + MAIN,
     InvalidProgram,
     "line 9: 'x' is not an except binding or a handler instance"),
    ('def f() -> int:\n    return 0\ndef f() -> int:\n    return 1\n'
     + MAIN, InvalidProgram, "line 10: function 'f' is defined twice"),
    ('class FileIO(Effect):\n    def read(path: str) -> str: ...\n' + MAIN,
     InvalidProgram, "line 8: effect 'FileIO' is declared twice"),
])
def test_rejected_programs(body, error, msg):
    with pytest.raises(error) as info:
        check_source(body)
    assert info.value.msg == msg

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
    ('class Fake(Handler[FileIO]):\n    items: list\n' + FAKE[29:] + MAIN,
     InvalidProgram,
     "line 9: field 'items' of handler class 'Fake' must be int or str, "
     "not list"),
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
    ('def f() -> int:\n    x.a = 1\n    return 0\n' + MAIN,
     InvalidProgram, "line 9: 'x' is not a handler instance"),
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
    ('def main() -> int / []:\n    with handle(nope):\n'
     '        pass\n    return 0\n', InvalidProgram,
     "line 9: 'nope' is not an effect or a handler instance"),
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
     'line 19: raise needs an exception, not a value of unknown type'),
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
    (CATCHING + '        x.throw(NotFound())\n    return 0\n',
     "line 23: 'x' is not an except binding or a handler instance"),
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
