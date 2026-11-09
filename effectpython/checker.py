"""The static effect checker (plan 2.2).

check() runs three passes over a parsed module before anything runs.
Pass 1 collects the effect declarations, the exception classes, the
handler classes, and the function signatures, so a function body can
call a function defined later or itself, and checks each handler
class against the effect it fulfills: one method per operation with
the operation's signature after self (check_signature), and typed
fields. Pass 2 walks each function and method body and infers the
effects it may perform: a perform() contributes its effect, a call
contributes the callee's declared row, and a handle block removes
the effects it names or fulfills from its body's set and adds
whatever its clauses and its handlers' methods perform. The result
must be a subset of the declared row, or the function fails with an
UnhandledEffectError. Pass 3 requires a main() with an empty row.

An exception class sits in the same set as an effect (plan 1.6). A
raise contributes the class of its value, a try/except removes the
classes its clauses catch from its suite's set and adds whatever the
clauses perform or raise, and main()'s empty row makes an exception
nobody catches a static error. An operation's row names the
exception classes a handler may throw into the body with eff.throw()
(plan 1.7), so a perform() contributes those classes beside its
effect, and eff.throw() must name one of them. A handler method's
row carries its exceptions to the function that installs the
handler, less the classes its operation's row declares, which a
method raising one of them delivers to the perform instead.

A type is a type name, and the checker types every expression. A
handler class name is the type of its instances, so a name holding
one may be passed to handle() and its fields read; an exception
class name is the type of the name an except clause binds;
"list[int]", "list[str]", and "list[bool]" are the list types (plan
1.9) and "dict[str, int]", "dict[str, str]", and "dict[str, bool]"
the dict types (plan 1.12), the element or value being one of the
three scalars, so a list literal, an append, a dict literal, or a
store refuses a list or dict value. A field is int, str, a list type,
or a dict type (plan 1.5, 1.9, 1.12). The empty string stands for a
type the checker cannot determine, and an unknown type matches
anything (matches). "list" is the type of [] alone and "dict" of {}
alone: each matches any type of its kind, and a literal with an
element or value of unknown type has the unknown type, so nothing
refines it as a [] or {} is refined. A dict's keys are str, in a
literal, a subscript, a store, and an in test (check_dict_literal,
check_index, check_index_assign, check_membership); x in xs needs a
value of the list's element type; and in gives bool. A for over a
list binds its name to the element type, over a dict to str, and
over range() to int. len(), str(), and range() are built-in names
beside print, and a function cannot take one of them. An f-string
is str, and each of its fields is int, str, or bool, as str() takes
(check_fstring). An augmented assignment to a name or a field
arrives as the assignment it means, so x += 1 needs x bound and
the pair x, 1 under OPERATORS; xs[i] op= v is an IndexAugAssign,
whose element type and value go to check_operands with the element
on the left (check_index_aug_assign, plan 1.14). For two lists
the checker requires one element type, which the runtime does not:
it compares them and finds the elements unequal; dicts have no
operator.

An operator whose operands both have known types must have a pair
the interpreter supports (OPERATORS), so the runtime's "unsupported
operand types" error is reached through an operand of unknown type.
The operands of and, or, and not, and the test of an if or a while,
must be bool where their types are known (require_bool, plan 1.11),
with the runtime's words: "and needs a bool, not int". The three
operators give bool. Both operands of and and or are typed and their
effects counted, though the runtime may skip the right one, since
the row must cover whatever it would perform. An elif is a nested if
from the parser on, so check_if merges each arm in turn.

A known type is the type the value has at runtime. The one way it
could be wrong was an unknown value handed to a typed slot: a
parameter, a return, a field, a constructor argument, a resume(), an
append, or an indexed assignment, where matches would have accepted
it and the receiver would have held the declared type for a value
the checker never saw. A typed slot therefore refuses a value of
unknown type (require_known), as "argument 1 of f() must be int, but
'x' has no known type", and an append of one to a [] leaves the list
with no known type. A value of unknown type may still be printed,
measured with len(), converted with str() or an f-string field,
indexed, iterated, compared, and used as an operand, where the
runtime keeps the check.
A name holding [] that a statement hands to a slot of type list[T]
takes list[T], since the receiver may append to it (hand_over). One
assigned to another name loses its type: the checker does not track
which names share a list, so an append through either name would
leave the other with a stale type.

A return value must have the function's declared return type, and a
bare return has the type None (check_return). A function whose
return type is not None must return or raise an exception on every
path the checker follows (always_returns): its last statement is a
return or a raise, an if/else whose branches both qualify, a try
whose finally qualifies or whose suite and clauses all do, or a
handle whose body qualifies and whose clauses each qualify or end by
resuming it. A loop never qualifies, so a function that returns from
inside one needs a return after it. A handler method's return type
equals its operation's, so the rule covers the value a perform()
gets from a method.

A read of a name that nothing has bound earlier in the function's
source is rejected, and so is a read of the name a try statement's
except clause bound, after the clause, until something binds it
again, since the clause deletes its name when it ends
(require_bound). The walk follows source order, as the typing does,
and does not ask whether the clause would run: a name one path bound
counts as bound, and the first pass over a loop or a handled body
uses the types before it, so a statement there that is right only
through a later reassignment, or through a clause's, is rejected on
that pass. A clause that ends in a return is the exception to the
deletion: the code after the try cannot follow it, so the name keeps
the type and the state it had before, while the try's own finally
suite, which does follow it, sees the name unbound (check_try). An
effect clause (except E.op as eff) leaves its name as the runtime
does (check_effect_clause): after the handle statement the name is
unbound when nothing bound it before, and otherwise has the type it
had before.

Where two paths meet, the types they left are merged (merge_types):
a name they leave with two types, or that one path alone binds, is
unknown, while a [] that one path refined to list[T] keeps the
refinement (merged). The branches of an if are two such paths
(check_if). A loop body is checked from the types before the loop,
what it leaves at its end and at each break or continue is merged
with them, and it is checked again from the merged types until
nothing changes (check_loop_body), so the code after the loop sees a
name the body gives another type as unknown, and a type the body can
carry into a later iteration is unknown on the next pass over the
body; a pass that unbinds a name is followed by another too, so a
read earlier in the body meets the unbound name (same_names). The
name a for binds is bound afresh to the element type at the start of
every pass, as every iteration binds it, and is the exception to the
one-path rule afterwards: it has the element type merged with the
type it had before, or the element type alone when it had none,
since an unbound name fails at runtime whatever its type
(check_loop). A try's clauses start from the types at every
statement boundary of its suite, the first included, since the
exception may arrive after any statement (check_suite), and the code
after the try sees the suite's end merged with the end of every
clause that does not return (check_try), while a finally suite is
checked from every boundary of the suite and of each clause, since
it runs on every path out of them, and then from the continuing
paths, types and bound names both, for the code after it. A handle
statement's clauses start from every boundary of its body, where a
perform() may suspend it, and the body runs on from any boundary of
a clause where resume() may stand. What the clauses did on one pass
(Pending: the names they retyped, through scope.written, with the
merge of their types, and the names they unbound) is applied on the
next pass at every perform point of the body and of the clauses,
where a clause may run before the suspended code continues: a
perform(), a call to a function whose row names an effect, and a
clause's resume() or throw() (widen_at_perform). The passes repeat
until the clauses change nothing more (check_handle,
check_handle_suites). Widening at the perform rather than at the
body's entry keeps a read before the first perform() at the type
the body gave the name, and a read after it at the widened type,
whatever the body assigned in between: until 2026-11-09 the entry
rule let a body assignment after the entry hide the clause's
retyping (tests/programs/runtime_clause_after_assign.epy). The
body's own end state is not fed back, since a resume does not
restart the body.

A break or continue outside a loop of the same function is rejected
with "'break' outside loop" or "'continue' not properly in loop"
(plan 1.10). The count is loop_depth, which check_loop_body
increments around every loop suite and check_function resets.

The checker dispatches by isinstance over the ast_nodes classes, as
the evaluator does, so adding a node means adding a branch in both.
"""
from effectpython import ast_nodes as ast
from effectpython.errors import InvalidProgram, UnhandledEffectError

