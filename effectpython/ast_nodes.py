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
       its exception classes, and its function definitions, each in
       source order. The import line (from effectpython import ...)
       leaves no node."""
    _attrs_ = ['functions', 'effects', 'handlers', 'exceptions']

    def __init__(self, functions, effects=None, handlers=None,
                 exceptions=None, lineno=0):
        Node.__init__(self, lineno)
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
    """def op(p1: T1, p2: T2) -> ReturnType: ...   inside an Effect class"""
    _attrs_ = ['name', 'params', 'param_types', 'return_type']

    def __init__(self, name, params, param_types, return_type, lineno=0):
        Node.__init__(self, lineno)
        self.name = name
        self.params = params            # list of str
        self.param_types = param_types  # list of str, parallel to params
        self.return_type = return_type  # str

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

class FieldDef(Node):
    """name: Type [= literal]   inside a handler class"""
    _attrs_ = ['name', 'type', 'default']

    def __init__(self, name, type, default, lineno=0):
        Node.__init__(self, lineno)
        self.name = name        # str
        self.type = type        # str
        self.default = default  # IntLiteral, StrLiteral, or None

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

class Assign(Stmt):
    """name = value"""
    _attrs_ = ['name', 'value']

    def __init__(self, name, value, lineno=0):
        Node.__init__(self, lineno)
        self.name = name    # str
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

class ExprStmt(Stmt):
    """An expression evaluated for its side effect, such as print(x)."""
    _attrs_ = ['expr']

    def __init__(self, expr, lineno=0):
        Node.__init__(self, lineno)
        self.expr = expr  # Expr

class Pass(Stmt):
    """pass"""
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
       An ordinary try/except (plan 1.6). The parser reads every try
       through one production and builds a Handle when the clauses
       name Effect.op, a Try when they name an exception class."""
    _attrs_ = ['body', 'clauses']

    def __init__(self, body, clauses, lineno=0):
        Node.__init__(self, lineno)
        self.body = body        # list of Stmt
        self.clauses = clauses  # list of ExceptClause

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
       survives only where it stands on its own."""
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

class Resume(Expr):
    """target.resume(value): returns value to the suspended perform and
       evaluates to the body's result once it completes (plan 3.4)."""
    _attrs_ = ['target', 'value']

    def __init__(self, target, value, lineno=0):
        Node.__init__(self, lineno)
        self.target = target  # str: a variable name
        self.value = value    # Expr
