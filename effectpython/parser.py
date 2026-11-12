"""The parser: an rply LALR grammar producing ast_nodes (plan 2.1).

The grammar is the plan's subset of Python 3: the import line, Effect
classes with operation stubs, Handler[Effect] classes with field
declarations and methods, exception classes, function definitions
with typed parameters, a return type, and an optional effect row;
return, raise, assignment, attribute assignment, expression, pass,
if/elif/else, while, for, try/except/finally, and handle statements;
int, str, bool, list, and dict literals, None, f-strings, names,
arithmetic, comparisons, in and not in, is None and is not None,
and, or, and not in Python's precedence, calls, indexing, attribute reads, and attribute calls. An elif builds an If alone in the else
suite of the one above it, as CPython's AST does (plan 1.11).

perform and handle are names in Python, not keywords, so the grammar
reads them as calls and the productions check them: perform(X) must
wrap an Effect.op(...) call and becomes a Perform node, with handle(...)
must name handle, and a class must derive from Effect, Handler[...],
or Exception, or have no base and @dataclass on the line above it,
which gives a DataDef of field declarations (plan 1.19).
An attribute call name.resume(x) becomes a Resume node and
name.throw(x) a Throw node; any other name.op(...) call is an
OpCall, whether the name is an effect or a list (plan 1.9). A
handle(...) argument is a bare
name or a constructor call Name(...); the checker decides whether a
bare name is an effect or a handler instance (plan 1.5).

Attribute reads, attribute calls, and indexing are postfix forms on
an expression, as in Python's grammar, so self.entries.append(x)
and collector.entries[0] parse. A name on the left of an attribute
read gives an AttrRead, and of an attribute assignment an AttrAssign;
any other expression gives a FieldRead or a FieldAssign, whose
augmented form keeps its operator (plan 1.20). An index target may be any postfix
expression, so f()[0] = 2 parses. One production reads every
assignment, and the target's shape picks Assign, AttrAssign, or
IndexAssign. An augmented assignment x += v builds the Assign or
AttrAssign it means, over a BinOp, for a name or a field target;
a subscript target gives an IndexAugAssign, since its target and
index are evaluated once (plan 1.14). A type is a name, list[name],
dict[str, name], or name | None with None on the right alone; a bare
list is rejected, since it needs an element type, and the checker
holds the name inside to int, str, bool, or a data class, which the
grammar cannot tell from a misspelling (plan 1.19). None is a type and an
expression, and is takes None alone on its right, giving an IsNone
(plan 1.16). tuple[T1, T2, ...] with two or more of the three scalars
is a type, and so is its optional; (a, b) with two or more elements
is a TupleLiteral, and a, b = value an Unpack, whose targets are
names (plan 1.17). A for whose iterable is a call to range becomes a ForRange,
and a unary minus is folded into the literal it negates or into
0 - x (plan 1.9). break and continue are simple statements giving
Break and Continue nodes (plan 1.10).

One nonterminal, try_stmt, reads every try statement, because
separate ones for a handler installation and an ordinary try/except
would conflict in the LALR tables: both begin TRY COLON NEWLINE
INDENT, and with handle(...) is also a statement (plan 1.6). The
action decides by the clauses. Clauses that name Effect.op around a
single with handle(...) statement give a Handle; clauses that name a
class give a Try; a mix is an error.

RPython requires every production to return one type, so every value on
the parse stack is a BaseBox: a Token, a Node (ast_nodes makes Node a
BaseBox), or one of the boxes below: list boxes for the sequences the
grammar accumulates, and _Type, _Skipped, and _ClauseBox for a type, an
item with no node, and a clause with its token. A production that
builds a node narrows its operands with isinstance asserts, which the
annotator reads as type information.
"""
from rply import ParserGenerator
from rply.token import BaseBox, Token

from effectpython import ast_nodes as ast
from effectpython.errors import InvalidSyntax
from effectpython.lexer import TOKENS, TokenList, tokenize

class _ModuleParts(BaseBox):
    _attrs_ = ['functions', 'effects', 'handlers', 'exceptions', 'records']

    def __init__(self):
        self.records = []     # list of DataDef
        self.functions = []   # list of FunctionDef
        self.effects = []     # list of EffectDef
        self.handlers = []    # list of HandlerDef
        self.exceptions = []  # list of ExceptionDef

class _Skipped(BaseBox):
    """The value of a module item that produces no node."""
    _attrs_ = []

class _OpList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of OperationDef

class _HandlerItems(BaseBox):
    _attrs_ = ['fields', 'methods']

    def __init__(self):
        self.fields = []   # list of FieldDef
        self.methods = []  # list of FunctionDef

class _HandleArgs(BaseBox):
    _attrs_ = ['names', 'constructions']

    def __init__(self):
        self.names = []          # list of str
        self.constructions = []  # list of Call

class _ClauseBox(BaseBox):
    """One except clause with its EXCEPT token, which positions the
    error for a clause of the wrong kind."""
    _attrs_ = ['token', 'node']

    def __init__(self, token, node):
        self.token = token  # Token
        self.node = node    # Clause or ExceptClause

