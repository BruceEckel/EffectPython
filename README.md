# EffectPython

An interpreter, written in RPython, for a small Python 3 dialect with algebraic effects.
A function declares the effects it may perform in its signature,
a static checker proves every effect is handled before the program runs,
and `perform` suspends the running code until a handler resumes it.
Handlers are delimited continuations built on RPython's `rstacklet`.

```python
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

class DBQuery(Effect):
    def execute(sql: str) -> str: ...

def query(sql: str) -> str / [DBQuery]:
    return perform(DBQuery.execute(sql))

def load(path: str) -> str / [FileIO, DBQuery]:
    names = perform(FileIO.read(path))
    return query("select " + names)

def main() -> int / []:
    try:
        with handle(FileIO):
            try:
                with handle(DBQuery):
                    print(load("users.txt"))
            except DBQuery.execute as eff:
                print("db:", eff.sql)
                eff.resume("rows for " + eff.sql)
    except FileIO.read as eff:
        print("file:", eff.path)
        eff.resume("names from " + eff.path)
    return 0
```

The program above is `tests/programs/nested.epy`.
The `try`/`with handle`/`except` block is valid Python 3 syntax,
but the interpreter runs it as a handler frame, not an exception handler:
`eff.resume(value)` returns control to the suspended `perform`,
and a clause that never resumes abandons the suspended code.
The checker rejects a function that performs an effect missing from its `/ [...]` row,
a `handle` block missing a clause for one of the effect's operations,
and a `main()` whose row is not empty.

## Running it

The host is PyPy 2 (`pypy2`) with the RPython source tree checked out beside it;
see `CLAUDE.md` for the paths and versions.

```
pypy2 -m pytest                      # all tests; translates once, about 40 seconds
pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --batch --continuation \
    --output=effectpython-c targeteffectpython.py
./effectpython-c tests/programs/nested.epy
```

Stacklets run only in a translated binary,
so every program that performs an effect is tested through one,
by `tests/test_runtime.py` against the `.expected` file beside each program.

## Reading further

`effectpython_implementation_plan.md` holds the language design, the checker's three passes,
how `rstacklet` is used, and the milestone log.
The source lives in `effectpython/`: `lexer.py` and `parser.py` (rply), `checker.py`,
`interpreter.py` (the evaluator and the handler runtime), and `model.py` (boxed values).
