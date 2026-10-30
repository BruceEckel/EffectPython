"""The AST evaluator (plan Milestone 1).

eval_expr returns a W_Root for every expression; exec_stmt runs one
statement. A return statement unwinds to the enclosing call through
ReturnSignal, an RPython exception. Each call gets a fresh Environment, so
locals are lexically scoped to the call that created them.

Dispatch is by isinstance over the node classes in ast_nodes. The checker
walks the same classes the same way.

The effect runtime (plan 3.3 and 3.4) runs each handle statement's body
in its own stacklet. A HandlerFrame is the mailbox between the two
sides, since a stacklet switch carries no value: perform() stores the
payload and switches to the handler side, which runs the matching
clause; eff.resume() stores the value and switches back. The body is a
suite, so eff.resume() evaluates to None once the body finishes. An
exception the body raises is stored in the frame and re-raised on the
handler side inside the eff.resume() call that resumed it, or at the
handle statement if the body never performed, so the rest of the
clause does not run. A clause runs in the function's own environment
with its binding defined for the clause's duration and removed
afterwards, as Python does for `except ... as e`, so a clause that
runs nested inside another clause's resume() cannot overwrite the
outer clause's binding. A clause whose last statement is a resume()
on its own binding does not nest: dispatch() switches into the body
from its loop, so any number of sequential performs handled that way
use constant stack.

rstacklet runs only translated, so the import below is guarded: the
unit tests import this module without RPython on the path and never
execute a handle statement. Every runtime error that depends on it
goes through the translated binary, in tests/test_runtime.py.

Some EffectPythonRuntimeError branches below are unreachable from the
translated binary, because checker.py rejects the program first: a call
to a function that does not exist (check_call), a call with the wrong
number of arguments (check_args), a module without main()
(check_entry_point), a perform() with no handler in scope, a clause
binding read where none is bound, and an eff.<attr> naming no
parameter. They stay because the unit tests build modules by hand and
run them without the checker. The cases the checker does not
see remain runtime-only: a variable that was never assigned (the checker
types an unbound name as UNKNOWN), an operator applied to operands of
the wrong types (the checker infers types only as far as argument checks
need), and integer division or modulo by zero.
"""
import os
try:
    from rpython.rlib import rstacklet
    from rpython.rtyper.lltypesystem import llmemory
except ImportError:
    rstacklet = llmemory = None
from effectpython import ast_nodes as ast
from effectpython.errors import (EffectError, EffectPythonRuntimeError,
                                 OneShotContinuationError)