UNKNOWN = ""
LIST = "list"
DICT = "dict"
SCALARS = ["int", "str", "bool"]
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

def is_dict(type_name):
    return type_name == DICT or type_name.startswith("dict[")

def is_empty(type_name):
    """Whether the type is that of a [] or a {}, which the first store
    refines."""
    return type_name == LIST or type_name == DICT

def container_of(type_name):
    """The list[T] or dict[str, T] type a [] or {} takes for T."""
    if type_name.startswith("list"):
        return "list[%s]"
    return "dict[str, %s]"

def value_of(type_name):
    """The value type of dict[str, T], or unknown for a bare dict."""
    if type_name == DICT:
        return UNKNOWN
    assert type_name.startswith("dict[str, ")
    end = len(type_name) - 1
    assert end >= 10
    return type_name[10:end]

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
    if actual == LIST:
        return is_list(expected)
    return actual == DICT and is_dict(expected)

def merged(a, b):
    """The type a name has where two paths meet and left it with types
    a and b: the one type, the list[T] that refines a [], or
    unknown."""
    if a == b:
        return a
    if is_empty(a) and matches(a, b):
        return b
    if is_empty(b) and matches(b, a):
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

def same_names(a, b):
    """Whether two unbound sets name the same names: a pass over a loop
    body or a handled body that unbinds a name must be followed by
    another, since a read earlier in the suite is now a read of an
    unbound name, whether or not the types changed."""
    if len(a) != len(b):
        return False
    for name in a:
        if name not in b:
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
        self.written = {}   # variable name -> True, since the last reset

    def set_type(self, name, type_name):
        """Every retyping of a name goes through here, so check_handle
        can tell which names a clause changed."""
        self.types[name] = type_name
        self.written[name] = True

