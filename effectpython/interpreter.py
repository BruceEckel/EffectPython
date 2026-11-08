"""The AST evaluator (plan Milestone 1).

eval_expr returns a W_Root for every expression; exec_stmt runs one
statement. A return statement unwinds to the enclosing call through
ReturnSignal, an RPython exception, and break and continue unwind to
the enclosing loop's exec_pass through BreakSignal and ContinueSignal
(plan 1.10); the three share the base ControlSignal, which is what
the handler runtime looks for. Each call gets a fresh Environment, so
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
handle statement if the body never performed or was last resumed
from the dispatch loop (a tail resume, a tail throw, or a handler
method), so the rest of the clause does not run. A clause runs in the
function's own environment with its binding defined for the clause's
duration. Afterwards the binding is restored to its earlier value, or
removed when it had none, which is not what Python does for
`except ... as e`. The restore keeps a clause that runs nested inside
another clause's resume() from overwriting the outer clause's
binding. The checker mirrors this (check_effect_clause). A clause
whose last statement is a resume() on its own binding does not nest:
dispatch() switches into the body from its loop, so any number of
sequential performs handled that way use constant stack.

A handler class (plan 1.5) adds no mechanism to that. A handle
statement evaluates its constructor calls and looks up its instance
names before installing the frame, and the frame maps each fulfilled
effect to its W_HandlerInstance. When the body performs an operation
of a fulfilled effect, dispatch() calls the method as a function with
the instance as self and the payload's arguments, and switches into
the body with the returned value along the tail-resume path, so a
method cannot resume the body twice, and it abandons the body by
raising an exception the operation's row does not name.

Exceptions (plan 1.6) need one mechanism, RaisedException, an
EffectError that carries the W_Exception. A raise statement raises
it, and a Try statement catches it around its suite and runs the
first clause that names the exception's class or Exception. The four
meetings with the handlers follow from where the RPython exception
travels. Raised in a handled body, it takes the path of any body
error: through the frame to the handler side, and out of the handle
statement or the enclosing resume(). Raised in a clause or a handler
method, it leaves dispatch() and the handle statement after the body
is unwound (plan 1.8, below), unless a method raises a class its
operation declares, which is thrown into the body (plan 1.7, below).
A Try inside the body sits on the body's stack slice, which the
stacklet keeps across a perform, so it catches what the body raises
after a resume. It does not catch what a clause or method raises,
because that exception travels on the handler side, unless a method
raises a class its operation declares, which plan 1.7 below delivers
at the perform site.

eff.throw(exc) (plan 1.7) is the second way to switch into the body:
switch_into() stores the exception in the frame instead of a value,
and perform() raises it when the switch returns, so the exception
starts on the body's stack at the perform site and a Try around the
perform catches it. A handler method whose operation declares the
class delivers its exception the same way (answer_with_method). A
tail eff.throw(...) switches from the dispatch loop as a tail resume
does, and any other eff.throw(...) nests through throw().

Abandoning a body (plan 1.8) is the third way to switch into it. A
clause that ends without resuming, a return, break, or continue that
leaves a clause, and an exception that leaves a clause or a method
with the body still suspended all unwind it: the dispatch loop switches in with an
Unwind, an EffectError the dialect cannot name, and perform() raises
it, so it runs every finally suite on the way out of the body's
stacklet while no except clause can catch it. exec_try runs its
finally under an RPython try/finally, so a finally that performs is
answered by the same loop, and one that raises an exception or
returns replaces the unwinding, as Python's does. The body therefore
always runs to completion; when the loop finds its own Unwind in the
mailbox it swallows it, and another frame's Unwind it re-raises,
which carries an outer abandonment through every body nested inside
the abandoned one.

Lists and the for loop (plan 1.9) add values, not mechanism. A W_List
is shared by reference, so exec_for walks the one the iterable
evaluates to by index against its live length, and a clause that
appends to that list while the body is suspended lengthens the walk.
A for over range() is a ForRange the parser folds, and counts in an
RPython local. xs.append(v) on a name is the OpCall the parser builds
for Effect.op(...), told apart by the name being bound, since an
effect is never a value; on any other expression it is a MethodCall.
len(), str(), and range() are Call nodes recognized by name, as
print is. A field default is evaluated per construction, so the [] a
list field declares gives each instance a list of its own.

rstacklet runs only translated, so the import below is guarded: the
unit tests import this module without RPython on the path and never
execute a handle statement. Every runtime error that depends on it
goes through the translated binary, in tests/test_runtime.py.

Some EffectPythonRuntimeError branches below are unreachable from the
translated binary, because checker.py rejects the program first: a call
to a function that does not exist (check_call), a call with the wrong
number of arguments (check_args), a module without main()
(check_entry_point), a perform() with no handler in scope, a clause
binding read where none is bound, an eff.<attr> naming no parameter,
and the handler instance errors: a constructor call with too few or
too many arguments (check_construction, in HandlerClass.construct),
a field assigned on a name that holds no instance (require_instance,
in Interpreter.instance), a field the class does not declare
(require_field, in field_index), and a handle() argument that is not
an instance or that fulfills an effect another argument fulfills
(check_handle, in install); and the exception errors: a raise of a
value that is not an exception (check_raise), an exception
constructor call with more than a str message where the checker knows
the argument's type (check_exception_call, in construct_exception),
and a RaisedException that reaches entry_point, since main()'s empty
row makes the checker reject an exception nobody catches; and an
operator on operands of the wrong types where the checker knows both
types (check_operands, in binop and compare); and the list errors on
a value the checker typed: a subscript, an append, or a for on a
value that is not a list (list_value), a non-integer index
(list_index), a method other than append (list_method), and a
built-in with the wrong argument (builtin), plus range() outside a
for (call). The claims hold where the checker knows the value's type;
a name an if leaves with two types, or a [] nothing appended to, has
the unknown type and reaches these branches as any untyped value does
(check_if, 2026-11-07). The branches stay because the unit tests
build modules by hand and run them without the checker. The cases the
checker does not see remain runtime-only: a read of a name whose
assignment comes earlier in the source but did not run, because it
sits in a loop body that ran zero times or in one branch of an if,
and a read of a name an except clause deleted where the read comes
earlier in the source (require_bound follows source order), an operator
applied to operands of the wrong types where one operand's type is
unknown (the checker infers types only as far as argument checks
need), integer division or modulo by zero, a list index out of
range, and a recursion that outgrows the C stack, which RPython's
stack check stops and run_body_callback or the entry point reports
as "maximum recursion depth exceeded".
"""
import os
try:
    from rpython.rlib import rstacklet, rstackovf
    from rpython.rtyper.lltypesystem import llmemory