from effectpython.model import (W_Root, W_Int, W_Str, W_Bool,
                                W_EffectPayload, W_EffBinding,
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

STATUS_RUNNING = 0
STATUS_SUSPENDED = 1
STATUS_COMPLETED = 2

class HandlerFrame(object):
    """One active handle statement: what it handles, where its clauses
    run, and the mailbox the body and handler sides share (plan 3.3)."""

    def __init__(self, stmt, env, sthread):
        self.stmt = stmt  # ast.Handle: the effects and clauses
        self.env = env
        self.h_handler = sthread.get_null_handle()
        self.status = STATUS_RUNNING
        self.pending_payload = None  # W_EffectPayload set by perform()
        self.resume_value = None     # W_Root set by eff.resume()
        self.pending_error = None    # EffectError the body raised
        self.pending_return = None   # ReturnSignal the body raised
        self.saved_frames = []       # hidden while a clause runs

    def handles(self, effect_name):
        return effect_name in self.stmt.effects

    def clause_for(self, payload):
        for clause in self.stmt.clauses:
            if (clause.effect == payload.effect_name and
                    clause.op == payload.op_name):
                return clause
        raise EffectPythonRuntimeError(
            "no clause for %s.%s" % (payload.effect_name, payload.op_name))

class GlobalState(object):
    """Carries the interpreter and the frame into run_body_callback,
    whose only argument is a raw address (plan 3.2, rule 4)."""

    def __init__(self):
        self.interp = None
        self.frame = None

global_state = GlobalState()

def run_body_callback(h, arg):
    frame = global_state.frame
    interp = global_state.interp
    frame.h_handler = h
    try:
        interp.exec_block(frame.stmt.body, frame.env)
    except EffectError as e:
        frame.pending_error = e
    except ReturnSignal as sig:
        frame.pending_return = sig
    frame.status = STATUS_COMPLETED
    return frame.h_handler

class Interpreter(object):

    def __init__(self, module, output=None):
        self.functions = {}
        for fn in module.functions:
            self.functions[fn.name] = fn
        self.operations = {}
        for effect in module.effects:
            for op in effect.operations:
                self.operations[effect.name + "." + op.name] = op
        if output is None:
            output = Output()
        self.output = output
        self.sthread = None  # created by the first handle statement
        self.handler_stack = []

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
        elif isinstance(stmt, ast.While):
            while self.eval_expr(stmt.test, env).is_true():
                self.exec_block(stmt.body, env)
        elif isinstance(stmt, ast.Assign):
            env.define(stmt.name, self.eval_expr(stmt.value, env))
        elif isinstance(stmt, ast.ExprStmt):
            self.eval_expr(stmt.expr, env)
        elif isinstance(stmt, ast.Handle):
            self.exec_handle(stmt, env)
        elif isinstance(stmt, ast.Pass):
            pass
        else:
            raise EffectPythonRuntimeError("unknown statement node")

    # --- effects (plan 3.4) --------------------------------------------------

    def exec_handle(self, stmt, env):
        """Step 1: run the body in a new stacklet and dispatch whatever
        comes back. The frame is popped once the body has completed;
        a clause that abandons the body leaves it hidden by perform()."""
        if self.sthread is None:
            self.sthread = rstacklet.StackletThread()
        frame = HandlerFrame(stmt, env, self.sthread)
        self.handler_stack.append(frame)
        global_state.interp = self
        global_state.frame = frame
        h = self.sthread.new(run_body_callback, llmemory.NULL)
        try:
            self.dispatch(frame, h)
        finally:
            if frame.status == STATUS_COMPLETED:
                self.handler_stack.pop()

    def dispatch(self, frame, h):
        """Step 3: run the clause for each payload the body performs,
        with its binding in scope, until the handle that comes back is
        empty; then surface what the body left in the mailbox. A clause
        that ends with eff.resume(...) on its own binding switches into
        the body from this loop, so sequential performs handled that
        way do not nest on the C stack. A resume() anywhere else runs
        nested through resume()."""
        while not self.sthread.is_empty_handle(h):
            payload = frame.pending_payload
            clause = frame.clause_for(payload)
            tail = tail_resume(clause)
            w_eff = W_EffBinding(payload, frame, h)
            env = frame.env
            name = clause.binding
            had_name = name in env.vars
            w_old = env.vars.get(name, None)
            env.define(name, w_eff)
            w_value = w_None
            try:
                count = len(clause.body)
                if tail is not None:
                    count -= 1
                for i in range(count):
                    self.exec_stmt(clause.body[i], env)
                if tail is not None:
                    w_value = self.eval_expr(tail.value, env)
            finally:
                if had_name:
                    env.vars[name] = w_old
                else:
                    del env.vars[name]
            if tail is None:
                return
            h = self.switch_into(w_eff, w_value)
        error = frame.pending_error
        if error is not None:
            raise error
        signal = frame.pending_return
        if signal is not None:
            raise signal

    def perform(self, effect_name, op_name, args_w):
        """Step 2: hide the handling frame and everything above it,
        mail the payload, and switch to the handler side. When a
        resume() switches back, restore the frames and return its value."""
        i = len(self.handler_stack) - 1
        while i >= 0 and not self.handler_stack[i].handles(effect_name):
            i -= 1
        if i < 0:
            raise EffectPythonRuntimeError(
                "no handler for %s.%s" % (effect_name, op_name))
        frame = self.handler_stack[i]
        frame.saved_frames = self.handler_stack[i:]
        del self.handler_stack[i:]
        frame.pending_payload = W_EffectPayload(effect_name, op_name, args_w)
        frame.status = STATUS_SUSPENDED
        frame.h_handler = self.sthread.switch(frame.h_handler)
        self.handler_stack.extend(frame.saved_frames)
        frame.saved_frames = []
        w_value = frame.resume_value
        frame.resume_value = None
        return w_value

    def switch_into(self, w_eff, w_value):
        """Step 4: consume the one-shot handle and switch into the body.
        Returns the handle that comes back when the body performs again
        or finishes."""
        if self.sthread.is_empty_handle(w_eff.h_body):
            raise OneShotContinuationError(
                "Cannot resume a suspended body more than once")
        frame = w_eff.frame
        h = w_eff.h_body
        w_eff.h_body = self.sthread.get_null_handle()
        frame.resume_value = w_value
        frame.status = STATUS_RUNNING
        return self.sthread.switch(h)

    def resume(self, w_eff, w_value):
        """eff.resume(...) anywhere but a clause's tail: switch into the
        body and dispatch what it does next, nested in this call."""
        h = self.switch_into(w_eff, w_value)
        self.dispatch(w_eff.frame, h)
        return w_None

    def read_attr(self, w_eff, attr):
        """eff.path: the performed operation's argument in the position
        of the parameter named attr (plan 3.1)."""
        payload = w_eff.payload
        op = self.operations[payload.effect_name + "." + payload.op_name]
        for i in range(len(op.params)):
            if op.params[i] == attr:
                return payload.args_w[i]
        raise EffectPythonRuntimeError(
            "operation %s.%s has no parameter '%s'" %
            (payload.effect_name, payload.op_name, attr))

    def binding(self, env, target):
        w_target = env.lookup(target)
        if isinstance(w_target, W_EffBinding):
            return w_target
        raise EffectPythonRuntimeError(
            "'%s' is not bound by an except clause" % target)

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
        elif isinstance(expr, ast.Perform):
            args_w = []
            for arg in expr.args:
                args_w.append(self.eval_expr(arg, env))
            return self.perform(expr.effect, expr.op, args_w)
        elif isinstance(expr, ast.OpCall):
            args_w = []
            for arg in expr.args:
                args_w.append(self.eval_expr(arg, env))
            return W_EffectPayload(expr.effect, expr.op, args_w)
        elif isinstance(expr, ast.AttrRead):
            return self.read_attr(self.binding(env, expr.target), expr.attr)
        elif isinstance(expr, ast.Resume):
            w_value = self.eval_expr(expr.value, env)
            return self.resume(self.binding(env, expr.target), w_value)
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

def tail_resume(clause):
    """The Resume node when the clause's last statement is
    eff.resume(...) on the clause's own binding, else None."""
    if len(clause.body) == 0:
        return None
    last = clause.body[len(clause.body) - 1]
    if isinstance(last, ast.ExprStmt):
        expr = last.expr
        if isinstance(expr, ast.Resume) and expr.target == clause.binding:
            return expr
    return None

def type_name(w):
    if isinstance(w, W_Int):
        return "int"
    elif isinstance(w, W_Str):
        return "str"
    elif isinstance(w, W_Bool):
        return "bool"
    return "object"
