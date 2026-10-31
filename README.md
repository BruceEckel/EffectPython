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

## Handler classes

A clause written inline handles one block.
A handler you want to reuse, or one that keeps state between operations, is a class:

```python
from effectpython import Effect, Handler, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

class CountingFileIO(Handler[FileIO]):
    writes: int = 0
    def read(self, path: str) -> str:
        return "contents of " + path
    def write(self, path: str, content: str) -> int:
        self.writes = self.writes + 1
        return self.writes

def save(name: str) -> int / [FileIO]:
    config = perform(FileIO.read(name + ".json"))
    return perform(FileIO.write(name, config))

def main() -> int / []:
    fake = CountingFileIO()
    with handle(fake):
        print(save("settings"))
        print(save("users"))
    print(fake.writes)
    return 0
```

The program above is `tests/programs/counting_handler.epy`, and it prints `1`, `2`, and then `2`.
A handler class derives from `Handler[E]` and defines one method per operation of `E`,
with the operation's parameters after `self` and the operation's return type.
The suspended `perform` receives the method's return value,
so a method always resumes the body, where an inline clause may abandon it.
A method that performs effects of its own declares them in a `/ [...]` row,
and those effects resolve to the handlers outside the `with` block.

Fields are declared like dataclass fields, as `int` or `str` with an optional literal default,
and the constructor takes them positionally in declaration order.
The instance lives for the whole block, so a field keeps its value from one operation to the next,
and the code after the block can read it, as `fake.writes` does above.

`handle()` accepts a handler instance or a constructor call such as `handle(CountingFileIO())`
alongside bare effect names.
When every argument is a handler, the `with` needs no `try` around it;
a bare effect name still needs its `except` clauses.
The checker rejects a handler class missing a method for one of the effect's operations,
a method that is not an operation or whose signature differs from the operation's,
a method that performs an effect missing from its row,
a field of a type other than `int` or `str`,
a constructor call with the wrong arguments,
a `self.<name>` that names no field,
and a clause for an effect that a handler class in the same `handle()` fulfills.

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
