"""The AST evaluator (plan Milestone 1).

eval_expr returns a W_Root for every expression; exec_stmt runs one
statement. Dispatch is by isinstance over the node classes in
ast_nodes, as the checker's is, so adding a node means a branch in
both. Each call gets a fresh Environment, so locals are lexically
scoped to the call that created them. A return statement unwinds to
the enclosing call through ReturnSignal, an RPython exception, and
break and continue unwind to the enclosing loop's exec_pass through
BreakSignal and ContinueSignal (plan 1.10); the three share the base
ControlSignal, which the handler runtime looks for.

Several constructs add values, not mechanism. and, or, and not (plan
1.11) take bool operands and give a W_Bool (truth); and and or
evaluate the right operand only when the left has not decided the
result, so an effect in a skipped operand is not performed, and a
perform() inside an operand suspends the body in the middle of the
expression, on its stacklet, as one inside a call's argument does.
An elif is a nested If from the parser on, as in CPython's AST. A
W_List (plan 1.9) is shared by reference, so exec_for walks the one
the iterable evaluates to by index against its live length, and a
clause that appends to that list while the body is suspended
lengthens the walk. A for over range() is a ForRange the parser
folds, and counts in an RPython local. xs.append(v) on a name is the
OpCall the parser builds for Effect.op(...), told apart by the name
being bound, since an effect is never a value; on any other
expression it is a MethodCall. len(), str(), and range() are Call
nodes recognized by name, as print is. An FString (plan 1.13)
evaluates its fields left to right and joins their str() with its
literal text, so a perform() in a field suspends the body in the
middle of the expression, as one in an argument does. An augmented
assignment to a name or a field is the Assign or AttrAssign the
parser built; a subscript target is an IndexAugAssign, which
exec_index_aug_assign evaluates in Python's order, the read before
the value and the store through the index value (plan 1.14). A W_Dict
(plan 1.12) is
shared the same way, over an RPython dict from str to W_Root, which
keeps insertion order; exec_for_dict walks its keys and stops with
Python's error when a store changes the size, and k in d and x in xs
are one In node (contains). A field default is evaluated per
construction, so the [] or {} a field declares gives each instance a
container of its own. A data class (plan 1.19) is a HandlerClass with
no methods and an empty effect, kept in a table of its own
(Interpreter.records), and its instances are W_HandlerInstance
values: a constructor call, a field read, and a field store take the
paths a handler instance takes, and install() asks for the class
among the handlers before it reads an effect from it. A field
through an expression that is no name is a FieldRead or a
FieldAssign (plan 1.20), which evaluate the target as any expression
and find the instance with field_owner.

Exceptions (plan 1.6) need one mechanism, RaisedException, an
EffectError that carries the W_Exception. A raise statement raises
it, and a Try statement catches it around its suite and runs the
first clause that names the exception's class or Exception. Where it
meets the handlers follows from where the RPython exception travels,
below.

The effect runtime (plan 3.3 and 3.4) runs each handle statement's
body in its own stacklet. A HandlerFrame is the mailbox between the
two sides, since a stacklet switch carries no value: perform()
stores the payload and switches to the handler side, which runs the
matching clause, and the clause switches back in one of three ways.
eff.resume(v) stores the value, and perform() returns it; the body
is a suite, so eff.resume() evaluates to None once the body
finishes. eff.throw(exc) (plan 1.7) stores the exception, and
perform() raises it, so it starts on the body's stack at the perform
site and a Try around the perform catches it. Abandoning the body
(plan 1.8) stores an Unwind, an EffectError the dialect cannot name,
and perform() raises it, so it runs every finally suite on the way
out of the body's stacklet while no except clause can catch it; a
clause that ends without resuming, a return, break, or continue that
leaves a clause, and an exception that leaves a clause or a method
with the body still suspended all abandon it. exec_try runs its
finally under an RPython try/finally, so a finally that performs is
answered by the same loop, and one that raises an exception or
returns replaces the unwinding, as Python's does. The body therefore
always runs to completion; when the loop finds its own Unwind in the
mailbox it swallows it, and another frame's Unwind it re-raises,
which carries an outer abandonment through every body nested inside
the abandoned one. A clause runs in the function's own environment
with its binding defined for the clause's duration, and afterwards
the binding is restored to its earlier value, or removed when it had
none, which is not what Python does for `except ... as e`; the
restore keeps a clause that runs nested inside another clause's
resume() from overwriting the outer clause's binding, and the
checker mirrors it (check_effect_clause). A switch that is the
clause's last statement on its own binding, a tail resume or a tail
throw, is made by dispatch() from its loop rather than nested inside
the clause, so any number of sequential performs handled that way
use constant stack; any other resume() or throw() nests.

A handler class (plan 1.5) adds no mechanism to that. A handle
statement evaluates its constructor calls and looks up its instance
names before installing the frame, and the frame maps each fulfilled
effect to its W_HandlerInstance. When the body performs an operation
of a fulfilled effect, dispatch() calls the method as a function
with the instance as self and the payload's arguments
(answer_with_method), and switches into the body along the tail
path: with the returned value, so a method cannot resume the body
twice; with the exception, when the method raises a class its
operation's row declares, delivered at the perform site as a throw
is; and with an Unwind when it raises any other exception, which
then leaves the handle statement.

Where an exception surfaces, then, follows from the side it travels
on. One the body raises, after a resume or before any perform, is
stored in the frame and re-raised on the handler side: inside the
eff.resume() call that resumed the body, so the rest of the clause
does not run, or at the handle statement when the body never
performed or was last resumed from the dispatch loop. One a clause
or a method raises travels on the handler side, abandons the
suspended body as above, and leaves the handle statement, unless it
is a method's declared class, which goes into the body instead. A
Try inside the body sits on the body's stack slice, which the
stacklet keeps across a perform, so it catches what the body raises
after a resume and what a throw or a declared class delivers, and
not what a clause or a method raises otherwise.

rstacklet runs only translated, so the import below is guarded: the
unit tests import this module without RPython on the path and never
execute a handle statement. Every runtime error that depends on it
goes through the translated binary, in tests/test_runtime.py.

Some EffectPythonRuntimeError branches below are unreachable from the
translated binary, because checker.py rejects the program first. The
branches stay because the unit tests build modules by hand and run
them without the checker. A program under tests/programs/ holds each
one: test_runtime.py runs each against its .expected, so a branch the
checker stops rejecting shows up there, and test_docstrings.py holds
this list and the directory to each other. The pairs, checker rule,
runtime site, and program: a call to a function that does not exist
(check_call; call; unreachable_undefined_function.epy), a call with
the wrong number of arguments (check_args; call_function;
unreachable_arity.epy), a module without main() (check_entry_point;
entry_point; unreachable_no_main.epy), a perform() with no handler in
scope (the row; perform; unreachable_unhandled_perform.epy), a clause
binding read where none is bound and an eff.<attr> naming no
parameter (require_binding and the AttrRead branch; binding and
read_attr; unreachable_unbound_binding.epy and
unreachable_no_parameter.epy), a handle statement without a clause
for an operation (check_handle; clause_for;
rejected_missing_clause.epy), a break or continue outside a loop
(require_loop; call_function; unreachable_break_outside_loop.epy), a
read of a name nothing bound (require_bound; Environment.lookup;
unreachable_finally_reads_returned_name.epy), a constructor call with
too few or too many arguments (check_construction;
HandlerClass.construct; unreachable_constructor_too_few.epy and
unreachable_constructor_arity.epy), a field assigned on a name that
holds no instance (require_instance; Interpreter.instance;
unreachable_field_on_non_instance.epy), a field the class does not
declare (require_field; field_index; unreachable_undeclared_field.epy),
a handle() argument that is not an instance or that fulfills an
effect another argument fulfills (check_handle; install;
unreachable_handle_non_instance.epy and unreachable_two_handlers.epy),
a raise or an eff.throw() of a value that is not an exception
(require_exception; exception_value;
unreachable_raise_non_exception.epy and
unreachable_throw_non_exception.epy), an exception constructor call
with more than a str message (check_exception_call;
construct_exception; unreachable_exception_arity.epy and
unreachable_exception_unknown_arg.epy), an operator on operands of
the wrong types (check_operands; binop and compare;
unreachable_operand_types.epy and unreachable_compare_types.epy), a
subscript, an append, or a for on a value that is not a list
(check_index, check_append, the For branch; list_value;
unreachable_subscript_non_list.epy, unreachable_append_non_list.epy,
and unreachable_for_non_list.epy), an in test on a value that is
neither a list nor a dict (check_membership; contains, through
list_value; unreachable_in_target.epy), a non-integer index or
range() argument (check_index, check_range; list_index and
int_value; unreachable_str_index.epy and
unreachable_range_unknown.epy), a non-str dict key (check_index,
check_dict_literal; dict_key; unreachable_dict_key_type.epy), a
method other than append or an append with the wrong number of
arguments (check_append; list_method; unreachable_list_method.epy and
unreachable_append_arity.epy), a built-in with the wrong number or
type of argument (check_builtin; builtin; unreachable_len_arity.epy,
unreachable_len_argument.epy, and unreachable_str_argument.epy), an
f-string field that is not a scalar (check_fstring; the FString
branch of eval_expr; unreachable_fstring_field.epy),
range() outside a for (check_call; call; unreachable_range_call.epy),
and a non-bool operand of and, or, or not, or test of an if or a
while (require_bool; truth; unreachable_bool_operand.epy and
unreachable_if_test.epy). A RaisedException nobody catches, which
entry_point in targeteffectpython.py would report, is unreachable
too, since main()'s empty row rejects it
(unreachable_uncaught_exception.epy). The "unknown node" branches
guard the dispatch and no parse reaches them.

Each pair holds where the checker has a type for the value, and a
type it holds is the type the value has at runtime: checker.py's
docstring gives the rules, and a program shows each holding where it
once did not (merge_types for the paths that meet,
unreachable_loop_carried_list.epy and
unreachable_clause_deleted_read*.epy; hand_over for a [],
unreachable_alias_param.epy and unreachable_nested_list.epy;
require_known for a typed slot, unreachable_range_unknown.epy;
check_return and always_returns for a return,
unreachable_return_type.epy and unreachable_missing_return.epy). An
unknown type, which a name two paths leave with two types has, as do
a [] handed to another name, a literal with an unknown element, and
an element read from a [] the checker never refined, reaches these
branches as any untyped value does, where the operation is one the
checker leaves to the runtime. Those cases are runtime-only, and a
program reaches each: a read of a name, or an append on one, whose
assignment comes earlier in the source but did not run, because it
sits in a loop body that ran zero times or in one branch of an if
(Environment.lookup, and the OpCall branch of eval_expr;
runtime_zero_trip_read.epy, runtime_if_branch_read.epy, and
runtime_zero_trip_append.epy); an operator or a comparison
(runtime_unknown_operand.epy, runtime_compare_unknown.epy,
runtime_alias_append.epy, runtime_unknown_elements.epy, and the
paths that leave a name with two types: runtime_zero_trip_retype.epy,
runtime_break_carried.epy, runtime_try_midsuite.epy,
runtime_clause_before_resume.epy, runtime_finally_after_return.epy,
runtime_finally_midsuite.epy, runtime_finally_break.epy,
runtime_finally_unwind.epy, and runtime_clause_after_assign.epy),
two instances met by the == of two lists
(scalars_equal; runtime_instance_compare.epy), a field read on a
value that is no instance (the AttrRead branch of eval_expr;
runtime_field_unknown.epy; and field_owner for a FieldRead;
runtime_field_expression.epy), a method on a value of the wrong kind (call_method;
runtime_method_unknown.epy), a negative exponent (power;
runtime_negative_exponent.epy), a subscript, append, for, or in target
(runtime_subscript_unknown.epy, runtime_append_unknown_target.epy,
and runtime_for_unknown.epy), a len() or str() argument or an
f-string field (runtime_len_unknown.epy, runtime_str_unknown.epy,
and runtime_fstring_field.epy), a list index
(runtime_index_unknown.epy), a dict key
(runtime_dict_key_unknown.epy), a bool operand
(runtime_bool_operand.epy), or an if or while test
(runtime_if_test.epy and runtime_while_test.epy) whose type the
checker could not see; integer division or modulo by zero
(runtime_division_by_zero.epy and runtime_modulo_by_zero.epy); a list
index out of range (list_index_error.epy); a key a dict lacks
(runtime_missing_key.epy, and runtime_augmented_key.epy through the
read of d[k] += 1), and a dict a store resizes while a for
walks it (runtime_dict_resized.epy, and runtime_items_resized.epy
for a for over items()); and a recursion that outgrows
the C stack, which RPython's stack check stops and the entry point
(deep_recursion.epy) or run_body_callback
(deep_recursion_in_body.epy) reports as "maximum recursion depth
exceeded". A read of a name an except clause deleted, where the read
comes earlier in the source, needs a loop or a resumed body to run
after the clause, and a pass that unbinds a name is followed by
another over the suite, which finds the read unbound
(unreachable_clause_deleted_read*.epy).
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
                                W_Tuple, W_Dict, W_EffectPayload, W_EffBinding,
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
    instances fulfill (plan 1.5). A data class is recorded the same
    way, with no methods and an empty effect (plan 1.19)."""

    def __init__(self, name, effect, fields, methods):
        self.name = name
        self.effect = effect
        self.field_names = []
        self.defaults = []  # the default Expr or None, parallel to it
        for field in fields:
            self.field_names.append(field.name)
            self.defaults.append(field.default)
        self.methods = {}
        for method in methods:
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
    """The value of a field default: an int, str, or bool literal,
    or the [] or {} the parser allows for a list or dict field."""
    if isinstance(expr, ast.IntLiteral):
        return W_Int(expr.value)
    elif isinstance(expr, ast.BoolLiteral):
        return wrap_bool(expr.value)
    elif isinstance(expr, ast.StrLiteral):
        return W_Str(expr.value)
    if isinstance(expr, ast.DictLiteral):
        return W_Dict({})
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
            self.handlers[handler.name] = HandlerClass(
                handler.name, handler.effect, handler.fields,
                handler.methods)
        self.records = {}
        for record in module.records:
            self.records[record.name] = HandlerClass(
                record.name, "", record.fields, [])
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
            if truth(self.eval_expr(stmt.test, env), "if"):
                self.exec_block(stmt.body, env)
            else:
                self.exec_block(stmt.orelse, env)
        elif isinstance(stmt, ast.While):
            while truth(self.eval_expr(stmt.test, env), "while"):
                if self.exec_pass(stmt.body, env):
                    break
        elif isinstance(stmt, ast.Break):
            raise BreakSignal()
        elif isinstance(stmt, ast.Continue):
            raise ContinueSignal()
        elif isinstance(stmt, ast.Assign):
            env.define(stmt.name, self.eval_expr(stmt.value, env))
        elif isinstance(stmt, ast.Unpack):
            items_w = unpacked(self.eval_expr(stmt.value, env),
                               len(stmt.names))
            for i in range(len(stmt.names)):
                env.define(stmt.names[i], items_w[i])
        elif isinstance(stmt, ast.AttrAssign):
            w_target = self.instance(env, stmt.target)
            i = self.field_index(w_target, stmt.attr)
            w_target.fields_w[i] = self.eval_expr(stmt.value, env)
        elif isinstance(stmt, ast.FieldAssign):
            self.exec_field_assign(stmt, env)
        elif isinstance(stmt, ast.IndexAssign):
            w_value = self.eval_expr(stmt.value, env)
            w_target = self.eval_expr(stmt.target, env)
            w_index = self.eval_expr(stmt.index, env)
            if isinstance(w_target, W_Dict):
                w_target.items_w[dict_key(w_index)] = w_value
            else:
                w_list = mutable_list(w_target)
                w_list.items_w[list_index(w_list, w_index)] = w_value
        elif isinstance(stmt, ast.IndexAugAssign):
            self.exec_index_aug_assign(stmt, env)
        elif isinstance(stmt, ast.For):
            self.exec_for(stmt, env)
        elif isinstance(stmt, ast.ForItems):
            self.exec_for_items(stmt, env)
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

    def exec_index_aug_assign(self, stmt, env):
        """xs[i] op= v or d[k] op= v in Python's order: the target, the
        index, the read, then the value, and the store through the
        index value, so a negative index names the last element at
        the store even when v's perform let a clause append (plan
        1.14). A missing key or an index out of range fails at the
        read, as a subscript does."""
        w_target = self.eval_expr(stmt.target, env)
        w_index = self.eval_expr(stmt.index, env)
        if isinstance(w_target, W_Dict):
            key = dict_key(w_index)
            if key not in w_target.items_w:
                raise EffectPythonRuntimeError("key '%s' not found" % key)
            w_old = w_target.items_w[key]
            w_value = self.eval_expr(stmt.value, env)
            w_target.items_w[key] = self.binop(stmt.op, w_old, w_value)
            return
        w_list = mutable_list(w_target)
        w_old = w_list.items_w[list_index(w_list, w_index)]
        w_value = self.eval_expr(stmt.value, env)
        w_new = self.binop(stmt.op, w_old, w_value)
        w_list.items_w[list_index(w_list, w_index)] = w_new

    def exec_for(self, stmt, env):
        """Walk the list by index against its live length, as Python
        does, so an append in the suite lengthens the walk; the name
        keeps the last element afterwards (plan 1.9). The index is a
        local of this call, so a perform in the suite suspends the
        loop where it is."""
        w_iterable = self.eval_expr(stmt.iterable, env)
        if isinstance(w_iterable, W_Dict):
            self.exec_for_dict(stmt, w_iterable, env)
            return
        w_list = list_value(w_iterable)
        i = 0
        while i < len(w_list.items_w):
            env.define(stmt.name, w_list.items_w[i])
            if self.exec_pass(stmt.body, env):
                break
            i += 1

    def exec_for_dict(self, stmt, w_dict, env):
        """Walk the keys in insertion order; a store that changes the
        size is found when the walk would advance, the last step
        included, which is the error Python raises for the same
        program (plan 1.12)."""
        size = len(w_dict.items_w)
        for key in w_dict.items_w.keys():
            env.define(stmt.name, W_Str(key))
            if self.exec_pass(stmt.body, env):
                break
            if len(w_dict.items_w) != size:
                raise EffectPythonRuntimeError(
                    "dict changed size during iteration")

    def exec_for_items(self, stmt, env):
        """for k, v in d.items(): walk the keys as exec_for_dict
        does, binding each with the value the dict holds for it when
        the pass starts; a store to a key the dict has is allowed,
        and one that changes the size is Python's error (plan
        1.22)."""
        w_dict = self.eval_expr(stmt.target, env)
        if not isinstance(w_dict, W_Dict):
            raise EffectPythonRuntimeError(
                "items() needs a dict on the left of the dot, not %s" %
                type_name(w_dict))
        size = len(w_dict.items_w)
        for key in w_dict.items_w.keys():
            env.define(stmt.key, W_Str(key))
            env.define(stmt.value, w_dict.items_w[key])
            if self.exec_pass(stmt.body, env):
                break
            if len(w_dict.items_w) != size:
                raise EffectPythonRuntimeError(
                    "dict changed size during iteration")

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
        if (not isinstance(w_instance, W_HandlerInstance)
                or w_instance.class_name not in self.handlers):
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
            "'%s' is not a handler instance or a data class instance"
            % target)

    def field_owner(self, w_target, attr):
        """The instance a field is read or stored through (plan
        1.20), or CPython's error for a value that has no fields."""
        if isinstance(w_target, W_HandlerInstance):
            return w_target
        raise EffectPythonRuntimeError(
            "'%s' object has no attribute '%s'" %
            (type_name(w_target), attr))

    def exec_field_assign(self, stmt, env):
        """A plain store evaluates the value and then the target; an
        augmented one evaluates the target once, reads the field,
        evaluates the value, and stores the result, as Python does
        (plan 1.20)."""
        if stmt.op == "":
            w_value = self.eval_expr(stmt.value, env)
            w_target = self.field_owner(
                self.eval_expr(stmt.target, env), stmt.attr)
            i = self.field_index(w_target, stmt.attr)
            w_target.fields_w[i] = w_value
            return
        w_target = self.field_owner(
            self.eval_expr(stmt.target, env), stmt.attr)
        i = self.field_index(w_target, stmt.attr)
        w_old = w_target.fields_w[i]
        w_value = self.eval_expr(stmt.value, env)
        w_target.fields_w[i] = self.binop(stmt.op, w_old, w_value)

    def field_index(self, w_instance, attr):
        i = w_instance.index_of(attr)
        if i < 0:
            kind = "handler class"
            if w_instance.class_name in self.records:
                kind = "data class"
            raise EffectPythonRuntimeError(
                "%s '%s' has no field '%s'" %
                (kind, w_instance.class_name, attr))
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
        elif isinstance(expr, ast.BoolOp):
            left = truth(self.eval_expr(expr.left, env), expr.op)
            if left != (expr.op == "and"):
                return wrap_bool(left)
            return wrap_bool(truth(self.eval_expr(expr.right, env),
                                   expr.op))
        elif isinstance(expr, ast.Not):
            return wrap_bool(not truth(self.eval_expr(expr.operand, env),
                                       "not"))
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
                return call_method(w_target, expr.op, args_w)
            if expr.effect + "." + expr.op not in self.operations:
                raise EffectPythonRuntimeError(
                    "name '%s' is not defined" % expr.effect)
            return W_EffectPayload(expr.effect, expr.op, args_w)
        elif isinstance(expr, ast.MethodCall):
            w_target = self.eval_expr(expr.target, env)
            args_w = []
            for arg in expr.args:
                args_w.append(self.eval_expr(arg, env))
            return call_method(w_target, expr.method, args_w)
        elif isinstance(expr, ast.ListLiteral):
            items_w = []
            for element in expr.elements:
                items_w.append(self.eval_expr(element, env))
            return W_List(items_w)
        elif isinstance(expr, ast.Index):
            w_target = self.eval_expr(expr.target, env)
            w_index = self.eval_expr(expr.index, env)
            if isinstance(w_target, W_Dict):
                key = dict_key(w_index)
                if key not in w_target.items_w:
                    raise EffectPythonRuntimeError(
                        "key '%s' not found" % key)
                return w_target.items_w[key]
            if isinstance(w_target, W_Tuple):
                return w_target.items_w[tuple_index(w_target, w_index)]
            w_list = list_value(w_target)
            return w_list.items_w[list_index(w_list, w_index)]
        elif isinstance(expr, ast.TupleLiteral):
            items_w = []
            for element in expr.elements:
                items_w.append(self.eval_expr(element, env))
            return W_Tuple(items_w)
        elif isinstance(expr, ast.DictLiteral):
            items_w = {}
            for i in range(len(expr.keys)):
                key = dict_key(self.eval_expr(expr.keys[i], env))
                items_w[key] = self.eval_expr(expr.values[i], env)
            return W_Dict(items_w)
        elif isinstance(expr, ast.FString):
            parts = [expr.literals[0]]
            for i in range(len(expr.exprs)):
                w_field = self.eval_expr(expr.exprs[i], env)
                if not is_scalar(w_field):
                    raise EffectPythonRuntimeError(
                        "an f-string field needs an int, str, or bool, not "
                        "%s" % type_name(w_field))
                parts.append(w_field.str())
                parts.append(expr.literals[i + 1])
            return W_Str("".join(parts))
        elif isinstance(expr, ast.NoneLiteral):
            return w_None
        elif isinstance(expr, ast.IsNone):
            w_operand = self.eval_expr(expr.operand, env)
            return wrap_bool((w_operand is w_None) != expr.negated)
        elif isinstance(expr, ast.In):
            w_left = self.eval_expr(expr.left, env)
            w_right = self.eval_expr(expr.right, env)
            return wrap_bool(contains(w_right, w_left) != expr.negated)
        elif isinstance(expr, ast.AttrRead):
            w_target = env.lookup(expr.target)
            if isinstance(w_target, W_HandlerInstance):
                i = self.field_index(w_target, expr.attr)
                return w_target.fields_w[i]
            if not isinstance(w_target, W_EffBinding):
                raise EffectPythonRuntimeError(
                    "'%s' is not an except binding, a handler instance, "
                    "or a data class instance" % expr.target)
            return self.read_attr(w_target, expr.attr)
        elif isinstance(expr, ast.FieldRead):
            w_target = self.field_owner(
                self.eval_expr(expr.target, env), expr.attr)
            return w_target.fields_w[
                self.field_index(w_target, expr.attr)]
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
        if name in self.records:
            return self.records[name].construct(args_w)
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
            elif op == "**":
                return W_Int(power(a, b))
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