class _ClauseList(BaseBox):
    """The clauses of one try statement; one of the lists is empty."""
    _attrs_ = ['effect_clauses', 'except_clauses']

    def __init__(self):
        self.effect_clauses = []  # list of Clause
        self.except_clauses = []  # list of ExceptClause

class _StmtList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of Stmt

class _ExprList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of Expr

class _DictItems(BaseBox):
    _attrs_ = ['keys', 'values']

    def __init__(self, keys, values):
        self.keys = keys      # list of Expr
        self.values = values  # list of Expr

class _FStringParts(BaseBox):
    _attrs_ = ['literals', 'exprs']

    def __init__(self, literals, exprs):
        self.literals = literals  # list of str, one longer than exprs
        self.exprs = exprs        # list of Expr

class _NameList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of str

class _Type(BaseBox):
    """A type annotation as its name: int, str, bool, a class name, or
    list[int], list[str], or list[bool]."""
    _attrs_ = ['name']

    def __init__(self, name):
        self.name = name  # str

class _ParamList(BaseBox):
    _attrs_ = ['names', 'types']

    def __init__(self, names, types):
        self.names = names  # list of str
        self.types = types  # list of str, parallel to names

def _text(box):
    assert isinstance(box, Token)
    return box.getstr()

def _line(box):
    assert isinstance(box, Token)
    return box.getsourcepos().lineno

def _expr(box):
    assert isinstance(box, ast.Expr)
    return box

def _stmts(box):
    assert isinstance(box, _StmtList)
    return box.items

def _type(box):
    assert isinstance(box, _Type)
    return box.name

pg = ParserGenerator(TOKENS)

# --- Module and definitions --------------------------------------------------

@pg.production('module : items')
def module(p):
    parts = p[0]
    assert isinstance(parts, _ModuleParts)
    return ast.Module(parts.functions, parts.effects, parts.handlers,
                      parts.exceptions, parts.records, 1)

@pg.production('items :')
def items_empty(p):
    return _ModuleParts()

@pg.production('items : items item')
def items_more(p):
    parts = p[0]
    item = p[1]
    assert isinstance(parts, _ModuleParts)
    if isinstance(item, ast.FunctionDef):
        parts.functions.append(item)
    elif isinstance(item, ast.EffectDef):
        parts.effects.append(item)
    elif isinstance(item, ast.HandlerDef):
        parts.handlers.append(item)
    elif isinstance(item, ast.ExceptionDef):
        parts.exceptions.append(item)
    elif isinstance(item, ast.DataDef):
        parts.records.append(item)
    else:
        assert isinstance(item, _Skipped)
    return parts

@pg.production('item : funcdef')
@pg.production('item : effectdef')
@pg.production('item : handlerdef')
@pg.production('item : exceptiondef')
@pg.production('item : datadef')
def item(p):
    return p[0]

@pg.production('item : FROM NAME IMPORT name_list NEWLINE')
def import_stmt(p):
    return _Skipped()

@pg.production('effectdef : CLASS NAME LPAREN NAME RPAREN COLON'
               ' NEWLINE INDENT opdefs DEDENT')
def effectdef(p):
    base = p[3]
    ops = p[8]
    assert isinstance(base, Token)
    assert isinstance(ops, _OpList)
    if base.getstr() == 'Exception':
        raise _error(base, EXCEPTION_BODY_ERROR)
    if base.getstr() != 'Effect':
        raise _error(base, BASE_ERROR)
    return ast.EffectDef(_text(p[1]), ops.items, _line(p[0]))

BASE_ERROR = "a class must derive from Effect, Handler[...], or Exception"
EXCEPTION_BODY_ERROR = "an exception class has no body beyond ... or pass"
EFFECT_BODY_ERROR = "an effect class declares at least one operation"

@pg.production('exceptiondef : CLASS NAME LPAREN NAME RPAREN COLON'
               ' empty_body')
def exceptiondef(p):
    base = p[3]
    assert isinstance(base, Token)
    if base.getstr() == 'Effect':
        raise _error(base, EFFECT_BODY_ERROR)
    if base.getstr() != 'Exception':
        raise _error(base, BASE_ERROR)
    return ast.ExceptionDef(_text(p[1]), _line(p[0]))

@pg.production('empty_body : ELLIPSIS NEWLINE')
@pg.production('empty_body : PASS NEWLINE')
@pg.production('empty_body : NEWLINE INDENT ELLIPSIS NEWLINE DEDENT')
@pg.production('empty_body : NEWLINE INDENT PASS NEWLINE DEDENT')
def empty_body(p):
    return _Skipped()

@pg.production('handlerdef : CLASS NAME LPAREN NAME LBRACKET NAME RBRACKET'
               ' RPAREN COLON NEWLINE INDENT handler_items DEDENT')
def handlerdef(p):
    base = p[3]
    items = p[11]
    assert isinstance(base, Token)
    assert isinstance(items, _HandlerItems)
    if base.getstr() != 'Handler':
        raise _error(base, BASE_ERROR)
    name = _text(p[1])
    for method in items.methods:
        method.param_types[0] = name
    return ast.HandlerDef(name, _text(p[5]), items.fields, items.methods,
                          _line(p[0]))

