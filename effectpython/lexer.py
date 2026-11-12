"""The lexer: rply tokens plus INDENT, DEDENT, and NEWLINE (plan 2.1).

rply has no notion of indentation, so the generated lexer sees a NEWLINE
token as the newline character followed by the indentation of the next
line. tokenize() lexes the whole source into a list and then makes a
second pass over that list to produce Python's line structure: blank and
comment-only lines vanish, newlines inside brackets vanish, and a change
of indentation between two statements becomes INDENT or DEDENT tokens.
Keywords come out of the generated lexer as NAME tokens and are renamed
in the same pass, so the keyword list lives in one place. An f-string
comes out as one FSTRING token, which raw_tokens() expands into the
sequence CPython 3.12 produces (PEP 701): FSTRING_START, then an
FSTRING_MIDDLE for each run of literal text and LBRACE, the field's
own tokens, RBRACE for each {expr} field, then FSTRING_END. A field
with a format spec, {expr:spec}, has one FSTRING_SPEC token holding
the spec's text between the expression's tokens and the RBRACE (plan
1.24). The
field's tokens come from the generated lexer run over the field's
text, with each position shifted to the field's place in the source
(plan 1.13). A field holds no brace and no quote of the enclosing
kind; a { with no }, a } with no {, an empty field, and a { inside a
field are the four f-string errors, the first three in the words of
CPython 3.12 and later.

The whole file is lexed before parsing because RPython's next() built-in
propagates StopIteration and RuntimeError alone: a LexingError raised
while the parser fetches a token would vanish in the translated binary
(plan 2.1).
TokenList gives the parser an iterator whose next() raises only
StopIteration.
"""
from rply import LexerGenerator
from rply.errors import LexingError
from rply.token import SourcePosition, Token

from effectpython.errors import InvalidSyntax

KEYWORDS = {
    'def': 'DEF', 'return': 'RETURN', 'if': 'IF', 'else': 'ELSE',
    'while': 'WHILE', 'raise': 'RAISE',
    'class': 'CLASS', 'pass': 'PASS', 'try': 'TRY', 'except': 'EXCEPT',
    'as': 'AS', 'with': 'WITH', 'from': 'FROM', 'import': 'IMPORT',
    'True': 'TRUE', 'False': 'FALSE', 'finally': 'FINALLY',
    'for': 'FOR', 'in': 'IN', 'break': 'BREAK', 'continue': 'CONTINUE',
    'and': 'AND', 'or': 'OR', 'not': 'NOT', 'elif': 'ELIF',
    'None': 'NONE', 'is': 'IS',
}

# Order matters: a longer operator precedes any prefix of it
RULES = [
    ('NEWLINE', r'\n[ \t]*'),
    ('INT', r'\d+'),
    ('STRING', r'"[^"\n]*"|\'[^\'\n]*\''),
    ('FSTRING', r'f"[^"\n]*"|f\'[^\'\n]*\''),
    ('NAME', r'[A-Za-z_][A-Za-z0-9_]*'),
    ('ELLIPSIS', r'\.\.\.'),
    ('DOT', r'\.'),
    ('ARROW', r'->'),
    ('PLUSEQUALS', r'\+='),
    ('MINUSEQUALS', r'-='),
    ('DOUBLESTAREQUALS', r'\*\*='),
    ('DOUBLESTAR', r'\*\*'),
    ('STAREQUALS', r'\*='),
    ('DOUBLESLASHEQUALS', r'//='),
    ('PERCENTEQUALS', r'%='),
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
    ('LBRACE', r'\{'),
    ('RBRACE', r'\}'),
    ('PIPE', r'\|'),
    ('AT', r'@'),
]

RAW_ONLY = ['FSTRING']  # expanded before the parser sees the list
FSTRING_TOKENS = ['FSTRING_START', 'FSTRING_MIDDLE', 'FSTRING_END',
                  'FSTRING_SPEC']

