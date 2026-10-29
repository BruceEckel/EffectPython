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
    """A whole .epy file: its effect declarations and its function
       definitions, each in source order. The import line
       (from effectpython import ...) leaves no node."""
    _attrs_ = ['functions', 'effects']

    def __init__(self, functions, effects=None, lineno=0):
        Node.__init__(self, lineno)
        if effects is None:
            effects = []
        self.functions = functions  # list of FunctionDef
        self.effects = effects      # list of EffectDef


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


class FunctionDef(Node):
    """def name(p1: T1, p2: T2) -> ReturnType / [Effect1, Effect2]:
       Parameter type names and the return type are kept as strings for the
       checker; the evaluator ignores them. A function without / [...] has
       an empty effect_row (plan 1.2)."""
    _attrs_ = ['name', 'params', 'param_types', 'return_type', 'effect_row', 'body']

    def __init__(self, name, params, param_types, return_type, effect_row, body, lineno=0):
        Node.__init__(self, lineno)
        self.name = name
        self.params = params            # list of str
        self.param_types = param_types  # list of str, parallel to params
        self.return_type = return_type  # str
        self.effect_row = effect_row    # list of str (effect class names)
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


class Assign(Stmt):
    """name = value"""
    _attrs_ = ['name', 'value']

    def __init__(self, name, value, lineno=0):
        Node.__init__(self, lineno)
        self.name = name    # str
        self.value = value  # Expr


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
           with handle(Effect1, Effect2):
               body
       except Effect1.op as eff:
           clause body
       ...
       The whole try/except is one handler installation (plan 1.4);
       the checker requires a clause for every operation of every
       handled effect."""
    _attrs_ = ['effects', 'body', 'clauses']

    def __init__(self, effects, body, clauses, lineno=0):
        Node.__init__(self, lineno)
        self.effects = effects  # list of str (effect class names)
        self.body = body        # list of Stmt
        self.clauses = clauses  # list of Clause


class Clause(Node):
    """except Effect.op as binding: body   (one handler clause)"""
    _attrs_ = ['effect', 'op', 'binding', 'body']

    def __init__(self, effect, op, binding, body, lineno=0):
        Node.__init__(self, lineno)
        self.effect = effect    # str
        self.op = op            # str
        self.binding = binding  # str: the name bound to the W_EffBinding
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
    """func(arg1, arg2): a call to a module-level function by name, or to
       the built-in print."""
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
       clause's eff binding, such as eff.path."""
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
