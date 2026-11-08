"""The static effect checker (plan 2.2).

check() runs three passes over a parsed module before anything runs.
Pass 1 collects the effect declarations, the exception classes, the
handler classes, and the function signatures, so a function body can
call a function defined later or itself, and checks each handler
class against the effect it fulfills: one method per operation with
the operation's signature after self, and fields of type int or str
(plan 1.5) or list[int], list[str], or list[bool] (plan 1.9).
Pass 2 walks each function and method body and infers the effects it
may perform: a perform() contributes its effect, a call contributes
the callee's declared row, and a handle block removes the effects it
names or fulfills from its body's set and adds whatever its clauses
and its handlers' methods perform. The result must be a subset of the
declared row, or the function fails with an UnhandledEffectError.
Pass 3 requires a main() with an empty row.

An exception class sits in the same set as an effect (plan 1.6). A
raise contributes the class of its value, a try/except removes the classes its
clauses catch from its suite's set and adds whatever the clauses
perform or raise, and a handler method's row carries its exceptions
to the function that installs the handler. A row may therefore name
exception classes beside effects, and main()'s empty row makes an
exception nobody catches a static error.

An operation's row names the exception classes a handler may throw
into the body with eff.throw() (plan 1.7), so a perform() contributes
those classes beside its effect, and eff.throw() must name one of
them. A handler method that raises one of them delivers it to the
perform, so those classes are left out of what the method's row
carries to the installing function.

Along the way the checker types expressions far enough to check the
arguments of perform(), resume(), ordinary calls, and constructor
calls against the declared parameter types. A type is a type name; a
handler class name is the type of its instances, so a name holding
one may be passed to handle() and its fields read, and an exception
class name is the type of the name an except clause binds. The empty
string stands for a type the checker cannot determine, and an unknown
type matches anything. An operator whose operands both have known
types must have a pair the interpreter supports (OPERATORS), so the
runtime's "unsupported operand types" error is reached through an
operand of unknown type. A name that two paths leave with two types
is unknown (merge_types, below). For two lists the checker also
requires one element type, which the runtime does not: it compares
them and finds the elements unequal.

A return value must have the function's declared return type, and a
bare return has the type None (check_return). A function whose
return type is not None must return or raise an exception on every
path the checker follows (always_returns): its last statement is a
return or a raise, an if/else whose branches both qualify, a try
whose finally qualifies or whose suite and clauses all do, or a
handle whose body qualifies and whose clauses each qualify or end by
resuming it. A loop never qualifies, so a function that returns from
inside one needs a return after it. A handler method's return type
equals its operation's (check_signature), so the rule covers the
value a perform() gets from a method.

A name holding [] that a statement hands to a parameter, a field, a
return, or a resume() of type list[T] takes list[T], since the
receiver may append to it (hand_over). One assigned to another name
or placed in a list literal loses its type: the checker does not
track which names share a list, so an append through either name
would leave the other with a stale type.

A read of a name that nothing has bound earlier in the function's
source is rejected, and so is a read of the name a try statement's
except clause bound, after the clause, until something binds it
again, since the clause deletes its name when it ends
(require_bound). The walk follows source order, as the typing does,
and does not ask whether the clause would run. A clause that ends in
a return is the exception: the code after the try cannot follow it,
so the name keeps the type and the state it had before. An effect
clause (except E.op as eff) leaves its name as the runtime does
(check_effect_clause). After the handle statement the name is
unbound when nothing bound it before, and otherwise has the type it
had before.

Where two paths meet, the types they left are merged (merge_types):
a name they leave with two types, or that one path alone binds, is
unknown, while a [] that one path refined to list[T] keeps the
refinement (merged). A name one path bound still counts as bound,
since the source-order rule reads bindings, not paths. The branches
of an if are two such paths (check_if). A loop body is checked from
the types before the loop, what it leaves at its end and at each
break or continue is merged with them, and it is checked again from
the merged types until nothing changes (check_loop_body), so the
code after the loop sees a name the body gives another type as
unknown, and a type the body can carry into a later iteration is
unknown on the next pass over the body. A try's clauses start from
the types at every statement boundary of its suite, the first
included, since the exception may arrive after any statement
(check_suite), and the code after the try sees the suite's end
merged with the end of every clause that does not return
(check_try). A handle statement's clauses start from every boundary
of its body, where a perform() may suspend it, and since the body
runs on from any boundary of a clause where resume() may stand, the
body and clauses are checked again from the entry widened with those
until it is stable (check_handle, check_handle_suites). The first
pass over a loop or a handled body uses the types before it, so a
statement there that is right only through a later reassignment,
or through a clause's, is rejected on that pass.

Lists (plan 1.9) are types like the others: "list[int]", "list[str]",
and "list[bool]" are type names. "list" is the type of a literal
whose element type nothing fixes: [], or one whose elements all have
unknown types. It matches any list type as an unknown type matches
anything (matches). A for over a list binds its name to the element
type, and over range() to int. len(), str(), and range() are
built-in names beside print, and a function cannot take one of them.

A break or continue outside a loop of the same function is rejected
with "'break' outside loop" or "'continue' not properly in loop"
(plan 1.10). The count is loop_depth, which check_loop_body
increments around every loop suite and check_function resets.

The checker dispatches by isinstance over the ast_nodes classes, as the
evaluator does, so adding a node means adding a branch in both.
"""
from effectpython import ast_nodes as ast
from effectpython.errors import InvalidProgram, UnhandledEffectError

UNKNOWN = ""
LIST = "list"
FIELD_TYPES = ["int", "str"]
OPERATORS = {
    "int": ["+", "-", "*", "//", "%", "<", "<=", ">", ">=", "==", "!="],
    "str": ["+", "==", "!="],
    "bool": ["==", "!="],
    LIST: ["==", "!="],
}
BUILTINS = ["print", "len", "str", "range"]
EXCEPTION = "Exception"