TOKENS = (['INDENT', 'DEDENT'] + FSTRING_TOKENS
          + [name for name, pattern in RULES if name not in RAW_ONLY]
          + sorted(KEYWORDS.values()))

OPENERS = ['LPAREN', 'LBRACKET', 'LBRACE']
CLOSERS = ['RPAREN', 'RBRACKET', 'RBRACE']

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
    the following line's indentation, keywords still NAME tokens, and
    each FSTRING token expanded."""
    tokens = []
    for tok in _lex(source, None):
        if tok.gettokentype() == 'FSTRING':
            tokens.extend(_expand_fstring(tok))
        else:
            tokens.append(tok)
    return tokens

def _lex(text, base):
    """The generated lexer's tokens for text: the whole source when
    base is None, else an f-string field that starts at the source
    position base and holds no newline."""
    stream = lexer.lex(text)
    tokens = []
    while True:
        try:
            tok = stream.next()
        except StopIteration:
            break
        except LexingError as e:
            idx = e.getsourcepos().idx
            pos = _shifted(base, text, idx)
            raise InvalidSyntax(pos.lineno, pos.colno,
                                "unexpected character '%s'" % text[idx])
        pos = tok.getsourcepos()
        tokens.append(Token(tok.gettokentype(), tok.getstr(),
                            _shifted(base, text, pos.idx)))
    return tokens

def _shifted(base, text, idx):
    """The source position of text[idx] when text starts at base."""
    if base is None:
        lineno, colno = _line_col(text, idx)
        return SourcePosition(idx, lineno, colno)
    return SourcePosition(base.idx + idx, base.lineno, base.colno + idx)

def _fstring_error(tok, idx, msg):
    pos = _shifted(tok.getsourcepos(), tok.getstr(), idx)
    return InvalidSyntax(pos.lineno, pos.colno, "f-string: " + msg)

def _expand_fstring(tok):
    """FSTRING_START, FSTRING_MIDDLE and LBRACE expr RBRACE parts in
    source order, and FSTRING_END, for one f"..." token."""
    text = tok.getstr()
    pos = tok.getsourcepos()
    end = len(text) - 1
    assert end >= 2  # the lexer guarantees the prefix and both quotes
    result = [Token('FSTRING_START', text[:2], pos)]
    i = 2
    while i < end:
        j = i
        while j < end and text[j] != '{' and text[j] != '}':
            j += 1
        if j > i:
            assert i >= 0
            result.append(Token('FSTRING_MIDDLE', text[i:j],
                                _shifted(pos, text, i)))
        if j == end:
            break
        if text[j] == '}':
            raise _fstring_error(tok, j, "single '}' is not allowed")
        k = j + 1
        while k < end and text[k] != '}' and text[k] != '{':
            k += 1
        if k == end:
            raise _fstring_error(tok, j, "expecting '}'")
        if text[k] == '{':
            raise _fstring_error(tok, k, "nested '{' is not allowed")
        start = j + 1
        assert start >= 0
        colon = _spec_start(text, start, k)
        field = text[start:colon]
        if field.strip() == '':
            raise _fstring_error(
                tok, j, "valid expression required before '%s'"
                % text[colon])
        result.append(Token('LBRACE', '{', _shifted(pos, text, j)))
        result.extend(_lex(field, _shifted(pos, text, start)))
        if colon < k:
            after = colon + 1
            assert after >= 0
            result.append(Token('FSTRING_SPEC', text[after:k],
                                _shifted(pos, text, colon)))
        result.append(Token('RBRACE', '}', _shifted(pos, text, k)))
        i = k + 1
    result.append(Token('FSTRING_END', text[end:],
                        _shifted(pos, text, end)))
    return result

def _spec_start(text, start, end):
    """The index of the colon that begins a field's format spec
    (plan 1.24): the first one outside a string literal between
    start and end, or end when the field has none."""
    quote = ''
    i = start
    while i < end:
        c = text[i]
        if quote != '':
            if c == quote:
                quote = ''
        elif c == '"' or c == "'":
            quote = c
        elif c == ':':
            return i
        i += 1
    return end

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
