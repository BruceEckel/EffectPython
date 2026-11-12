"""AST node classes (plan 4.1).

Nodes are data only. The evaluator in interpreter.py and, later, the checker
in checker.py walk them with isinstance dispatch, so one node class serves
both. Every list field is homogeneous (all Stmt or all Expr), as RPython
requires. lineno is 0 for nodes built by hand; the parser fills it in.

Node extends rply's BaseBox so that parser productions can return nodes
directly: RPython needs every value on the parse stack to share one type,
and BaseBox is the type rply gives it. BaseBox adds no fields or behavior.

The surface syntax each node represents is given in its docstring.
"""
from rply.token import BaseBox

class Node(BaseBox):
    _attrs_ = ['lineno']

    def __init__(self, lineno=0):
        self.lineno = lineno

# --- Module and definitions --------------------------------------------------

class Module(Node):
    """A whole .epy file: its effect declarations, its handler classes,
       its exception classes, its data classes, and its function
       definitions, each in source order. The import line (from
       effectpython import ...) leaves no node."""
    _attrs_ = ['functions', 'effects', 'handlers', 'exceptions', 'records']

    def __init__(self, functions, effects=None, handlers=None,
                 exceptions=None, records=None, lineno=0):
        Node.__init__(self, lineno)
        if records is None:
            records = []
        self.records = records        # list of DataDef
        if effects is None:
            effects = []
        if handlers is None:
            handlers = []
        if exceptions is None:
            exceptions = []
        self.functions = functions    # list of FunctionDef
        self.effects = effects        # list of EffectDef
        self.handlers = handlers      # list of HandlerDef
        self.exceptions = exceptions  # list of ExceptionDef

class EffectDef(Node):
    """class Name(Effect): followed by operation stubs (plan 1.1)"""
    _attrs_ = ['name', 'operations']

    def __init__(self, name, operations, lineno=0):
        Node.__init__(self, lineno)
        self.name = name              # str
        self.operations = operations  # list of OperationDef

class OperationDef(Node):
    """def op(p1: T1, p2: T2) -> ReturnType / [Exc1, Exc2]: ...   inside
       an Effect class. The row names the exception classes a handler
       may throw into the body at the perform (plan 1.7); without it
       the row is empty."""
    _attrs_ = ['name', 'params', 'param_types', 'return_type', 'row']

    def __init__(self, name, params, param_types, return_type, row,
                 lineno=0):
        Node.__init__(self, lineno)
        self.name = name
        self.params = params            # list of str
        self.param_types = param_types  # list of str, parallel to params
        self.return_type = return_type  # str
        self.row = row                  # list of str (exception classes)

class HandlerDef(Node):
    """class Name(Handler[Effect]): followed by field declarations and
       one method per operation (plan 1.5). A method is a FunctionDef
       whose first parameter is self, typed as the handler class."""
    _attrs_ = ['name', 'effect', 'fields', 'methods']

    def __init__(self, name, effect, fields, methods, lineno=0):
        Node.__init__(self, lineno)
        self.name = name        # str
        self.effect = effect    # str: the fulfilled effect's name
        self.fields = fields    # list of FieldDef
        self.methods = methods  # list of FunctionDef

class DataDef(Node):
    """@dataclass over class Name: followed by field declarations
       (plan 1.19). The class name is the type of its instances."""
    _attrs_ = ['name', 'fields']

    def __init__(self, name, fields, lineno=0):
        Node.__init__(self, lineno)
        self.name = name      # str
        self.fields = fields  # list of FieldDef

class FieldDef(Node):
    """name: Type [= literal]   inside a handler class or a data
       class"""
    _attrs_ = ['name', 'type', 'default']

    def __init__(self, name, type, default, lineno=0):
        Node.__init__(self, lineno)
        self.name = name        # str
        self.type = type        # str
        self.default = default  # a literal, [], {}, or None

class ExceptionDef(Node):
    """class Name(Exception): ...   (plan 1.6). The body is ... or pass;
       an exception class has no fields and no base below Exception."""
    _attrs_ = ['name']

    def __init__(self, name, lineno=0):
        Node.__init__(self, lineno)
        self.name = name  # str