@pg.production('datadef : AT NAME NEWLINE CLASS NAME COLON NEWLINE INDENT'
               ' handler_items DEDENT')
def datadef(p):
    """@dataclass over a class with no base (plan 1.19). The body
    shares the field productions of a handler class, so a method
    parses and is refused here."""
    items = p[8]
    assert isinstance(items, _HandlerItems)
    if _text(p[1]) != 'dataclass':
        raise _error(p[1], DECORATOR_ERROR)
    if len(items.methods) > 0:
        raise _error(p[3], "a data class has fields and no methods")
    return ast.DataDef(_text(p[4]), items.fields, _line(p[3]))

@pg.production('datadef : CLASS NAME COLON NEWLINE INDENT handler_items'
               ' DEDENT')
def undecorated_class(p):
    raise _error(p[0], "a class with no base needs @dataclass on the "
                 "line above it")

DECORATOR_ERROR = "the one decorator is @dataclass, above a class"

@pg.production('handler_items : handler_item')
def handler_items_one(p):
    return _add_handler_item(_HandlerItems(), p[0])

@pg.production('handler_items : handler_items handler_item')
def handler_items_more(p):
    items = p[0]
    assert isinstance(items, _HandlerItems)
    return _add_handler_item(items, p[1])

def _add_handler_item(items, item):
    if isinstance(item, ast.FieldDef):
        items.fields.append(item)
    else:
        assert isinstance(item, ast.FunctionDef)
        items.methods.append(item)
    return items

@pg.production('handler_item : NAME COLON type NEWLINE')
def field_without_default(p):
    return ast.FieldDef(_text(p[0]), _type(p[2]), None, _line(p[0]))

@pg.production('handler_item : NAME COLON type EQUALS expr NEWLINE')
def field_with_default(p):
    default = _expr(p[4])
    if isinstance(default, ast.ListLiteral):
        if len(default.elements) > 0:
            raise _error(p[3], "a list field's default must be []")
    elif isinstance(default, ast.DictLiteral):
        if len(default.keys) > 0:
            raise _error(p[3], "a dict field's default must be {}")
    elif not (isinstance(default, ast.IntLiteral)
              or isinstance(default, ast.StrLiteral)
              or isinstance(default, ast.BoolLiteral)):
        raise _error(p[3], "a field default must be an int, str, or "
                     "bool literal, [], or {}")
    return ast.FieldDef(_text(p[0]), _type(p[2]), default, _line(p[0]))

@pg.production('handler_item : DEF NAME LPAREN method_params RPAREN ARROW'
               ' type effect_row COLON suite')
def methoddef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    # A bare self is the one parameter the grammar leaves untyped
    if len(params.types) == 0 or params.types[0] != '':
        raise _error(p[2], SELF_ERROR)
    return ast.FunctionDef(_text(p[1]), params.names, params.types,
                           _type(p[6]), row.items, _stmts(p[9]),
                           _line(p[0]))

@pg.production('method_params : params')
def method_params_without_self(p):
    return p[0]

@pg.production('method_params : NAME')
def method_params_self(p):
    return _ParamList([_self(p[0])], [''])

@pg.production('method_params : NAME COMMA param_list')
def method_params_self_and_more(p):
    params = p[2]
    assert isinstance(params, _ParamList)
    params.names.insert(0, _self(p[0]))
    params.types.insert(0, '')
    return params

SELF_ERROR = "a handler method's first parameter must be self"

def _self(box):
    if _text(box) != 'self':
        raise _error(box, SELF_ERROR)
    return 'self'

@pg.production('opdefs : opdef')
def opdefs_one(p):
    op = p[0]
    assert isinstance(op, ast.OperationDef)
    return _OpList([op])

@pg.production('opdefs : opdefs opdef')
def opdefs_more(p):
    ops = p[0]
    op = p[1]
    assert isinstance(ops, _OpList)
    assert isinstance(op, ast.OperationDef)
    ops.items.append(op)
    return ops

@pg.production('opdef : DEF NAME LPAREN params RPAREN ARROW type'
               ' effect_row COLON ELLIPSIS NEWLINE')
def opdef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    return ast.OperationDef(_text(p[1]), params.names, params.types,
                            _type(p[6]), row.items, _line(p[0]))

@pg.production('funcdef : DEF NAME LPAREN params RPAREN ARROW type'
               ' effect_row COLON suite')
def funcdef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    return ast.FunctionDef(_text(p[1]), params.names, params.types,
                           _type(p[6]), row.items, _stmts(p[9]),
                           _line(p[0]))

@pg.production('type : NAME')
def plain_type(p):
    if _text(p[0]) == 'list':
        raise _error(p[0], "list needs an element type: list[int], "
                     "list[str], or list[bool]")
    if _text(p[0]) == 'dict':
        raise _error(p[0], "dict needs a key and a value type: "
                     "dict[str, int], dict[str, str], or dict[str, bool]")
    if _text(p[0]) == 'tuple':
        raise _error(p[0], "tuple needs element types: tuple[int, str]")
    return _Type(_text(p[0]))

