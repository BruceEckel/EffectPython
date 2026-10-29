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
    """A whole .epy file: its function definitions, in order."""
    _attrs_ = ['functions']

    def __init__(self, functions, lineno=0):
        Node.__init__(self, lineno)
        self.functions = functions  # list of FunctionDef


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
