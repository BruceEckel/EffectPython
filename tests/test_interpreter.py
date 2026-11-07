"""Milestone 1 acceptance: the evaluator runs a recursive Fibonacci.

Run with:  pypy2 -m pytest
These tests import no RPython modules, so they need no PYTHONPATH.
"""
import pytest

from effectpython import ast_nodes as ast
from effectpython.errors import EffectPythonRuntimeError, RaisedException
from effectpython.interpreter import Interpreter, Output, tail_switch
from effectpython.model import W_Int, W_Str, W_None, w_None
from effectpython.parser import parse
from effectpython.samples import build_fib_module

class ListOutput(Output):
    def __init__(self):
        self.lines = []

    def write_line(self, text):
        self.lines.append(text)

def run_module(module):
    out = ListOutput()
    interp = Interpreter(module, out)
    return interp.run_main(), out.lines

def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)

@pytest.mark.parametrize("n", [0, 1, 2, 10, 20])
def test_fibonacci(n):
    exit_code, lines = run_module(build_fib_module(n))
    assert exit_code == 0
    assert lines == [str(fib(n))]

def one_function(name, params, body):
    return ast.FunctionDef(name, params, ["int"] * len(params), "int", [], body)

def test_locals_are_per_call():
    # def shadow(x): y = x * 2; return y
    # def main(): y = 1; shadow(5); return y      -> 1, not 10
    shadow = one_function("shadow", ["x"], [
        ast.Assign("y", ast.BinOp("*", ast.Name("x"), ast.IntLiteral(2))),
        ast.Return(ast.Name("y")),
    ])
    main = one_function("main", [], [
        ast.Assign("y", ast.IntLiteral(1)),
        ast.ExprStmt(ast.Call("shadow", [ast.IntLiteral(5)])),
        ast.Return(ast.Name("y")),
    ])
    exit_code, lines = run_module(ast.Module([shadow, main]))
    assert exit_code == 1
    assert lines == []

def test_if_else_and_string_concat():
    # def main(): if 3 > 4: print("yes") else: print("no" + "pe"); return 0
    main = one_function("main", [], [
        ast.If(ast.Compare(">", ast.IntLiteral(3), ast.IntLiteral(4)),
               [ast.ExprStmt(ast.Call("print", [ast.StrLiteral("yes")]))],
               [ast.ExprStmt(ast.Call("print", [
                   ast.BinOp("+", ast.StrLiteral("no"), ast.StrLiteral("pe"))]))]),
        ast.Return(ast.IntLiteral(0)),
    ])
    exit_code, lines = run_module(ast.Module([main]))
    assert exit_code == 0
    assert lines == ["nope"]

def test_while_loop():
    # def main(): i = 0; while i < 5: i = i + 2; return i      -> 6
    main = one_function("main", [], [
        ast.Assign("i", ast.IntLiteral(0)),
        ast.While(ast.Compare("<", ast.Name("i"), ast.IntLiteral(5)),
                  [ast.Assign("i", ast.BinOp("+", ast.Name("i"),
                                             ast.IntLiteral(2)))]),
        ast.Return(ast.Name("i")),
    ])
    exit_code, lines = run_module(ast.Module([main]))
    assert exit_code == 6
    assert lines == []

def test_print_several_values_and_bare_return():
    main = one_function("main", [], [
        ast.ExprStmt(ast.Call("print", [
            ast.IntLiteral(7), ast.StrLiteral("x"),
            ast.Compare("==", ast.IntLiteral(1), ast.IntLiteral(1))])),
        ast.Return(None),
    ])
    exit_code, lines = run_module(ast.Module([main]))
    assert exit_code == 0  # a non-int result from main() is exit code 0
    assert lines == ["7 x True"]

def test_undefined_name():
    main = one_function("main", [], [ast.Return(ast.Name("nope"))])
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_module(ast.Module([main]))
    assert "nope" in info.value.msg

def test_arity_mismatch():
    f = one_function("f", ["a", "b"], [ast.Return(ast.Name("a"))])
    main = one_function("main", [], [ast.Return(ast.Call("f", [ast.IntLiteral(1)]))])
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_module(ast.Module([f, main]))
    assert info.value.msg == "f() takes 2 arguments (1 given)"