@pg.production('type : NAME LBRACKET NAME RBRACKET')
def list_type(p):
    if _text(p[0]) == 'tuple':
        raise _error(p[0], "a tuple has two or more element types: "
                     "tuple[int, str]")
    if _text(p[0]) != 'list':
        raise _error(p[0], "'%s' takes no type parameter; list[...] does"
                     % _text(p[0]))
    return _Type('list[%s]' % _text(p[2]))

@pg.production('type : NAME LBRACKET NAME COMMA NAME RBRACKET')
def dict_type(p):
    if _text(p[0]) == 'tuple':
        return _Type(_tuple_type(p[0], [_text(p[2]), _text(p[4])]))
    if _text(p[0]) != 'dict':
        raise _error(p[0], "'%s' takes no key and value types; "
                     "dict[str, ...] does" % _text(p[0]))
    if _text(p[2]) != 'str':
        raise _error(p[2], "dict keys are str, not %s" % _text(p[2]))
    return _Type('dict[str, %s]' % _text(p[4]))

@pg.production('type : NAME LBRACKET NAME COMMA NAME COMMA name_list '
               'RBRACKET')
def long_tuple_type(p):
    return _Type(_tuple_type(p[0], _long_elements(p)))

@pg.production('type : NAME LBRACKET NAME COMMA NAME RBRACKET PIPE NONE')
def optional_pair_type(p):
    elements = [_text(p[2]), _text(p[4])]
    return _Type(_optional_tuple(p[0], elements))

@pg.production('type : NAME LBRACKET NAME COMMA NAME COMMA name_list '
               'RBRACKET PIPE NONE')
def optional_long_tuple_type(p):
    return _Type(_optional_tuple(p[0], _long_elements(p)))

def _long_elements(p):
    rest = p[6]
    assert isinstance(rest, _NameList)
    return [_text(p[2]), _text(p[4])] + rest.items

def _tuple_type(token, elements):
    """tuple[T1, T2, ...] as one string, with two or more of int, str,
    and bool (plan 1.17)."""
    if _text(token) != 'tuple':
        raise _error(token, "'%s' takes no list of element types; "
                     "tuple[...] does" % _text(token))
    for element in elements:
        if element not in LIST_ELEMENTS:
            raise _error(token, "tuple[..., %s] is not a type; an "
                         "element type is int, str, or bool" % element)
    return 'tuple[%s]' % ', '.join(elements)

def _optional_tuple(token, elements):
    if _text(token) != 'tuple':
        raise _error(token, OPTIONALS % ('%s[...]' % _text(token)))
    return '%s | None' % _tuple_type(token, elements)

OPTIONALS = ("%s | None is not a type; the optional types are "
             "int | None, str | None, bool | None, tuple[...] | None, and "
             "a data class | None")

@pg.production('type : NONE')
def none_type(p):
    return _Type('None')

@pg.production('type : NAME PIPE NONE')
def optional_type(p):
    base = _text(p[0])
    if base in ['list', 'dict', 'tuple']:
        raise _error(p[0], OPTIONALS % base)
    return _Type('%s | None' % base)

LIST_ELEMENTS = ['int', 'str', 'bool']

@pg.production('params :')
def params_empty(p):
    return _ParamList([], [])

@pg.production('params : param_list')
@pg.production('names : name_list')
@pg.production('args : arg_list')
def pass_through_list(p):
    return p[0]

@pg.production('effect_row : SLASH LBRACKET names RBRACKET')
def effect_row(p):
    return p[2]

@pg.production('param_list : NAME COLON type')
def param_list_one(p):
    return _ParamList([_text(p[0])], [_type(p[2])])

@pg.production('param_list : param_list COMMA NAME COLON type')
def param_list_more(p):
    params = p[0]
    assert isinstance(params, _ParamList)
    params.names.append(_text(p[2]))
    params.types.append(_type(p[4]))
    return params

@pg.production('effect_row :')
@pg.production('names :')
def names_empty(p):
    return _NameList([])

@pg.production('name_list : NAME')
def name_list_one(p):
    return _NameList([_text(p[0])])

@pg.production('name_list : name_list COMMA NAME')
def name_list_more(p):
    names = p[0]
    assert isinstance(names, _NameList)
    names.items.append(_text(p[2]))
    return names

# --- Statements --------------------------------------------------------------

@pg.production('suite : NEWLINE INDENT stmts DEDENT')
def suite(p):
    return p[2]

@pg.production('stmts : stmt')
def stmts_one(p):
    stmt = p[0]
    assert isinstance(stmt, ast.Stmt)
    return _StmtList([stmt])

@pg.production('stmts : stmts stmt')
def stmts_more(p):
    stmts = p[0]
    stmt = p[1]
    assert isinstance(stmts, _StmtList)
    assert isinstance(stmt, ast.Stmt)
    stmts.items.append(stmt)
    return stmts

@pg.production('stmt : simple_stmt NEWLINE')
@pg.production('stmt : if_stmt')
@pg.production('stmt : while_stmt')
@pg.production('stmt : for_stmt')
@pg.production('stmt : try_stmt')
@pg.production('stmt : with_stmt')
def stmt(p):
    return p[0]

