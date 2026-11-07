"""The parser: an rply LALR grammar producing ast_nodes (plan 2.1).

The grammar is the plan's subset of Python 3: the import line, Effect
classes with operation stubs, Handler[Effect] classes with field
declarations and methods, exception classes, function definitions
with typed parameters, a return type, and an optional effect row;
return, raise, assignment, attribute assignment, expression, pass,
if/else, while, try/except/finally, and handle statements; int, str, and
bool literals, names,
arithmetic, comparisons, calls, attribute reads, and attribute calls.

perform and handle are names in Python, not keywords, so the grammar
reads them as calls and the productions check them: perform(X) must
wrap an Effect.op(...) call and becomes a Perform node, with handle(...)
must name handle, and a class must derive from Effect, Handler[...],
or Exception.
An attribute call name.resume(x) becomes a Resume node and
name.throw(x) a Throw node; any other Effect.op(...) call is an
OpCall. A handle(...) argument is a bare
name or a constructor call Name(...); the checker decides whether a
bare name is an effect or a handler instance (plan 1.5).

One production reads every try statement, because separate ones for
a handler installation and an ordinary try/except would conflict in
the LALR tables: both begin TRY COLON NEWLINE INDENT, and with
handle(...) is also a statement (plan 1.6). The action decides by
the clauses. Clauses that name Effect.op around a single with
handle(...) statement give a Handle; clauses that name a class give
a Try; a mix is an error.

RPython requires every production to return one type, so every value on
the parse stack is a BaseBox: a Token, a Node (ast_nodes makes Node a
BaseBox), or one of the list boxes below for the sequences the grammar
accumulates. Each production narrows its operands with isinstance
asserts, which the annotator reads as type information.
"""
from rply import ParserGenerator
from rply.token import BaseBox, Token

from effectpython import ast_nodes as ast
from effectpython.errors import InvalidSyntax
from effectpython.lexer import TOKENS, TokenList, tokenize

class _ModuleParts(BaseBox):
    _attrs_ = ['functions', 'effects', 'handlers', 'exceptions']

    def __init__(self):
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

class _NameList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of str

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

pg = ParserGenerator(TOKENS)

# --- Module and definitions --------------------------------------------------

@pg.production('module : items')
def module(p):
    parts = p[0]
    assert isinstance(parts, _ModuleParts)
    return ast.Module(parts.functions, parts.effects, parts.handlers,
                      parts.exceptions, 1)

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
    else:
        assert isinstance(item, _Skipped)
    return parts

@pg.production('item : funcdef')
@pg.production('item : effectdef')
@pg.production('item : handlerdef')
@pg.production('item : exceptiondef')
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

@pg.production('handler_item : NAME COLON NAME NEWLINE')
def field_without_default(p):
    return ast.FieldDef(_text(p[0]), _text(p[2]), None, _line(p[0]))

@pg.production('handler_item : NAME COLON NAME EQUALS expr NEWLINE')
def field_with_default(p):
    default = _expr(p[4])
    if not (isinstance(default, ast.IntLiteral)
            or isinstance(default, ast.StrLiteral)):
        raise _error(p[3], "a field default must be an int or str literal")
    return ast.FieldDef(_text(p[0]), _text(p[2]), default, _line(p[0]))

@pg.production('handler_item : DEF NAME LPAREN method_params RPAREN ARROW'
               ' NAME effect_row COLON suite')
