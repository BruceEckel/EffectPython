"""Milestone 2 acceptance: the static effect checker (plan 2.2, 4.2).

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
     InvalidProgram, "line 8: unknown effect 'Nope'"),
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
     InvalidProgram, "line 9: 'x' is not bound by an except clause"),
    ('def f() -> int:\n    return x.path\n' + MAIN,
     InvalidProgram, "line 9: 'x' is not bound by an except clause"),
    ('def f() -> int:\n    return 0\ndef f() -> int:\n    return 1\n'
     + MAIN, InvalidProgram, "line 10: function 'f' is defined twice"),
    ('class FileIO(Effect):\n    def read(path: str) -> str: ...\n' + MAIN,
     InvalidProgram, "line 8: effect 'FileIO' is declared twice"),
])
def test_rejected_programs(body, error, msg):
    with pytest.raises(error) as info:
        check_source(body)
    assert info.value.msg == msg