@pg.production('simple_stmt : PASS')
def pass_stmt(p):
    return ast.Pass(_line(p[0]))

@pg.production('simple_stmt : BREAK')
def break_stmt(p):
    return ast.Break(_line(p[0]))

@pg.production('simple_stmt : CONTINUE')
def continue_stmt(p):
    return ast.Continue(_line(p[0]))

@pg.production('simple_stmt : RETURN')
def return_bare(p):
    return ast.Return(None, _line(p[0]))

@pg.production('simple_stmt : RETURN expr')
def return_value(p):
    return ast.Return(_expr(p[1]), _line(p[0]))

@pg.production('simple_stmt : RAISE expr')
def raise_stmt(p):
    return ast.Raise(_expr(p[1]), _line(p[0]))

@pg.production('simple_stmt : postfix EQUALS expr')
def assign(p):
    target = _expr(p[0])
    value = _expr(p[2])
    if isinstance(target, ast.Name):
        return ast.Assign(target.id, value, target.lineno)
    if isinstance(target, ast.AttrRead):
        return ast.AttrAssign(target.target, target.attr, value,
                              target.lineno)
    if isinstance(target, ast.FieldRead):
        return ast.FieldAssign("", target.target, target.attr, value,
                               target.lineno)
    if isinstance(target, ast.Index):
        return ast.IndexAssign(target.target, target.index, value,
                               target.lineno)
    raise _error(p[1], "cannot assign to this expression")

@pg.production('simple_stmt : postfix COMMA arg_list EQUALS expr')
def unpack(p):
    rest = p[2]
    assert isinstance(rest, _ExprList)
    first = _expr(p[0])
    names = []
    for target in [first] + rest.items:
        if not isinstance(target, ast.Name):
            raise _error(p[3], "cannot assign to this expression")
        names.append(target.id)
    return ast.Unpack(names, _expr(p[4]), first.lineno)

@pg.production('simple_stmt : postfix augop expr')
def aug_assign(p):
    target = _expr(p[0])
    op = _text(p[1])[:-1]
    value = _expr(p[2])
    if isinstance(target, ast.Name):
        return ast.Assign(
            target.id, ast.BinOp(op, target, value, target.lineno),
            target.lineno)
    if isinstance(target, ast.AttrRead):
        return ast.AttrAssign(
            target.target, target.attr,
            ast.BinOp(op, target, value, target.lineno), target.lineno)
    if isinstance(target, ast.FieldRead):
        return ast.FieldAssign(op, target.target, target.attr, value,
                               target.lineno)
    if isinstance(target, ast.Index):
        return ast.IndexAugAssign(op, target.target, target.index, value,
                                  target.lineno)
    raise _error(p[1], "cannot assign to this expression")

@pg.production('simple_stmt : expr')
def expr_stmt(p):
    expr = _expr(p[0])
    return ast.ExprStmt(expr, expr.lineno)

@pg.production('if_stmt : IF expr COLON suite')
def if_stmt(p):
    return ast.If(_expr(p[1]), _stmts(p[3]), [], _line(p[0]))

@pg.production('if_stmt : IF expr COLON suite ELSE COLON suite')
@pg.production('elif_part : ELIF expr COLON suite ELSE COLON suite')
def if_else_stmt(p):
    return ast.If(_expr(p[1]), _stmts(p[3]), _stmts(p[6]), _line(p[0]))

@pg.production('if_stmt : IF expr COLON suite elif_part')
@pg.production('elif_part : ELIF expr COLON suite elif_part')
def if_elif_stmt(p):
    """An elif is an if alone in the else suite, as CPython's AST has
    it, so nothing below the parser knows the keyword (plan 1.11)."""
    rest = p[4]
    assert isinstance(rest, ast.If)
    return ast.If(_expr(p[1]), _stmts(p[3]), [rest], _line(p[0]))

@pg.production('elif_part : ELIF expr COLON suite')
def elif_stmt(p):
    return ast.If(_expr(p[1]), _stmts(p[3]), [], _line(p[0]))

@pg.production('for_stmt : FOR NAME IN expr COLON suite')
def for_stmt(p):
    iterable = _expr(p[3])
    if isinstance(iterable, ast.Call) and iterable.func == 'range':
        return ast.ForRange(_text(p[1]), iterable.args, _stmts(p[5]),
                            _line(p[0]))
    return ast.For(_text(p[1]), iterable, _stmts(p[5]), _line(p[0]))

@pg.production('for_stmt : FOR NAME COMMA NAME IN expr COLON suite')
def for_items_stmt(p):
    """for k, v in d.items(): the one for with two names (plan
    1.22). The call is an OpCall for a name on the left of the dot
    and a MethodCall for anything else."""
    iterable = _expr(p[5])
    target = None
    if isinstance(iterable, ast.OpCall):
        if iterable.op == 'items' and len(iterable.args) == 0:
            target = ast.Name(iterable.effect, iterable.lineno)
    elif isinstance(iterable, ast.MethodCall):
        if iterable.method == 'items' and len(iterable.args) == 0:
            target = iterable.target
    if target is None:
        raise _error(p[2], "a for with two names walks a dict: "
                     "for k, v in d.items()")
    if _text(p[1]) == _text(p[3]):
        raise _error(p[3], "the two names of a for must differ")
    return ast.ForItems(_text(p[1]), _text(p[3]), target, _stmts(p[7]),
                        _line(p[0]))

