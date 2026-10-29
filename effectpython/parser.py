"""The parser: an rply LALR grammar producing ast_nodes (plan 2.1).

This covers the subset the evaluator runs today: function definitions
with typed parameters, a return type, and an optional effect row;
return, assignment, expression, and if/else statements; integer and
string literals, names, arithmetic, comparisons, and calls. Effect
declarations, perform, and handle arrive with the checker.

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


class _FuncList(BaseBox):
    _attrs_ = ['items']

    def __init__(self, items):
        self.items = items  # list of FunctionDef


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

@pg.production('module :')
def module_empty(p):
    return ast.Module([], 1)


@pg.production('module : funcdefs')
def module_funcdefs(p):
    funcs = p[0]
    assert isinstance(funcs, _FuncList)
    return ast.Module(funcs.items, 1)


@pg.production('funcdefs : funcdef')
def funcdefs_one(p):
    fn = p[0]
    assert isinstance(fn, ast.FunctionDef)
    return _FuncList([fn])


@pg.production('funcdefs : funcdefs funcdef')
def funcdefs_more(p):
    funcs = p[0]
    fn = p[1]
    assert isinstance(funcs, _FuncList)
    assert isinstance(fn, ast.FunctionDef)
    funcs.items.append(fn)
    return funcs


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
def stmt(p):
    return p[0]


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
    return ast.Call(_text(p[0]), args.items, _line(p[0]))


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


@pg.error
def on_error(token):
    kind = token.gettokentype()
    if kind in DESCRIPTIONS:
        what = "unexpected " + DESCRIPTIONS[kind]
    else:
        what = "unexpected '%s'" % token.getstr()
    pos = token.getsourcepos()
    if pos is None:
        raise InvalidSyntax(0, 0, what)
    raise InvalidSyntax(pos.lineno, pos.colno, what)


parser = pg.build()


def parse(source):
    """Parse one .epy source text into an ast.Module."""
    tree = parser.parse(TokenList(tokenize(source)))
    assert isinstance(tree, ast.Module)
    return tree
