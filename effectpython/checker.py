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
store refuses a list or dict value. A field is int, str, bool, a list
type, or a dict type (plan 1.5, 1.9, 1.12, 1.19). The empty string stands for a
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

None is a type and a value, and int | None, str | None, and
bool | None are the optional types (plan 1.16). A slot of type
T | None takes a T, a None, or the optional (matches), and a name
two paths leave as a scalar T and as None is T | None where the
paths meet (merged), so the lattice has one level between a type and
unknown. An optional is refused wherever a T is wanted: a typed
slot, an operator, == included, a subscript, len(), str(), an
f-string field, a for, and a test; print() takes it. A list element
or a dict value is no None and no optional (require_scalar). The
test `name is None` or `name is not None` of an if retypes a local
name for each branch (narrow): None where it is None, and T in the
other for a T | None. A test says the same through not, through and
where it is true, and through or where it is false (facts), and what
it says applies to the branches of an if, to the body of a while, and
to the right operand of and and or, which runs only where the left
one has not decided (plan 1.18). A name that a perform point later in
the test widens, because a clause assigns it, loses its fact for the
statement (widen_back). Where the name's type is None the other branch
cannot run under these types, so it is checked with the name unknown
and kept out of the types after the if, as a branch that leaves is;
the first pass over a loop meets `best = None` before it that way
(tests/programs/optional_value.epy). The guard `if x is None:
return` needs no rule of its own, since the branch leaves. Narrowing
is a retyping on a path, so a perform point in a narrowed branch
widens the name again where a clause assigns it.

A tuple type is tuple[T1, T2, ...] with two or more of the three
scalars, and the literal (a, b) has the type its elements give it
(plan 1.17). It matches itself alone and its optional. a, b = t
needs a tuple with as many elements as names and gives each name
its element's type (check_unpack). t[0] takes an int literal, which
names one element and so one type (tuple_element). A tuple takes no
operator, len(), for, in, str(), or f-string field, is no element of
a list, a dict, or a tuple (require_scalar) and no field, and takes
no store (require_mutable); print() takes it. A value of unknown
type may be unpacked, and the runtime counts its elements.

A data class is a class of fields under @dataclass, recorded as a
handler class is, with no effect (plan 1.19). Its name is the type
of its instances, so a constructor call, a field read, and a field
store go through the rules a handler class has (info_of), and
handle() refuses an instance, since check_handle reads the handler
classes alone. An instance may be a list element or a dict value, and
C | None is the optional of a class C (can_be_absent), which narrowing
serves with no rule of its own. The parser takes any name in list[T],
dict[str, T], and T | None, and Pass 1 holds each such type written
in a signature or a field to a scalar or a data class
(require_type). An instance has no operator, so == on two lists of
them and in on one are refused where the element type is known
(comparable). A field read on a name of unknown type is left to the
runtime, as a subscript is, so the first pass over a loop may read
best.pages where `best = None` stands before it; a field store is a
typed slot and needs the class. A field read or store through an
expression that is no name, ts[0].name, is a FieldRead or a
FieldAssign with the same rules (check_field_read,
check_field_assign; plan 1.20).

A method call is chosen by the method's name (check_method, plan
1.21): s.join(xs) needs a str and a list[str] and is a str;
d.get(k, default) has the dict's value type and d.get(k) its
optional; xs.append(v) is the list's. ** takes two ints and gives
one; the runtime refuses a negative exponent. A for over d.items()
binds a str and the dict's value type (check_items_loop, plan 1.22).
A call by name may end in keyword arguments (check_keyword_call,
plan 1.23): each argument is typed in the order written against the
parameter or field it goes to, and a class may leave out any field
that has a default.

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
(check_if), unless one ends in a return, continue, break, or raise:
the code after the if then has the other branch's types, and a name
the leaving branch alone binds is unknown (plan 1.15). A loop body
is checked from the types before the loop, what it leaves at its
end and at each break or continue is merged with them, and it is
checked again from the merged types until
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
clause that does not end in a return, continue, break, or raise
(check_try, leaves), with a name unknown that a clause ending in one
of the last three alone binds, since the paths such a clause takes
are recorded where the statement stands (plan 1.15), while a
finally suite is checked from every boundary of the suite and of
each clause, since
it runs on every path out of them, and then from the continuing
paths, types and bound names both, for the code after it. Under a
loop the types the first check leaves also join the loop's exits,
since a break or continue in the suite or a clause leaves through
the finally suite after recording its own types
(tests/programs/unreachable_finally_continue.epy). A handle
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

Where an operator, a test, a subscript, or len() or str() meets an
operand of unknown type, the checker lets it pass and the runtime
judges it. Checker.unknowns records each such place as
line * KINDS + kind, for a test or a script to read; nothing prints
it. A suite checked more than once would count more than once, and a
pass before the last may meet an unknown the last one resolves, so
each pass of check_loop_body and of check_handle notes the length of
the list when it starts and, when another pass follows, cuts the
list back to it (_drop_unknowns): an inner loop's last pass is
dropped with the outer pass around it. The two checks of a finally
suite are both paths that run, and neither starts from wider types
than the other, since a [] one boundary refined may reach the end
unrefined, so both count, less what the second repeats
(_drop_repeats).