def dict_key(w_value):
    if isinstance(w_value, W_Str):
        return w_value.val
    raise EffectPythonRuntimeError(
        "a dict key must be str, not %s" % type_name(w_value))

def contains(w_container, w_value):
    """k in d, or x in xs element by element (plan 1.12)."""
    if isinstance(w_container, W_Dict):
        return dict_key(w_value) in w_container.items_w
    for w_item in list_value(w_container).items_w:
        if scalars_equal(w_item, w_value):
            return True
    return False

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

def tuple_index(w_tuple, w_index):
    """The position a subscript names in a tuple, as list_index gives
    it for a list (plan 1.17)."""
    i = int_value(w_index, "a tuple index")
    count = len(w_tuple.items_w)
    if i < 0:
        i += count
    if i < 0 or i >= count:
        raise EffectPythonRuntimeError("tuple index out of range")
    return i

def mutable_list(w_value):
    """The list a store goes into; a tuple takes none, in CPython's
    words (plan 1.17)."""
    if isinstance(w_value, W_Tuple):
        raise EffectPythonRuntimeError(
            "'tuple' object does not support item assignment")
    return list_value(w_value)

def unpacked(w_value, count):
    """The values of a tuple for count names (plan 1.17); the checker
    makes each error unreachable where it knows the value's type."""
    if not isinstance(w_value, W_Tuple):
        raise EffectPythonRuntimeError(
            "cannot unpack %s; the value must be a tuple" %
            type_name(w_value))
    given = len(w_value.items_w)
    if given > count:
        raise EffectPythonRuntimeError(
            "too many values to unpack (expected %d, got %d)" %
            (count, given))
    if given < count:
        raise EffectPythonRuntimeError(
            "not enough values to unpack (expected %d, got %d)" %
            (count, given))
    return w_value.items_w