@pg.production('while_stmt : WHILE expr COLON suite')
def while_stmt(p):
    return ast.While(_expr(p[1]), _stmts(p[3]), _line(p[0]))

@pg.production('try_stmt : TRY COLON suite clauses')
def try_stmt(p):
    return _try(p[0], _stmts(p[2]), p[3], [])

@pg.production('try_stmt : TRY COLON suite clauses FINALLY COLON suite')
def try_finally_stmt(p):
    return _try(p[0], _stmts(p[2]), p[3], _stmts(p[6]))

@pg.production('try_stmt : TRY COLON suite FINALLY COLON suite')
def finally_stmt(p):
    return ast.Try(_stmts(p[2]), [], _stmts(p[5]), _line(p[0]))

def _try(token, body, clauses, finalbody):
    """Exception clauses give a Try. Effect clauses around a single
    clause-less with handle(...) give a Handle, which a finally wraps
    in a Try with no clauses (plan 1.8)."""
    assert isinstance(clauses, _ClauseList)
    if len(clauses.except_clauses) > 0:
        return ast.Try(body, clauses.except_clauses, finalbody,
                       _line(token))
    if len(body) == 1:
        handle = body[0]
        if isinstance(handle, ast.Handle) and len(handle.clauses) == 0:
            handle = ast.Handle(handle.effects, handle.body,
                                clauses.effect_clauses,
                                handle.constructions, _line(token))
            if len(finalbody) == 0:
                return handle
            return ast.Try([handle], [], finalbody, _line(token))
    raise _error(token, "effect clauses need a with handle(...) statement")

@pg.production('with_stmt : WITH NAME LPAREN handle_args RPAREN COLON suite')
def with_stmt(p):
    return _handle(p[1], p[3], p[6], [], _line(p[0]))

def _handle(handle, args, body, clauses, lineno):
    assert isinstance(handle, Token)
    assert isinstance(args, _HandleArgs)
    if handle.getstr() != 'handle':
        raise _error(handle, "a with statement must use handle(...)")
    return ast.Handle(args.names, _stmts(body), clauses,
                      args.constructions, lineno)

@pg.production('handle_args : handle_arg')
def handle_args_one(p):
    return _add_handle_arg(_HandleArgs(), p[0])

@pg.production('handle_args : handle_args COMMA handle_arg')
def handle_args_more(p):
    args = p[0]
    assert isinstance(args, _HandleArgs)
    return _add_handle_arg(args, p[2])

def _add_handle_arg(args, arg):
    if isinstance(arg, Token):
        args.names.append(arg.getstr())
    else:
        assert isinstance(arg, ast.Call)
        args.constructions.append(arg)
    return args

@pg.production('handle_arg : NAME')
def handle_arg_name(p):
    return p[0]

@pg.production('handle_arg : NAME LPAREN args RPAREN')
def handle_arg_construction(p):
    args = p[2]
    assert isinstance(args, _ExprList)
    return ast.Call(_text(p[0]), args.items, _line(p[0]))

@pg.production('clauses : clause')
def clauses_one(p):
    return _add_clause(_ClauseList(), p[0])

@pg.production('clauses : clauses clause')
def clauses_more(p):
    clauses = p[0]
    assert isinstance(clauses, _ClauseList)
    return _add_clause(clauses, p[1])

MIXED_ERROR = ("a try statement cannot mix effect clauses and exception "
               "clauses")

def _add_clause(clauses, box):
    assert isinstance(box, _ClauseBox)
    node = box.node
    if isinstance(node, ast.Clause):
        if len(clauses.except_clauses) > 0:
            raise _error(box.token, MIXED_ERROR)
        clauses.effect_clauses.append(node)
    else:
        assert isinstance(node, ast.ExceptClause)
        if len(clauses.effect_clauses) > 0:
            raise _error(box.token, MIXED_ERROR)
        clauses.except_clauses.append(node)
    return clauses

@pg.production('clause : EXCEPT NAME DOT NAME AS NAME COLON suite')
def effect_clause(p):
    return _ClauseBox(p[0], ast.Clause(
        _text(p[1]), _text(p[3]), _text(p[5]), _stmts(p[7]), _line(p[0])))

@pg.production('clause : EXCEPT NAME AS NAME COLON suite')
def except_clause_with_binding(p):
    return _ClauseBox(p[0], ast.ExceptClause(
        _text(p[1]), _text(p[3]), _stmts(p[5]), _line(p[0])))

@pg.production('clause : EXCEPT NAME COLON suite')
def except_clause(p):
    return _ClauseBox(p[0], ast.ExceptClause(
        _text(p[1]), None, _stmts(p[3]), _line(p[0])))