The checker dispatches by isinstance over the ast_nodes classes, as
the evaluator does, so adding a node means adding a branch in both.
"""
from effectpython import ast_nodes as ast
from effectpython.errors import InvalidProgram, UnhandledEffectError

UNKNOWN = ""
LIST = "list"
DICT = "dict"
SCALARS = ["int", "str", "bool"]
OPERATORS = {
    "int": ["+", "-", "*", "//", "%", "**", "<", "<=", ">", ">=", "==",
            "!="],
    "str": ["+", "==", "!="],
    "bool": ["==", "!="],
    LIST: ["==", "!="],
}
BUILTINS = ["print", "len", "str", "range"]
EXCEPTION = "Exception"
NONE = "None"
OPTIONAL = " | None"
OPERANDS = 0
BOOL = 1
INDEX = 2
BUILTIN = 3
KINDS = 4

def is_list(type_name):
    return type_name == LIST or type_name.startswith("list[")

def is_dict(type_name):
    return type_name == DICT or type_name.startswith("dict[")

def is_tuple(type_name):
    return type_name.startswith("tuple[") and not is_optional(type_name)

def elements_of(type_name):
    """The element types of tuple[T1, T2, ...] (plan 1.17)."""
    end = len(type_name) - 1
    assert end >= 6
    return type_name[6:end].split(", ")

def can_be_absent(type_name):
    """Whether T | None is a type: a scalar (plan 1.16), a tuple
    (plan 1.17), or a class name (plan 1.19), which is any type that
    is no list, dict, optional, None, or unknown. A handler class
    and an exception class qualify beside a data class: no table is
    at hand here to tell them apart, and the type is true of the
    value."""
    return not (type_name == UNKNOWN or type_name == NONE
                or is_optional(type_name) or is_list(type_name)
                or is_dict(type_name))

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

def is_optional(type_name):
    return type_name.endswith(OPTIONAL)

def base_of(type_name):
    """The T of the optional type T | None."""
    end = len(type_name) - len(OPTIONAL)
    assert end >= 0
    return type_name[:end]

def matches(actual, expected):
    """Whether a value of the actual type may stand where the expected
    type is wanted: an unknown type matches anything, [] matches any
    list, and T and None match T | None (plan 1.16)."""
    if actual == UNKNOWN or expected == UNKNOWN or actual == expected:
        return True
    if is_optional(expected):
        return actual == NONE or actual == base_of(expected)
    if actual == LIST:
        return is_list(expected)
    return actual == DICT and is_dict(expected)

def merged(a, b):
    """The type a name has where two paths meet and left it with types
    a and b: the one type, the list[T] that refines a [], the
    optional T | None of None and a T that is a scalar (plan 1.16)
    or a tuple (plan 1.17), or unknown."""
    if a == b:
        return a
    if a == NONE and can_be_absent(b):
        return b + OPTIONAL
    if b == NONE and can_be_absent(a):
        return a + OPTIONAL
    if is_optional(a) and (b == NONE or b == base_of(a)):
        return a
    if is_optional(b) and (a == NONE or a == base_of(b)):
        return b
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

def leaves(stmts):
    """Whether no path runs from the end of these statements to the
    statement after the enclosing one, though code later in the
    function may still run: the last is a continue, a break, or a
    raise (plan 1.15). The last statement alone is read, as
    ends_in_return reads it."""
    if len(stmts) == 0:
        return False
    last = stmts[-1]
    return (isinstance(last, ast.Continue) or isinstance(last, ast.Break)
            or isinstance(last, ast.Raise))

def keep_bound(types, left):
    """Enter each name bound at the end of a path that leaves, and
    absent from the types of the paths that continue, with the unknown
    type: a later pass of a loop may reach the read with the name
    bound, and the source-order rule reads bindings, not paths."""
    for name in left:
        if name not in types:
            types[name] = UNKNOWN

class Fact(object):
    """A local name with whether a test says it is None (plan 1.18)."""

    def __init__(self, name, is_none):
        self.name = name
        self.is_none = is_none

def facts(test, when):
    """What a test says about its names where it evaluates to when:
    `x is None` says x is None where it is True and is not where it
    is False; not swaps the two; `a and b` says what both say where
    it is True, and `a or b` where it is False, and neither says
    anything on its other side, where either operand may have
    decided (plan 1.18)."""
    if isinstance(test, ast.IsNone):
        operand = test.operand
        if isinstance(operand, ast.Name):
            return [Fact(operand.id, test.negated != when)]
        return []
    if isinstance(test, ast.Not):
        return facts(test.operand, not when)
    if isinstance(test, ast.BoolOp) and (test.op == "and") == when:
        return facts(test.left, when) + facts(test.right, when)
    return []

class Narrowing(object):
    """The names a list of facts retyped, each with its type before
    and after, and whether a fact ruled the path out."""

    def __init__(self):
        self.names = []
        self.before = []
        self.after = []
        self.dead = False

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
    its operation's row lets the handler throw. A data class (plan
    1.19) is recorded the same way, with no effect and no rows, and
    kind is the word a message calls the class by."""

    def __init__(self, name, effect, kind):
        self.name = name
        self.effect = effect
        self.kind = kind       # "handler class" or "data class"
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
        self.records = {}     # data class name -> HandlerInfo
        self.functions = {}   # function name -> FunctionDef
        self.loop_depth = 0   # loops around the statement being checked
        self.boundaries = []  # types at each statement boundary, per suite
        self.loop_exits = []  # types at each break or continue, per loop
        self.spoiled = {}     # names a perform in the test widened
        self.handles = []     # Pending of each enclosing handle statement
        self.fn = None        # the FunctionDef being checked
        self.what = ""        # "function" or "method"
        self.unknowns = []    # line * KINDS + kind, per unknown operand

    def _note_unknown(self, kind, lineno):
        self.unknowns.append(lineno * KINDS + kind)

    def _drop_unknowns(self, mark):
        """Forget what a pass noted when another pass follows it."""
        assert mark >= 0
        del self.unknowns[mark:]

    def _drop_repeats(self, first, second):
        """Of what the second check of a suite noted, from second on,
        keep what the first, from first to second, did not."""
        assert first >= 0
        assert second >= first
        seen = {}
        for site in self.unknowns[first:second]:
            seen[site] = True
        fresh = []
        for site in self.unknowns[second:]:
            if site not in seen:
                fresh.append(site)
        del self.unknowns[second:]
        for site in fresh:
            self.unknowns.append(site)

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
        for record in self.module.records:
            if (record.name in self.records or record.name in self.effects
                    or record.name in self.exceptions):
                raise InvalidProgram(
                    record.lineno,
                    "data class '%s' is declared twice" % record.name)
            self.records[record.name] = HandlerInfo(record.name, "",
                                                    "data class")
        for record in self.module.records:
            for field in record.fields:
                self.collect_field(self.records[record.name], field)
        for effect in self.module.effects:
            for op in effect.operations:
                self.check_operation_row(effect, op)
                self.require_types(op.param_types, op.return_type,
                                   op.lineno)
        for handler in self.module.handlers:
            self.collect_handler(handler)
        for fn in self.module.functions:
            if (fn.name in self.functions or fn.name in self.handlers
                    or fn.name in self.exceptions
                    or fn.name in self.records):
                raise InvalidProgram(
                    fn.lineno,
                    "function '%s' is defined twice" % fn.name)
            if fn.name in BUILTINS:
                raise InvalidProgram(
                    fn.lineno, "'%s' is a built-in" % fn.name)
            self.functions[fn.name] = fn
            for name in fn.effect_row:
                self.require_row_name(name, fn.lineno)
            self.require_types(fn.param_types, fn.return_type, fn.lineno)

    def require_types(self, param_types, return_type, lineno):
        for type_name in param_types:
            self.require_type(type_name, lineno)
        self.require_type(return_type, lineno)

    def require_type(self, type_name, lineno):
        """A written list[T], dict[str, T], or T | None names int,
        str, bool, or a data class for T: the parser takes any name
        there, since it cannot tell a data class from a misspelling
        (plan 1.19). A tuple's optional was held to scalars by the
        parser, and a plain name is left as written."""
        if is_optional(type_name):
            inner = base_of(type_name)
            if is_tuple(inner):
                return
            what = "the optional types are int | None, str | None, " \
                   "bool | None, tuple[...] | None, and a data class | None"
        elif type_name.startswith("list["):
            inner = element_of(type_name)
            what = "the element type is int, str, bool, or a data class"
        elif type_name.startswith("dict["):
            inner = value_of(type_name)
            what = "the value type is int, str, bool, or a data class"
        else:
            return
        if inner not in SCALARS and inner not in self.records:
            raise InvalidProgram(
                lineno, "%s is not a type; %s" % (type_name, what))

    def info_of(self, type_name):
        """The handler class or data class a type names, or None."""
        if type_name in self.handlers:
            return self.handlers[type_name]
        return self.records.get(type_name, None)

    def collect_handler(self, handler):
        if (handler.name in self.handlers or handler.name in self.effects
                or handler.name in self.exceptions
                or handler.name in self.records):
            raise InvalidProgram(
                handler.lineno,
                "handler class '%s' is declared twice" % handler.name)
        info = HandlerInfo(handler.name, handler.effect, "handler class")
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
                field.lineno, "field '%s' is declared twice in %s '%s'"
                % (field.name, info.kind, info.name))
        if (field.type not in SCALARS and not is_list(field.type)
                and not is_dict(field.type)):
            raise InvalidProgram(
                field.lineno, "field '%s' of %s '%s' must be int, str, "
                "bool, list[...], or dict[str, ...], not %s" %
                (field.name, info.kind, info.name, field.type))
        self.require_type(field.type, field.lineno)
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
        elif isinstance(field.default, ast.BoolLiteral):
            self.check_default(field, "bool")
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
        self.spoiled = {}
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
        elif isinstance(stmt, ast.ForItems):
            self.check_items_loop(stmt, scope, effects)
        elif isinstance(stmt, ast.ForRange):
            self.check_range(stmt.args, stmt.lineno, scope, effects)
            self.check_loop(stmt.name, "int", stmt.body, scope, effects)
        elif isinstance(stmt, ast.Assign):
            actual = self.type_of(stmt.value, scope, effects)
            if self.hand_over(stmt.value, LIST, scope):
                actual = UNKNOWN
            scope.set_type(stmt.name, actual)
            self.rebind(scope, stmt.name)
        elif isinstance(stmt, ast.Unpack):
            self.check_unpack(stmt, scope, effects)
        elif isinstance(stmt, ast.AttrAssign):
            info = self.require_instance(scope, stmt.target, stmt.lineno)
            expected = self.require_field(info, stmt.attr, stmt.lineno)
            actual = self.type_of(stmt.value, scope, effects)
            self.require_known(
                stmt.value, actual, expected,
                "field '%s' of %s '%s' must be %s" %
                (stmt.attr, info.kind, info.name, expected), stmt.lineno)
            if not matches(actual, expected):
                raise InvalidProgram(
                    stmt.lineno, "field '%s' of %s '%s' is %s; "
                    "cannot assign %s" % (stmt.attr, info.kind, info.name,
                                          expected, actual))
            self.hand_over(stmt.value, expected, scope)
        elif isinstance(stmt, ast.FieldAssign):
            self.check_field_assign(stmt, scope, effects)
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

    def check_field_assign(self, stmt, scope, effects):
        """target.attr = value through an expression (plan 1.20): the
        value is typed first, as the runtime evaluates it first, and
        the target must be an instance of a class the checker knows,
        since a store is a typed slot. The augmented form types the
        target first and holds the field and the value to the
        operator."""
        actual = UNKNOWN
        if stmt.op == "":
            actual = self.type_of(stmt.value, scope, effects)
        held = self.type_of(stmt.target, scope, effects)
        info = self.info_of(held)
        if info is None:
            if held == UNKNOWN:
                held = "a value of unknown type"
            raise InvalidProgram(
                stmt.lineno, "a field store needs an instance, not %s"
                % held)
        expected = self.require_field(info, stmt.attr, stmt.lineno)
        if stmt.op != "":
            actual = self.type_of(stmt.value, scope, effects)
            self.check_operands(stmt.op, expected, actual, stmt.lineno)
            return
        self.require_known(
            stmt.value, actual, expected,
            "field '%s' of %s '%s' must be %s" %
            (stmt.attr, info.kind, info.name, expected), stmt.lineno)
        if not matches(actual, expected):
            raise InvalidProgram(
                stmt.lineno, "field '%s' of %s '%s' is %s; "
                "cannot assign %s" % (stmt.attr, info.kind, info.name,
                                      expected, actual))
        self.hand_over(stmt.value, expected, scope)

    def check_field_read(self, expr, scope, effects):
        """target.attr through an expression (plan 1.20): the field's
        type where the target is an instance, unknown where the
        target is, and CPython's words for any other type."""
        held = self.type_of(expr.target, scope, effects)
        info = self.info_of(held)
        if info is not None:
            return self.require_field(info, expr.attr, expr.lineno)
        if held == UNKNOWN:
            self._note_unknown(INDEX, expr.lineno)
            return UNKNOWN
        if is_optional(held):
            raise InvalidProgram(
                expr.lineno, "the value is %s; a field read needs a "
                "test against None first" % held)
        raise InvalidProgram(
            expr.lineno, "'%s' object has no attribute '%s'" %
            (held, expr.attr))

    def check_if(self, stmt, scope, effects):
        """Each branch starts from the types before the if, and a name
        the branches leave with two types, or that one branch alone
        binds, is unknown afterwards: either branch may have run, so
        the checker cannot hold a later use to one type. A name still
        counts as bound after the if when one branch bound it, since
        the source-order rule reads bindings, not paths. A branch
        whose last statement is a return, continue, break, or raise
        does not reach the code after the if, which then has the
        other branch's types, with a name the leaving branch alone
        binds unknown (plan 1.15); two such branches are merged as
        before, since no path is left to take the types from. What
        the test says about a name and None where it is true retypes
        the name for the body, and what it says where it is false for
        the other branch (facts, narrow; plan 1.16, 1.18); the names
        a perform point in the test spoiled are those of the test
        just typed, taken before the body's statements empty the
        list."""
        spoiled = self.spoiled
        before = scope.types.copy()
        body_left = self.narrow(facts(stmt.test, True), scope,
                                spoiled).dead
        self.check_block(stmt.body, scope, effects)
        body_types = scope.types
        scope.types = before
        else_left = self.narrow(facts(stmt.test, False), scope,
                                spoiled).dead
        self.check_block(stmt.orelse, scope, effects)
        if leaves(stmt.body) or ends_in_return(stmt.body):
            body_left = True
        if leaves(stmt.orelse) or ends_in_return(stmt.orelse):
            else_left = True
        if body_left and not else_left:
            keep_bound(scope.types, body_types)
        elif else_left and not body_left:
            keep_bound(body_types, scope.types)
            scope.types = body_types
        else:
            scope.types = merge_types(body_types, scope.types)

    def narrow(self, found, scope, spoiled):
        """Retype the name of each fact for the path the facts hold
        on (plan 1.16, 1.18): None where the name is None, if it was
        optional or unknown, and T where a T | None is not None. A
        name whose type is None cannot be on a path that says it is
        not, so the answer is marked dead, for check_if and
        check_loop_body to keep that path out of the types after the
        statement, and the name is unknown while the path is
        checked: the first pass over a loop meets `best = None`
        before it that way, and the pass after it has the optional.
        This is no assignment, so it does not go through set_type;
        a clause binding or a handler instance is left alone, and so
        is a name a perform point in the test has spoiled."""
        result = Narrowing()
        for fact in found:
            name = fact.name
            if (name not in scope.types or name in scope.bindings
                    or name in spoiled):
                continue
            current = scope.types[name]
            if fact.is_none:
                if current != UNKNOWN and not is_optional(current):
                    continue
                retyped = NONE
            elif is_optional(current):
                retyped = base_of(current)
            elif current == NONE:
                retyped = UNKNOWN
                result.dead = True
            else:
                continue
            scope.types[name] = retyped
            result.names.append(name)
            result.before.append(current)
            result.after.append(retyped)
        return result

    def widen_back(self, narrowing, scope):
        """Give the names an operand was narrowed for their types
        back. A name whose type is no longer the narrowed one met a
        perform point inside the operand, where a clause assigns it
        (widen_at_perform), so it takes the merge of the type it had
        and the type it has, and its fact holds no longer: the name
        is spoiled for the rest of the statement (plan 1.18)."""
        for i in range(len(narrowing.names)):
            name = narrowing.names[i]
            current = scope.types[name]
            if current == narrowing.after[i]:
                scope.types[name] = narrowing.before[i]
            else:
                scope.types[name] = merged(narrowing.before[i], current)
                self.spoiled[name] = True

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

    def check_items_loop(self, stmt, scope, effects):
        """for k, v in d.items() (plan 1.22): the key is str and the
        value the dict's value type, unknown for a {} nothing has
        refined or a target of unknown type, which the runtime holds
        to a dict. Both names are bound on every pass and merged
        with what they held before afterwards, as check_loop does
        for one."""
        held = self.type_of(stmt.target, scope, effects)
        if is_dict(held):
            value = value_of(held)
        elif held == UNKNOWN:
            value = UNKNOWN
        else:
            raise InvalidProgram(
                stmt.lineno, "items() needs a dict on the left of the "
                "dot, not %s" % held)
        old_key = scope.types.get(stmt.key, None)
        old_value = scope.types.get(stmt.value, None)
        self.bind_element(scope, stmt.key, "str")
        self.bind_element(scope, stmt.value, value)
        self.check_loop_body(None, stmt.body, scope, effects, stmt.key,
                             "str", stmt.value, value)
        if old_key is not None:
            scope.types[stmt.key] = merged(old_key, scope.types[stmt.key])
        if old_value is not None:
            scope.types[stmt.value] = merged(old_value,
                                             scope.types[stmt.value])

    def bind_element(self, scope, name, element):
        scope.set_type(name, element)
        self.rebind(scope, name)

    def check_loop_body(self, test, body, scope, effects, name=None,
                        element=UNKNOWN, second=None,
                        second_element=UNKNOWN):
        """Check the test and the body from the types before the loop,
        merge what the body left with them, and check again from the
        merged types until nothing changes, so the body is checked
        against the types a name can have on any iteration and the
        code after the loop sees a name the body gives another type as
        unknown. A for binds its name afresh on every iteration, so
        each pass starts with the name bound to the element type,
        whatever the body did to it; a for over d.items() binds a
        second name the same way (plan 1.22).
        A break or continue may stand anywhere under a loop in the
        same function, a handle body or a clause included, since the
        runtime carries it out of a stacklet as it carries a return
        (plan 1.10); a method is its own function.
        What a while test says where it is true retypes its names for
        the body on every pass (plan 1.18). A body the test's facts
        rule out, `while x is not None:` for an x of type None, is
        checked and then left out: the types before the loop stand
        for the pass, with the names the body bound, and the loop's
        exits are those from before it."""
        self.loop_depth += 1
        before = scope.types.copy()
        exits = before.copy()
        self.loop_exits.append(exits)
        while True:
            mark = len(self.unknowns)
            unbound = scope.unbound.copy()
            if name is not None:
                self.bind_element(scope, name, element)
            if second is not None:
                self.bind_element(scope, second, second_element)
            dead = False
            if test is not None:
                self.spoiled = {}
                self.require_bool(self.type_of(test, scope, effects),
                                  "while", test.lineno)
                dead = self.narrow(facts(test, True), scope,
                                   self.spoiled).dead
            if dead:
                exits = exits.copy()
            self.check_block(body, scope, effects)
            if dead:
                self.loop_exits[-1] = exits
                after = before.copy()
                keep_bound(after, scope.types)
            else:
                after = merge_types(merge_types(before, scope.types),
                                    exits)
            if (same_types(after, before)
                    and same_names(scope.unbound, unbound)):
                break
            self._drop_unknowns(mark)
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
        if is_tuple(type_name):
            return self.tuple_element(type_name, index, lineno)
        if type_name != UNKNOWN and not is_list(type_name):
            raise InvalidProgram(
                lineno, "%s is not a list" % describe(target, type_name))
        actual = self.type_of(index, scope, effects)
        if not matches(actual, "int"):
            raise InvalidProgram(
                lineno, "a list index must be int, not %s" % actual)
        if type_name == UNKNOWN:
            self._note_unknown(INDEX, lineno)
            return UNKNOWN
        return element_of(type_name)

    def tuple_element(self, type_name, index, lineno):
        """t[0] on a tuple: the index is an int literal, so that it
        names one element and one type, and a negative one counts
        from the end (plan 1.17)."""
        if not isinstance(index, ast.IntLiteral):
            raise InvalidProgram(
                lineno, "a tuple index must be an int literal")
        elements = elements_of(type_name)
        i = index.value
        if i < 0:
            i += len(elements)
        if i < 0 or i >= len(elements):
            raise InvalidProgram(lineno, "tuple index out of range")
        return elements[i]

    def require_mutable(self, target, scope, lineno):
        """A store through a subscript needs a list or a dict; a tuple
        takes none, in the runtime's words (plan 1.17)."""
        if is_tuple(self.type_of(target, scope, EffectSet())):
            raise InvalidProgram(
                lineno, "'tuple' object does not support item assignment")

    def check_unpack(self, stmt, scope, effects):
        """a, b = value: the value is a tuple with as many elements as
        there are names, and each name takes its element's type; a
        value of unknown type leaves the names unknown and the count
        to the runtime (plan 1.17)."""
        actual = self.type_of(stmt.value, scope, effects)
        count = len(stmt.names)
        if actual == UNKNOWN:
            types = [UNKNOWN] * count
        elif is_tuple(actual):
            types = elements_of(actual)
            if len(types) != count:
                raise InvalidProgram(
                    stmt.lineno, "cannot unpack %s into %d names" %
                    (actual, count))
        else:
            raise InvalidProgram(
                stmt.lineno, "cannot unpack %s; the value must be a "
                "tuple" % actual)
        for i in range(count):
            scope.set_type(stmt.names[i], types[i])
            self.rebind(scope, stmt.names[i])

    def check_index_assign(self, stmt, scope, effects):
        """xs[i] = v or d[k] = v: the value must have the element or the
        value type, and the first store into a name holding {} gives it
        the dict type, as the first append gives a [] its type. The
        value is typed first, as the runtime evaluates it first, so a
        clause that rebinds the container during the value's perform
        is seen at the target."""
        actual = self.type_of(stmt.value, scope, effects)
        self.require_mutable(stmt.target, scope, stmt.lineno)
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
        if kind == "list" and not (is_list(actual) or is_dict(actual)
                                   or is_tuple(actual)):
            self.require_scalar(actual, "list elements", stmt.lineno)
        else:
            self.require_scalar(actual, "dict values", stmt.lineno)
        self.hand_over(stmt.value, element, scope)
        target = stmt.target
        if (isinstance(target, ast.Name)
                and scope.types.get(target.id, UNKNOWN) == DICT):
            if actual == UNKNOWN:
                scope.set_type(target.id, UNKNOWN)
            else:
                scope.set_type(target.id, "dict[str, %s]" % actual)

    def require_scalar(self, actual, what, lineno):
        """A list element or a dict value is an int, str, or bool where
        its type is known, and so is a tuple element: no list or
        dict (plan 1.9, 1.12), no None or optional, which no element
        type names (plan 1.16), and no tuple (plan 1.17)."""
        if is_list(actual) or is_dict(actual) or is_tuple(actual):
            raise InvalidProgram(
                lineno, "%s must be int, str, or bool, not a %s" %
                (what, kind_of(actual)))
        if actual == NONE or is_optional(actual):
            raise InvalidProgram(
                lineno, "%s must be int, str, or bool, not %s" %
                (what, actual))

    def check_index_aug_assign(self, stmt, scope, effects):
        """xs[i] op= v or d[k] op= v: the element or value type on the
        left and the value on the right must be a pair the operator
        takes. The result has the element's type, so the store needs
        no rule of its own, and {} gets no refinement, since a key
        must hold a value before anything is added to it."""
        self.require_mutable(stmt.target, scope, stmt.lineno)
        element = self.check_index(stmt.target, stmt.index, stmt.lineno,
                                   scope, effects)
        actual = self.type_of(stmt.value, scope, effects)
        self.check_operands(stmt.op, element, actual, stmt.lineno)

    def check_fstring(self, expr, scope, effects):
        """Each field is int, str, or bool, as str() takes, or unknown,
        and its effects count; the result is str."""
        for field in expr.exprs:
            if isinstance(field, ast.Formatted):
                self.check_formatted(field, scope, effects)
                continue
            actual = self.type_of(field, scope, effects)
            if actual != UNKNOWN and actual not in SCALARS:
                raise InvalidProgram(
                    expr.lineno, "an f-string field needs an int, str, or "
                    "bool, not %s" % actual)
        return "str"

    def check_formatted(self, field, scope, effects):
        """{expr:spec} (plan 1.24): an int or a str, since Python
        formats a bool with a spec as the int it is, and the type
        letter must be the value's, in CPython's words. A value of
        unknown type is left to the runtime."""
        actual = self.type_of(field.value, scope, effects)
        if actual == UNKNOWN:
            return
        if actual != "int" and actual != "str":
            raise InvalidProgram(
                field.lineno, "a format spec needs an int or str, not %s"
                % actual)
        if ((field.kind == "d" and actual == "str")
                or (field.kind == "s" and actual == "int")):
            raise InvalidProgram(
                field.lineno, "Unknown format code '%s' for object of "
                "type '%s'" % (field.kind, actual))

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
            self.require_scalar(actual, "dict values", expr.lineno)
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
        if is_list(right) and not comparable(expected):
            raise InvalidProgram(
                expr.lineno, "in compares int, str, or bool elements, "
                "not %s" % expected)
        return "bool"

    def check_method(self, target, method, args, lineno, scope, effects):
        """A method call, chosen by the method's name: s.join(xs),
        d.get(k) or d.get(k, default), and xs.append(v) (plan 1.21).
        Any other name is refused by check_append, in the words of
        the target's kind."""
        if method == "join":
            return self.check_join(target, args, lineno, scope, effects)
        if method == "get":
            return self.check_get(target, args, lineno, scope, effects)
        return self.check_append(target, method, args, lineno, scope,
                                 effects)

    def check_join(self, target, args, lineno, scope, effects):
        """s.join(xs): a str on the left, a list[str] argument, and
        a str result. A target of unknown type is left to the
        runtime and noted."""
        held = self.type_of(target, scope, effects)
        if held == UNKNOWN:
            self._note_unknown(BUILTIN, lineno)
        elif held != "str":
            raise InvalidProgram(
                lineno, "join() needs a str on the left of the dot, "
                "not %s" % held)
        self.check_args(["words"], ["list[str]"], args, "join()", lineno,
                        scope, effects)
        return "str"

    def check_get(self, target, args, lineno, scope, effects):
        """d.get(k, default) has the dict's value type, which the
        default must have, and d.get(k) its optional, since a missing
        key gives None. The result has no known type where the
        dict's value type has none: a target of unknown type, which
        is noted, or a {} nothing has refined."""
        held = self.type_of(target, scope, effects)
        if held == UNKNOWN:
            self._note_unknown(BUILTIN, lineno)
        elif not is_dict(held):
            raise InvalidProgram(
                lineno, "get() needs a dict on the left of the dot, "
                "not %s" % held)
        if len(args) < 1 or len(args) > 2:
            raise InvalidProgram(
                lineno, "get() takes 1 to 2 arguments (%d given)" %
                len(args))
        key = self.type_of(args[0], scope, effects)
        if not matches(key, "str"):
            raise InvalidProgram(
                lineno, "a dict key must be str, not %s" % key)
        value = UNKNOWN
        if is_dict(held):
            value = value_of(held)
        if len(args) == 1:
            if value == UNKNOWN:
                return UNKNOWN
            return value + OPTIONAL
        actual = self.type_of(args[1], scope, effects)
        if value == UNKNOWN:
            return UNKNOWN
        self.require_known(args[1], actual, value,
                           "the default of get() must be %s" % value,
                           lineno)
        if not matches(actual, value):
            raise InvalidProgram(
                lineno, "the default of get() must be %s, not %s" %
                (value, actual))
        return value

    def check_append(self, target, method, args, lineno, scope, effects):
        """xs.append(v) on a list: the one method a list has. A name
        holding [] takes the element type of the first value appended,
        so the next append must match it. A method that no kind has
        is refused here, by the target's kind where it is a str or a
        dict."""
        type_name = self.type_of(target, scope, effects)
        if method != "append" and type_name == "str":
            raise InvalidProgram(
                lineno, "a str has no method '%s'" % method)
        if method == "items" and is_dict(type_name):
            raise InvalidProgram(
                lineno, "items() is allowed only in a for with two "
                "names: for k, v in d.items()")
        if method != "append" and is_dict(type_name):
            raise InvalidProgram(
                lineno, "a dict has no method '%s'" % method)
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
        self.require_scalar(actual, "list elements", lineno)
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
        does not end in a return, continue, break, or raise, so it
        sees those paths merged; a name that a clause ending in one
        of the last three alone binds is unknown there, where one a
        returning clause alone binds is not defined (plan 1.15). The
        finally suite may follow any boundary of the suite or of a
        clause, a return or an exception included, so it is checked
        first from all of them merged, with the name of a clause that
        returned unbound, since exec_clauses deleted it, and then
        again from the paths that continue, for the code after it,
        with the bound names those paths left, since the first check
        may have unbound a name in the finally suite. A break or
        continue records its types before the finally suite runs, so
        under a loop the types the first check leaves join the loop's
        exits as well, for the next pass and the code after the loop
        (plan 1.15)."""
        body_effects = EffectSet()
        entry = self.check_suite(stmt.body, scope, body_effects)
        after = scope.types
        into_finally = entry.copy()
        absorb(into_finally, after)
        returned = []
        left = []
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
            elif leaves(clause.body):
                left.append(scope.types)
            else:
                after = merge_types(after, scope.types)
            absorb(into_finally, boundaries)
        for types in left:
            keep_bound(after, types)
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
            first = len(self.unknowns)
            self.check_block(stmt.finalbody, scope, effects)
            if len(self.loop_exits) > 0:
                absorb(self.loop_exits[-1], scope.types)
            scope.unbound = unbound
            scope.types = after
            second = len(self.unknowns)
            self.check_block(stmt.finalbody, scope, effects)
            self._drop_repeats(first, second)
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
            mark = len(self.unknowns)
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
            self._drop_unknowns(mark)
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
                self.require_scalar(actual, "list elements", expr.lineno)
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
        elif isinstance(expr, ast.TupleLiteral):
            types = []
            untyped = False
            for item in expr.elements:
                actual = self.type_of(item, scope, effects)
                self.require_scalar(actual, "tuple elements", expr.lineno)
                if actual == UNKNOWN:
                    untyped = True
                types.append(actual)
            if untyped:
                return UNKNOWN
            return "tuple[%s]" % ", ".join(types)
        elif isinstance(expr, ast.NoneLiteral):
            return NONE
        elif isinstance(expr, ast.IsNone):
            self.type_of(expr.operand, scope, effects)
            return "bool"
        elif isinstance(expr, ast.Index):
            return self.check_index(expr.target, expr.index, expr.lineno,
                                    scope, effects)
        elif isinstance(expr, ast.MethodCall):
            return self.check_method(expr.target, expr.method, expr.args,
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
            narrowing = self.narrow(
                facts(expr.left, expr.op == "and"), scope, self.spoiled)
            self.require_bool(self.type_of(expr.right, scope, effects),
                              expr.op, expr.lineno)
            self.widen_back(narrowing, scope)
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
        elif isinstance(expr, ast.KeywordCall):
            return self.check_keyword_call(expr, scope, effects)
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
                return self.check_method(
                    ast.Name(expr.effect, expr.lineno), expr.op, expr.args,
                    expr.lineno, scope, effects)
            raise InvalidProgram(
                expr.lineno, "%s.%s(...) must be the argument of perform()"
                % (expr.effect, expr.op))
        elif isinstance(expr, ast.AttrRead):
            info = self.info_of(scope.types.get(expr.target, UNKNOWN))
            if info is not None:
                return self.require_field(info, expr.attr, expr.lineno)
            self.require_bound(scope, expr.target, expr.lineno)
            held = scope.types[expr.target]
            if expr.target not in scope.bindings:
                if held == UNKNOWN:
                    self._note_unknown(INDEX, expr.lineno)
                    return UNKNOWN
                if is_optional(held):
                    raise InvalidProgram(
                        expr.lineno, "'%s' is %s; a field read needs a "
                        "test against None first" % (expr.target, held))
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            op = binding.op
            for i in range(len(op.params)):
                if op.params[i] == expr.attr:
                    return op.param_types[i]
            raise InvalidProgram(
                expr.lineno, "operation %s.%s has no parameter '%s'" %
                (binding.effect, op.name, expr.attr))
        elif isinstance(expr, ast.FieldRead):
            return self.check_field_read(expr, scope, effects)
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
        if actual == UNKNOWN:
            self._note_unknown(BOOL, lineno)
        elif actual != "bool":
            raise InvalidProgram(
                lineno, "%s needs a bool, not %s" % (what, actual))

    def check_operands(self, op, left, right, lineno):
        """Both operand types known and not a pair the interpreter's
        binop() or compare() accepts is the runtime error, reported
        early with the runtime's words."""
        if left == UNKNOWN or right == UNKNOWN:
            self._note_unknown(OPERANDS, lineno)
            return
        if is_list(left) and is_list(right):
            if ((matches(left, right) or matches(right, left))
                    and op in OPERATORS[LIST]
                    and comparable(element_of(left))
                    and comparable(element_of(right))):
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
        if self.info_of(expr.func) is not None:
            return self.check_construction(expr, scope, effects)
        if expr.func in self.exceptions:
            return self.check_exception_call(expr, scope, effects)
        if expr.func not in self.functions:
            raise InvalidProgram(
                expr.lineno, "name '%s' is not defined" % expr.func)
        fn = self.functions[expr.func]
        self.check_args(fn.params, fn.param_types, expr.args,
                        fn.name + "()", expr.lineno, scope, effects)
        return self.called(fn, expr.lineno, scope, effects)

    def called(self, fn, lineno, scope, effects):
        """What a call to a function adds once its arguments are
        checked: its row, a perform point where the row names an
        effect, and its return type."""
        for name in fn.effect_row:
            effects.add(name, lineno)
        for name in fn.effect_row:
            if name in self.effects:
                self.widen_at_perform(scope)
                break
        return fn.return_type

    def check_keyword_call(self, expr, scope, effects):
        """A call by name that ends in keyword arguments (plan 1.23),
        to a function or to the constructor of a handler class or a
        data class. Each argument is typed in the order written, as
        the runtime evaluates it, against the parameter it goes to:
        a positional one by position, a keyword by name. A function
        needs every parameter, and a class every field without a
        default."""
        what = expr.func + "()"
        info = self.info_of(expr.func)
        fn = None
        if info is not None:
            names = info.field_names
            types = []
            for name in names:
                types.append(info.field_types[name])
            required = info.required
            slot = "field"
        elif expr.func in BUILTINS or expr.func in self.exceptions:
            raise InvalidProgram(
                expr.lineno, "%s takes no keyword arguments" % what)
        elif expr.func in self.functions:
            fn = self.functions[expr.func]
            names = fn.params
            types = fn.param_types
            required = len(names)
            slot = "parameter"
        else:
            raise InvalidProgram(
                expr.lineno, "name '%s' is not defined" % expr.func)
        slots = self.keyword_slots(names, expr, what)
        filled = {}
        positional = len(expr.args) - len(expr.keywords)
        for i in range(len(expr.args)):
            j = slots[i]
            filled[j] = True
            if i < positional:
                which = "argument %d" % (i + 1)
            else:
                which = "argument '%s'" % names[j]
            actual = self.type_of(expr.args[i], scope, effects)
            self.require_known(expr.args[i], actual, types[j],
                               "%s of %s must be %s" %
                               (which, what, types[j]), expr.lineno)
            if not matches(actual, types[j]):
                raise InvalidProgram(
                    expr.lineno, "%s of %s must be %s, not %s" %
                    (which, what, types[j], actual))
            self.hand_over(expr.args[i], types[j], scope)
        for j in range(required):
            if j not in filled:
                raise InvalidProgram(
                    expr.lineno, "%s needs a value for %s '%s'" %
                    (what, slot, names[j]))
        if fn is None:
            return expr.func
        return self.called(fn, expr.lineno, scope, effects)

    def keyword_slots(self, names, expr, what):
        """The parameter each argument goes to, by its index in
        names: the positional arguments to the first parameters and
        each keyword to the one it names, in CPython's words where a
        keyword names none or one already filled. The parser has
        refused a repeated keyword."""
        positional = len(expr.args) - len(expr.keywords)
        if positional > len(names):
            raise InvalidProgram(
                expr.lineno, "%s takes %d arguments (%d given)" %
                (what, len(names), len(expr.args)))
        slots = []
        for i in range(positional):
            slots.append(i)
        for keyword in expr.keywords:
            j = -1
            for k in range(len(names)):
                if names[k] == keyword:
                    j = k
            if j < 0:
                raise InvalidProgram(
                    expr.lineno, "%s got an unexpected keyword argument "
                    "'%s'" % (what, keyword))
            if j < positional:
                raise InvalidProgram(
                    expr.lineno, "%s got multiple values for argument "
                    "'%s'" % (what, keyword))
            slots.append(j)
        return slots

    def check_builtin(self, expr, scope, effects):
        """len() of a list or str is int; str() of a scalar is str."""
        if len(expr.args) != 1:
            raise InvalidProgram(
                expr.lineno, "%s() takes 1 arguments (%d given)" %
                (expr.func, len(expr.args)))
        actual = self.type_of(expr.args[0], scope, effects)
        if actual == UNKNOWN:
            self._note_unknown(BUILTIN, expr.lineno)
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
        info = self.info_of(expr.func)
        assert info is not None
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
                lineno, "'%s' is not an except binding, a handler "
                "instance, or a data class instance" % name)
        return scope.bindings[name]

    def require_instance(self, scope, name, lineno):
        self.require_bound(scope, name, lineno)
        info = self.info_of(scope.types.get(name, UNKNOWN))
        if info is None:
            raise InvalidProgram(
                lineno, "'%s' is not a handler instance or a data class "
                "instance" % name)
        return info

    def require_field(self, info, attr, lineno):
        if attr not in info.field_types:
            raise InvalidProgram(
                lineno, "%s '%s' has no field '%s'" %
                (info.kind, info.name, attr))
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

def comparable(element):
    """Whether == and in may compare a list's elements: scalars, or
    a type the checker does not know, which the runtime judges. An
    instance has no ==, so a list of them has none (plan 1.19)."""
    return element == UNKNOWN or element in SCALARS

def kind_of(type_name):
    """'list', 'tuple', or 'dict' for a container type, in a message
    about an element that cannot be one."""
    if is_list(type_name):
        return "list"
    if is_tuple(type_name):
        return "tuple"
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
