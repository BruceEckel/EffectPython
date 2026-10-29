# EffectPython

An RPython interpreter for a Python 3 dialect with algebraic effects.
The architecture and milestones are in `effectpython_implementation_plan.md`;
read the relevant section before changing the code it describes.

## Two dialects, never mixed

- Everything under `effectpython/`, `targeteffectpython.py`, `experiments/`, and `tests/` is RPython:
  Python 2.7 syntax under RPython's restrictions (homogeneous lists, no dynamic attributes, uniform `W_Root` returns).
  It runs under `pypy2` only.
- The `.epy` programs the interpreter reads are Python 3 syntax.
  The host parses them with its own `rply` grammar and never imports them.

## Style: the Thinking in Python skill

Bruce's book conventions live in `/mnt/c/git/ThinkingInPython/thinking-in-python-skill.md`
(`C:\git\ThinkingInPython\thinking-in-python-skill.md` from Windows).
The same file is installed as the `thinking-in-python` skill under `.claude/skills/`,
as a symlink to that path, so the Windows copy stays the source of truth.
Load it before writing or reviewing Python here, and apply it as far as each dialect allows.

Applies to the RPython host code:

- Naming: `snake_case` functions, `PascalCase` classes, a leading underscore on names only the class uses,
  no identifiers named after soft keywords, exception names without an `Error` suffix.
- Density: at most one blank line anywhere, imports grouped and sorted but contiguous, 60-column lines where practical.
- Comments: a module docstring and prose explain the design; no comment narrates the next line;
  a one-line comment ends without a period. Comments already in the code stay unless asked about.
- EAFP with a narrow `try` around the one call that can fail, catching specific exception types.
- Demos make their point once. Tests are Arrange, Act, Assert, one behavior per test,
  with near-duplicate tests collapsed into `@pytest.mark.parametrize`.
- Pattern names are used only when the structure has the pattern, italicized and capitalized in prose.

Does not apply to the RPython host code, because the dialect lacks it:
PEP 695 generics, `match`, dataclasses, `@record`, `Protocol`, `Final`, `ClassVar`,
`X | None`, `@override`, the `sentinel` builtin, f-strings, `pathlib`, `#:` output markers.
RPython also forbids `str(e)` on an exception and `repr()` on a string in translated code;
every error carries a `msg` attribute instead.

Applies to `.epy` sample programs as far as the dialect implements the construct.

## Toolchain

The only Python 2 host is PyPy 8.0.1 at `~/.local/bin/pypy2`, with pytest 4.6.11 and rply 0.7.8 importable.
The RPython source tree is `~/pypy/pypy2.7-v8.0.1-src`. No CPython 2.7 is installed.

```
# Unit tests (no RPython imports, so no PYTHONPATH)
pypy2 -m pytest

# Run a target or experiment untranslated
PYTHONPATH=~/pypy/pypy2.7-v8.0.1-src pypy2 targeteffectpython.py [n]

# Translate (about 15 seconds for a small target)
pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --batch --continuation \
    --output=effectpython-c targeteffectpython.py
```

`--batch` makes a failed translation print instead of opening pdb.
Do not pass `-O0`: it selects the refcounting GC, which cannot combine with `--continuation`.

## Translation gotchas

- Stacklets cannot run untranslated on a PyPy host, so any test that performs an effect runs through a translated binary.
- A target that uses `rstacklet` links `rvmprof.c`, which fails in gcc unless a function decorated with
  `rvmprof.vmprof_execute_code` is reachable from the entry point, guarded by a condition the backend cannot fold.
  The stub in `targeteffectpython.py` does this; copy it to any new target.
- rply's parser fetches tokens with the `next()` built-in, and RPython propagates only `StopIteration` from it,
  so a `LexingError` raised inside the lexer stream vanishes in the translated binary.
  Lex the whole file into a token list first, catching `LexingError` around direct `stream.next()` calls,
  and feed the parser an iterator over that list.

## Workflow

Commit when a unit of work is done, and push after committing.