# --- Expressions -------------------------------------------------------------

@pg.production('expr : or_test')
@pg.production('or_test : and_test')
@pg.production('and_test : not_test')
@pg.production('not_test : comparison')
@pg.production('comparison : arith')
@pg.production('arith : term')
@pg.production('term : power')
@pg.production('power : postfix')
@pg.production('postfix : atom')
def pass_through_expr(p):
    return p[0]

@pg.production('or_test : or_test OR and_test')
@pg.production('and_test : and_test AND not_test')
def bool_op(p):
    left = _expr(p[0])
    return ast.BoolOp(_text(p[1]), left, _expr(p[2]), left.lineno)

@pg.production('not_test : NOT not_test')
def not_op(p):
    return ast.Not(_expr(p[1]), _line(p[0]))

@pg.production('comparison : arith IN arith')
def membership(p):
    left = _expr(p[0])
    return ast.In(left, _expr(p[2]), False, left.lineno)

@pg.production('comparison : arith NOT IN arith')
def non_membership(p):
    left = _expr(p[0])
    return ast.In(left, _expr(p[3]), True, left.lineno)

@pg.production('comparison : arith IS NONE')
def is_none(p):
    operand = _expr(p[0])
    return ast.IsNone(operand, False, operand.lineno)

@pg.production('comparison : arith IS NOT NONE')
def is_not_none(p):
    operand = _expr(p[0])
    return ast.IsNone(operand, True, operand.lineno)

@pg.production('comparison : arith cmpop arith')
def compare(p):
    left = _expr(p[0])
    return ast.Compare(_text(p[1]), left, _expr(p[2]), left.lineno)

@pg.production('term : MINUS power')
def negate(p):
    """A unary minus folds into the literal it negates, and elsewhere
    into 0 - x, so no node is added for it (plan 1.9). Its operand
    is a power, so -2 ** 2 is 0 - (2 ** 2), as in Python."""
    return _negated(p[0], _expr(p[1]))

def _negated(minus, operand):
    if isinstance(operand, ast.IntLiteral):
        return ast.IntLiteral(-operand.value, _line(minus))
    return ast.BinOp('-', ast.IntLiteral(0, _line(minus)), operand,
                     _line(minus))

@pg.production('power : postfix DOUBLESTAR MINUS power')
def power_of_negative(p):
    """2 ** -n parses, and the runtime refuses the exponent, which
    would give a float (plan 1.21)."""
    left = _expr(p[0])
    return ast.BinOp('**', left, _negated(p[2], _expr(p[3])),
                     left.lineno)

@pg.production('power : postfix DOUBLESTAR power')
@pg.production('arith : arith addop term')
@pg.production('term : term mulop power')
def binop(p):
    left = _expr(p[0])
    return ast.BinOp(_text(p[1]), left, _expr(p[2]), left.lineno)

@pg.production('cmpop : LT')
@pg.production('cmpop : LE')
@pg.production('cmpop : GT')
@pg.production('cmpop : GE')
@pg.production('cmpop : EQ')
@pg.production('cmpop : NE')
@pg.production('addop : PLUS')
@pg.production('addop : MINUS')
@pg.production('mulop : STAR')
@pg.production('mulop : DOUBLESLASH')
@pg.production('mulop : PERCENT')
@pg.production('augop : PLUSEQUALS')
@pg.production('augop : MINUSEQUALS')
@pg.production('augop : STAREQUALS')
@pg.production('augop : DOUBLESTAREQUALS')
@pg.production('augop : DOUBLESLASHEQUALS')
@pg.production('augop : PERCENTEQUALS')
def operator(p):
    return p[0]

@pg.production('atom : INT')
def int_literal(p):
    return ast.IntLiteral(int(_text(p[0])), _line(p[0]))

@pg.production('atom : TRUE')
def true_literal(p):
    return ast.BoolLiteral(True, _line(p[0]))

@pg.production('atom : FALSE')
def false_literal(p):
    return ast.BoolLiteral(False, _line(p[0]))

@pg.production('atom : NONE')
def none_literal(p):
    return ast.NoneLiteral(_line(p[0]))

@pg.production('atom : STRING')
def str_literal(p):
    text = _text(p[0])
    end = len(text) - 1
    assert end >= 1  # the lexer guarantees both quotes are present
    return ast.StrLiteral(text[1:end], _line(p[0]))

@pg.production('atom : NAME')
def name(p):
    return ast.Name(_text(p[0]), _line(p[0]))

@pg.production('atom : NAME LPAREN args RPAREN')
def call(p):
    args = p[2]
    assert isinstance(args, _ExprList)
    if _text(p[0]) == 'perform':
        return _perform(p[0], args.items)
    return ast.Call(_text(p[0]), args.items, _line(p[0]))

def _perform(tok, args):
    if len(args) == 1:
        payload = args[0]
        if isinstance(payload, ast.OpCall):
            return ast.Perform(payload.effect, payload.op, payload.args,
                               _line(tok))
    raise _error(tok, "perform() takes one Effect.op(...) argument")