except ImportError:
    rstacklet = rstackovf = llmemory = None
from effectpython import ast_nodes as ast
from effectpython.errors import (EffectError, EffectPythonRuntimeError,
                                 OneShotContinuationError, RaisedException,
                                 Unwind)
from effectpython.model import (W_Root, W_Int, W_Str, W_Bool, W_List,
                                W_EffectPayload, W_EffBinding,
                                W_Exception, W_HandlerInstance, w_None,
                                wrap_bool)

class Environment(object):
    """One lexical scope: a name -> W_Root table with an optional parent."""

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def find(self, name):
        env = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        return None

    def lookup(self, name):
        w_value = self.find(name)
        if w_value is None:
            raise EffectPythonRuntimeError(
                "name '%s' is not defined" % name)
        return w_value

    def define(self, name, w_value):
        self.vars[name] = w_value

class Output(object):
    """Where print() writes. The default writes to file descriptor 1, which
    behaves the same untranslated and translated; tests substitute a
    subclass that collects lines."""

    def write_line(self, text):
        os.write(1, text + "\n")

class ControlSignal(Exception):
    """A statement that leaves the block it is in: return, break, or
    continue. The handler runtime carries one out of a body's
    stacklet and treats one leaving a clause as an abandonment, with
    no regard for which of the three it is."""

