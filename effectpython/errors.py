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


class UnhandledEffectError(EffectError):
    """Compile-time: a function body performs an effect its signature does
    not declare (plan 2.2, Pass 2). Raised by the checker in Milestone 2."""


class OneShotContinuationError(EffectError):
    """Runtime: a handler clause called eff.resume() twice (plan 3.4, step 4).
    Raised by the interpreter in Milestone 3."""
