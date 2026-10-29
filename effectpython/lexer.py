"""The lexer: rply tokens plus INDENT, DEDENT, and NEWLINE (plan 2.1).

rply has no notion of indentation, so the generated lexer sees a NEWLINE
token as the newline character followed by the indentation of the next
line. tokenize() lexes the whole source into a list and then makes a
second pass over that list to produce Python's line structure: blank and
comment-only lines vanish, newlines inside brackets vanish, and a change
of indentation between two statements becomes INDENT or DEDENT tokens.
Keywords come out of the generated lexer as NAME tokens and are renamed
in the same pass, so the keyword list lives in one place.

The whole file is lexed before parsing because RPython's next() built-in
propagates only StopIteration: a LexingError raised while the parser
fetches a token would vanish in the translated binary (plan 2.1).
TokenList gives the parser an iterator whose next() raises only
StopIteration.
"""
from rply import LexerGenerator
from rply.errors import LexingError
from rply.token import Token

from effectpython.errors import InvalidSyntax

KEYWORDS = {
    'def': 'DEF', 'return': 'RETURN', 'if': 'IF', 'else': 'ELSE',
}

# Order matters: a longer operator precedes any prefix of it
RULES = [
    ('NEWLINE', r'\n[ \t]*'),
    ('INT', r'\d+'),
    ('STRING', r'"[^"\n]*"|\'[^\'\n]*\''),
    ('NAME', r'[A-Za-z_][A-Za-z0-9_]*'),
    ('ARROW', r'->'),
    ('DOUBLESLASH', r'//'),
    ('LE', r'<='),
    ('GE', r'>='),
    ('EQ', r'=='),
    ('NE', r'!='),
    ('LT', r'<'),
    ('GT', r'>'),
    ('EQUALS', r'='),
    ('PLUS', r'\+'),
    ('MINUS', r'-'),
    ('STAR', r'\*'),
    ('SLASH', r'/'),
    ('PERCENT', r'%'),
    ('COLON', r':'),
    ('COMMA', r','),
    ('LPAREN', r'\('),
    ('RPAREN', r'\)'),
    ('LBRACKET', r'\['),
    ('RBRACKET', r'\]'),
]

TOKENS = (['INDENT', 'DEDENT'] + [name for name, pattern in RULES]
          + sorted(KEYWORDS.values()))

OPENERS = ['LPAREN', 'LBRACKET']
CLOSERS = ['RPAREN', 'RBRACKET']


def _build_lexer():
    lg = LexerGenerator()
    lg.ignore(r'[ \t\r]+')
    lg.ignore(r'#[^\n]*')
    for name, pattern in RULES:
        lg.add(name, pattern)
    return lg.build()


lexer = _build_lexer()


class TokenList(object):
    """An iterator over an already-lexed token list for rply's parser."""

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def next(self):
        if self.i >= len(self.tokens):
            raise StopIteration
        tok = self.tokens[self.i]
        self.i += 1
        return tok


def _line_col(source, idx):
    lineno = source.count('\n', 0, idx) + 1
    colno = idx - source.rfind('\n', 0, idx)
    return lineno, colno


def raw_tokens(source):
    """The generated lexer's tokens, with NEWLINE tokens still carrying
    the following line's indentation and keywords still NAME tokens."""
    stream = lexer.lex(source)
    tokens = []
    while True:
        try:
            tok = stream.next()
        except StopIteration:
            break
        except LexingError as e:
            idx = e.getsourcepos().idx
            lineno, colno = _line_col(source, idx)
            raise InvalidSyntax(lineno, colno,
                                "unexpected character '%s'" % source[idx])
        tokens.append(tok)
    return tokens


def _rename_keyword(tok):
    text = tok.getstr()
    if tok.gettokentype() == 'NAME' and text in KEYWORDS:
        return Token(KEYWORDS[text], text, tok.getsourcepos())
    return tok


def _change_indent(indent, stack, pos, result):
    if indent > stack[-1]:
        stack.append(indent)
        result.append(Token('INDENT', '', pos))
        return
    while indent < stack[-1]:
        stack.pop()
        result.append(Token('DEDENT', '', pos))
    if indent != stack[-1]:
        raise InvalidSyntax(
            pos.lineno, pos.colno,
            "unindent does not match any outer indentation level")


def tokenize(source):
    """The token list the parser reads: raw_tokens() with line structure."""
    result = []
    stack = [0]
    openers = []
    at_line_start = True
    indent = 0
    last_pos = None
    for tok in raw_tokens(source):
        name = tok.gettokentype()
        last_pos = tok.getsourcepos()
        if name == 'NEWLINE':
            if len(openers) > 0:
                continue
            indent = len(tok.getstr()) - 1
            if not at_line_start:
                result.append(tok)
                at_line_start = True
            continue
        if at_line_start:
            _change_indent(indent, stack, last_pos, result)
            at_line_start = False
        if name in OPENERS:
            openers.append(tok)
        elif name in CLOSERS and len(openers) > 0:
            openers.pop()
        result.append(_rename_keyword(tok))
    if len(openers) > 0:
        pos = openers[-1].getsourcepos()
        raise InvalidSyntax(pos.lineno, pos.colno,
                            "'%s' was never closed" % openers[-1].getstr())
    if not at_line_start:
        result.append(Token('NEWLINE', '\n', last_pos))
    while len(stack) > 1:
        stack.pop()
        result.append(Token('DEDENT', '', last_pos))
    return result