class ReturnSignal(ControlSignal):
    def __init__(self, w_value):
        self.w_value = w_value

class BreakSignal(ControlSignal):
    pass

class ContinueSignal(ControlSignal):
    pass

STATUS_RUNNING = 0
STATUS_SUSPENDED = 1
STATUS_COMPLETED = 2

class HandlerClass(object):
    """A handler class as the interpreter records it: the fields with
    their defaults, the method for each operation, and the effect its
    instances fulfill (plan 1.5)."""

    def __init__(self, node):
        self.name = node.name
        self.effect = node.effect
        self.field_names = []
        self.defaults = []  # the default Expr or None, parallel to it
        for field in node.fields:
            self.field_names.append(field.name)
            self.defaults.append(field.default)
        self.methods = {}
        for method in node.methods:
            self.methods[method.name] = method

    def construct(self, args_w):
        """Each default is evaluated afresh per construction, so two
        instances with a list field hold two lists (plan 1.9)."""
        fields_w = []
        for i in range(len(self.field_names)):
            if i < len(args_w):
                fields_w.append(args_w[i])
            elif self.defaults[i] is not None:
                fields_w.append(default_value(self.defaults[i]))
            else:
                raise EffectPythonRuntimeError(
                    "%s() needs a value for field '%s'" %
                    (self.name, self.field_names[i]))
        if len(args_w) > len(self.field_names):
            raise EffectPythonRuntimeError(
                "%s() takes %d arguments (%d given)" %
                (self.name, len(self.field_names), len(args_w)))
        return W_HandlerInstance(self.name, self.field_names, fields_w)

def default_value(expr):
    """The value of a field default: an int or str literal, or the []
    the parser allows for a list field."""
    if isinstance(expr, ast.IntLiteral):
        return W_Int(expr.value)
    elif isinstance(expr, ast.StrLiteral):
        return W_Str(expr.value)
    assert isinstance(expr, ast.ListLiteral)
    return W_List([])

class HandlerFrame(object):
    """One active handle statement: what it handles, where its clauses
    run, the handler instances that fulfill its effects, and the
    mailbox the body and handler sides share (plan 3.3)."""

    def __init__(self, stmt, env, sthread, instances_w):
        self.stmt = stmt  # ast.Handle: the effects and clauses
        self.env = env
        self.instances_w = instances_w  # effect name -> W_HandlerInstance
        self.h_handler = sthread.get_null_handle()
        self.status = STATUS_RUNNING
        self.pending_payload = None  # W_EffectPayload set by perform()
        self.resume_value = None     # W_Root set by eff.resume()
        self.resume_exception = None # W_Exception set by eff.throw()
        self.resume_unwind = None    # Unwind set when the body is abandoned
        self.pending_error = None    # EffectError the body raised
        self.pending_return = None   # ControlSignal the body raised
        self.saved_frames = []       # hidden while a clause runs

    def handles(self, effect_name):
        return (effect_name in self.stmt.effects
                or effect_name in self.instances_w)

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

RECURSION_LIMIT = "maximum recursion depth exceeded"