class FunctionDef(Node):
    """def name(p1: T1, p2: T2) -> ReturnType / [Effect1, Effect2]:
       Parameter type names and the return type are kept as strings for the
       checker; the evaluator ignores them. A function without / [...] has
       an empty effect_row (plan 1.2). The row names effects and
       exception classes (plan 1.6)."""
    _attrs_ = ['name', 'params', 'param_types', 'return_type', 'effect_row', 'body']

    def __init__(self, name, params, param_types, return_type, effect_row, body, lineno=0):
        Node.__init__(self, lineno)
        self.name = name
        self.params = params            # list of str
        self.param_types = param_types  # list of str, parallel to params
        self.return_type = return_type  # str
        self.effect_row = effect_row    # list of str (class names)
        self.body = body                # list of Stmt

# --- Statements --------------------------------------------------------------

class Stmt(Node):
    _attrs_ = []

class Return(Stmt):
    """return value   (value is None for a bare return)"""
    _attrs_ = ['value']

    def __init__(self, value, lineno=0):
        Node.__init__(self, lineno)
        self.value = value  # Expr or None

class If(Stmt):
    """if test: body  [else: orelse]   (orelse is an empty list without else)"""
    _attrs_ = ['test', 'body', 'orelse']

    def __init__(self, test, body, orelse, lineno=0):
        Node.__init__(self, lineno)
        self.test = test      # Expr
        self.body = body      # list of Stmt
        self.orelse = orelse  # list of Stmt

class While(Stmt):
    """while test: body"""
    _attrs_ = ['test', 'body']

    def __init__(self, test, body, lineno=0):
        Node.__init__(self, lineno)
        self.test = test  # Expr
        self.body = body  # list of Stmt

class For(Stmt):
    """for name in iterable: body, over a list (plan 1.9)"""
    _attrs_ = ['name', 'iterable', 'body']

    def __init__(self, name, iterable, body, lineno=0):
        Node.__init__(self, lineno)
        self.name = name          # str
        self.iterable = iterable  # Expr
        self.body = body          # list of Stmt

class ForItems(Stmt):
    """for key, value in target.items(): body, over a dict (plan
       1.22). The parser folds it from the two-name for, as it folds
       ForRange, since items() has no value anywhere else."""
    _attrs_ = ['key', 'value', 'target', 'body']

    def __init__(self, key, value, target, body, lineno=0):
        Node.__init__(self, lineno)
        self.key = key        # str
        self.value = value    # str
        self.target = target  # Expr: the dict
        self.body = body      # list of Stmt

class ForRange(Stmt):
    """for name in range(args): body, which the parser folds from a
       For whose iterable is a call to range, so the runtime counts
       without building a list (plan 1.9)"""
    _attrs_ = ['name', 'args', 'body']

    def __init__(self, name, args, body, lineno=0):
        Node.__init__(self, lineno)
        self.name = name  # str
        self.args = args  # list of Expr: stop, or start and stop
        self.body = body  # list of Stmt

class Assign(Stmt):
    """name = value"""
    _attrs_ = ['name', 'value']

    def __init__(self, name, value, lineno=0):
        Node.__init__(self, lineno)
        self.name = name    # str
        self.value = value  # Expr

class Unpack(Stmt):
    """name1, name2, ... = value: binds each name to an element of a
       tuple (plan 1.17)"""
    _attrs_ = ['names', 'value']

    def __init__(self, names, value, lineno=0):
        Node.__init__(self, lineno)
        self.names = names  # list of str
        self.value = value  # Expr

