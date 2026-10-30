"""The parser: an rply LALR grammar producing ast_nodes (plan 2.1).

The grammar is the plan's subset of Python 3: the import line, Effect
classes with operation stubs, function definitions with typed
parameters, a return type, and an optional effect row; return,
assignment, expression, pass, if/else, and try/with handle/except
statements; literals, names, arithmetic, comparisons, calls,
attribute reads, and attribute calls.

perform and handle are names in Python, not keywords, so the grammar
reads them as calls and the productions check them: perform(X) must
wrap an Effect.op(...) call and becomes a Perform node, with handle(...)
must name handle, and a class must derive from Effect. An attribute
call name.resume(x) becomes a Resume node; any other Effect.op(...)
call is an OpCall.

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
    _attrs_ = ['functions', 'effects']

    def __init__(self):
        self.functions = []  # list of FunctionDef
        self.effects = []    # list of EffectDef

class _Skipped(BaseBox):
    """The value of a module item that produces no node."""
    _attrs_ = []

class _OpList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of OperationDef

class _ClauseList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of Clause

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
    return ast.Module(parts.functions, parts.effects, 1)

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
    else:
        assert isinstance(item, _Skipped)
    return parts

@pg.production('item : funcdef')
@pg.production('item : effectdef')
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
    if base.getstr() != 'Effect':
        raise _error(base, "a class must derive from Effect")
    return ast.EffectDef(_text(p[1]), ops.items, _line(p[0]))

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

@pg.production('opdef : DEF NAME LPAREN params RPAREN ARROW NAME COLON'
               ' ELLIPSIS NEWLINE')
def opdef(p):
    params = p[3]
    assert isinstance(params, _ParamList)
    return ast.OperationDef(_text(p[1]), params.names, params.types,
                            _text(p[6]), _line(p[0]))

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
@pg.production('stmt : handle_stmt')
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

@pg.production('simple_stmt : NAME EQUALS expr')
def assign(p):
    return ast.Assign(_text(p[0]), _expr(p[2]), _line(p[0]))

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

@pg.production('handle_stmt : TRY COLON NEWLINE INDENT'
               ' WITH NAME LPAREN name_list RPAREN COLON suite'
               ' DEDENT clauses')
def handle_stmt(p):
    handle = p[5]
    effects = p[7]
    clauses = p[12]
    assert isinstance(handle, Token)
    assert isinstance(effects, _NameList)
    assert isinstance(clauses, _ClauseList)
    if handle.getstr() != 'handle':
        raise _error(handle, "a with statement must use handle(...)")
    return ast.Handle(effects.items, _stmts(p[10]), clauses.items,
                      _line(p[0]))

@pg.production('clauses : clause')
def clauses_one(p):
    clause = p[0]
    assert isinstance(clause, ast.Clause)
    return _ClauseList([clause])

@pg.production('clauses : clauses clause')
def clauses_more(p):
    clauses = p[0]
    clause = p[1]
    assert isinstance(clauses, _ClauseList)
    assert isinstance(clause, ast.Clause)
    clauses.items.append(clause)
    return clauses

@pg.production('clause : EXCEPT NAME DOT NAME AS NAME COLON suite')
def clause(p):
    return ast.Clause(_text(p[1]), _text(p[3]), _text(p[5]), _stmts(p[7]),
                      _line(p[0]))

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