def test_type_error_in_operator():
    main = one_function("main", [], [
        ast.Return(ast.BinOp("+", ast.IntLiteral(1), ast.StrLiteral("a")))])
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_module(ast.Module([main]))
    assert info.value.msg == "unsupported operand types for +: int and str"

def test_division_by_zero():
    main = one_function("main", [], [
        ast.Return(ast.BinOp("//", ast.IntLiteral(1), ast.IntLiteral(0)))])
    with pytest.raises(EffectPythonRuntimeError):
        run_module(ast.Module([main]))

def test_missing_main():
    with pytest.raises(EffectPythonRuntimeError):
        run_module(ast.Module([]))

# --- Handler instances (Milestone 5), without a handle statement -------------

HANDLER = (
    'class FileIO(Effect):\n'
    '    def read(path: str) -> str: ...\n'
    'class Fake(Handler[FileIO]):\n'
    '    tag: str\n'
    '    count: int = 0\n'
    '    def read(self, path: str) -> str:\n'
    '        return path\n')

def test_constructor_fills_fields_from_arguments_and_defaults():
    exit_code, lines = run_module(parse(
        HANDLER + 'def main() -> int:\n'
        '    print(Fake("t"), Fake("u", 9))\n    return 0\n'))
    assert lines == ["Fake(tag='t', count=0) Fake(tag='u', count=9)"]

def test_field_assignment_and_read():
    exit_code, lines = run_module(parse(
        HANDLER + 'def main() -> int:\n'
        '    fake = Fake("t")\n'
        '    fake.count = fake.count + 1\n'
        '    return fake.count\n'))
    assert exit_code == 1

@pytest.mark.parametrize('body, msg', [
    ('    f = Fake()\n    return 0\n',
     "Fake() needs a value for field 'tag'"),
    ('    f = Fake("t", 1, 2)\n    return 0\n',
     'Fake() takes 2 arguments (3 given)'),
    ('    f = Fake("t")\n    return f.nope\n',
     "handler class 'Fake' has no field 'nope'"),
    ('    x = 1\n    x.count = 2\n    return 0\n',
     "'x' is not a handler instance"),
])
def test_instance_runtime_errors(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_module(parse(HANDLER + 'def main() -> int:\n' + body))
    assert info.value.msg == msg

# --- Exceptions (Milestone 6), without a handle statement --------------------

EXCEPTIONS = (
    'class NotFound(Exception): ...\n'
    'class Denied(Exception): ...\n')

def run_main_body(body, functions=''):
    return run_module(parse(
        EXCEPTIONS + functions + 'def main() -> int:\n' + body))

@pytest.mark.parametrize('functions, body', [
    ('',
     '    try:\n'
     '        raise NotFound("a")\n'
     '        print("skipped")\n'
     '    except NotFound as e:\n'
     '        print("caught")\n'
     '    print("after")\n    return 0\n'),
    ('def find() -> int:\n'
     '    raise NotFound("a")\n',
     '    try:\n'
     '        find()\n'
     '        print("skipped")\n'
     '    except NotFound as e:\n'
     '        print("caught")\n'
     '    print("after")\n    return 0\n'),
])
def test_raised_exception_is_caught_and_execution_continues(
        functions, body):
    exit_code, lines = run_main_body(body, functions)
    assert lines == ["caught", "after"]

@pytest.mark.parametrize('clauses, printed', [
    ('    except Denied as e:\n'
     '        print("denied")\n'
     '    except NotFound as e:\n'
     '        print("not found")\n',
     ["not found"]),
    ('    except Exception as e:\n'
     '        print(e)\n',
     ["settings.json"]),
    ('    except NotFound:\n'
     '        print("no binding")\n',
     ["no binding"]),
])
def test_first_matching_clause_runs(clauses, printed):
    exit_code, lines = run_main_body(
        '    try:\n'
        '        raise NotFound("settings.json")\n'
        + clauses + '    return 0\n')
    assert lines == printed

@pytest.mark.parametrize('raise_stmt, msg', [
    ('raise NotFound("settings.json")', 'NotFound: settings.json'),
    ('raise NotFound()', 'NotFound'),
])
def test_unmatched_exception_propagates_out_of_main(raise_stmt, msg):
    with pytest.raises(RaisedException) as info:
        run_main_body(
            '    try:\n'
            '        ' + raise_stmt + '\n'
            '    except Denied as e:\n'
            '        print("denied")\n'
            '    return 0\n')
    assert info.value.msg == msg

def test_bool_literals():
    exit_code, lines = run_main_body(
        '    flag = True\n'
        '    print(flag, False, flag == True)\n'
        '    if False:\n'
        '        print("skipped")\n'
        '    return 0\n')
    assert lines == ["True False True"]

def test_exception_without_message_prints_empty_message():
    exit_code, lines = run_main_body(
        '    try:\n'
        '        raise NotFound()\n'
        '    except NotFound as e:\n'
        '        print("empty:", e, "end")\n'
        '    return 0\n')
    assert lines == ["empty:  end"]

@pytest.mark.parametrize('body', [
    '    try:\n'
    '        raise NotFound("a")\n'
    '    except NotFound as e:\n'
    '        print(e)\n'
    '    print(e)\n'
    '    return 0\n',
    '    e = 7\n'
    '    try:\n'
    '        raise NotFound("a")\n'
    '    except NotFound as e:\n'
    '        print(e)\n'
    '    return e\n',
    '    try:\n'
    '        raise NotFound("a")\n'
    '    except NotFound as e:\n'
    '        try:\n'
    '            raise NotFound("b")\n'
    '        except NotFound as e:\n'
    '            print(e)\n'
    '        print(e)\n'
    '    return 0\n',
], ids=['fresh name', 'name assigned before the try',
        'name a nested clause bound'])
def test_as_name_is_unbound_after_the_clause(body):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body)
    assert info.value.msg == "name 'e' is not defined"