def power(base, exponent):
    """base ** exponent by squaring. A negative exponent would give
    a float (plan 1.21)."""
    if exponent < 0:
        raise EffectPythonRuntimeError(
            "a negative exponent needs a float, which the dialect lacks")
    result = 1
    while exponent > 0:
        if exponent & 1:
            result = result * base
        base = base * base
        exponent >>= 1
    return result

def call_method(w_target, method, args_w):
    """s.join(xs), d.get(k) or d.get(k, default), and xs.append(v),
    chosen by the method's name (plan 1.21)."""
    if method == "join":
        return str_join(w_target, args_w)
    if method == "get":
        return dict_get(w_target, args_w)
    if method != "append":
        if isinstance(w_target, W_Str):
            raise EffectPythonRuntimeError(
                "a str has no method '%s'" % method)
        if isinstance(w_target, W_Dict):
            raise EffectPythonRuntimeError(
                "a dict has no method '%s'" % method)
    return list_method(w_target, method, args_w)

def str_join(w_target, args_w):
    if not isinstance(w_target, W_Str):
        raise EffectPythonRuntimeError(
            "join() needs a str on the left of the dot, not %s" %
            type_name(w_target))
    if len(args_w) != 1:
        raise EffectPythonRuntimeError(
            "join() takes 1 arguments (%d given)" % len(args_w))
    w_words = args_w[0]
    if not isinstance(w_words, W_List):
        raise EffectPythonRuntimeError(
            "join() needs a list of str, not %s" % type_name(w_words))
    words = []
    for i in range(len(w_words.items_w)):
        w_word = w_words.items_w[i]
        if not isinstance(w_word, W_Str):
            raise EffectPythonRuntimeError(
                "sequence item %d: expected str instance, %s found" %
                (i, type_name(w_word)))
        words.append(w_word.val)
    return W_Str(w_target.val.join(words))