def run_body_callback(h, arg):
    """Run the body and leave what ended it in the frame. RPython's
    stack check raises StackOverflow in a body that recurses too deep,
    and it becomes a runtime error here: an RPython exception that
    escaped this callback would hand the stacklet code a garbage
    handle, and the binary would segfault instead of reporting it."""
    frame = global_state.frame
    interp = global_state.interp
    frame.h_handler = h
    try:
        interp.exec_block(frame.stmt.body, frame.env)
    except EffectError as e:
        frame.pending_error = e
    except ControlSignal as sig:
        frame.pending_return = sig
    except rstackovf.StackOverflow:
        rstackovf.check_stack_overflow()
        frame.pending_error = EffectPythonRuntimeError(RECURSION_LIMIT)
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
        self.handlers = {}
        for handler in module.handlers:
            self.handlers[handler.name] = HandlerClass(handler)
        self.exceptions = {}
        for exc in module.exceptions:
            self.exceptions[exc.name] = exc
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
        except ControlSignal:
            raise EffectPythonRuntimeError("break or continue outside a loop")
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
                if self.exec_pass(stmt.body, env):
                    break
        elif isinstance(stmt, ast.Break):
            raise BreakSignal()
        elif isinstance(stmt, ast.Continue):
            raise ContinueSignal()
        elif isinstance(stmt, ast.Assign):
            env.define(stmt.name, self.eval_expr(stmt.value, env))
        elif isinstance(stmt, ast.AttrAssign):
            w_target = self.instance(env, stmt.target)
            i = self.field_index(w_target, stmt.attr)
            w_target.fields_w[i] = self.eval_expr(stmt.value, env)
        elif isinstance(stmt, ast.IndexAssign):
            w_value = self.eval_expr(stmt.value, env)
            w_list = list_value(self.eval_expr(stmt.target, env))
            i = list_index(w_list, self.eval_expr(stmt.index, env))
            w_list.items_w[i] = w_value
        elif isinstance(stmt, ast.For):
            self.exec_for(stmt, env)
        elif isinstance(stmt, ast.ForRange):
            self.exec_for_range(stmt, env)
        elif isinstance(stmt, ast.ExprStmt):
            self.eval_expr(stmt.expr, env)
        elif isinstance(stmt, ast.Handle):
            self.exec_handle(stmt, env)
        elif isinstance(stmt, ast.Raise):
            w_value = self.eval_expr(stmt.value, env)
            raise RaisedException(exception_value(w_value, "raise"))
        elif isinstance(stmt, ast.Try):
            self.exec_try(stmt, env)
        elif isinstance(stmt, ast.Pass):
            pass
        else:
            raise EffectPythonRuntimeError("unknown statement node")

    def exec_for(self, stmt, env):
        """Walk the list by index against its live length, as Python
        does, so an append in the suite lengthens the walk; the name
        keeps the last element afterwards (plan 1.9). The index is a
        local of this call, so a perform in the suite suspends the
        loop where it is."""
        w_list = list_value(self.eval_expr(stmt.iterable, env))
        i = 0
        while i < len(w_list.items_w):
            env.define(stmt.name, w_list.items_w[i])
            if self.exec_pass(stmt.body, env):
                break
            i += 1

    def exec_for_range(self, stmt, env):
        """Count from start, or 0, up to stop without building a list."""
        args_w = []
        for arg in stmt.args:
            args_w.append(self.eval_expr(arg, env))
        stop = int_value(args_w[len(args_w) - 1], "range()")
        i = 0
        if len(args_w) == 2:
            i = int_value(args_w[0], "range()")
        while i < stop:
            env.define(stmt.name, W_Int(i))
            if self.exec_pass(stmt.body, env):
                break
            i += 1

    def exec_pass(self, body, env):
        """One pass of a loop's suite: True when a break ended it, so
        the loop stops; a continue ends the pass and the loop goes on
        (plan 1.10). Either signal crosses a try through exec_try's
        finally, and a handle statement through its frame."""
        try:
            self.exec_block(body, env)
        except BreakSignal:
            return True
        except ContinueSignal:
            pass
        return False

    def exec_try(self, stmt, env):
        """Run the suite and the clause that catches what it raises,
        then the finally suite however the first part ended: a
        ControlSignal, a runtime error, an uncaught RaisedException,
        and an Unwind all pass through it with the finally run, and a
        return or an exception in the finally replaces them (plan 1.8).
        """
        try:
            self.exec_clauses(stmt, env)
        finally:
            self.exec_block(stmt.finalbody, env)

    def exec_clauses(self, stmt, env):
        """Run the suite; a RaisedException goes to the first clause
        that names its class or Exception, with the clause's name bound
        to the exception. The name is deleted after the clause, as
        Python 3 deletes it, so a value it held before the try does
        not come back; answer_with_clause restores eff instead. A nested
        clause that binds the same name has deleted it by then.
        Without a matching clause the exception propagates. A
        ReturnSignal and a runtime error pass through (plan 1.6)."""
        try:
            self.exec_block(stmt.body, env)
            return
        except RaisedException as e:
            raised = e
        w_exception = raised.w_exception
        clause = clause_catching(stmt, w_exception)
        if clause is None:
            raise raised
        name = clause.binding
        if name is None:
            self.exec_block(clause.body, env)
            return
        env.define(name, w_exception)
        try:
            self.exec_block(clause.body, env)
        finally:
            if name in env.vars:
                del env.vars[name]

    # --- effects (plan 3.4) --------------------------------------------------

    def exec_handle(self, stmt, env):
        """Step 1: run the body in a new stacklet and dispatch whatever
        comes back. The frame is popped once the body has completed,
        which a body that was abandoned does by unwinding."""
        instances_w = {}
        for call in stmt.constructions:
            self.install(instances_w, self.eval_expr(call, env))
        for name in stmt.instances:
            self.install(instances_w, self.instance(env, name))
        if self.sthread is None:
            self.sthread = rstacklet.StackletThread()
        frame = HandlerFrame(stmt, env, self.sthread, instances_w)
        self.handler_stack.append(frame)
        global_state.interp = self
        global_state.frame = frame
        h = self.sthread.new(run_body_callback, llmemory.NULL)
        try:
            self.dispatch(frame, h)
        finally:
            if frame.status == STATUS_COMPLETED:
                self.handler_stack.pop()

    def install(self, instances_w, w_instance):
        if not isinstance(w_instance, W_HandlerInstance):
            raise EffectPythonRuntimeError(
                "handle() argument is not a handler instance")
        handler = self.handlers[w_instance.class_name]
        if handler.effect in instances_w:
            raise EffectPythonRuntimeError(
                "handle() has two handlers for %s" % handler.effect)
        instances_w[handler.effect] = w_instance

    def dispatch(self, frame, h):
        """Step 3: run the clause or method for each payload the body
        performs until the handle that comes back is empty; then
        surface what the body left in the mailbox. A method, or a
        clause that ends with eff.resume(...) on its own binding,
        switches into the body from this loop, so sequential performs
        handled that way do not nest on the C stack. A resume()
        anywhere else runs nested through resume(). A clause that ends
        without switching abandons the body, and so does a control
        signal or an exception leaving a clause or a method: the body
        is unwound before the loop goes on or the signal continues
        (plan 1.8)."""
        while not self.sthread.is_empty_handle(h):
            payload = frame.pending_payload
            w_eff = W_EffBinding(payload, frame, h)
            try:
                if payload.effect_name in frame.instances_w:
                    h = self.answer_with_method(w_eff, payload)
                else:
                    h = self.answer_with_clause(w_eff, payload)
            except (ControlSignal, EffectError):
                self.unwind(w_eff)
                raise
        error = frame.pending_error
        if error is not None:
            frame.pending_error = None
            if isinstance(error, Unwind) and error.frame is frame:
                return
            raise error
        signal = frame.pending_return
        if signal is not None:
            frame.pending_return = None
            raise signal

    def answer_with_clause(self, w_eff, payload):
        """Bind the clause's name for the clause's duration and run it,
        then switch into the body with its tail value or exception, or
        unwind the body when the clause ends without a tail."""
        frame = w_eff.frame
        clause = frame.clause_for(payload)
        tail = tail_switch(clause)
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
                w_value = self.eval_expr(switch_value(tail), env)
        finally:
            if had_name:
                env.vars[name] = w_old
            else:
                del env.vars[name]
        if tail is None:
            if self.sthread.is_empty_handle(w_eff.h_body):
                return w_eff.h_body
            return self.unwind_into(w_eff)
        if isinstance(tail, ast.Throw):
            return self.switch_into(w_eff, None,
                                    exception_value(w_value, "throw"))
        return self.switch_into(w_eff, w_value, None)

    def unwind(self, w_eff):
        """Unwind the body a clause or method is leaving by a return or
        an exception, when it is still suspended, and dispatch what it
        performs on the way out. The loop ends by swallowing this
        frame's Unwind, or by raising what replaced it."""
        if self.sthread.is_empty_handle(w_eff.h_body):
            return
        h = self.unwind_into(w_eff)
        self.dispatch(w_eff.frame, h)

    def unwind_into(self, w_eff):
        """Switch into the suspended body with an Unwind for its
        perform to raise (plan 1.8)."""
        frame = w_eff.frame
        frame.resume_unwind = Unwind(frame)
        return self.switch_into(w_eff, None, None)

    def answer_with_method(self, w_eff, payload):
        """A handler method's return value resumes the body, and an
        exception it raises whose class its operation declares is
        thrown into the body (plan 1.7); any other exception abandons
        the body by propagating out of dispatch (plan 1.6)."""
        frame = w_eff.frame
        try:
            w_value = self.call_method(
                frame.instances_w[payload.effect_name], payload)
        except RaisedException as e:
            op = self.operations[payload.effect_name + "." + payload.op_name]
            if e.w_exception.class_name not in op.row:
                raise
            return self.switch_into(w_eff, None, e.w_exception)
        return self.switch_into(w_eff, w_value, None)

    def perform(self, effect_name, op_name, args_w):
        """Step 2: hide the handling frame and everything above it,
        mail the payload, and switch to the handler side. When a
        resume() switches back, restore the frames and return its
        value; when a throw() does, raise its exception here, at the
        perform site (plan 1.7); when an abandoning clause does, raise
        the Unwind that runs the body's finally suites (plan 1.8)."""
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
        unwind = frame.resume_unwind
        frame.resume_unwind = None
        if unwind is not None:
            raise unwind
        w_exception = frame.resume_exception
        frame.resume_exception = None
        if w_exception is not None:
            raise RaisedException(w_exception)
        w_value = frame.resume_value
        frame.resume_value = None
        return w_value

    def switch_into(self, w_eff, w_value, w_exception):
        """Step 4: consume the one-shot handle and switch into the body
        with a value for the perform to return or an exception for it
        to raise; unwind_into() sets the Unwind beforehand and passes
        neither. Returns the handle that comes back when the body
        performs again or finishes."""
        if self.sthread.is_empty_handle(w_eff.h_body):
            raise OneShotContinuationError(
                "Cannot resume a suspended body more than once")
        frame = w_eff.frame
        h = w_eff.h_body
        w_eff.h_body = self.sthread.get_null_handle()
        frame.resume_value = w_value
        frame.resume_exception = w_exception
        frame.status = STATUS_RUNNING
        return self.sthread.switch(h)

    def resume(self, w_eff, w_value):
        """eff.resume(...) anywhere but a clause's tail: switch into the
        body and dispatch what it does next, nested in this call."""
        h = self.switch_into(w_eff, w_value, None)
        self.dispatch(w_eff.frame, h)
        return w_None

    def throw(self, w_eff, w_exception):
        """eff.throw(...) anywhere but a clause's tail: as resume(),
        with the perform raising instead of returning."""
        h = self.switch_into(w_eff, None, w_exception)
        self.dispatch(w_eff.frame, h)
        return w_None

    def call_method(self, w_instance, payload):
        """A handler method runs as a function with the instance as
        self ahead of the payload's arguments (plan 1.5)."""
        handler = self.handlers[w_instance.class_name]
        method = handler.methods[payload.op_name]
        return self.call_function(method, [w_instance] + payload.args_w)

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

    def instance(self, env, target):
        w_target = env.lookup(target)
        if isinstance(w_target, W_HandlerInstance):
            return w_target
        raise EffectPythonRuntimeError(
            "'%s' is not a handler instance" % target)

    def field_index(self, w_instance, attr):
        i = w_instance.index_of(attr)
        if i < 0:
            raise EffectPythonRuntimeError(
                "handler class '%s' has no field '%s'" %
                (w_instance.class_name, attr))
        return i

    # --- expressions -------------------------------------------------------

    def eval_expr(self, expr, env):
        if isinstance(expr, ast.IntLiteral):
            return W_Int(expr.value)
        elif isinstance(expr, ast.StrLiteral):
            return W_Str(expr.value)
        elif isinstance(expr, ast.BoolLiteral):
            return wrap_bool(expr.value)
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
            w_target = env.find(expr.effect)
            if w_target is not None:
                return list_method(w_target, expr.op, args_w)
            return W_EffectPayload(expr.effect, expr.op, args_w)
        elif isinstance(expr, ast.MethodCall):
            w_target = self.eval_expr(expr.target, env)
            args_w = []
            for arg in expr.args:
                args_w.append(self.eval_expr(arg, env))
            return list_method(w_target, expr.method, args_w)
        elif isinstance(expr, ast.ListLiteral):
            items_w = []
            for element in expr.elements:
                items_w.append(self.eval_expr(element, env))
            return W_List(items_w)
        elif isinstance(expr, ast.Index):
            w_list = list_value(self.eval_expr(expr.target, env))
            return w_list.items_w[
                list_index(w_list, self.eval_expr(expr.index, env))]
        elif isinstance(expr, ast.AttrRead):
            w_target = env.lookup(expr.target)
            if isinstance(w_target, W_HandlerInstance):
                i = self.field_index(w_target, expr.attr)
                return w_target.fields_w[i]
            return self.read_attr(self.binding(env, expr.target), expr.attr)
        elif isinstance(expr, ast.Resume):
            w_value = self.eval_expr(expr.value, env)
            return self.resume(self.binding(env, expr.target), w_value)
        elif isinstance(expr, ast.Throw):
            w_value = self.eval_expr(expr.value, env)
            return self.throw(self.binding(env, expr.target),
                              exception_value(w_value, "throw"))
        else:
            raise EffectPythonRuntimeError("unknown expression node")

    def call(self, name, args_w):
        if name == "print":
            parts = []
            for w in args_w:
                parts.append(w.str())
            self.output.write_line(" ".join(parts))
            return w_None
        if name == "len" or name == "str":
            return builtin(name, args_w)
        if name == "range":
            raise EffectPythonRuntimeError(
                "range() is allowed only as the iterable of a for statement")
        if name in self.functions:
            return self.call_function(self.functions[name], args_w)
        if name in self.handlers:
            return self.handlers[name].construct(args_w)
        if name in self.exceptions:
            return self.construct_exception(name, args_w)
        raise EffectPythonRuntimeError("name '%s' is not defined" % name)

    def construct_exception(self, name, args_w):
        if len(args_w) == 0:
            return W_Exception(name, "")
        w_message = args_w[0]
        if len(args_w) > 1 or not isinstance(w_message, W_Str):
            raise EffectPythonRuntimeError(
                "%s() takes an optional str message" % name)
        return W_Exception(name, w_message.val)

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
        elif isinstance(w_left, W_Bool) and isinstance(w_right, W_Bool):
            if op == "==":
                return wrap_bool(w_left.val == w_right.val)
            elif op == "!=":
                return wrap_bool(w_left.val != w_right.val)
        elif isinstance(w_left, W_List) and isinstance(w_right, W_List):
            if op == "==":
                return wrap_bool(lists_equal(w_left, w_right))
            elif op == "!=":
                return wrap_bool(not lists_equal(w_left, w_right))
        raise EffectPythonRuntimeError(
            "unsupported operand types for %s: %s and %s" %
            (op, type_name(w_left), type_name(w_right)))