def test_nested_clauses_may_bind_the_same_name():
    exit_code, lines = run_main_body(
        '    try:\n'
        '        raise NotFound("a")\n'
        '    except NotFound as e:\n'
        '        try:\n'
        '            raise NotFound("b")\n'
        '        except NotFound as e:\n'
        '            print(e)\n'
        '    return 0\n')
    assert (exit_code, lines) == (0, ["b"])

@pytest.mark.parametrize('body, expected_exit, printed', [
    ('    try:\n'
     '        return 3\n'
     '    except NotFound as e:\n'
     '        print("clause")\n'
     '    return 0\n',
     3, []),
    ('    try:\n'
     '        raise NotFound("a")\n'
     '    except NotFound as e:\n'
     '        return 4\n'
     '    print("after")\n'
     '    return 0\n',
     4, []),
])
def test_return_returns_from_the_function(body, expected_exit, printed):
    exit_code, lines = run_main_body(body)
    assert (exit_code, lines) == (expected_exit, printed)

def test_runtime_error_passes_through_except_exception():
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(
            '    try:\n'
            '        x = 1 // 0\n'
            '    except Exception as e:\n'
            '        print("caught")\n'
            '    return 0\n')
    assert info.value.msg == "integer division by zero"

def test_reraised_exception_reaches_an_outer_try():
    exit_code, lines = run_main_body(
        '    try:\n'
        '        try:\n'
        '            raise NotFound("a")\n'
        '        except NotFound as e:\n'
        '            print("inner")\n'
        '            raise e\n'
        '    except NotFound as e:\n'
        '        print("outer", e)\n'
        '    return 0\n')
    assert lines == ["inner", "outer a"]

@pytest.mark.parametrize('body, msg', [
    ('    raise 1\n', 'raise needs an exception, not int'),
    ('    raise NotFound(1)\n', 'NotFound() takes an optional str message'),
    ('    raise NotFound("a", "b")\n',
     'NotFound() takes an optional str message'),
])
def test_exception_runtime_errors(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body)
    assert info.value.msg == msg

# --- Throwing into the body (Milestone 7) ------------------------------------