def methoddef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    # A bare self is the one parameter the grammar leaves untyped
    if len(params.types) == 0 or params.types[0] != '':
        raise _error(p[2], SELF_ERROR)
    return ast.FunctionDef(_text(p[1]), params.names, params.types,
                           _text(p[6]), row.items, _stmts(p[9]),
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

@pg.production('opdef : DEF NAME LPAREN params RPAREN ARROW NAME'
               ' effect_row COLON ELLIPSIS NEWLINE')
def opdef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    return ast.OperationDef(_text(p[1]), params.names, params.types,
                            _text(p[6]), row.items, _line(p[0]))

@pg.production('funcdef : DEF NAME LPAREN params RPAREN ARROW NAME'
               ' effect_row COLON suite')
def funcdef(p):
    params = p[3]
    row = p[7]
    assert isinstance(params, _ParamList)
    assert isinstance(row, _NameList)
    return ast.FunctionDef(_text(p[1]), params.names, params.types,
                           _text(p[6]), row.items, _stmts(p[9]),
                           _line(p[0]))

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

@pg.production('param_list : NAME COLON NAME')
def param_list_one(p):
    return _ParamList([_text(p[0])], [_text(p[2])])

@pg.production('param_list : param_list COMMA NAME COLON NAME')
def param_list_more(p):
    params = p[0]
    assert isinstance(params, _ParamList)
    params.names.append(_text(p[2]))
    params.types.append(_text(p[4]))
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
@pg.production('stmt : try_stmt')
@pg.production('stmt : with_stmt')
def stmt(p):
    return p[0]

@pg.production('simple_stmt : PASS')
def pass_stmt(p):
    return ast.Pass(_line(p[0]))

@pg.production('simple_stmt : RETURN')
def return_bare(p):
    return ast.Return(None, _line(p[0]))

@pg.production('simple_stmt : RETURN expr')
def return_value(p):
    return ast.Return(_expr(p[1]), _line(p[0]))

@pg.production('simple_stmt : RAISE expr')
def raise_stmt(p):
    return ast.Raise(_expr(p[1]), _line(p[0]))

@pg.production('simple_stmt : NAME EQUALS expr')
def assign(p):
    return ast.Assign(_text(p[0]), _expr(p[2]), _line(p[0]))

@pg.production('simple_stmt : NAME DOT NAME EQUALS expr')
def attr_assign(p):
    return ast.AttrAssign(_text(p[0]), _text(p[2]), _expr(p[4]),
                          _line(p[0]))

@pg.production('simple_stmt : expr')
def expr_stmt(p):
    expr = _expr(p[0])
    return ast.ExprStmt(expr, expr.lineno)

@pg.production('if_stmt : IF expr COLON suite')
def if_stmt(p):
    return ast.If(_expr(p[1]), _stmts(p[3]), [], _line(p[0]))

@pg.production('if_stmt : IF expr COLON suite ELSE COLON suite')
def if_else_stmt(p):
    return ast.If(_expr(p[1]), _stmts(p[3]), _stmts(p[6]), _line(p[0]))

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

@pg.production('expr : arith')
@pg.production('arith : term')
@pg.production('term : atom')
def pass_through_expr(p):
    return p[0]

@pg.production('expr : arith cmpop arith')
def compare(p):
    left = _expr(p[0])
    return ast.Compare(_text(p[1]), left, _expr(p[2]), left.lineno)

@pg.production('arith : arith addop term')
@pg.production('term : term mulop atom')
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

@pg.production('atom : NAME DOT NAME')
def attr_read(p):
    return ast.AttrRead(_text(p[0]), _text(p[2]), _line(p[0]))

@pg.production('atom : NAME DOT NAME LPAREN args RPAREN')
def attr_call(p):
    args = p[4]
    assert isinstance(args, _ExprList)
    if _text(p[2]) == 'resume':
        if len(args.items) != 1:
            raise _error(p[2], "resume() takes one argument")
        return ast.Resume(_text(p[0]), args.items[0], _line(p[0]))
    if _text(p[2]) == 'throw':
        if len(args.items) != 1:
            raise _error(p[2], "throw() takes one argument")
        return ast.Throw(_text(p[0]), args.items[0], _line(p[0]))
    return ast.OpCall(_text(p[0]), _text(p[2]), args.items, _line(p[0]))

@pg.production('atom : LPAREN expr RPAREN')
def parenthesized(p):
    return p[1]

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