# --- lists (plan 1.9) --------------------------------------------------------

def list_value(w_value):
    if isinstance(w_value, W_List):
        return w_value
    raise EffectPythonRuntimeError(
        "%s is not a list" % type_name(w_value))

def int_value(w_value, what):
    if isinstance(w_value, W_Int):
        return w_value.val
    raise EffectPythonRuntimeError(
        "%s needs an int, not %s" % (what, type_name(w_value)))

def list_index(w_list, w_index):
    """The position a subscript names, with a negative one counting
    from the end as Python's does."""
    i = int_value(w_index, "a list index")
    count = len(w_list.items_w)
    if i < 0:
        i += count
    if i < 0 or i >= count:
        raise EffectPythonRuntimeError("list index out of range")
    return i

def list_method(w_target, method, args_w):
    """xs.append(v), the one method a list has."""
    w_list = list_value(w_target)
    if method != "append":
        raise EffectPythonRuntimeError(
            "a list has no method '%s'" % method)
    if len(args_w) != 1:
        raise EffectPythonRuntimeError(
            "append() takes 1 arguments (%d given)" % len(args_w))
    w_list.items_w.append(args_w[0])
    return w_None

def builtin(name, args_w):
    """len(xs) or len(s), and str(x) for a scalar: what print would
    show for it."""
    if len(args_w) != 1:
        raise EffectPythonRuntimeError(
            "%s() takes 1 arguments (%d given)" % (name, len(args_w)))
    w_arg = args_w[0]
    if name == "len":
        if isinstance(w_arg, W_List):
            return W_Int(len(w_arg.items_w))
        if isinstance(w_arg, W_Str):
            return W_Int(len(w_arg.val))
        raise EffectPythonRuntimeError(
            "len() needs a list or str, not %s" % type_name(w_arg))
    if (isinstance(w_arg, W_Int) or isinstance(w_arg, W_Str)
            or isinstance(w_arg, W_Bool)):
        return W_Str(w_arg.str())
    raise EffectPythonRuntimeError(
        "str() needs an int, str, or bool, not %s" % type_name(w_arg))