CLAUSE_PROGRAM = (
    'class Ask(Effect):\n'
    '    def value() -> int / [Refused]: ...\n'
    'class Refused(Exception): ...\n'
    'def main() -> int / []:\n'
    '    try:\n'
    '        with handle(Ask):\n'
    '            print(perform(Ask.value()))\n'
    '    except Ask.value as eff:\n'
    '%s'
    '    return 0\n')

@pytest.mark.parametrize('clause_body, expected', [
    ('        eff.throw(Refused())\n', ast.Throw),
    ('        eff.resume(1)\n', ast.Resume),
    ('        print(1)\n        eff.throw(Refused())\n', ast.Throw),
    ('        x = eff.throw(Refused())\n', type(None)),
    ('        eff.throw(Refused())\n        print(1)\n', type(None)),
    ('        other.throw(Refused())\n', type(None)),
], ids=['throw', 'resume', 'throw after a statement', 'assigned',
        'statement after', 'another binding'])
def test_tail_switch_finds_a_final_throw_or_resume(clause_body, expected):
    handle = parse(CLAUSE_PROGRAM % clause_body).functions[0].body[0]
    clause = handle.clauses[0]
    assert type(tail_switch(clause)) is expected

# --- try/finally (Milestone 8), without a handle statement -------------------

@pytest.mark.parametrize('body, expected_exit, printed', [
    ('    try:\n'
     '        print("body")\n'
     '    finally:\n'
     '        print("finally")\n'
     '    print("after")\n'
     '    return 0\n',
     0, ["body", "finally", "after"]),
    ('    try:\n'
     '        return 3\n'
     '    finally:\n'
     '        print("finally")\n',
     3, ["finally"]),
    ('    try:\n'
     '        raise NotFound("a")\n'
     '    except NotFound as e:\n'
     '        print("caught")\n'
     '    finally:\n'
     '        print("finally")\n'
     '    return 0\n',
     0, ["caught", "finally"]),
    ('    try:\n'
     '        raise NotFound("a")\n'
     '    except NotFound as e:\n'
     '        return 4\n'
     '    finally:\n'
     '        print("finally")\n',
     4, ["finally"]),
    ('    try:\n'
     '        try:\n'
     '            raise NotFound("a")\n'
     '        finally:\n'
     '            print("inner")\n'
     '    except NotFound as e:\n'
     '        print("caught", e)\n'
     '    finally:\n'
     '        print("outer")\n'
     '    return 0\n',
     0, ["inner", "caught a", "outer"]),
], ids=['completes', 'return in the suite', 'caught exception',
        'return from a clause', 'nested finally after a clause'])
def test_finally_runs_however_the_try_ends(body, expected_exit, printed):
    exit_code, lines = run_main_body(body)
    assert (exit_code, lines) == (expected_exit, printed)

@pytest.mark.parametrize('clauses', [
    '',
    '        except Denied as e:\n'
    '            print("denied")\n',
], ids=['no clauses', 'clause for another class'])
def test_finally_runs_before_an_uncaught_exception_propagates(clauses):
    exit_code, lines = run_main_body(
        '    try:\n'
        '        try:\n'
        '            raise NotFound("a")\n'
        + clauses +
        '        finally:\n'
        '            print("finally")\n'
        '    except NotFound as e:\n'
        '        print("outer", e)\n'
        '    return 0\n')
    assert lines == ["finally", "outer a"]

def test_return_in_finally_replaces_the_exception():
    exit_code, lines = run_main_body(
        '    try:\n'
        '        raise NotFound("a")\n'
        '    finally:\n'
        '        return 5\n')
    assert (exit_code, lines) == (5, [])

def test_exception_in_finally_replaces_the_return():
    exit_code, lines = run_main_body(
        '    try:\n'
        '        try:\n'
        '            return 3\n'
        '        finally:\n'
        '            raise Denied("b")\n'
        '    except Denied as e:\n'
        '        print("denied", e)\n'
        '    return 0\n')
    assert (exit_code, lines) == (0, ["denied b"])

def test_runtime_error_passes_through_a_finally():
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(
            '    try:\n'
            '        x = 1 // 0\n'
            '    finally:\n'
            '        print("finally")\n'
            '    return 0\n')
    assert info.value.msg == "integer division by zero"

