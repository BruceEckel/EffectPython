"""Exceptions raised by the EffectPython frontend and runtime (plan 4.1)."""

class EffectError(Exception):
    """Base class for every error EffectPython reports about a program."""

    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class EffectPythonRuntimeError(EffectError):
    """A runtime failure in the program under evaluation: an undefined name,
    a type mismatch in an operator, a call with the wrong number of
    arguments."""

def _at(lineno, what):
    if lineno > 0:
        return "line %d: %s" % (lineno, what)
    return what

class UnhandledEffectError(EffectError):
    """Compile-time: a function body performs or calls into an effect its
    signature does not declare, or main() declares one (plan 2.2,
    Pass 2 and Pass 3)."""

    def __init__(self, lineno, what):
        self.lineno = lineno
        EffectError.__init__(self, _at(lineno, what))

class InvalidProgram(EffectError):
    """Compile-time: any other mistake the checker finds, such as an
    unknown effect or operation, a handle block missing a clause, a
    perform() or resume() with the wrong arguments, or a call to an
    undefined function (plan 2.2)."""

    def __init__(self, lineno, what):
        self.lineno = lineno
        EffectError.__init__(self, _at(lineno, what))

class OneShotContinuationError(EffectError):
    """Runtime: a handler clause called eff.resume() twice (plan 3.4, step 4).
    Raised by the interpreter in Milestone 3."""

class InvalidSyntax(EffectError):
    """Compile-time: the lexer or parser rejected the source. lineno and
    colno are 1-based; lineno is 0 when the error is at end of input and
    there is no position to report."""

    def __init__(self, lineno, colno, what):
        self.lineno = lineno
        self.colno = colno
        if lineno > 0:
            what = "line %d, column %d: %s" % (lineno, colno, what)
        EffectError.__init__(self, what)
