"""Experiment: does rply translate with this toolchain?

A lexer and parser for sums of integers, built with rply the way the
EffectPython frontend will be: the lexer and the LR parser are built at
import time and become prebuilt constants in the translated binary;
production functions return BaseBox subclasses.

Two findings from the first translation of this file shape the frontend:

1. A LexingError raised inside LexerStream.next() disappears in the
   translated binary. rply's parse loop fetches tokens with the next()
   built-in, and RPython's `next` operation only carries exception links
   for StopIteration (rpython/flowspace/operation.py, class Next), so any
   other exception leaves the loop with a null token, which the parser
   reads as end of input. "1 - 2" parsed as 1 with exit code 0. The fix
   is to lex the whole source into a list first, calling the stream's
   next() method directly inside try/except LexingError, and hand the
   parser an iterator over that list. The INDENT/DEDENT post-processor
   needs that list anyway.
2. str(e) on an exception prints an object address when translated, so
   every error the frontend raises carries its own msg attribute.

Translate and run:

    pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --batch --continuation \
        --output=/path/to/rply_addition-c experiments/rply_addition.py
    /path/to/rply_addition-c "1 + 2 + 39"

Run untranslated:

    PYTHONPATH=~/pypy/pypy2.7-v8.0.1-src pypy2 experiments/rply_addition.py "1 + 2"
"""
import sys

from rply import LexerGenerator, ParserGenerator
from rply.errors import LexingError
from rply.token import BaseBox, Token


class SyntaxErr(Exception):
    """Carries a message RPython can print; str(e) cannot."""

    def __init__(self, msg):
        self.msg = msg


# --- Lexer -----------------------------------------------------------------

lg = LexerGenerator()
lg.add("NUMBER", r"\d+")
lg.add("PLUS", r"\+")
lg.ignore(r"\s+")
lexer = lg.build()


# --- AST boxes -------------------------------------------------------------

class Expr(BaseBox):
    _attrs_ = []

    def eval(self):
        return 0

    def show(self):
        return "?"


class Number(Expr):
    _attrs_ = ['value']

    def __init__(self, value):
        self.value = value

    def eval(self):
        return self.value

    def show(self):
        return str(self.value)


class Add(Expr):
    _attrs_ = ['left', 'right']

    def __init__(self, left, right):
        self.left = left
        self.right = right

    def eval(self):
        return self.left.eval() + self.right.eval()

    def show(self):
        return "(%s + %s)" % (self.left.show(), self.right.show())


# --- Parser ----------------------------------------------------------------

pg = ParserGenerator(["NUMBER", "PLUS"])


@pg.production("expr : expr PLUS NUMBER")
def expr_add(p):
    left = p[0]
    tok = p[2]
    assert isinstance(left, Expr)
    assert isinstance(tok, Token)
    return Add(left, Number(int(tok.getstr())))


@pg.production("expr : NUMBER")
def expr_number(p):
    tok = p[0]
    assert isinstance(tok, Token)
    return Number(int(tok.getstr()))


@pg.error
def error_handler(token):
    pos = token.getsourcepos()
    if pos is None:  # the $end token has no position
        raise SyntaxErr("unexpected end of input")
    raise SyntaxErr("unexpected token %s at column %d" %
                    (token.gettokentype(), pos.colno))


parser = pg.build()


class TokenList(object):
    """An iterator over an already-lexed token list. Its next() raises
    only StopIteration, which is the one exception RPython's next()
    built-in propagates (see finding 1 above)."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def next(self):
        if self.i >= len(self.tokens):
            raise StopIteration
        tok = self.tokens[self.i]
        self.i += 1
        return tok


def tokenize(source):
    stream = lexer.lex(source)
    tokens = []
    while True:
        try:
            tok = stream.next()
        except StopIteration:
            break
        except LexingError as e:
            # pos.colno is the column of the previous token, not of the
            # failure; pos.idx is the failing offset, so derive the column
            # from it. repr() is not RPython, so quote by hand.
            pos = e.getsourcepos()
            raise SyntaxErr("cannot lex '%s' at column %d" %
                            (source[pos.idx], pos.idx + 1))
        tokens.append(tok)
    return tokens


def parse(source):
    tree = parser.parse(TokenList(tokenize(source)))
    assert isinstance(tree, Expr)
    return tree


def entry_point(argv):
    source = "1 + 2 + 39"
    if len(argv) > 1:
        source = argv[1]
    try:
        tree = parse(source)
    except SyntaxErr as e:
        print "parse error:", e.msg
        return 1
    print tree.show(), "=", tree.eval()
    return 0


def target(driver, args):
    return entry_point, None


if __name__ == "__main__":
    sys.exit(entry_point(sys.argv))