def lists_equal(w_left, w_right):
    """Element by element; elements of two types are unequal, as 1 and
    "1" are, so a list of unknown element type compares without an
    operator error."""
    if len(w_left.items_w) != len(w_right.items_w):
        return False
    for i in range(len(w_left.items_w)):
        if not scalars_equal(w_left.items_w[i], w_right.items_w[i]):
            return False
    return True

def scalars_equal(w_a, w_b):
    if isinstance(w_a, W_Int) and isinstance(w_b, W_Int):
        return w_a.val == w_b.val
    if isinstance(w_a, W_Str) and isinstance(w_b, W_Str):
        return w_a.val == w_b.val
    if isinstance(w_a, W_Bool) and isinstance(w_b, W_Bool):
        return w_a.val == w_b.val
    return False

def tail_switch(clause):
    """The Resume or Throw node when the clause's last statement is
    eff.resume(...) or eff.throw(...) on the clause's own binding,
    else None."""
    if len(clause.body) == 0:
        return None
    last = clause.body[len(clause.body) - 1]
    if isinstance(last, ast.ExprStmt):
        expr = last.expr
        if isinstance(expr, ast.Resume) and expr.target == clause.binding:
            return expr
        if isinstance(expr, ast.Throw) and expr.target == clause.binding:
            return expr
    return None

def switch_value(expr):
    """The argument expression of a Resume or Throw node."""
    if isinstance(expr, ast.Resume):
        return expr.value
    assert isinstance(expr, ast.Throw)
    return expr.value

def exception_value(w_value, what):
    """The W_Exception a raise or a throw delivers; the checker rejects
    any other value whose type it knows."""
    if not isinstance(w_value, W_Exception):
        raise EffectPythonRuntimeError(
            "%s needs an exception, not %s" % (what, type_name(w_value)))
    return w_value

def clause_catching(stmt, w_exception):
    """The first clause of a Try that names the exception's class or
    Exception, else None."""
    for clause in stmt.clauses:
        if (clause.name == w_exception.class_name
                or clause.name == "Exception"):
            return clause
    return None

def type_name(w):
    if isinstance(w, W_Int):
        return "int"
    elif isinstance(w, W_Str):
        return "str"
    elif isinstance(w, W_Bool):
        return "bool"
    elif isinstance(w, W_Exception):
        return w.class_name
    elif isinstance(w, W_List):
        return "list"
    return "object"