def is_list(type_name):
    return type_name == LIST or type_name.startswith("list[")

def element_of(type_name):
    """The element type of list[T], or unknown for a bare list."""
    if type_name == LIST:
        return UNKNOWN
    assert type_name.startswith("list[")
    end = len(type_name) - 1
    assert end >= 5
    return type_name[5:end]

def matches(actual, expected):
    """Whether a value of the actual type may stand where the expected
    type is wanted: an unknown type matches anything, and [] matches
    any list."""
    if actual == UNKNOWN or expected == UNKNOWN or actual == expected:
        return True
    return actual == LIST and is_list(expected)

def merged(a, b):
    """The type a name has where two paths meet and left it with types
    a and b: the one type, the list[T] that refines a [], or
    unknown."""
    if a == b:
        return a
    if a == LIST and is_list(b):
        return b
    if b == LIST and is_list(a):
        return a
    return UNKNOWN

def merge_types(a, b):
    """The types after two paths that left the types a and b: merged()
    for a name both hold, and unknown for a name one alone holds, which
    still counts as bound."""
    result = {}
    for name in a:
        if name in b:
            result[name] = merged(a[name], b[name])
        else:
            result[name] = UNKNOWN
    for name in b:
        if name not in a:
            result[name] = UNKNOWN
    return result

def absorb(acc, types):
    """Merge the types into the accumulator in place: the types at one
    more point a path may leave from."""
    for name in types:
        if name in acc:
            acc[name] = merged(acc[name], types[name])
        else:
            acc[name] = UNKNOWN
    for name in acc:
        if name not in types:
            acc[name] = UNKNOWN

def same_types(a, b):
    if len(a) != len(b):
        return False
    for name in a:
        if name not in b or a[name] != b[name]:
            return False
    return True

def ends_in_return(stmts):
    """Whether nothing after the enclosing statement can run once
    these statements have. A raise does not qualify: an enclosing try
    in the same function may catch the exception and continue."""
    return len(stmts) > 0 and isinstance(stmts[-1], ast.Return)

def always_returns(stmts):
    """Whether the function returns or raises an exception before
    these statements run out, on every path the checker follows: the
    last statement is a return or a raise, an if/else whose branches
    both qualify, a try whose finally qualifies or whose suite and
    clauses all do, or a handle whose body qualifies and whose clauses
    each qualify or end by resuming it. A loop never qualifies."""
    if len(stmts) == 0:
        return False
    last = stmts[-1]
    if isinstance(last, ast.Return) or isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.If):
        return always_returns(last.body) and always_returns(last.orelse)
    if isinstance(last, ast.Try):
        if always_returns(last.finalbody):
            return True
        if not always_returns(last.body):
            return False
        for clause in last.clauses:
            if not always_returns(clause.body):
                return False
        return True
    if isinstance(last, ast.Handle):
        if not always_returns(last.body):
            return False
        for clause in last.clauses:
            if not (always_returns(clause.body)
                    or ends_in_resume(clause)):
                return False
        return True
    return False

def ends_in_resume(clause):
    """Whether the clause's last statement resumes its own binding, so
    the body runs on."""
    if len(clause.body) == 0:
        return False
    last = clause.body[-1]
    if not isinstance(last, ast.ExprStmt):
        return False
    expr = last.expr
    if not isinstance(expr, ast.Resume):
        return False
    return expr.target == clause.binding

class EffectSet(object):
    """The effects a piece of code may perform and the exception classes
    it may raise, each with the line where it was first seen, in order
    of first appearance."""

    def __init__(self):
        self.names = []
        self.linenos = {}

    def add(self, name, lineno):
        if name not in self.linenos:
            self.names.append(name)
            self.linenos[name] = lineno

class Binding(object):
    """What an except clause's name stands for: one operation of one
    effect."""

    def __init__(self, effect, op):
        self.effect = effect  # str
        self.op = op          # OperationDef

class Scope(object):
    """The types of a function's variables, its clause bindings, and
    the names an except clause has deleted."""

    def __init__(self):
        self.types = {}     # variable name -> type name
        self.bindings = {}  # variable name -> Binding
        self.unbound = {}   # variable name -> True

class HandlerInfo(object):
    """A handler class as Pass 1 records it: its fields in declaration
    order, with the count that a constructor call must supply, and the
    union of its methods' effect rows, each less the exception classes
    its operation's row lets the handler throw."""

    def __init__(self, node):
        self.node = node
        self.name = node.name
        self.effect = node.effect
        self.field_names = []  # in declaration order
        self.field_types = {}  # field name -> type name
        self.required = 0      # leading fields without a default
        self.rows = []         # the names in the methods' rows