@pg.production('postfix : postfix DOT NAME')
def attr_read(p):
    target = _expr(p[0])
    if not isinstance(target, ast.Name):
        return ast.FieldRead(target, _text(p[2]), target.lineno)
    return ast.AttrRead(target.id, _text(p[2]), target.lineno)

@pg.production('postfix : postfix DOT NAME LPAREN args RPAREN')
def attr_call(p):
    target = _expr(p[0])
    args = p[4]
    assert isinstance(args, _ExprList)
    method = _text(p[2])
    if not isinstance(target, ast.Name):
        return ast.MethodCall(target, method, args.items, target.lineno)
    if method == 'resume':
        if len(args.items) != 1:
            raise _error(p[2], "resume() takes one argument")
        return ast.Resume(target.id, args.items[0], target.lineno)
    if method == 'throw':
        if len(args.items) != 1:
            raise _error(p[2], "throw() takes one argument")
        return ast.Throw(target.id, args.items[0], target.lineno)
    return ast.OpCall(target.id, method, args.items, target.lineno)

@pg.production('postfix : postfix LBRACKET expr RBRACKET')
def index(p):
    target = _expr(p[0])
    return ast.Index(target, _expr(p[2]), target.lineno)

@pg.production('atom : LBRACKET args RBRACKET')
def list_literal(p):
    elements = p[1]
    assert isinstance(elements, _ExprList)
    return ast.ListLiteral(elements.items, _line(p[0]))

@pg.production('atom : FSTRING_START FSTRING_END')
def empty_fstring(p):
    return ast.FString([""], [], _line(p[0]))

@pg.production('atom : FSTRING_START fstring_parts FSTRING_END')
def fstring(p):
    parts = p[1]
    assert isinstance(parts, _FStringParts)
    return ast.FString(parts.literals, parts.exprs, _line(p[0]))

@pg.production('fstring_parts : FSTRING_MIDDLE')
def fstring_text(p):
    return _FStringParts([_text(p[0])], [])

@pg.production('fstring_parts : LBRACE expr RBRACE')
def fstring_field(p):
    return _FStringParts(["", ""], [_expr(p[1])])

@pg.production('fstring_parts : fstring_parts FSTRING_MIDDLE')
def fstring_more_text(p):
    parts = p[0]
    assert isinstance(parts, _FStringParts)
    parts.literals[-1] = parts.literals[-1] + _text(p[1])
    return parts

@pg.production('fstring_parts : fstring_parts LBRACE expr RBRACE')
def fstring_more_fields(p):
    parts = p[0]
    assert isinstance(parts, _FStringParts)
    parts.exprs.append(_expr(p[2]))
    parts.literals.append("")
    return parts

@pg.production('atom : LBRACE RBRACE')
def empty_dict_literal(p):
    return ast.DictLiteral([], [], _line(p[0]))

@pg.production('atom : LBRACE dict_items RBRACE')
def dict_literal(p):
    items = p[1]
    assert isinstance(items, _DictItems)
    return ast.DictLiteral(items.keys, items.values, _line(p[0]))

@pg.production('dict_items : expr COLON expr')
def dict_item(p):
    return _DictItems([_expr(p[0])], [_expr(p[2])])

@pg.production('dict_items : dict_items COMMA expr COLON expr')
def dict_items(p):
    items = p[0]
    assert isinstance(items, _DictItems)
    items.keys.append(_expr(p[2]))
    items.values.append(_expr(p[4]))
    return items

@pg.production('atom : LPAREN expr RPAREN')
def parenthesized(p):
    return p[1]

@pg.production('atom : LPAREN expr COMMA arg_list RPAREN')
def tuple_literal(p):
    rest = p[3]
    assert isinstance(rest, _ExprList)
    return ast.TupleLiteral([_expr(p[1])] + rest.items, _line(p[0]))

@pg.production('args :')
def args_empty(p):
    return _ExprList([])

@pg.production('arg_list : expr')
def arg_list_one(p):
    return _ExprList([_expr(p[0])])

@pg.production('arg_list : arg_list COMMA expr')
def arg_list_more(p):
    args = p[0]
    assert isinstance(args, _ExprList)
    args.items.append(_expr(p[2]))
    return args

# --- Errors and entry point --------------------------------------------------

DESCRIPTIONS = {
    'NEWLINE': 'end of line', 'INDENT': 'indent', 'DEDENT': 'dedent',
    '$end': 'end of input',
}

def _error(box, what):
    """An InvalidSyntax positioned at a token."""
    assert isinstance(box, Token)
    pos = box.getsourcepos()
    if pos is None:
        return InvalidSyntax(0, 0, what)
    return InvalidSyntax(pos.lineno, pos.colno, what)

@pg.error
def on_error(token):
    kind = token.gettokentype()
    if kind in DESCRIPTIONS:
        raise _error(token, "unexpected " + DESCRIPTIONS[kind])
    raise _error(token, "unexpected '%s'" % token.getstr())

parser = pg.build()

def parse(source):
    """Parse one .epy source text into an ast.Module."""
    tree = parser.parse(TokenList(tokenize(source)))
    assert isinstance(tree, ast.Module)
    return tree