def test_as_name_is_unbound_in_the_finally():
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(
            '    try:\n'
            '        raise NotFound("a")\n'
            '    except NotFound as e:\n'
            '        print(e)\n'
            '    finally:\n'
            '        print(e)\n')
    assert info.value.msg == "name 'e' is not defined"

# --- Lists and for (Milestone 9), without a handle statement -----------------

@pytest.mark.parametrize('statement, printed', [
    ('print([3, 1, 2], ["a", "b"], [True, False], [])',
     ["[3, 1, 2] ['a', 'b'] [True, False] []"]),
    ('print(len([1, 2, 3]), len("abcd"), len([]))', ["3 4 0"]),
    ('xs = [3, 1, 2]\n'
     '    print(xs[0], xs[2], xs[-1], xs[-3])',
     ["3 2 2 3"]),
    ('xs = [1, 2, 3]\n'
     '    xs[1] = 9\n'
     '    xs[-1] = 8\n'
     '    print(xs)',
     ["[1, 9, 8]"]),
    ('xs = []\n'
     '    xs.append(1)\n'
     '    xs.append(2)\n'
     '    print(xs, len(xs))',
     ["[1, 2] 2"]),
    ('print([1, 2] == [1, 2], [1, 2] != [1, 2], [1] == [1, 2],'
     ' [] == [], ["a"] == ["a"])',
     ["True False False True True"]),
    ('print(str(7) + str(True) + str("s"))', ["7Trues"]),
], ids=['print', 'len', 'index from both ends', 'indexed assignment',
        'append', 'equality', 'str'])
def test_list_operations(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n')
    assert (exit_code, lines) == (0, printed)

def test_names_bound_to_one_list_share_it():
    exit_code, lines = run_main_body(
        '    xs = [1]\n'
        '    ys = xs\n'
        '    print(add(xs, 2), add(ys, 3))\n'
        '    print(xs, ys)\n'
        '    return 0\n',
        'def add(xs: list[int], n: int) -> int:\n'
        '    xs.append(n)\n'
        '    return len(xs)\n')
    assert lines == ["2 3", "[1, 2, 3] [1, 2, 3]"]

@pytest.mark.parametrize('body, printed', [
    ('    for x in [1, 2, 3]:\n'
     '        print(x)\n'
     '    print(x)\n',
     ["1", "2", "3", "3"]),
    ('    xs = [1, 2]\n'
     '    for x in xs:\n'
     '        if x == 1:\n'
     '            xs.append(3)\n'
     '        print(x)\n',
     ["1", "2", "3"]),
    ('    for x in []:\n'
     '        print("never")\n'
     '    print("done")\n',
     ["done"]),
    ('    for i in range(3):\n'
     '        print(i)\n',
     ["0", "1", "2"]),
    ('    for i in range(2, 5):\n'
     '        print(i)\n',
     ["2", "3", "4"]),
    ('    for i in range(3, 1):\n'
     '        print(i)\n',
     []),
    ('    for i in range(3):\n'
     '        pass\n'
     '    print(i)\n',
     ["2"]),
], ids=['list keeps the last element', 'list walks the live length',
        'empty list', 'range(3)', 'range(2, 5)', 'empty range',
        'range keeps the last value'])
def test_for_loop(body, printed):
    exit_code, lines = run_main_body(body + '    return 0\n')
    assert (exit_code, lines) == (0, printed)

@pytest.mark.parametrize('body, msg', [
    ('    xs = [1, 2]\n    print(xs[2])\n', 'list index out of range'),
    ('    xs = [1, 2]\n    print(xs[-3])\n', 'list index out of range'),
    ('    xs = [1, 2]\n    xs[-3] = 1\n', 'list index out of range'),
    ('    xs = []\n    print(xs[0])\n', 'list index out of range'),
    ('    n = 3\n    print(n[0])\n', 'int is not a list'),
    ('    print(len(3))\n', 'len() needs a list or str, not int'),
], ids=['past the end', 'before the start', 'assignment before the start',
        'empty list', 'index an int', 'len of an int'])
def test_list_runtime_errors(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body + '    return 0\n')
    assert info.value.msg == msg