class Checker(object):

    def __init__(self, module):
        self.module = module
        self.effects = {}     # effect name -> {op name -> OperationDef}
        self.exceptions = {}  # exception class name -> ExceptionDef
        self.handlers = {}    # handler class name -> HandlerInfo
        self.functions = {}   # function name -> FunctionDef
        self.loop_depth = 0   # loops around the statement being checked
        self.boundaries = []  # types at each statement boundary, per suite
        self.loop_exits = []  # types at each break or continue, per loop
        self.fn = None        # the FunctionDef being checked
        self.what = ""        # "function" or "method"

    def check(self):
        self.collect_declarations()
        for fn in self.module.functions:
            self.check_function(fn, "function")
        for handler in self.module.handlers:
            for method in handler.methods:
                self.check_function(method, "method")
        self.check_entry_point()

    # --- pass 1 ------------------------------------------------------------

    def collect_declarations(self):
        for effect in self.module.effects:
            if effect.name in self.effects:
                raise InvalidProgram(
                    effect.lineno,
                    "effect '%s' is declared twice" % effect.name)
            ops = {}
            for op in effect.operations:
                if op.name in ops:
                    raise InvalidProgram(
                        op.lineno, "operation '%s' is declared twice in "
                        "effect '%s'" % (op.name, effect.name))
                ops[op.name] = op
            self.effects[effect.name] = ops
        for exc in self.module.exceptions:
            if (exc.name in self.exceptions or exc.name in self.effects
                    or exc.name == EXCEPTION):
                raise InvalidProgram(
                    exc.lineno,
                    "exception class '%s' is declared twice" % exc.name)
            self.exceptions[exc.name] = exc
        for effect in self.module.effects:
            for op in effect.operations:
                self.check_operation_row(effect, op)
        for handler in self.module.handlers:
            self.collect_handler(handler)
        for fn in self.module.functions:
            if (fn.name in self.functions or fn.name in self.handlers
                    or fn.name in self.exceptions):
                raise InvalidProgram(
                    fn.lineno,
                    "function '%s' is defined twice" % fn.name)
            if fn.name in BUILTINS:
                raise InvalidProgram(
                    fn.lineno, "'%s' is a built-in" % fn.name)
            self.functions[fn.name] = fn
            for name in fn.effect_row:
                self.require_row_name(name, fn.lineno)

    def collect_handler(self, handler):
        if (handler.name in self.handlers or handler.name in self.effects
                or handler.name in self.exceptions):
            raise InvalidProgram(
                handler.lineno,
                "handler class '%s' is declared twice" % handler.name)
        info = HandlerInfo(handler)
        ops = self.require_effect(handler.effect, handler.lineno)
        for field in handler.fields:
            self.collect_field(info, field)
        methods = {}
        for method in handler.methods:
            if method.name in methods:
                raise InvalidProgram(
                    method.lineno, "method '%s' is declared twice in "
                    "handler class '%s'" % (method.name, handler.name))
            methods[method.name] = method
            if method.name not in ops:
                raise InvalidProgram(
                    method.lineno, "method '%s' of handler class '%s' is "
                    "not an operation of %s" %
                    (method.name, handler.name, handler.effect))
            op = ops[method.name]
            self.check_signature(handler, method, op)
            for name in method.effect_row:
                self.require_row_name(name, method.lineno)
                if name not in info.rows and name not in op.row:
                    info.rows.append(name)
        for op in ops.keys():
            if op not in methods:
                raise InvalidProgram(
                    handler.lineno, "handler class '%s' has no method for "
                    "%s.%s" % (handler.name, handler.effect, op))
        self.handlers[handler.name] = info

    def collect_field(self, info, field):
        if field.name in info.field_types:
            raise InvalidProgram(
                field.lineno, "field '%s' is declared twice in handler "
                "class '%s'" % (field.name, info.name))
        if field.type not in FIELD_TYPES and not is_list(field.type):
            raise InvalidProgram(
                field.lineno, "field '%s' of handler class '%s' must be "
                "int, str, or list[...], not %s" %
                (field.name, info.name, field.type))
        if field.default is None:
            if info.required < len(info.field_names):
                raise InvalidProgram(
                    field.lineno, "field '%s' without a default follows a "
                    "field with one" % field.name)
            info.required += 1
        elif isinstance(field.default, ast.IntLiteral):
            self.check_default(field, "int")
        elif isinstance(field.default, ast.StrLiteral):
            self.check_default(field, "str")
        else:
            self.check_default(field, LIST)
        info.field_names.append(field.name)
        info.field_types[field.name] = field.type

    def check_default(self, field, actual):
        if not matches(actual, field.type):
            raise InvalidProgram(
                field.lineno, "default of field '%s' must be %s, not %s" %
                (field.name, field.type, actual))

    def check_signature(self, handler, method, op):
        """The parameters after self and the return type match the
        operation's."""
        what = "method '%s' of handler class '%s'" % (method.name,
                                                      handler.name)
        if (method.params[1:] != op.params
                or method.param_types[1:] != op.param_types):
            raise InvalidProgram(
                method.lineno, "%s must take (self, %s), as %s.%s does" %
                (what, signature(op), handler.effect, op.name))
        if method.return_type != op.return_type:
            raise InvalidProgram(
                method.lineno, "%s must return %s, as %s.%s does" %
                (what, op.return_type, handler.effect, op.name))

    def check_operation_row(self, effect, op):
        """An operation performs nothing, so its row names the exception
        classes a handler may throw into the body, and no effect."""
        for name in op.row:
            if name in self.exceptions:
                continue
            if name == EXCEPTION:
                raise InvalidProgram(
                    op.lineno, "the row of %s.%s names exception classes, "
                    "not Exception" % (effect.name, op.name))
            if name in self.effects:
                what = "an effect"
            else:
                what = "not an exception class"
            raise InvalidProgram(
                op.lineno, "the row of %s.%s names exception classes; "
                "'%s' is %s" % (effect.name, op.name, name, what))

    def require_effect(self, name, lineno):
        if name not in self.effects:
            raise InvalidProgram(lineno, "unknown effect '%s'" % name)
        return self.effects[name]

    def require_row_name(self, name, lineno):
        """A row names the effects and the exception classes that can
        reach the caller, so the catch-all Exception has no place in it."""
        if name == EXCEPTION:
            raise InvalidProgram(
                lineno, "an effect row names exception classes, not "
                "Exception")
        if name not in self.effects and name not in self.exceptions:
            raise InvalidProgram(
                lineno,
                "'%s' is not an effect or an exception class" % name)

    def require_op(self, effect, op, lineno):
        ops = self.require_effect(effect, lineno)
        if op not in ops:
            raise InvalidProgram(
                lineno, "effect '%s' has no operation '%s'" % (effect, op))
        return ops[op]

    # --- pass 2 ------------------------------------------------------------

    def check_function(self, fn, what):
        scope = Scope()
        for i in range(len(fn.params)):
            scope.types[fn.params[i]] = fn.param_types[i]
        effects = EffectSet()
        self.loop_depth = 0
        self.boundaries = []
        self.loop_exits = []
        self.fn = fn
        self.what = what
        self.check_block(fn.body, scope, effects)
        if fn.return_type != "None" and not always_returns(fn.body):
            raise InvalidProgram(
                fn.lineno, "%s '%s' can reach its end without returning "
                "%s" % (what, fn.name, fn.return_type))
        performed = []
        raised = []
        for name in effects.names:
            if name not in fn.effect_row:
                entry = "%s (line %d)" % (name, effects.linenos[name])
                if name in self.exceptions:
                    raised.append(entry)
                else:
                    performed.append(entry)
        undeclared = []
        if len(performed) > 0:
            undeclared.append("performs " + ", ".join(performed))
        if len(raised) > 0:
            undeclared.append("raises " + ", ".join(raised))
        if len(undeclared) > 0:
            raise UnhandledEffectError(
                fn.lineno, "%s '%s' %s without declaring it in its "
                "effect row" % (what, fn.name, ", ".join(undeclared)))

    def check_block(self, stmts, scope, effects):
        for stmt in stmts:
            self.check_stmt(stmt, scope, effects)

    def check_stmt(self, stmt, scope, effects):
        """Check one statement, then record the types it leaves in every
        accumulator around it: a try suite's exception may arrive, and
        a clause's resume() may return to the body, after any
        statement."""
        self.dispatch_stmt(stmt, scope, effects)
        for acc in self.boundaries:
            absorb(acc, scope.types)

    def dispatch_stmt(self, stmt, scope, effects):
        if isinstance(stmt, ast.Return):
            self.check_return(stmt, scope, effects)
        elif isinstance(stmt, ast.If):
            self.type_of(stmt.test, scope, effects)
            self.check_if(stmt, scope, effects)
        elif isinstance(stmt, ast.While):
            self.check_loop_body(stmt.test, stmt.body, scope, effects)
        elif isinstance(stmt, ast.Break):
            self.require_loop(stmt, "'break' outside loop")
            absorb(self.loop_exits[-1], scope.types)
        elif isinstance(stmt, ast.Continue):
            self.require_loop(stmt, "'continue' not properly in loop")
            absorb(self.loop_exits[-1], scope.types)
        elif isinstance(stmt, ast.For):
            iterable = self.type_of(stmt.iterable, scope, effects)
            if iterable == UNKNOWN or iterable == LIST:
                element = UNKNOWN
            elif is_list(iterable):
                element = element_of(iterable)
            else:
                raise InvalidProgram(
                    stmt.lineno,
                    "for needs a list or range(), not %s" % iterable)
            self.check_loop(stmt.name, element, stmt.body, scope, effects)
        elif isinstance(stmt, ast.ForRange):
            self.check_range(stmt.args, stmt.lineno, scope, effects)
            self.check_loop(stmt.name, "int", stmt.body, scope, effects)
        elif isinstance(stmt, ast.Assign):
            actual = self.type_of(stmt.value, scope, effects)
            if self.hand_over(stmt.value, LIST, scope):
                actual = UNKNOWN
            scope.types[stmt.name] = actual
            self.rebind(scope, stmt.name)
        elif isinstance(stmt, ast.AttrAssign):
            info = self.require_instance(scope, stmt.target, stmt.lineno)
            expected = self.require_field(info, stmt.attr, stmt.lineno)
            actual = self.type_of(stmt.value, scope, effects)
            if not matches(actual, expected):
                raise InvalidProgram(
                    stmt.lineno, "field '%s' of handler class '%s' is %s; "
                    "cannot assign %s" % (stmt.attr, info.name, expected,
                                          actual))
            self.hand_over(stmt.value, expected, scope)
        elif isinstance(stmt, ast.IndexAssign):
            element = self.check_index(stmt.target, stmt.index, stmt.lineno,
                                       scope, effects)
            actual = self.type_of(stmt.value, scope, effects)
            if element != UNKNOWN and not matches(actual, element):
                raise InvalidProgram(
                    stmt.lineno, "the list holds %s; cannot assign %s" %
                    (element, actual))
            self.hand_over(stmt.value, element, scope)
        elif isinstance(stmt, ast.ExprStmt):
            self.type_of(stmt.expr, scope, effects)
        elif isinstance(stmt, ast.Pass):
            pass
        elif isinstance(stmt, ast.Handle):
            self.check_handle(stmt, scope, effects)
        elif isinstance(stmt, ast.Raise):
            self.check_raise(stmt, scope, effects)
        elif isinstance(stmt, ast.Try):
            self.check_try(stmt, scope, effects)
        else:
            raise InvalidProgram(stmt.lineno, "unknown statement node")

    def check_if(self, stmt, scope, effects):
        """Each branch starts from the types before the if, and a name
        the branches leave with two types, or that one branch alone
        binds, is unknown afterwards: either branch may have run, so
        the checker cannot hold a later use to one type. A name still
        counts as bound after the if when one branch bound it, since
        the source-order rule reads bindings, not paths."""
        before = scope.types.copy()
        self.check_block(stmt.body, scope, effects)
        body_types = scope.types
        scope.types = before
        self.check_block(stmt.orelse, scope, effects)
        scope.types = merge_types(body_types, scope.types)

    def check_return(self, stmt, scope, effects):
        """The value must have the declared return type; a bare return
        gives None."""
        if stmt.value is None:
            actual = "None"
        else:
            actual = self.type_of(stmt.value, scope, effects)
        expected = self.fn.return_type
        if not matches(actual, expected):
            raise InvalidProgram(
                stmt.lineno, "%s '%s' must return %s, not %s" %
                (self.what, self.fn.name, expected, actual))
        if stmt.value is not None:
            self.hand_over(stmt.value, expected, scope)

    def check_loop(self, name, element, body, scope, effects):
        """The name a for binds is an assignment for the source-order
        rule: it stays bound after the loop."""
        scope.types[name] = element
        self.rebind(scope, name)
        self.check_loop_body(None, body, scope, effects)

    def check_loop_body(self, test, body, scope, effects):
        """Check the test and the body from the types before the loop,
        merge what the body left with them, and check again from the
        merged types until nothing changes, so the body is checked
        against the types a name can have on any iteration and the
        code after the loop sees a name the body reassigns as unknown.
        A break or continue may stand anywhere under a loop in the
        same function, a handle body or a clause included, since the
        runtime carries it out of a stacklet as it carries a return
        (plan 1.10); a method is its own function."""
        self.loop_depth += 1
        before = scope.types.copy()
        exits = before.copy()
        self.loop_exits.append(exits)
        while True:
            if test is not None:
                self.type_of(test, scope, effects)
            self.check_block(body, scope, effects)
            after = merge_types(merge_types(before, scope.types), exits)
            if same_types(after, before):
                break
            before = after
            scope.types = after.copy()
        self.loop_exits.pop()
        scope.types = after
        self.loop_depth -= 1

    def hand_over(self, expr, expected, scope):
        """A name holding [] that a statement hands to a parameter,
        field, return, resume, list, or another name. The receiver may
        append to the list, so the name takes the receiver's list[T]
        type; where the receiver has no element type the name loses
        its type, since the checker does not track which names share
        a list. True when the name lost its type."""
        if not isinstance(expr, ast.Name):
            return False
        if scope.types.get(expr.id, UNKNOWN) != LIST:
            return False
        if expected != LIST and is_list(expected):
            scope.types[expr.id] = expected
            return False
        scope.types[expr.id] = UNKNOWN
        return True

    def require_loop(self, stmt, msg):
        if self.loop_depth == 0:
            raise InvalidProgram(stmt.lineno, msg)

    def check_range(self, args, lineno, scope, effects):
        if len(args) < 1 or len(args) > 2:
            raise InvalidProgram(
                lineno, "range() takes 1 to 2 arguments (%d given)" %
                len(args))
        self.check_args(["start", "stop"][:len(args)], ["int", "int"],
                        args, "range()", lineno, scope, effects)

    def check_index(self, target, index, lineno, scope, effects):
        """The element type of the list target, unknown when the checker
        cannot see it."""
        type_name = self.type_of(target, scope, effects)
        if type_name != UNKNOWN and not is_list(type_name):
            raise InvalidProgram(
                lineno, "%s is not a list" % describe(target, type_name))
        actual = self.type_of(index, scope, effects)
        if not matches(actual, "int"):
            raise InvalidProgram(
                lineno, "a list index must be int, not %s" % actual)
        if type_name == UNKNOWN:
            return UNKNOWN
        return element_of(type_name)

    def check_append(self, target, method, args, lineno, scope, effects):
        """xs.append(v) on a list: the one method a list has. A name
        holding [] takes the element type of the first value appended,
        so the next append must match it."""
        type_name = self.type_of(target, scope, effects)
        if type_name != UNKNOWN and not is_list(type_name):
            raise InvalidProgram(
                lineno, "%s is not a list" % describe(target, type_name))
        if method != "append":
            raise InvalidProgram(
                lineno, "a list has no method '%s'" % method)
        if type_name == UNKNOWN:
            element = UNKNOWN
        else:
            element = element_of(type_name)
        self.check_args(["value"], [element], args, "append()", lineno,
                        scope, effects)
        if type_name == LIST and isinstance(target, ast.Name):
            element = self.type_of(args[0], scope, effects)
            if element != UNKNOWN:
                scope.types[target.id] = "list[%s]" % element
        return "None"

    def check_raise(self, stmt, scope, effects):
        """The row needs the class a raise contributes."""
        name = self.require_exception(stmt.value, scope, effects,
                                      "raise", stmt.lineno)
        effects.add(name, stmt.lineno)

    def require_exception(self, value, scope, effects, what, lineno):
        """The declared exception class that is value's type: a
        constructor call, or a name an except clause bound to that
        class. A name caught as Exception has no class to give."""
        if isinstance(value, ast.OpCall):
            actual = "%s.%s(...)" % (value.effect, value.op)
        elif isinstance(value, ast.Call) and value.func == EXCEPTION:
            actual = EXCEPTION
        else:
            actual = self.type_of(value, scope, effects)
        if actual in self.exceptions:
            return actual
        if actual == EXCEPTION:
            raise InvalidProgram(
                lineno, "%s needs a declared exception class, not "
                "Exception" % what)
        if actual == UNKNOWN:
            actual = "a value of unknown type"
        raise InvalidProgram(
            lineno, "%s needs an exception, not %s" % (what, actual))

    def check_try(self, stmt, scope, effects):
        """The suite's effects, less the classes the clauses catch, plus
        whatever the clauses perform or raise: the formula of a handle
        block with exception classes in place of handled effects. The
        finally suite's effects join unconditionally (plan 1.8).

        A clause may start after any statement of the suite, so it
        starts from the types before the suite merged with the types
        after it, and the code after the try may follow the suite or
        any clause that does not end in a return, so it sees those
        paths merged."""
        body_effects = EffectSet()
        entry = self.check_suite(stmt.body, scope, body_effects)
        after = scope.types
        caught = {}
        for clause in stmt.clauses:
            if (clause.name != EXCEPTION
                    and clause.name not in self.exceptions):
                raise InvalidProgram(
                    clause.lineno,
                    "'%s' is not an exception class" % clause.name)
            caught[clause.name] = True
            scope.types = entry.copy()
            if clause.binding is None:
                self.check_block(clause.body, scope, effects)
            else:
                self.check_named_clause(clause, scope, effects)
            if not ends_in_return(clause.body):
                after = merge_types(after, scope.types)
        scope.types = after
        for name in body_effects.names:
            if name in self.exceptions and (name in caught
                                            or EXCEPTION in caught):
                continue
            effects.add(name, body_effects.linenos[name])
        self.check_block(stmt.finalbody, scope, effects)

    def check_named_clause(self, clause, scope, effects):
        """Check a clause with its name typed as the class it catches.
        Afterwards the name is unbound, as Python 3 leaves it. A
        clause that ends in a return is the exception: no code after
        the try follows it, so the name gets back the type and the
        state it had before the clause."""
        name = clause.binding
        assert name is not None
        old_binding = scope.bindings.get(name, None)
        if old_binding is not None:
            del scope.bindings[name]
        was_unbound = name in scope.unbound
        old_type = scope.types.get(name, None)
        scope.types[name] = clause.name
        self.rebind(scope, name)
        self.check_block(clause.body, scope, effects)
        returns = ends_in_return(clause.body)
        if returns and old_type is not None:
            scope.types[name] = old_type
        elif name in scope.types:
            del scope.types[name]
        if returns and old_binding is not None:
            scope.bindings[name] = old_binding
        if was_unbound or not returns:
            scope.unbound[name] = True

    def check_suite(self, stmts, scope, effects, binding=None, clause=None):
        """Check a suite and give the types at every statement boundary
        in it, the first included: where a try suite's exception may
        arrive, where a handle body's perform() may suspend it, or
        where a clause's resume() may return to the body. With a
        binding the suite is an effect clause's, checked through
        check_effect_clause, and its name is left as that leaves it."""
        acc = scope.types.copy()
        self.boundaries.append(acc)
        if binding is None:
            self.check_block(stmts, scope, effects)
        else:
            self.check_effect_clause(clause, binding, scope, effects)
        self.boundaries.pop()
        if clause is not None:
            name = clause.binding
            if name in scope.types:
                acc[name] = scope.types[name]
            elif name in acc:
                del acc[name]
        return acc

    def check_effect_clause(self, clause, binding, scope, effects):
        """Check the clause with its name bound to the operation, then
        leave the name as answer_with_clause leaves it: what it held
        before the clause, or unbound when it held nothing."""
        name = clause.binding
        old_type = scope.types.get(name, None)
        old_binding = scope.bindings.get(name, None)
        was_unbound = name in scope.unbound
        self.rebind(scope, name)
        scope.bindings[name] = binding
        scope.types[name] = UNKNOWN
        self.check_block(clause.body, scope, effects)
        if old_type is None:
            del scope.types[name]
            scope.unbound[name] = True
        else:
            scope.types[name] = old_type
        if old_binding is None:
            del scope.bindings[name]
        else:
            scope.bindings[name] = old_binding
        if was_unbound:
            scope.unbound[name] = True

    def check_handle(self, stmt, scope, effects):
        """Sort the arguments into effects, which need clauses, and
        handlers, which fulfill their effect; then check the clauses
        cover the effects and nothing the handlers fulfill."""
        fulfilled = {}  # effect name -> handler class name
        handled = []
        for name in stmt.effects:
            if name in self.effects:
                handled.append(name)
            elif scope.types.get(name, UNKNOWN) in self.handlers:
                info = self.handlers[scope.types[name]]
                self.fulfill(fulfilled, info, stmt.lineno)
                stmt.instances.append(name)
            else:
                self.require_bound(scope, name, stmt.lineno)
                raise InvalidProgram(
                    stmt.lineno,
                    "'%s' is not an effect or a handler instance" % name)
        stmt.effects = handled
        for call in stmt.constructions:
            if call.func not in self.handlers:
                raise InvalidProgram(
                    call.lineno,
                    "'%s' is not a handler class" % call.func)
            self.type_of(call, scope, effects)
            self.fulfill(fulfilled, self.handlers[call.func], stmt.lineno)
        for name in handled:
            if name in fulfilled:
                raise InvalidProgram(
                    stmt.lineno, "handle() names %s and a handler class "
                    "for it" % name)
        if len(stmt.clauses) == 0 and len(handled) > 0:
            raise InvalidProgram(
                stmt.lineno, "with handle(%s) outside try needs except "
                "clauses for %s" % (", ".join(handled),
                                    ", ".join(handled)))
        for handler_name in fulfilled.values():
            for name in self.handlers[handler_name].rows:
                effects.add(name, stmt.lineno)
        body_effects = EffectSet()
        entry = scope.types.copy()
        while True:
            after = self.check_handle_suites(stmt, fulfilled, entry, scope,
                                             effects, body_effects)
            widened = merge_types(entry, after)
            if same_types(widened, entry):
                break
            entry = widened
        scope.types = after
        for name in body_effects.names:
            if name not in stmt.effects and name not in fulfilled:
                effects.add(name, body_effects.linenos[name])

    def check_handle_suites(self, stmt, fulfilled, entry, scope, effects,
                            body_effects):
        """One check of the body and the clauses from the entry types,
        giving the types after the statement. A clause runs while the
        body is suspended at any of its performs, so it starts from the
        entry types merged with the body's end types, and the body runs
        on from whatever the clause assigned, which is why check_handle
        checks again from the widened entry until it stops changing.
        The statement ends after the body, or after a clause that does
        not resume or return, so those paths are merged."""
        scope.types = entry.copy()
        clause_entry = self.check_suite(stmt.body, scope, body_effects)
        after = scope.types
        covered = {}
        for clause in stmt.clauses:
            if clause.effect in fulfilled:
                raise InvalidProgram(
                    clause.lineno, "clause for %s.%s, but %s fulfills %s" %
                    (clause.effect, clause.op, fulfilled[clause.effect],
                     clause.effect))
            if clause.effect not in stmt.effects:
                raise InvalidProgram(
                    clause.lineno, "clause for %s.%s, but handle(%s) does "
                    "not name %s" % (clause.effect, clause.op,
                                     ", ".join(stmt.effects), clause.effect))
            op = self.require_op(clause.effect, clause.op, clause.lineno)
            key = clause.effect + "." + clause.op
            if key in covered:
                raise InvalidProgram(
                    clause.lineno, "duplicate clause for %s" % key)
            covered[key] = True
            scope.types = clause_entry.copy()
            resumed = self.check_suite(clause.body, scope, effects,
                                       Binding(clause.effect, op), clause)
            if not ends_in_return(clause.body):
                after = merge_types(after, scope.types)
            after = merge_types(after, resumed)
        missing = []
        for name in stmt.effects:
            for op in self.effects[name].keys():
                if name + "." + op not in covered:
                    missing.append(name + "." + op)
        if len(missing) > 0:
            raise InvalidProgram(
                stmt.lineno, "handle(%s) is missing a clause for %s" %
                (", ".join(stmt.effects), ", ".join(missing)))
        return after

    def fulfill(self, fulfilled, info, lineno):
        if info.effect in fulfilled:
            raise InvalidProgram(
                lineno, "handle() has two handlers for %s" % info.effect)
        fulfilled[info.effect] = info.name

    # --- expressions -------------------------------------------------------

    def type_of(self, expr, scope, effects):
        if isinstance(expr, ast.IntLiteral):
            return "int"
        elif isinstance(expr, ast.StrLiteral):
            return "str"
        elif isinstance(expr, ast.BoolLiteral):
            return "bool"
        elif isinstance(expr, ast.Name):
            self.require_bound(scope, expr.id, expr.lineno)
            return scope.types.get(expr.id, UNKNOWN)
        elif isinstance(expr, ast.ListLiteral):
            element = UNKNOWN
            for item in expr.elements:
                actual = self.type_of(item, scope, effects)
                self.hand_over(item, LIST, scope)
                if element == UNKNOWN:
                    element = actual
                elif actual != UNKNOWN and actual != element:
                    raise InvalidProgram(
                        expr.lineno, "list elements must share a type: "
                        "%s and %s" % (element, actual))
            if element == UNKNOWN:
                return LIST
            return "list[%s]" % element
        elif isinstance(expr, ast.Index):
            return self.check_index(expr.target, expr.index, expr.lineno,
                                    scope, effects)
        elif isinstance(expr, ast.MethodCall):
            return self.check_append(expr.target, expr.method, expr.args,
                                     expr.lineno, scope, effects)
        elif isinstance(expr, ast.BinOp):
            left = self.type_of(expr.left, scope, effects)
            right = self.type_of(expr.right, scope, effects)
            self.check_operands(expr.op, left, right, expr.lineno)
            if left == UNKNOWN:
                return right
            return left
        elif isinstance(expr, ast.Compare):
            left = self.type_of(expr.left, scope, effects)
            right = self.type_of(expr.right, scope, effects)
            self.check_operands(expr.op, left, right, expr.lineno)
            return "bool"
        elif isinstance(expr, ast.Call):
            return self.check_call(expr, scope, effects)
        elif isinstance(expr, ast.Perform):
            op = self.require_op(expr.effect, expr.op, expr.lineno)
            self.check_args(op.params, op.param_types, expr.args,
                            expr.effect + "." + expr.op, expr.lineno,
                            scope, effects)
            effects.add(expr.effect, expr.lineno)
            for name in op.row:
                effects.add(name, expr.lineno)
            return op.return_type
        elif isinstance(expr, ast.OpCall):
            if expr.effect in scope.types:
                return self.check_append(
                    ast.Name(expr.effect, expr.lineno), expr.op, expr.args,
                    expr.lineno, scope, effects)
            raise InvalidProgram(
                expr.lineno, "%s.%s(...) must be the argument of perform()"
                % (expr.effect, expr.op))
        elif isinstance(expr, ast.AttrRead):
            if scope.types.get(expr.target, UNKNOWN) in self.handlers:
                info = self.handlers[scope.types[expr.target]]
                return self.require_field(info, expr.attr, expr.lineno)
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            op = binding.op
            for i in range(len(op.params)):
                if op.params[i] == expr.attr:
                    return op.param_types[i]
            raise InvalidProgram(
                expr.lineno, "operation %s.%s has no parameter '%s'" %
                (binding.effect, op.name, expr.attr))
        elif isinstance(expr, ast.Resume):
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            actual = self.type_of(expr.value, scope, effects)
            expected = binding.op.return_type
            if not matches(actual, expected):
                raise InvalidProgram(
                    expr.lineno, "%s.resume() for %s.%s must pass %s, not %s"
                    % (expr.target, binding.effect, binding.op.name,
                       expected, actual))
            self.hand_over(expr.value, expected, scope)
            return "None"
        elif isinstance(expr, ast.Throw):
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            name = self.require_exception(
                expr.value, scope, effects, "%s.throw()" % expr.target,
                expr.lineno)
            if name not in binding.op.row:
                raise InvalidProgram(
                    expr.lineno, "%s.%s does not declare %s, so "
                    "%s.throw() cannot deliver it" %
                    (binding.effect, binding.op.name, name, expr.target))
            return "None"
        else:
            raise InvalidProgram(expr.lineno, "unknown expression node")

    def check_operands(self, op, left, right, lineno):
        """Both operand types known and not a pair the interpreter's
        binop() or compare() accepts is the runtime error, reported
        early with the runtime's words."""
        if left == UNKNOWN or right == UNKNOWN:
            return
        if is_list(left) and is_list(right):
            if (matches(left, right) or matches(right, left)) and op in OPERATORS[LIST]:
                return
        elif left == right and op in OPERATORS.get(left, []):
            return
        raise InvalidProgram(
            lineno, "unsupported operand types for %s: %s and %s" %
            (op, left, right))

    def check_call(self, expr, scope, effects):
        if expr.func == "print":
            for arg in expr.args:
                self.type_of(arg, scope, effects)
            return "None"
        if expr.func == "len" or expr.func == "str":
            return self.check_builtin(expr, scope, effects)
        if expr.func == "range":
            raise InvalidProgram(
                expr.lineno, "range() is allowed only as the iterable of "
                "a for statement")
        if expr.func in self.handlers:
            return self.check_construction(expr, scope, effects)
        if expr.func in self.exceptions:
            return self.check_exception_call(expr, scope, effects)
        if expr.func not in self.functions:
            raise InvalidProgram(
                expr.lineno, "name '%s' is not defined" % expr.func)
        fn = self.functions[expr.func]
        self.check_args(fn.params, fn.param_types, expr.args,
                        fn.name + "()", expr.lineno, scope, effects)
        for name in fn.effect_row:
            effects.add(name, expr.lineno)
        return fn.return_type

    def check_builtin(self, expr, scope, effects):
        """len() of a list or str is int; str() of a scalar is str."""
        if len(expr.args) != 1:
            raise InvalidProgram(
                expr.lineno, "%s() takes 1 arguments (%d given)" %
                (expr.func, len(expr.args)))
        actual = self.type_of(expr.args[0], scope, effects)
        if expr.func == "len":
            if actual == UNKNOWN or actual == "str" or is_list(actual):
                return "int"
            raise InvalidProgram(
                expr.lineno, "len() needs a list or str, not %s" % actual)
        if actual == UNKNOWN or actual in ["int", "str", "bool"]:
            return "str"
        raise InvalidProgram(
            expr.lineno, "str() needs an int, str, or bool, not %s" % actual)

    def check_construction(self, expr, scope, effects):
        """A handler class's constructor takes its fields in order; the
        trailing ones with defaults may be left out."""
        info = self.handlers[expr.func]
        given = len(expr.args)
        total = len(info.field_names)
        if given < info.required or given > total:
            if info.required == total:
                count = "%d" % total
            else:
                count = "%d to %d" % (info.required, total)
            raise InvalidProgram(
                expr.lineno, "%s() takes %s arguments (%d given)" %
                (expr.func, count, given))
        types = []
        for name in info.field_names[:given]:
            types.append(info.field_types[name])
        self.check_args(info.field_names[:given], types, expr.args,
                        expr.func + "()", expr.lineno, scope, effects)
        return info.name

    def check_exception_call(self, expr, scope, effects):
        """An exception class's constructor takes an optional str
        message."""
        given = len(expr.args)
        if given > 1:
            raise InvalidProgram(
                expr.lineno, "%s() takes 0 to 1 arguments (%d given)" %
                (expr.func, given))
        self.check_args(["message"][:given], ["str"][:given], expr.args,
                        expr.func + "()", expr.lineno, scope, effects)
        return expr.func

    def check_args(self, params, param_types, args, what, lineno,
                   scope, effects):
        if len(args) != len(params):
            raise InvalidProgram(
                lineno, "%s takes %d arguments (%d given)" %
                (what, len(params), len(args)))
        for i in range(len(args)):
            actual = self.type_of(args[i], scope, effects)
            if not matches(actual, param_types[i]):
                raise InvalidProgram(
                    lineno, "argument %d of %s must be %s, not %s" %
                    (i + 1, what, param_types[i], actual))
            self.hand_over(args[i], param_types[i], scope)

    def rebind(self, scope, name):
        """An assignment or a loop binding gives the name a value that
        is no clause binding, whatever it held before."""
        if name in scope.unbound:
            del scope.unbound[name]
        if name in scope.bindings:
            del scope.bindings[name]

    def require_bound(self, scope, name, lineno):
        """A read needs a parameter, an assignment, or a clause that
        bound the name earlier in the function's source: every one of
        those puts the name in scope.types. Python 3 deletes the name
        of an except clause when the clause ends, and exec_try does the
        same, so a read after the clause is an error too, until
        something binds the name again, whether or not the clause would
        run. check_named_clause leaves out a clause that ends in a
        return. The walk is in source order, so a read that an
        assignment later in a loop body would satisfy at runtime is
        rejected."""
        if name in scope.unbound:
            raise InvalidProgram(
                lineno, "name '%s' is unbound after the except clause "
                "that bound it" % name)
        if name not in scope.types:
            raise InvalidProgram(
                lineno, "name '%s' is not defined" % name)

    def require_binding(self, scope, name, lineno):
        self.require_bound(scope, name, lineno)
        if name not in scope.bindings:
            raise InvalidProgram(
                lineno, "'%s' is not an except binding or a handler "
                "instance" % name)
        return scope.bindings[name]

    def require_instance(self, scope, name, lineno):
        self.require_bound(scope, name, lineno)
        type_name = scope.types.get(name, UNKNOWN)
        if type_name not in self.handlers:
            raise InvalidProgram(
                lineno, "'%s' is not a handler instance" % name)
        return self.handlers[type_name]

    def require_field(self, info, attr, lineno):
        if attr not in info.field_types:
            raise InvalidProgram(
                lineno, "handler class '%s' has no field '%s'" %
                (info.name, attr))
        return info.field_types[attr]

    # --- pass 3 ------------------------------------------------------------

    def check_entry_point(self):
        if "main" not in self.functions:
            raise InvalidProgram(0, "no main() function defined")
        main = self.functions["main"]
        if len(main.params) > 0:
            raise InvalidProgram(main.lineno, "main() takes no parameters")
        if len(main.effect_row) > 0:
            raise UnhandledEffectError(
                main.lineno, "main() must have an empty effect row, not "
                "[%s]" % ", ".join(main.effect_row))

def describe(target, type_name):
    """'xs' for a name, 'self.entries' for a field, and the type for
    anything else, in a 'is not a list' message."""
    if isinstance(target, ast.Name):
        return "'%s'" % target.id
    if isinstance(target, ast.AttrRead):
        return "'%s.%s'" % (target.target, target.attr)
    return "a value of type %s" % type_name

def signature(op):
    """name: type, name: type for an operation's parameters."""
    parts = []
    for i in range(len(op.params)):
        parts.append("%s: %s" % (op.params[i], op.param_types[i]))
    return ", ".join(parts)

def check(module):
    """Run all three passes; raise on the first mistake found."""
    Checker(module).check()