class Pending(object):
    """What the clauses of a handle statement did on the pass before
    the one being checked: the names they retyped, with the merge of
    their types, and the names they left unbound. The body and the
    clauses take these at every perform point (widen_at_perform)."""

    def __init__(self, changed, carried):
        self.changed = changed  # variable name -> type name
        self.carried = carried  # variable name -> True

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
        self.handles = []     # Pending of each enclosing handle statement
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
        if (field.type not in FIELD_TYPES and not is_list(field.type)
                and not is_dict(field.type)):
            raise InvalidProgram(
                field.lineno, "field '%s' of handler class '%s' must be "
                "int, str, list[...], or dict[str, ...], not %s" %
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
        elif isinstance(field.default, ast.DictLiteral):
            self.check_default(field, DICT)
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
        self.handles = []
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
            self.require_bool(self.type_of(stmt.test, scope, effects),
                              "if", stmt.lineno)
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
            elif is_dict(iterable):
                element = "str"
            else:
                raise InvalidProgram(
                    stmt.lineno,
                    "for needs a list, a dict, or range(), not %s" %
                    iterable)
            self.check_loop(stmt.name, element, stmt.body, scope, effects)
        elif isinstance(stmt, ast.ForRange):
            self.check_range(stmt.args, stmt.lineno, scope, effects)
            self.check_loop(stmt.name, "int", stmt.body, scope, effects)
        elif isinstance(stmt, ast.Assign):
            actual = self.type_of(stmt.value, scope, effects)
            if self.hand_over(stmt.value, LIST, scope):
                actual = UNKNOWN
            scope.set_type(stmt.name, actual)
            self.rebind(scope, stmt.name)
        elif isinstance(stmt, ast.AttrAssign):
            info = self.require_instance(scope, stmt.target, stmt.lineno)
            expected = self.require_field(info, stmt.attr, stmt.lineno)
            actual = self.type_of(stmt.value, scope, effects)
            self.require_known(
                stmt.value, actual, expected,
                "field '%s' of handler class '%s' must be %s" %
                (stmt.attr, info.name, expected), stmt.lineno)
            if not matches(actual, expected):
                raise InvalidProgram(
                    stmt.lineno, "field '%s' of handler class '%s' is %s; "
                    "cannot assign %s" % (stmt.attr, info.name, expected,
                                          actual))
            self.hand_over(stmt.value, expected, scope)
        elif isinstance(stmt, ast.IndexAssign):
            self.check_index_assign(stmt, scope, effects)
        elif isinstance(stmt, ast.IndexAugAssign):
            self.check_index_aug_assign(stmt, scope, effects)
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
        self.require_known(
            stmt.value, actual, expected, "%s '%s' must return %s" %
            (self.what, self.fn.name, expected), stmt.lineno)
        if not matches(actual, expected):
            raise InvalidProgram(
                stmt.lineno, "%s '%s' must return %s, not %s" %
                (self.what, self.fn.name, expected, actual))
        if stmt.value is not None:
            self.hand_over(stmt.value, expected, scope)

    def check_loop(self, name, element, body, scope, effects):
        """The name a for binds is an assignment for the source-order
        rule: it stays bound after the loop. Over an empty list it
        keeps the value it had before, so afterwards it has that type
        merged with the element type."""
        old_type = scope.types.get(name, None)
        self.bind_element(scope, name, element)
        self.check_loop_body(None, body, scope, effects, name, element)
        if old_type is not None:
            scope.types[name] = merged(old_type, scope.types[name])

    def bind_element(self, scope, name, element):
        scope.set_type(name, element)
        self.rebind(scope, name)

    def check_loop_body(self, test, body, scope, effects, name=None,
                        element=UNKNOWN):
        """Check the test and the body from the types before the loop,
        merge what the body left with them, and check again from the
        merged types until nothing changes, so the body is checked
        against the types a name can have on any iteration and the
        code after the loop sees a name the body gives another type as
        unknown. A for binds its name afresh on every iteration, so
        each pass starts with the name bound to the element type,
        whatever the body did to it.
        A break or continue may stand anywhere under a loop in the
        same function, a handle body or a clause included, since the
        runtime carries it out of a stacklet as it carries a return
        (plan 1.10); a method is its own function."""
        self.loop_depth += 1
        before = scope.types.copy()
        exits = before.copy()
        self.loop_exits.append(exits)
        while True:
            unbound = scope.unbound.copy()
            if name is not None:
                self.bind_element(scope, name, element)
            if test is not None:
                self.require_bool(self.type_of(test, scope, effects),
                                  "while", test.lineno)
            self.check_block(body, scope, effects)
            after = merge_types(merge_types(before, scope.types), exits)
            if (same_types(after, before)
                    and same_names(scope.unbound, unbound)):
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
        held = scope.types.get(expr.id, UNKNOWN)
        if not is_empty(held):
            return False
        if not is_empty(expected) and matches(held, expected):
            scope.set_type(expr.id, expected)
            return False
        scope.set_type(expr.id, UNKNOWN)
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
        """The element type of the list target or the value type of the
        dict target, unknown when the checker cannot see it; a list
        takes an int index and a dict a str key."""
        type_name = self.type_of(target, scope, effects)
        if is_dict(type_name):
            actual = self.type_of(index, scope, effects)
            if not matches(actual, "str"):
                raise InvalidProgram(
                    lineno, "a dict key must be str, not %s" % actual)
            return value_of(type_name)
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

    def check_index_assign(self, stmt, scope, effects):
        """xs[i] = v or d[k] = v: the value must have the element or the
        value type, and the first store into a name holding {} gives it
        the dict type, as the first append gives a [] its type. The
        value is typed first, as the runtime evaluates it first, so a
        clause that rebinds the container during the value's perform
        is seen at the target."""
        actual = self.type_of(stmt.value, scope, effects)
        element = self.check_index(stmt.target, stmt.index, stmt.lineno,
                                   scope, effects)
        kind = kind_of(self.type_of(stmt.target, scope, EffectSet()))
        slot = "an element"
        if kind == "dict":
            slot = "a value"
        self.require_known(stmt.value, actual, element,
                           "%s of the %s must be %s" % (slot, kind, element),
                           stmt.lineno)
        if element != UNKNOWN and not matches(actual, element):
            raise InvalidProgram(
                stmt.lineno, "the %s holds %s; cannot assign %s" %
                (kind, element, actual))
        if is_list(actual) or is_dict(actual):
            raise InvalidProgram(
                stmt.lineno, "dict values must be int, str, or bool, not "
                "a %s" % kind_of(actual))
        self.hand_over(stmt.value, element, scope)
        target = stmt.target
        if (isinstance(target, ast.Name)
                and scope.types.get(target.id, UNKNOWN) == DICT):
            if actual == UNKNOWN:
                scope.set_type(target.id, UNKNOWN)
            else:
                scope.set_type(target.id, "dict[str, %s]" % actual)

    def check_index_aug_assign(self, stmt, scope, effects):
        """xs[i] op= v or d[k] op= v: the element or value type on the
        left and the value on the right must be a pair the operator
        takes. The result has the element's type, so the store needs
        no rule of its own, and {} gets no refinement, since a key
        must hold a value before anything is added to it."""
        element = self.check_index(stmt.target, stmt.index, stmt.lineno,
                                   scope, effects)
        actual = self.type_of(stmt.value, scope, effects)
        self.check_operands(stmt.op, element, actual, stmt.lineno)

    def check_fstring(self, expr, scope, effects):
        """Each field is int, str, or bool, as str() takes, or unknown,
        and its effects count; the result is str."""
        for field in expr.exprs:
            actual = self.type_of(field, scope, effects)
            if actual != UNKNOWN and actual not in SCALARS:
                raise InvalidProgram(
                    expr.lineno, "an f-string field needs an int, str, or "
                    "bool, not %s" % actual)
        return "str"

    def check_dict_literal(self, expr, scope, effects):
        """{k: v, ...}: str keys and values of one scalar type; a value
        of unknown type makes the literal unknown, as it does a list
        literal (plan 1.12)."""
        value = UNKNOWN
        untyped = False
        for i in range(len(expr.keys)):
            key = self.type_of(expr.keys[i], scope, effects)
            if not matches(key, "str"):
                raise InvalidProgram(
                    expr.lineno, "dict keys must be str, not %s" % key)
            actual = self.type_of(expr.values[i], scope, effects)
            if is_list(actual) or is_dict(actual):
                raise InvalidProgram(
                    expr.lineno, "dict values must be int, str, or bool, "
                    "not a %s" % kind_of(actual))
            if actual == UNKNOWN:
                untyped = True
            elif value == UNKNOWN:
                value = actual
            elif actual != value:
                raise InvalidProgram(
                    expr.lineno, "dict values must share a type: %s and %s"
                    % (value, actual))
        if untyped:
            return UNKNOWN
        if value == UNKNOWN:
            return DICT
        return "dict[str, %s]" % value

    def check_membership(self, expr, scope, effects):
        """k in d or x in xs (plan 1.12): a str key against a dict, or a
        value of the element type against a list, giving bool."""
        left = self.type_of(expr.left, scope, effects)
        right = self.type_of(expr.right, scope, effects)
        if is_dict(right):
            expected = "str"
        elif is_list(right):
            expected = element_of(right)
        elif right == UNKNOWN:
            return "bool"
        else:
            raise InvalidProgram(
                expr.lineno, "in needs a list or dict, not %s" % right)
        if not matches(left, expected):
            raise InvalidProgram(
                expr.lineno, "%s holds %s; cannot test %s" %
                (describe(expr.right, right), expected, left))
        return "bool"

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
        actual = self.type_of(args[0], scope, effects)
        if is_list(actual) or is_dict(actual):
            raise InvalidProgram(
                lineno, "list elements must be int, str, or bool, not a "
                "%s" % kind_of(actual))
        if type_name == LIST and isinstance(target, ast.Name):
            if actual == UNKNOWN:
                scope.set_type(target.id, UNKNOWN)
            else:
                scope.set_type(target.id, "list[%s]" % actual)
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
        starts from the types at every boundary of the suite, and the
        code after the try may follow the suite or any clause that
        does not end in a return, so it sees those paths merged. The
        finally suite may follow any boundary of the suite or of a
        clause, a return or an exception included, so it is checked
        first from all of them merged, with the name of a clause that
        returned unbound, since exec_clauses deleted it, and then
        again from the paths that continue, for the code after it,
        with the bound names those paths left, since the first check
        may have unbound a name in the finally suite."""
        body_effects = EffectSet()
        entry = self.check_suite(stmt.body, scope, body_effects)
        after = scope.types
        into_finally = entry.copy()
        absorb(into_finally, after)
        returned = []
        caught = {}
        for clause in stmt.clauses:
            if (clause.name != EXCEPTION
                    and clause.name not in self.exceptions):
                raise InvalidProgram(
                    clause.lineno,
                    "'%s' is not an exception class" % clause.name)
            caught[clause.name] = True
            scope.types = entry.copy()
            boundaries = self.check_suite(clause.body, scope, effects,
                                          None, None, clause)
            if ends_in_return(clause.body):
                if clause.binding is not None:
                    returned.append(clause.binding)
            else:
                after = merge_types(after, scope.types)
            absorb(into_finally, boundaries)
        for name in body_effects.names:
            if name in self.exceptions and (name in caught
                                            or EXCEPTION in caught):
                continue
            effects.add(name, body_effects.linenos[name])
        if len(stmt.finalbody) > 0:
            unbound = scope.unbound.copy()
            scope.types = into_finally
            for name in returned:
                scope.unbound[name] = True
            self.check_block(stmt.finalbody, scope, effects)
            scope.unbound = unbound
            scope.types = after
            self.check_block(stmt.finalbody, scope, effects)
        else:
            scope.types = after

    def check_named_clause(self, clause, scope, effects):
        """Check a clause with its name typed as the class it catches.
        Afterwards the name is unbound, as Python 3 leaves it. A
        clause that ends in a return is the exception: no code after
        the try follows it, so the name gets back the type and the
        state it had before the clause; check_try unbinds it again
        while it checks the finally suite, which does follow."""
        name = clause.binding
        assert name is not None
        old_binding = scope.bindings.get(name, None)
        if old_binding is not None:
            del scope.bindings[name]
        was_unbound = name in scope.unbound
        old_type = scope.types.get(name, None)
        scope.set_type(name, clause.name)
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

    def check_suite(self, stmts, scope, effects, binding=None, clause=None,
                    except_clause=None):
        """Check a suite and give the types at every statement boundary
        in it, the first included: where a try suite's exception may
        arrive, where a handle body's perform() may suspend it, or
        where a clause's resume() may return to the body. With a
        clause the suite is an effect clause's, checked through
        check_effect_clause, and with an except_clause a try's, checked
        through check_named_clause when it binds a name; the name is
        left as those leave it."""
        acc = scope.types.copy()
        self.boundaries.append(acc)
        name = None
        if clause is not None:
            name = clause.binding
            self.check_effect_clause(clause, binding, scope, effects)
        elif except_clause is not None and except_clause.binding is not None:
            name = except_clause.binding
            self.check_named_clause(except_clause, scope, effects)
        else:
            self.check_block(stmts, scope, effects)
        self.boundaries.pop()
        if name is not None:
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
        scope.set_type(name, UNKNOWN)
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
        cover the effects and nothing the handlers fulfill. The sort
        reads the instances of an earlier pass too, since a suite is
        checked more than once and the first pass moved them."""
        fulfilled = {}  # effect name -> handler class name
        handled = []
        instances = []
        for name in stmt.effects + stmt.instances:
            if name in self.effects:
                handled.append(name)
            elif scope.types.get(name, UNKNOWN) in self.handlers:
                info = self.handlers[scope.types[name]]
                self.fulfill(fulfilled, info, stmt.lineno)
                instances.append(name)
            else:
                self.require_bound(scope, name, stmt.lineno)
                raise InvalidProgram(
                    stmt.lineno,
                    "'%s' is not an effect or a handler instance" % name)
        stmt.effects = handled
        stmt.instances = instances
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
        entry_unbound = scope.unbound.copy()
        pending = Pending({}, {})
        while True:
            changed = pending.changed.copy()
            carried = pending.carried.copy()
            scope.unbound = entry_unbound.copy()
            self.handles.append(pending)
            after = self.check_handle_suites(stmt, fulfilled, entry, scope,
                                             effects, body_effects, changed,
                                             carried)
            self.handles.pop()
            if (same_types(changed, pending.changed)
                    and same_names(carried, pending.carried)):
                break
            pending = Pending(changed, carried)
        scope.types = after
        for name in body_effects.names:
            if name not in stmt.effects and name not in fulfilled:
                effects.add(name, body_effects.linenos[name])

    def widen_at_perform(self, scope):
        """A perform() suspends the body, and before it continues a
        clause of any enclosing handle statement may run, so each
        name a clause retyped on the previous pass takes the merge of
        its type here and the clause's, and each name a clause unbound
        is unbound, unless it is a live clause binding, which the
        runtime restores when the clause that rebound it ends; a read
        typed after this point in evaluation order sees the change. A
        clause's resume() or throw() and a call to a function whose
        row names an effect are points too, since the body runs on
        and the callee performs (plan 2.2)."""
        for pending in self.handles:
            for name in pending.changed:
                if name in scope.types:
                    scope.types[name] = merged(scope.types[name],
                                               pending.changed[name])
            for name in pending.carried:
                if name not in scope.bindings:
                    scope.unbound[name] = True

    def check_handle_suites(self, stmt, fulfilled, entry, scope, effects,
                            body_effects, changed, carried):
        """One check of the body and the clauses from the entry types,
        giving the types after the statement. A clause runs while the
        body is suspended at any of its performs, so it starts from the
        types at every boundary of the body, and the body runs on from
        whatever the clause assigned, which widen_at_perform applies
        at every perform point from the previous pass's Pending, and
        check_handle checks again until nothing more changes: changed
        collects the names a clause retyped (scope.written) with their
        type at any clause boundary, and carried the names a clause
        left unbound, each accumulated over the passes. The body's own end
        state is not fed back, since a resume continues the body where
        it stopped and does not restart it. The statement ends after
        the body or after a clause, so its end merges the body's end,
        the end of every clause that does not end in a return (a
        resuming one included, since a resume that is not the last
        statement returns into the clause), and every clause
        boundary."""
        scope.types = entry.copy()
        clause_entry = self.check_suite(stmt.body, scope, body_effects)
        after = scope.types
        body_unbound = scope.unbound.copy()
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
            written = scope.written
            scope.written = {}
            resumed = self.check_suite(clause.body, scope, effects,
                                       Binding(clause.effect, op), clause)
            for name in scope.written:
                if name in resumed:
                    changed[name] = merged(changed.get(name, resumed[name]),
                                           resumed[name])
                written[name] = True
            scope.written = written
            if not ends_in_return(clause.body):
                after = merge_types(after, scope.types)
            after = merge_types(after, resumed)
        for name in scope.unbound:
            if name not in body_unbound:
                carried[name] = True
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
            untyped = False
            for item in expr.elements:
                actual = self.type_of(item, scope, effects)
                if is_list(actual) or is_dict(actual):
                    raise InvalidProgram(
                        expr.lineno, "list elements must be int, str, or "
                        "bool, not a %s" % kind_of(actual))
                if actual == UNKNOWN:
                    untyped = True
                elif element == UNKNOWN:
                    element = actual
                elif actual != element:
                    raise InvalidProgram(
                        expr.lineno, "list elements must share a type: "
                        "%s and %s" % (element, actual))
            if untyped:
                return UNKNOWN
            if element == UNKNOWN:
                return LIST
            return "list[%s]" % element
        elif isinstance(expr, ast.DictLiteral):
            return self.check_dict_literal(expr, scope, effects)
        elif isinstance(expr, ast.FString):
            return self.check_fstring(expr, scope, effects)
        elif isinstance(expr, ast.In):
            return self.check_membership(expr, scope, effects)
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
        elif isinstance(expr, ast.BoolOp):
            self.require_bool(self.type_of(expr.left, scope, effects),
                              expr.op, expr.lineno)
            self.require_bool(self.type_of(expr.right, scope, effects),
                              expr.op, expr.lineno)
            return "bool"
        elif isinstance(expr, ast.Not):
            self.require_bool(self.type_of(expr.operand, scope, effects),
                              "not", expr.lineno)
            return "bool"
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
            self.widen_at_perform(scope)
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
            self.require_known(
                expr.value, actual, expected,
                "%s.resume() for %s.%s must pass %s" %
                (expr.target, binding.effect, binding.op.name, expected),
                expr.lineno)
            if not matches(actual, expected):
                raise InvalidProgram(
                    expr.lineno, "%s.resume() for %s.%s must pass %s, not %s"
                    % (expr.target, binding.effect, binding.op.name,
                       expected, actual))
            self.hand_over(expr.value, expected, scope)
            self.widen_at_perform(scope)
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
            self.widen_at_perform(scope)
            return "None"
        else:
            raise InvalidProgram(expr.lineno, "unknown expression node")

    def require_bool(self, actual, what, lineno):
        """An if or while test and an operand of and, or, or not must
        be bool where the type is known (plan 1.11), with the
        runtime's words."""
        if actual != UNKNOWN and actual != "bool":
            raise InvalidProgram(
                lineno, "%s needs a bool, not %s" % (what, actual))

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
        for name in fn.effect_row:
            if name in self.effects:
                self.widen_at_perform(scope)
                break
        return fn.return_type

    def check_builtin(self, expr, scope, effects):
        """len() of a list or str is int; str() of a scalar is str."""
        if len(expr.args) != 1:
            raise InvalidProgram(
                expr.lineno, "%s() takes 1 arguments (%d given)" %
                (expr.func, len(expr.args)))
        actual = self.type_of(expr.args[0], scope, effects)
        if expr.func == "len":
            if (actual == UNKNOWN or actual == "str" or is_list(actual)
                    or is_dict(actual)):
                return "int"
            raise InvalidProgram(
                expr.lineno, "len() needs a list, dict, or str, not %s" %
                actual)
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
            self.require_known(args[i], actual, param_types[i],
                               "argument %d of %s must be %s" %
                               (i + 1, what, param_types[i]), lineno)
            if not matches(actual, param_types[i]):
                raise InvalidProgram(
                    lineno, "argument %d of %s must be %s, not %s" %
                    (i + 1, what, param_types[i], actual))
            self.hand_over(args[i], param_types[i], scope)

    def require_known(self, expr, actual, expected, demand, lineno):
        """A typed slot refuses a value of unknown type: were it
        accepted, the receiver would hold the declared type for a
        value the checker never saw, the one way a known type could be
        wrong at runtime (settled 2026-11-08). The demand reads
        "argument 1 of f() must be int"."""
        if actual == UNKNOWN and expected != UNKNOWN:
            raise InvalidProgram(
                lineno, "%s, but %s has no known type" %
                (demand, value_name(expr)))

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

def kind_of(type_name):
    """'list' or 'dict' for a container type, in a message about an
    element that cannot be one."""
    if is_list(type_name):
        return "list"
    return "dict"

def value_name(expr):
    """'x' for a name, 'self.n' for a field, and 'the value' for
    anything else, in a 'has no known type' message."""
    if isinstance(expr, ast.Name):
        return "'%s'" % expr.id
    if isinstance(expr, ast.AttrRead):
        return "'%s.%s'" % (expr.target, expr.attr)
    return "the value"

def signature(op):
    """name: type, name: type for an operation's parameters."""
    parts = []
    for i in range(len(op.params)):
        parts.append("%s: %s" % (op.params[i], op.param_types[i]))
    return ", ".join(parts)

def check(module):
    """Run all three passes; raise on the first mistake found."""
    Checker(module).check()
