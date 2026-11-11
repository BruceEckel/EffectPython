# EffectPython

An interpreter, written in RPython, for a small Python 3 dialect with algebraic effects.
A function declares the effects it may perform in its signature,
a static checker proves every effect is handled before the program runs,
and `perform` suspends the running code until a handler resumes it.
Handlers are delimited continuations built on RPython's `rstacklet`.

This file is the short version.
[TUTORIAL.md](TUTORIAL.md) walks through the dialect in eleven sections with a working program for each step,
from a first effect and handler through nested handlers, handler classes, exceptions, `eff.throw()`, `finally`, lists and dicts with the `for` loop, f-strings, and augmented assignment;
every listing in it is a file under `tests/programs/` with its recorded output beside it, and a test holds the two to each other.

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
and a clause that does not resume abandons the suspended code,
which is unwound so that a `finally` inside it runs.
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
so a method that returns resumes the body.
A method abandons the body by raising an exception, as the next section describes.
A method that performs effects of its own declares them in a `/ [...]` row,
and those effects resolve to the handlers outside the `with` block.

Fields are declared like dataclass fields, as `int` or `str` with an optional literal default, as a `list[int]`, `list[str]`, or `list[bool]` defaulting to `[]`, or as a `dict[str, T]` defaulting to `{}`,
and the constructor takes them positionally in declaration order.
The instance lives for the whole block, so a field keeps its value from one operation to the next,
and the code after the block can read it, as `fake.writes` does above.
A handler that collects into a list field is `tests/programs/collector.epy`, which the tutorial's section 9 walks through along with the list operations and the `for` loop over a list or a `range()`.

`handle()` accepts a handler instance or a constructor call such as `handle(CountingFileIO())`
alongside bare effect names.
When every argument is a handler, the `with` needs no `try` around it;
a bare effect name still needs its `except` clauses.
The checker rejects a handler class missing a method for one of the effect's operations,
a method that is not an operation or whose signature differs from the operation's,
a method that performs an effect missing from its row,
a field of a type other than `int`, `str`, or a list,
a constructor call with the wrong arguments,
a `self.<name>` that names no field,
and a clause for an effect that a handler class in the same `handle()` fulfills.

## Exceptions

A function fails on purpose with `raise`, and the failure is part of its signature:

```python
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

class NotFound(Exception): ...

def read_config(path: str) -> str / [FileIO, NotFound]:
    config = perform(FileIO.read(path))
    if config == "":
        raise NotFound(path)
    return config

def main() -> int / []:
    try:
        try:
            with handle(FileIO):
                print(read_config("settings.json"))
        except FileIO.read as eff:
            eff.resume("")
    except NotFound as e:
        print("missing:", e)
    print("after")
    return 0
```

The program above is `tests/programs/raise_in_body.epy`, and it prints `missing: settings.json` and then `after`.
An exception class derives from `Exception` and takes an optional `str` message, which `print(e)` prints.
The class belongs in the `/ [...]` row beside the effects:
`read_config` declares `NotFound` because it raises one,
and `main()` keeps its empty row because it catches the failure.
A `try` whose clauses name a class is a Python `try`/`except`,
and `except Exception` catches every class.
A `finally` suite may follow the clauses or stand alone after the `try` suite;
it runs however the `try` ends, including when a handler abandons the body around it.
A clause that names a class raises what it caught again with `raise e`, and the function then declares that class;
a clause written `except Exception as e` cannot, since `e` has no class for the row.
The checker rejects a function that raises a class missing from its row, or calls a function that does,
so an exception nobody catches is a static error at `main()`.

Where the exception is raised decides what it does to a handled body.
Raised in the body, it surfaces at the `handle` statement, and a `try` around that statement catches it, as `main()` does here.
Raised in a clause or a handler method, it abandons the suspended body, which is unwound before the exception travels on;
a handler class reports a failure this way, and the method's row carries the class to the function that installs the handler.
A `try` inside the body catches an exception the body raises, including one raised after a `perform` resumes.
It does not catch an exception a handler raises, since the handler runs outside the body.

A handler that leaves the recovery to the performer throws the exception instead:

```python
class FileIO(Effect):
    def read(path: str) -> str / [NotFound]: ...

def load(path: str) -> str / [FileIO]:
    try:
        return perform(FileIO.read(path))
    except NotFound as e:
        print("missing:", e)
        return "defaults"

def main() -> int / []:
    try:
        with handle(FileIO):
            print(load("settings.json"))
    except FileIO.read as eff:
        eff.throw(NotFound(eff.path))
    return 0
```

This is `tests/programs/throw_caught.epy` without its import and its `NotFound` class, and it prints `missing: settings.json` and then `defaults`.
`eff.throw(exc)` resumes the body with the suspended `perform` raising `exc` where `eff.resume(value)` makes it return `value`,
as `gen.throw()` and `gen.send()` do for a Python generator.
The operation's row names the classes a handler may throw, so `perform(FileIO.read(path))` adds `NotFound` to the performer's effects,
and `load` catches it or declares it.
A handler class method raises a class its operation declares to the same effect;
any other exception a method raises abandons the body as before.

## Installing the toolchain

The host is PyPy 2.7 v8.0.1 with its own source tree, which holds RPython, plus pytest 4.6.11, rply 0.7.8, and a C compiler for the translation.
These steps were run on Ubuntu 26.04 under WSL2 on 2026-11-11 and put everything where `CLAUDE.md` and the commands below expect it.

```
sudo apt-get install -y build-essential libffi-dev pkg-config

mkdir -p ~/pypy ~/.local/bin
cd ~/pypy
curl -LO https://downloads.python.org/pypy/pypy2.7-v8.0.1-linux64.tar.gz
curl -LO https://downloads.python.org/pypy/pypy2.7-v8.0.1-src.tar.gz
sha256sum pypy2.7-v8.0.1-*.tar.gz    # compare with https://pypy.org/checksums.html
tar xzf pypy2.7-v8.0.1-linux64.tar.gz
tar xzf pypy2.7-v8.0.1-src.tar.gz
ln -s ~/pypy/pypy2.7-v8.0.1-linux64/bin/pypy ~/.local/bin/pypy2

pypy2 -m ensurepip
pypy2 -m pip install pytest==4.6.11 rply==0.7.8
```

`~/.local/bin` must be on `PATH`.
`build-essential` supplies the `gcc` and `make` that the translation calls; `libffi-dev` and `pkg-config` were installed with it, and whether the translation needs them was not tested.
The release ships as `.tar.gz`: the `.tar.bz2` names of earlier PyPy releases give a 404.
No CPython 2.7 is needed, and PyPy's pip warns that Python 2 is past its end of life, which is expected.

## Running it

The host is PyPy 2 (`pypy2`) with the RPython source tree beside it, as installed above;
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

[TUTORIAL.md](TUTORIAL.md) is the long version, described at the top of this file.
`effectpython_implementation_plan.md` holds the language design, the checker's three passes,
how `rstacklet` is used, and the milestone log.
The source lives in `effectpython/`: `lexer.py` and `parser.py` (rply), `checker.py`,
`interpreter.py` (the evaluator and the handler runtime), and `model.py` (boxed values).
