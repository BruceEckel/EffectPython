"""Milestone 1 acceptance: the evaluator runs a recursive Fibonacci;
from Milestone 11, the boolean operators and elif (plan 1.11);
from Milestone 12, dicts and in (plan 1.12); from Milestone 13,
f-strings (plan 1.13); from Milestone 14, augmented assignment
(plan 1.14); from Milestone 16, None and is (plan 1.16); from
Milestone 17, tuples (plan 1.17).

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
     "'x' is not a handler instance or a data class instance"),
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
    ('    print(len(3))\n', 'len() needs a list, dict, or str, not int'),
], ids=['past the end', 'before the start', 'assignment before the start',
        'empty list', 'index an int', 'len of an int'])
def test_list_runtime_errors(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body + '    return 0\n')
    assert info.value.msg == msg

# --- break and continue (Milestone 10), without a handle statement -----------

@pytest.mark.parametrize('body, printed', [
    ('    n = 0\n'
     '    while True:\n'
     '        n = n + 1\n'
     '        if n == 3:\n'
     '            break\n'
     '    print(n)\n',
     ["3"]),
    ('    n = 0\n'
     '    while n < 5:\n'
     '        n = n + 1\n'
     '        if n % 2 == 0:\n'
     '            continue\n'
     '        print(n)\n',
     ["1", "3", "5"]),
    ('    for x in [1, 2, 3, 4]:\n'
     '        if x == 3:\n'
     '            break\n'
     '    print(x)\n',
     ["3"]),
    ('    for i in range(5):\n'
     '        if i % 2 == 1:\n'
     '            continue\n'
     '        print(i)\n',
     ["0", "2", "4"]),
    ('    for i in range(2):\n'
     '        for j in range(3):\n'
     '            if j == 1:\n'
     '                break\n'
     '            print(i, j)\n',
     ["0 0", "1 0"]),
    ('    for i in range(3):\n'
     '        try:\n'
     '            if i == 1:\n'
     '                break\n'
     '            print("body", i)\n'
     '        finally:\n'
     '            print("finally", i)\n',
     ["body 0", "finally 0", "finally 1"]),
    ('    for i in range(3):\n'
     '        try:\n'
     '            if i == 1:\n'
     '                continue\n'
     '            print("body", i)\n'
     '        finally:\n'
     '            print("finally", i)\n',
     ["body 0", "finally 0", "finally 1", "body 2", "finally 2"]),
], ids=['while break', 'while continue', 'for break keeps the element',
        'range continue', 'break leaves the innermost loop',
        'break runs finally', 'continue runs finally'])
def test_break_and_continue(body, printed):
    exit_code, lines = run_main_body(body + '    return 0\n')
    assert (exit_code, lines) == (0, printed)

def test_break_in_a_callee_leaves_the_caller_loop_alone():
    exit_code, lines = run_main_body(
        '    for i in range(2):\n'
        '        print(first_over(4))\n'
        '    return 0\n',
        'def first_over(limit: int) -> int:\n'
        '    for x in [1, 5, 9]:\n'
        '        if x > limit:\n'
        '            break\n'
        '    return x\n')
    assert (exit_code, lines) == (0, ["5", "5"])

def test_break_outside_a_loop_is_a_runtime_error():
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body('    break\n    return 0\n')
    assert info.value.msg == 'break or continue outside a loop'

# --- and, or, not, and elif (Milestone 11) -----------------------------------

@pytest.mark.parametrize('source, printed', [
    ('True and False', 'False'),
    ('True and True', 'True'),
    ('True or False', 'True'),
    ('False or False', 'False'),
    ('not True', 'False'),
    ('not 1 == 2', 'True'),
], ids=['and-false', 'and-true', 'or-true', 'or-false', 'not',
        'not-compare'])
def test_boolean_operator_values(source, printed):
    exit_code, lines = run_main_body('    print(%s)\n    return 0\n' % source)
    assert (exit_code, lines) == (0, [printed])

NOISY = 'def noisy() -> bool:\n    print("ran")\n    return True\n'

@pytest.mark.parametrize('source, printed', [
    ('False and noisy()', ['False']),
    ('True or noisy()', ['True']),
    ('True and noisy()', ['ran', 'True']),
    ('False or noisy()', ['ran', 'True']),
], ids=['and-stops', 'or-stops', 'and-continues', 'or-continues'])
def test_the_right_operand_runs_only_when_the_left_does_not_decide(
        source, printed):
    exit_code, lines = run_main_body(
        '    print(%s)\n    return 0\n' % source, NOISY)
    assert (exit_code, lines) == (0, printed)

def test_an_elif_chain_runs_the_first_arm_whose_test_holds():
    exit_code, lines = run_main_body(
        '    for n in range(3):\n'
        '        pick(n)\n'
        '    return 0\n',
        'def pick(n: int) -> None:\n'
        '    if n == 0:\n'
        '        print("if")\n'
        '    elif n == 1:\n'
        '        print("elif")\n'
        '    else:\n'
        '        print("else")\n')
    assert (exit_code, lines) == (0, ["if", "elif", "else"])

@pytest.mark.parametrize('body, msg', [
    ('    n = 1\n    if n:\n        pass\n',
     'if needs a bool, not int'),
    ('    n = 1\n    while n:\n        n = 0\n',
     'while needs a bool, not int'),
    ('    print(1 and True)\n', 'and needs a bool, not int'),
    ('    print(True and 1)\n', 'and needs a bool, not int'),
    ('    print(False or "s")\n', 'or needs a bool, not str'),
    ('    print(not "s")\n', 'not needs a bool, not str'),
], ids=['if', 'while', 'and-left', 'and-right', 'or-right', 'not'])
def test_a_non_bool_test_or_operand_is_a_runtime_error(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body + '    return 0\n')
    assert info.value.msg == msg

# --- dict[str, T] and in (Milestone 12) --------------------------------------

@pytest.mark.parametrize('statement, printed', [
    ('print({"a": 1, "b": "x"}, {}, len({"a": 1}))',
     ["{'a': 1, 'b': 'x'} {} 1"]),
    ('d = {}\n'
     '    d["a"] = 1\n'
     '    d["a"] = d["a"] + 1\n'
     '    print(d, d["a"])',
     ["{'a': 2} 2"]),
    ('d = {"a": 1}\n'
     '    print("a" in d, "b" in d, "b" not in d)',
     ["True False True"]),
    ('print(2 in [1, 2], 3 in [1, 2], 3 not in [1, 2])',
     ["True False True"]),
    ('d = {"c": 1, "a": 2}\n'
     '    d["b"] = 3\n'
     '    for k in d:\n'
     '        print(k, d[k])',
     ["c 1", "a 2", "b 3"]),
], ids=['print', 'store-and-read', 'in-dict', 'in-list',
        'insertion-order'])
def test_dict_operations(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n')
    assert (exit_code, lines) == (0, printed)

@pytest.mark.parametrize('body, msg', [
    ('    d = {"a": 1}\n    print(d["b"])\n', "key 'b' not found"),
    ('    d = {"a": 1}\n    print(d[1])\n',
     'a dict key must be str, not int'),
    ('    d = {"a": 1, "b": 2}\n    for k in d:\n        d["new"] = 1\n',
     'dict changed size during iteration'),
    ('    d = {"a": 1}\n    for k in d:\n        d["new"] = 1\n',
     'dict changed size during iteration'),
], ids=['missing-key', 'int-key', 'resized', 'resized-on-last-key'])
def test_a_dict_misuse_is_a_runtime_error(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body + '    return 0\n')
    assert info.value.msg == msg

# --- f-strings (Milestone 13) ------------------------------------------------

@pytest.mark.parametrize('statement, printed', [
    ('n = 7\n'
     '    s = "pin"\n'
     '    print(f"n={n} s={s} big={n > 5} sum={n + 1}")',
     ["n=7 s=pin big=True sum=8"]),
    ('print(f"")', [""]),
    ('print(f"text")', ["text"]),
    ('n = 7\n'
     '    s = "pin"\n'
     '    print(f"{n}{s}")',
     ["7pin"]),
    ('s = "pin"\n'
     '    print(f"[{s}]")',
     ["[pin]"]),
    ('print(f"{True} {False}")', ["True False"]),
    ('n = -3\n'
     '    print(f"{n}")',
     ["-3"]),
    ('d = {"k": 3}\n'
     '    print(f\'{d["k"]}\', f"{d[\'k\'] + 1}")',
     ["3 4"]),
    ('n = 7\n'
     '    d = {}\n'
     '    d[f"row{n}"] = n\n'
     '    print(d)',
     ["{'row7': 7}"]),
    ('n = 7\n'
     '    print(str(n) == f"{n}", str(True) == f"{True}")',
     ["True True"]),
], ids=['fields', 'empty', 'no-fields', 'adjacent-fields', 'bare-str',
        'bool', 'negative-int', 'other-quote-subscript', 'dict-key',
        'agrees-with-str'])
def test_an_fstring_puts_each_field_between_its_literals(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n')
    assert (exit_code, lines) == (0, printed)

def test_fstring_fields_are_evaluated_left_to_right():
    functions = (
        'def first() -> int:\n'
        '    print("a")\n'
        '    return 1\n'
        'def second() -> int:\n'
        '    print("b")\n'
        '    return 2\n')
    exit_code, lines = run_main_body(
        '    print(f"{first()}-{second()}")\n    return 0\n', functions)
    assert (exit_code, lines) == (0, ["a", "b", "1-2"])

@pytest.mark.parametrize('value, msg', [
    ('[1]', 'an f-string field needs an int, str, or bool, not list'),
    ('{"a": 1}', 'an f-string field needs an int, str, or bool, not dict'),
], ids=['list', 'dict'])
def test_a_non_scalar_fstring_field_is_a_runtime_error(value, msg):
    body = (
        '    if 1 == 1:\n'
        '        v = ' + value + '\n'
        '    else:\n'
        '        v = 1\n'
        '    print(f"{v}")\n'
        '    return 0\n')
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body)
    assert info.value.msg == msg

# --- augmented assignment (Milestone 14) -------------------------------------

@pytest.mark.parametrize('statement, printed', [
    ('x = 7\n'
     '    x += 3\n'
     '    x -= 1\n'
     '    x *= 2\n'
     '    x //= 4\n'
     '    x %= 3\n'
     '    print(x)',
     ["1"]),
    ('s = "a"\n'
     '    s += "b"\n'
     '    print(s)',
     ["ab"]),
    ('xs = [1, 2]\n'
     '    xs[0] += 10\n'
     '    xs[-1] += 5\n'
     '    print(xs)',
     ["[11, 7]"]),
    ('d = {"k": 1}\n'
     '    d["k"] += 2\n'
     '    print(d)',
     ["{'k': 3}"]),
], ids=['int-operators', 'str', 'list-element', 'dict-value'])
def test_augmented_assignment(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n')
    assert (exit_code, lines) == (0, printed)

PICK_AND_VAL = (
    'def pick() -> int:\n'
    '    print("pick")\n'
    '    return 0\n'
    'def val() -> int:\n'
    '    print("val")\n'
    '    return 1\n')

@pytest.mark.parametrize('statement, printed', [
    ('xs[pick()] += 1', ["pick", "[2]"]),
    ('xs[pick()] += val()', ["pick", "val", "[2]"]),
], ids=['index-once', 'index-before-value'])
def test_the_index_is_evaluated_once_and_before_the_value(
        statement, printed):
    body = ('    xs = [1]\n    ' + statement +
            '\n    print(xs)\n    return 0\n')
    exit_code, lines = run_main_body(body, PICK_AND_VAL)
    assert (exit_code, lines) == (0, printed)

def test_the_element_is_read_before_the_value_is_evaluated():
    functions = (
        'def bump(xs: list[int]) -> int:\n'
        '    xs[0] = 1000\n'
        '    return 10\n')
    exit_code, lines = run_main_body(
        '    xs = [1]\n    xs[0] += bump(xs)\n    print(xs)\n'
        '    return 0\n', functions)
    assert (exit_code, lines) == (0, ["[11]"])

def test_the_store_goes_through_the_index_value():
    functions = (
        'def grow(xs: list[int]) -> int:\n'
        '    xs.append(100)\n'
        '    return 10\n')
    exit_code, lines = run_main_body(
        '    xs = [1, 2]\n    xs[-1] += grow(xs)\n    print(xs)\n'
        '    return 0\n', functions)
    assert (exit_code, lines) == (0, ["[1, 2, 12]"])

@pytest.mark.parametrize('body, msg', [
    ('    d = {"a": 1}\n    d["b"] += 1\n', "key 'b' not found"),
    ('    xs = [1]\n    xs[3] += 1\n', 'list index out of range'),
    ('    x = 1\n    x //= 0\n', 'integer division by zero'),
], ids=['missing-key', 'index-out-of-range', 'division-by-zero'])
def test_an_augmented_assignment_misuse_is_a_runtime_error(body, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(body + '    return 0\n')
    assert info.value.msg == msg

# --- None and optional types (Milestone 16) ----------------------------------

MAYBE = ('def maybe(i: int) -> int | None:\n'
         '    if i == 1:\n'
         '        return None\n'
         '    return i\n')

@pytest.mark.parametrize('statement, printed', [
    ('x = None\n    print(x)', ['None']),
    ('x = None\n    print(x is None, x is not None)', ['True False']),
    ('print(maybe(1) is None, maybe(2) is None)', ['True False']),
    ('print(1 is None, "a" is not None, [1] is None)',
     ['False True False']),
    ('print(None is None, not None is None)', ['True False']),
    ('y = maybe(2)\n'
     '    if y is not None:\n'
     '        print(y + 1)', ['3']),
    ('y = maybe(1)\n'
     '    if y is None:\n'
     '        y = 0\n'
     '    print(y + 1)', ['1']),
], ids=['literal', 'is', 'call', 'other-values', 'none-itself',
        'narrowed', 'defaulted'])
def test_none_and_is(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n', MAYBE)
    assert (exit_code, lines) == (0, printed)

def test_the_operand_of_is_is_evaluated_once():
    functions = ('def val() -> int | None:\n'
                 '    print("val")\n'
                 '    return None\n')
    exit_code, lines = run_main_body(
        '    print(val() is not None)\n    return 0\n', functions)
    assert (exit_code, lines) == (0, ['val', 'False'])

# --- Tuples (Milestone 17) ---------------------------------------------------

ONE_AND_TWO = ('def one() -> int:\n'
               '    print("one")\n'
               '    return 1\n'
               'def two() -> int:\n'
               '    print("two")\n'
               '    return 2\n')
EITHER_TUPLE = ('    if 1 == 1:\n'
                '        x = (1, 2, 3)\n'
                '    else:\n'
                '        x = (1, 2)\n')

@pytest.mark.parametrize('statement, printed', [
    ('print(("a", True, 3), (1, "b"))', ["('a', True, 3) (1, 'b')"]),
    ('a, b = (1, "x")\n    print(a, b)', ['1 x']),
    ('a, b = (one(), two())\n    print(a, b)', ['one', 'two', '1 2']),
    ('a, b = (1, 2)\n    b, a = (a, b)\n    print(a, b)', ['2 1']),
    ('t = (1, "x", True)\n    print(t[0], t[-1], t[1])', ['1 True x']),
    ('t = (1, 2)\n    u = t\n    print(u, t is None)',
     ['(1, 2) False']),
], ids=['printed', 'unpack', 'left-to-right', 'swap', 'index',
        'shared'])
def test_tuples(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n', ONE_AND_TWO)
    assert (exit_code, lines) == (0, printed)

def test_a_tuple_of_unknown_type_is_indexed_by_a_computed_int():
    exit_code, lines = run_main_body(
        EITHER_TUPLE + '    i = 1\n    print(x[i], x[-1])\n    return 0\n')
    assert (exit_code, lines) == (0, ['2 3'])

@pytest.mark.parametrize('statement, msg', [
    ('a, b = x', 'too many values to unpack (expected 2, got 3)'),
    ('a, b, c, d = x',
     'not enough values to unpack (expected 4, got 3)'),
    ('a, b = x[0]', 'cannot unpack int; the value must be a tuple'),
    ('print(x[3])', 'tuple index out of range'),
    ('print(x[-4])', 'tuple index out of range'),
    ('x[0] = 1', "'tuple' object does not support item assignment"),
    ('x[0] += 1', "'tuple' object does not support item assignment"),
    ('print(x == x)',
     'unsupported operand types for ==: tuple and tuple'),
], ids=['too-many', 'too-few', 'not-a-tuple', 'past-end',
        'before-start', 'store', 'augmented-store', 'equality'])
def test_a_tuple_misuse_is_a_runtime_error(statement, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(EITHER_TUPLE + '    ' + statement
                      + '\n    return 0\n')
    assert info.value.msg == msg

# --- Data classes (Milestone 19) ---------------------------------------------

POINT = ('@dataclass\nclass Point:\n    x: int\n    tag: str = "p"\n'
         '    seen: list[int] = []\n    on: bool = False\n')
EITHER_POINT = ('    if 1 == 1:\n        p = Point(1)\n'
                '    else:\n        p = 1\n')

@pytest.mark.parametrize('statement, printed', [
    ('print(Point(1), Point(2, "q", [3], True))',
     ["Point(x=1, tag='p', seen=[], on=False) "
      "Point(x=2, tag='q', seen=[3], on=True)"]),
    ('p = Point(1)\n    p.x += 2\n    p.on = True\n    print(p.x, p.on)',
     ['3 True']),
    ('p = Point(1)\n    q = p\n    q.x = 5\n    print(p.x)', ['5']),
    ('p = Point(1)\n    q = Point(2)\n    p.seen.append(7)\n'
     '    print(p.seen, q.seen)', ['[7] []']),
    ('ps = [Point(1), Point(2)]\n    for p in ps:\n        p.x *= 10\n'
     '    print(ps)',
     ["[Point(x=10, tag='p', seen=[], on=False), "
      "Point(x=20, tag='p', seen=[], on=False)]"]),
    ('d = {"a": Point(1)}\n    p = d["a"]\n    print(p.tag, d)',
     ["p {'a': Point(x=1, tag='p', seen=[], on=False)}"]),
    ('p = Point(1)\n    print(p is None, [p] == [1])',
     ['False False']),
], ids=['repr', 'store', 'shared', 'default-per-instance', 'list',
        'dict', 'against-a-scalar'])
def test_a_data_class_instance(statement, printed):
    exit_code, lines = run_main_body(
        '    ' + statement + '\n    return 0\n', POINT)
    assert (exit_code, lines) == (0, printed)

@pytest.mark.parametrize('statement, msg', [
    ('print(p == p)',
     'unsupported operand types for ==: Point and Point'),
    ('print([p] == [p])',
     'unsupported operand types for ==: Point and Point'),
    ('print(p in [p])',
     'unsupported operand types for ==: Point and Point'),
    ('print(p.nope)', "data class 'Point' has no field 'nope'"),
    ('p = Point()', "Point() needs a value for field 'x'"),
    ('p = Point(1, "a", [], True, 2)',
     'Point() takes 4 arguments (5 given)'),
    ('p = 1\n    print(p.x)',
     "'p' is not an except binding, a handler instance, or a data "
     'class instance'),
], ids=['equality', 'list-equality', 'in', 'no-field', 'too-few',
        'too-many', 'field-of-int'])
def test_a_data_class_misuse_is_a_runtime_error(statement, msg):
    with pytest.raises(EffectPythonRuntimeError) as info:
        run_main_body(EITHER_POINT + '    ' + statement
                      + '\n    return 0\n', POINT)
    assert info.value.msg == msg
