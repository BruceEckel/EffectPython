"""The AST evaluator (plan Milestone 1).

eval_expr returns a W_Root for every expression; exec_stmt runs one
statement. A return statement unwinds to the enclosing call through
ReturnSignal, an RPython exception. Each call gets a fresh Environment, so
locals are lexically scoped to the call that created them.

Dispatch is by isinstance over the node classes in ast_nodes. The checker
will walk the same classes the same way.
"""
import os

from effectpython import ast_nodes as ast
from effectpython.errors import EffectPythonRuntimeError
from effectpython.model import (W_Root, W_Int, W_Str, W_Bool,
                                w_None, wrap_bool)

class Environment(object):
    """One lexical scope: a name -> W_Root table with an optional parent."""

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def lookup(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise EffectPythonRuntimeError("name '%s' is not defined" % name)

    def define(self, name, w_value):
        self.vars[name] = w_value

class Output(object):
    """Where print() writes. The default writes to file descriptor 1, which
    behaves the same untranslated and translated; tests substitute a
    subclass that collects lines."""

    def write_line(self, text):
        os.write(1, text + "\n")

class ReturnSignal(Exception):
    def __init__(self, w_value):
        self.w_value = w_value

class Interpreter(object):

    def __init__(self, module, output=None):
        self.functions = {}
        for fn in module.functions:
            self.functions[fn.name] = fn
        if output is None:
            output = Output()
        self.output = output

    # --- entry points ------------------------------------------------------

    def run_main(self):
        """Call main() and return its result as the process exit code."""
        if "main" not in self.functions:
            raise EffectPythonRuntimeError("no main() function defined")
        w_result = self.call_function(self.functions["main"], [])
        if isinstance(w_result, W_Int):
            return w_result.val
        return 0

    def call_function(self, fn, args_w):
        if len(args_w) != len(fn.params):
            raise EffectPythonRuntimeError(
                "%s() takes %d arguments (%d given)" %
                (fn.name, len(fn.params), len(args_w)))
        env = Environment()
        for i in range(len(fn.params)):
            env.define(fn.params[i], args_w[i])
        try:
            self.exec_block(fn.body, env)
        except ReturnSignal as sig:
            return sig.w_value
        return w_None

    # --- statements --------------------------------------------------------

    def exec_block(self, stmts, env):
        for stmt in stmts:
            self.exec_stmt(stmt, env)

    def exec_stmt(self, stmt, env):
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                raise ReturnSignal(w_None)
            raise ReturnSignal(self.eval_expr(stmt.value, env))
        elif isinstance(stmt, ast.If):
            if self.eval_expr(stmt.test, env).is_true():
                self.exec_block(stmt.body, env)
            else:
                self.exec_block(stmt.orelse, env)
        elif isinstance(stmt, ast.Assign):
            env.define(stmt.name, self.eval_expr(stmt.value, env))
        elif isinstance(stmt, ast.ExprStmt):
            self.eval_expr(stmt.expr, env)
        else:
            raise EffectPythonRuntimeError("unknown statement node")

    # --- expressions -------------------------------------------------------

    def eval_expr(self, expr, env):
        if isinstance(expr, ast.IntLiteral):
            return W_Int(expr.value)
        elif isinstance(expr, ast.StrLiteral):
            return W_Str(expr.value)
        elif isinstance(expr, ast.Name):
            return env.lookup(expr.id)
        elif isinstance(expr, ast.BinOp):
            w_left = self.eval_expr(expr.left, env)
            w_right = self.eval_expr(expr.right, env)
            return self.binop(expr.op, w_left, w_right)
        elif isinstance(expr, ast.Compare):
            w_left = self.eval_expr(expr.left, env)
            w_right = self.eval_expr(expr.right, env)
            return self.compare(expr.op, w_left, w_right)
        elif isinstance(expr, ast.Call):
            args_w = []
            for arg in expr.args:
                args_w.append(self.eval_expr(arg, env))
            return self.call(expr.func, args_w)
        else:
            raise EffectPythonRuntimeError("unknown expression node")

    def call(self, name, args_w):
        if name == "print":
            parts = []
            for w in args_w:
                parts.append(w.str())
            self.output.write_line(" ".join(parts))
            return w_None
        if name in self.functions:
            return self.call_function(self.functions[name], args_w)
        raise EffectPythonRuntimeError("name '%s' is not defined" % name)

    # --- operators ---------------------------------------------------------

    def binop(self, op, w_left, w_right):
        if isinstance(w_left, W_Int) and isinstance(w_right, W_Int):
            a = w_left.val
            b = w_right.val
            if op == "+":
                return W_Int(a + b)
            elif op == "-":
                return W_Int(a - b)
            elif op == "*":
                return W_Int(a * b)
            elif op == "//":
                if b == 0:
                    raise EffectPythonRuntimeError("integer division by zero")
                return W_Int(a // b)
            elif op == "%":
                if b == 0:
                    raise EffectPythonRuntimeError("integer modulo by zero")
                return W_Int(a % b)
        elif isinstance(w_left, W_Str) and isinstance(w_right, W_Str):
            if op == "+":
                return W_Str(w_left.val + w_right.val)
        raise EffectPythonRuntimeError(
            "unsupported operand types for %s: %s and %s" %
            (op, type_name(w_left), type_name(w_right)))

    def compare(self, op, w_left, w_right):
        if isinstance(w_left, W_Int) and isinstance(w_right, W_Int):
            a = w_left.val
            b = w_right.val
            if op == "<":
                return wrap_bool(a < b)
            elif op == "<=":
                return wrap_bool(a <= b)
            elif op == ">":
                return wrap_bool(a > b)
            elif op == ">=":
                return wrap_bool(a >= b)
            elif op == "==":
                return wrap_bool(a == b)
            elif op == "!=":
                return wrap_bool(a != b)
        elif isinstance(w_left, W_Str) and isinstance(w_right, W_Str):
            if op == "==":
                return wrap_bool(w_left.val == w_right.val)
            elif op == "!=":
                return wrap_bool(w_left.val != w_right.val)
        raise EffectPythonRuntimeError(
            "unsupported operand types for %s: %s and %s" %
            (op, type_name(w_left), type_name(w_right)))

def type_name(w):
    if isinstance(w, W_Int):
        return "int"
    elif isinstance(w, W_Str):
        return "str"
    elif isinstance(w, W_Bool):
        return "bool"
    return "object"