class AttrAssign(Stmt):
    """target.attr = value: assigns a field of a handler instance,
       such as self.writes = self.writes + 1 (plan 1.5)."""
    _attrs_ = ['target', 'attr', 'value']

    def __init__(self, target, attr, value, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # str: a variable name
        self.attr = attr      # str
        self.value = value    # Expr

class FieldAssign(Stmt):
    """target.attr = value or target.attr op= value where target is
       an expression rather than a name, such as ts[0].seconds += 1
       (plan 1.20). op is empty for a plain store. The augmented
       form is a node and not a store over a BinOp so that the
       target is evaluated once, as IndexAugAssign's is."""
    _attrs_ = ['op', 'target', 'attr', 'value']

    def __init__(self, op, target, attr, value, lineno=0):
        Node.__init__(self, lineno)
        self.op = op          # str: "" or an operator
        self.target = target  # Expr
        self.attr = attr      # str
        self.value = value    # Expr

class IndexAssign(Stmt):
    """target[index] = value on a list (plan 1.9)"""
    _attrs_ = ['target', 'index', 'value']

    def __init__(self, target, index, value, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # Expr
        self.index = index    # Expr
        self.value = value    # Expr

class IndexAugAssign(Stmt):
    """target[index] op= value (plan 1.14). A name or a field target
       is built as the Assign or AttrAssign it means; a subscript gets
       its own node because the target and the index are evaluated
       once, before the value."""
    _attrs_ = ['op', 'target', 'index', 'value']

    def __init__(self, op, target, index, value, lineno=0):
        Node.__init__(self, lineno)
        self.op = op          # str, one of + - * // %
        self.target = target  # Expr
        self.index = index    # Expr
        self.value = value    # Expr

class ExprStmt(Stmt):
    """An expression evaluated for its side effect, such as print(x)."""
    _attrs_ = ['expr']

    def __init__(self, expr, lineno=0):
        Node.__init__(self, lineno)
        self.expr = expr  # Expr

class Pass(Stmt):
    """pass"""
    _attrs_ = []

class Break(Stmt):
    """break, inside a while or a for (plan 1.10)"""
    _attrs_ = []

class Continue(Stmt):
    """continue, inside a while or a for (plan 1.10)"""
    _attrs_ = []

class Handle(Stmt):
    """try:
           with handle(Effect1, FakeEffect2(), fake3):
               body
       except Effect1.op as eff:
           clause body
       ...
       The whole try/except is one handler installation (plan 1.4);
       the checker requires a clause for every operation of every
       handled effect. A handle(...) argument is a bare name, a handler
       class constructor call, or a name bound to a handler instance
       (plan 1.5). The parser cannot tell an effect name from an
       instance name, so it puts every bare name in effects, and the
       checker moves the instance names to instances. A with handle(...)
       outside try has no clauses."""
    _attrs_ = ['effects', 'body', 'clauses', 'constructions',
               'instances']

    def __init__(self, effects, body, clauses, constructions=None,
                 lineno=0):
        Node.__init__(self, lineno)
        if constructions is None:
            constructions = []
        self.effects = effects              # list of str
        self.body = body                    # list of Stmt
        self.clauses = clauses              # list of Clause
        self.constructions = constructions  # list of Call
        self.instances = []                 # list of str, by the checker

class Clause(Node):
    """except Effect.op as binding: body   (one handler clause)"""
    _attrs_ = ['effect', 'op', 'binding', 'body']

    def __init__(self, effect, op, binding, body, lineno=0):
        Node.__init__(self, lineno)
        self.effect = effect    # str
        self.op = op            # str
        self.binding = binding  # str: the name bound to the W_EffBinding
        self.body = body        # list of Stmt

class Raise(Stmt):
    """raise value   (plan 1.6). The checker requires value's type to
       be a declared exception class: a constructor call such as
       NotFound(path), or a name an except clause bound."""
    _attrs_ = ['value']

    def __init__(self, value, lineno=0):
        Node.__init__(self, lineno)
        self.value = value  # Expr

class Try(Stmt):
    """try:
           body
       except NotFound as e:
           clause body
       ...
       finally:
           finalbody
       An ordinary try/except/finally (plan 1.6, 1.8). The parser
       reads every try through one set of productions and builds a
       Handle when the clauses name Effect.op, a Try when they name an
       exception class; a finally on effect clauses gives a Try with
       no clauses around the Handle. Either part may be empty, not
       both; finalbody is [] without a finally."""
    _attrs_ = ['body', 'clauses', 'finalbody']

    def __init__(self, body, clauses, finalbody, lineno=0):
        Node.__init__(self, lineno)
        self.body = body            # list of Stmt
        self.clauses = clauses      # list of ExceptClause
        self.finalbody = finalbody  # list of Stmt

class ExceptClause(Node):
    """except Name [as binding]: body   (one clause of a Try). Name is
       an exception class or Exception, which catches every class."""
    _attrs_ = ['name', 'binding', 'body']

    def __init__(self, name, binding, body, lineno=0):
        Node.__init__(self, lineno)
        self.name = name        # str
        self.binding = binding  # str, or None without as
        self.body = body        # list of Stmt

# --- Expressions -------------------------------------------------------------

class Expr(Node):
    _attrs_ = []

class IntLiteral(Expr):
    _attrs_ = ['value']

    def __init__(self, value, lineno=0):
        Node.__init__(self, lineno)
        self.value = value  # int

class StrLiteral(Expr):
    _attrs_ = ['value']

    def __init__(self, value, lineno=0):
        Node.__init__(self, lineno)
        self.value = value  # str

class BoolLiteral(Expr):
    """True or False"""
    _attrs_ = ['value']

    def __init__(self, value, lineno=0):
        Node.__init__(self, lineno)
        self.value = value  # bool

class NoneLiteral(Expr):
    """None (plan 1.16)"""
    _attrs_ = []

    def __init__(self, lineno=0):
        Node.__init__(self, lineno)

class ListLiteral(Expr):
    """[e1, e2, ...] or [] (plan 1.9)"""
    _attrs_ = ['elements']

    def __init__(self, elements, lineno=0):
        Node.__init__(self, lineno)
        self.elements = elements  # list of Expr

class TupleLiteral(Expr):
    """(e1, e2, ...) with two or more elements (plan 1.17)"""
    _attrs_ = ['elements']

    def __init__(self, elements, lineno=0):
        Node.__init__(self, lineno)
        self.elements = elements  # list of Expr

class Index(Expr):
    """target[index] on a list (plan 1.9)"""
    _attrs_ = ['target', 'index']

    def __init__(self, target, index, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # Expr
        self.index = index    # Expr

class MethodCall(Expr):
    """target.method(args) where target is an expression rather than a
       name, such as self.entries.append(text); a name on the left
       gives an OpCall instead, and the checker tells a list's append
       from an operation by the name's type (plan 1.9)."""
    _attrs_ = ['target', 'method', 'args']

    def __init__(self, target, method, args, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # Expr
        self.method = method  # str
        self.args = args      # list of Expr

class Name(Expr):
    """A variable reference."""
    _attrs_ = ['id']

    def __init__(self, id, lineno=0):
        Node.__init__(self, lineno)
        self.id = id  # str

class BinOp(Expr):
    """left op right, where op is one of + - * // %"""
    _attrs_ = ['op', 'left', 'right']

    def __init__(self, op, left, right, lineno=0):
        Node.__init__(self, lineno)
        self.op = op        # str
        self.left = left    # Expr
        self.right = right  # Expr

class FString(Expr):
    """f"..." (plan 1.13): the literal text around and between the
       fields, one entry more than exprs, so the value is literals[0],
       then exprs[0] as text, then literals[1], and so on"""
    _attrs_ = ['literals', 'exprs']

    def __init__(self, literals, exprs, lineno=0):
        Node.__init__(self, lineno)
        self.literals = literals  # list of str
        self.exprs = exprs        # list of Expr

class DictLiteral(Expr):
    """{key: value, ...} or {} (plan 1.12); keys and values are
       parallel lists"""
    _attrs_ = ['keys', 'values']

    def __init__(self, keys, values, lineno=0):
        Node.__init__(self, lineno)
        self.keys = keys      # list of Expr
        self.values = values  # list of Expr

class In(Expr):
    """left in right, or left not in right (plan 1.12): a key of a
       dict or an element of a list"""
    _attrs_ = ['left', 'right', 'negated']

    def __init__(self, left, right, negated, lineno=0):
        Node.__init__(self, lineno)
        self.left = left        # Expr
        self.right = right      # Expr
        self.negated = negated  # bool

class IsNone(Expr):
    """operand is None, or operand is not None (plan 1.16): the one
       use of is in the dialect"""
    _attrs_ = ['operand', 'negated']

    def __init__(self, operand, negated, lineno=0):
        Node.__init__(self, lineno)
        self.operand = operand  # Expr
        self.negated = negated  # bool

class BoolOp(Expr):
    """left and right, or left or right (plan 1.11). The right operand
       is evaluated only when the left one does not decide the result,
       so an effect or an exception in it may not occur."""
    _attrs_ = ['op', 'left', 'right']

    def __init__(self, op, left, right, lineno=0):
        Node.__init__(self, lineno)
        self.op = op        # str: "and" or "or"
        self.left = left    # Expr
        self.right = right  # Expr

class Not(Expr):
    """not operand (plan 1.11)"""
    _attrs_ = ['operand']

    def __init__(self, operand, lineno=0):
        Node.__init__(self, lineno)
        self.operand = operand  # Expr

class Compare(Expr):
    """left op right, where op is one of < <= > >= == !="""
    _attrs_ = ['op', 'left', 'right']

    def __init__(self, op, left, right, lineno=0):
        Node.__init__(self, lineno)
        self.op = op        # str
        self.left = left    # Expr
        self.right = right  # Expr

class Call(Expr):
    """func(arg1, arg2): a call to a module-level function by name, to
       the built-in print, or to the constructor of a handler class or
       an exception class."""
    _attrs_ = ['func', 'args']

    def __init__(self, func, args, lineno=0):
        Node.__init__(self, lineno)
        self.func = func  # str
        self.args = args  # list of Expr

class OpCall(Expr):
    """Effect.op(arg1, arg2): builds the effect payload (plan 1.3). The
       parser folds perform(Effect.op(...)) into a Perform, so an OpCall
       survives only where it stands on its own. The same shape is
       xs.append(v) on a name holding a list, which the checker and
       the interpreter tell apart by the name (plan 1.9)."""
    _attrs_ = ['effect', 'op', 'args']

    def __init__(self, effect, op, args, lineno=0):
        Node.__init__(self, lineno)
        self.effect = effect  # str
        self.op = op          # str
        self.args = args      # list of Expr

class Perform(Expr):
    """perform(Effect.op(arg1, arg2)): suspends to the nearest handler
       for Effect and evaluates to the value the handler resumes with."""
    _attrs_ = ['effect', 'op', 'args']

    def __init__(self, effect, op, args, lineno=0):
        Node.__init__(self, lineno)
        self.effect = effect  # str
        self.op = op          # str
        self.args = args      # list of Expr

class AttrRead(Expr):
    """target.attr: a parameter of the performed operation read from the
       clause's eff binding, such as eff.path, or a field of a handler
       instance, such as self.writes or fake.writes."""
    _attrs_ = ['target', 'attr']

    def __init__(self, target, attr, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # str: a variable name
        self.attr = attr      # str

class FieldRead(Expr):
    """target.attr where target is an expression rather than a name,
       such as ts[0].name or make().name: a field of an instance
       (plan 1.20)."""
    _attrs_ = ['target', 'attr']

    def __init__(self, target, attr, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # Expr
        self.attr = attr      # str

class Resume(Expr):
    """target.resume(value): returns value to the suspended perform and
       evaluates to the body's result once it completes (plan 3.4)."""
    _attrs_ = ['target', 'value']

    def __init__(self, target, value, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # str: a variable name
        self.value = value    # Expr

class Throw(Expr):
    """target.throw(value): makes the suspended perform raise value,
       an exception the operation's row declares, and evaluates to
       None once the body completes (plan 1.7)."""
    _attrs_ = ['target', 'value']

    def __init__(self, target, value, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # str: a variable name
        self.value = value    # Expr