def dict_get(w_target, args_w):
    if not isinstance(w_target, W_Dict):
        raise EffectPythonRuntimeError(
            "get() needs a dict on the left of the dot, not %s" %
            type_name(w_target))
    if len(args_w) < 1 or len(args_w) > 2:
        raise EffectPythonRuntimeError(
            "get() takes 1 to 2 arguments (%d given)" % len(args_w))
    key = dict_key(args_w[0])
    if key in w_target.items_w:
        return w_target.items_w[key]
    if len(args_w) == 2:
        return args_w[1]
    return w_None

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
        if isinstance(w_arg, W_Dict):
            return W_Int(len(w_arg.items_w))
        raise EffectPythonRuntimeError(
            "len() needs a list, dict, or str, not %s" % type_name(w_arg))
    if is_scalar(w_arg):
        return W_Str(w_arg.str())
    raise EffectPythonRuntimeError(
        "str() needs an int, str, or bool, not %s" % type_name(w_arg))

def is_scalar(w):
    return (isinstance(w, W_Int) or isinstance(w, W_Str)
            or isinstance(w, W_Bool))

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
    if (isinstance(w_a, W_HandlerInstance)
            and isinstance(w_b, W_HandlerInstance)):
        raise EffectPythonRuntimeError(
            "unsupported operand types for ==: %s and %s" %
            (w_a.class_name, w_b.class_name))
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

def truth(w, what):
    """The bool an if or while test, or an operand of and, or, or not,
    must be (plan 1.11); the checker makes the error unreachable where
    it knows the type."""
    if not isinstance(w, W_Bool):
        raise EffectPythonRuntimeError(
            "%s needs a bool, not %s" % (what, type_name(w)))
    return w.val

def type_name(w):
    if isinstance(w, W_Int):
        return "int"
    elif isinstance(w, W_Str):
        return "str"
    elif isinstance(w, W_Bool):
        return "bool"
    elif isinstance(w, W_Exception):
        return w.class_name
    elif isinstance(w, W_HandlerInstance):
        return w.class_name
    elif isinstance(w, W_List):
        return "list"
    elif isinstance(w, W_Dict):
        return "dict"
    elif isinstance(w, W_Tuple):
        return "tuple"
    return "object"
