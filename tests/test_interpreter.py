"""Milestone 1 acceptance: the evaluator runs a recursive Fibonacci.

Run with:  pypy2 -m pytest
These tests import no RPython modules, so they need no PYTHONPATH.
"""
import pytest

from effectpython import ast_nodes as ast
from effectpython.errors import EffectPythonRuntimeError
from effectpython.interpreter import Interpreter, Output
from effectpython.model import W_Int, W_Str, W_None, w_None
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
