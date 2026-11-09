# EffectPython Tutorial

EffectPython is a small Python 3 dialect with algebraic effects.
A function declares in its signature which effects it may perform,
a static checker proves every effect is handled before the program runs,
and `perform` suspends the running code until a handler resumes it.
This tutorial takes you from a program without effects to handlers that fail and recover,
one working program at a time.

Every listing here is a file in `tests/programs/`, and the output shown after it is the file's recorded output.
The test suite runs each program through the interpreter and compares,
so a listing in this tutorial cannot stop working without a test failing.

## Before you start

The interpreter is written in RPython and runs as a translated binary.
`README.md` has the setup, and `CLAUDE.md` has the exact paths.
Once you have the binary:

```
./effectpython-c tests/programs/fib.epy
```

A program needs a `main()`, and the `int` it returns is the exit code.
An error the program does not handle prints one `error:` line and exits 1.
Each program file begins with a comment that the listings here leave out,
so a line number in an error message counts from the file's first line, a few lines above the listing's.

The dialect is a proof of concept, and you will notice what it lacks sooner than what it has.
The values are `int`, `str`, and `bool`, with `True` and `False` as the literals, and a `list` of one of those three.
There is a `dict` with `str` keys, and no tuples, no string methods, no slicing, no chained comparisons, no `else` on a loop, and no `else` or bare `except:` on a `try`.
The built-ins are `print`, which takes any number of arguments and separates them with spaces, as Python does, `len`, and `str`.
Every parameter and return type is written out, and the checker reads them.
Those limits are the size of the project, not design choices, and they do not get in the way of the effects.

## 1. A program without effects

```python tests/programs/tutorial_basics.epy
def repeat(word: str, times: int) -> str:
    text = word
    while times > 1:
        text = text + " " + word
        times = times - 1
    return text

def parity(n: int) -> str:
    if n % 2 == 0:
        return "even"
    else:
        return "odd"

def small(n: int) -> bool:
    if n < 10:
        return True
    return False

def between(n: int, lo: int, hi: int) -> bool:
    return lo <= n and n < hi

def main() -> int / []:
    print(repeat("hello", 3))
    print(parity(7), parity(10))
    print(3 * 4 + 10 // 3, 7 == 7, small(30))
    print(between(5, 1, 10), not small(3) or between(3, 1, 10))
    return 0
```

```text tests/programs/tutorial_basics.expected
hello hello hello
odd even
15 True False
True True
```

The syntax is Python 3, and a Python 3 parser accepts the file.
Two things differ from ordinary Python.
The `/ []` after `main`'s return type is an *effect row*, the list of effects the function may perform;
`main()` must have an empty one, and a function with no row written has an empty row too.
And the annotations are required, not optional:
every value has a type the checker knows, so the arithmetic here is `int`, a comparison and `small` are `bool`, and `repeat` builds a `str`.
`and`, `or`, and `not` combine `bool` values as Python's do, with the same precedence and the same short circuit, and take `bool` operands alone:
`if n:` on an `int` is a checker error, `if needs a bool, not int`, where Python would test the number for zero.

## 2. An effect and a handler

An *effect* is a class deriving from `Effect` whose methods are stubs.
Each stub is an *operation*: a request the program can make without saying who answers it.

```python tests/programs/read_config.epy
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

def read_config(path: str) -> str / [FileIO]:
    return perform(FileIO.read(path))

def load_app(name: str) -> int / [FileIO]:
    config = read_config(name + ".json")
    print(config)
    return perform(FileIO.write(name, config))

def main() -> int / []:
    try:
        with handle(FileIO):
            print(load_app("settings"))
    except FileIO.read as eff:
        eff.resume("contents of " + eff.path)
    except FileIO.write as eff:
        print("writing", eff.path, eff.content)
        eff.resume(7)
    return 0
```

```text tests/programs/read_config.expected
contents of settings.json
writing settings contents of settings.json
7
```

`perform(FileIO.read(path))` suspends the running code, carrying the operation and its arguments,
and evaluates to whatever the handler sends back.
`read_config` declares `/ [FileIO]` because it performs a `FileIO` operation,
and `load_app` declares it too, because it calls `read_config`.
A row names the effects that can reach a caller, through any number of calls.

The handler is the `try` block in `main()`.
The `with handle(FileIO):` statement installs a handler for the whole block beneath it,
and each `except FileIO.read as eff:` clause answers one operation.
Inside a clause, `eff.path` is the argument the operation was performed with,
and `eff.resume(value)` sends `value` back to the suspended `perform`, which returns it.
The clause for `write` prints both arguments and resumes with `7`, which `load_app` returns and `main()` prints.

This is valid Python 3 syntax, and a Python reader sees an exception handler.
The interpreter does something else with it: the block is a handler frame, and a clause is called when the body performs, not when it fails.
Section 7 shows what the same syntax does when the clauses name exception classes.

`main()` handles `FileIO`, so its row stays empty.
Leave the row off `read_config` and the checker stops the program before it runs:

```python tests/programs/rejected_unhandled.epy
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

def read_config(path: str) -> str:
    return perform(FileIO.read(path))

def main() -> int / []:
    return 0
```

```text tests/programs/rejected_unhandled.expected
error: line 9: function 'read_config' performs FileIO (line 10) without declaring it in its effect row
```

The checker also requires a clause for every operation of a handled effect.
A `handle(FileIO)` whose clauses cover `read` alone reads
`handle(FileIO) is missing a clause for FileIO.write`, from `tests/programs/rejected_missing_clause.epy`.

## 3. One clause, many performs

A clause runs once per `perform`, and the body carries on from each one.

```python tests/programs/sequential.epy
from effectpython import Effect, perform, handle

class Counter(Effect):
    def tick(label: str) -> int: ...

def main() -> int / []:
    try:
        with handle(Counter):
            a = perform(Counter.tick("a"))
            b = perform(Counter.tick("b"))
            c = perform(Counter.tick("c"))
            print(a + b + c)
    except Counter.tick as eff:
        print("tick", eff.label)
        eff.resume(10)
    return 0
```

```text tests/programs/sequential.expected
tick a
tick b
tick c
30
```

Each `perform` suspends the body where it stands, with its local variables intact;
the clause runs, and `eff.resume(10)` continues the body at that `perform`.
After three rounds the body adds the three results.
The body's stack is kept across the suspension, so the pattern scales:
`tests/programs/many_performs.epy` runs ten thousand performs in a loop.

## 4. Nested handlers

A `perform` goes to the nearest enclosing handler for its effect.

```python tests/programs/nested.epy
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

```text tests/programs/nested.expected
file: users.txt
db: select names from users.txt
rows for select names from users.txt
```

`load` performs two effects, so its row names both.
The inner block handles `DBQuery` and the outer block handles `FileIO`,
and each `perform` finds its own handler however deep the call that performs it.
A clause runs outside the block it handles, so anything a clause performs goes to the handlers outside it;
the `DBQuery` clause here could perform `FileIO.read`, and the outer clause would answer.

## 5. A clause that does not resume

A clause may finish without calling `eff.resume()`.
The suspended body is then abandoned, and the program continues after the `try` block.

```python tests/programs/abort.epy
from effectpython import Effect, perform, handle

class Abort(Effect):
    def stop(reason: str) -> int: ...

def main() -> int / []:
    try:
        with handle(Abort):
            print("before")
            perform(Abort.stop("done early"))
            print("never printed")
    except Abort.stop as eff:
        print("aborted:", eff.reason)
    print("after")
    return 0
```

```text tests/programs/abort.expected
before
aborted: done early
after
```

The `print` after the `perform` does not run.
This is how an effect expresses an early exit: the code that performs `Abort.stop` does not decide what comes next; the handler does.
A `return` inside a clause leaves the function the same way:

```python tests/programs/return_in_clause.epy
from effectpython import Effect, perform, handle

class Ask(Effect):
    def value(label: str) -> int: ...

def main() -> int / []:
    try:
        with handle(Ask):
            print(perform(Ask.value("n")))
    except Ask.value as eff:
        print("leaving from the clause")
        return 3
    print("not reached")
    return 0
```

```text tests/programs/return_in_clause.expected
leaving from the clause
```

The exit code is 3, from the clause's `return`.
A `return` inside the body behaves as you would expect: the function returns its value once the body gets there.

```python tests/programs/return_in_body.epy
from effectpython import Effect, perform, handle

class Ask(Effect):
    def value(label: str) -> int: ...

def main() -> int / []:
    try:
        with handle(Ask):
            n = perform(Ask.value("n"))
            print("got", n)
            return n + 1
    except Ask.value as eff:
        eff.resume(41)
        print("after resume")
    print("not reached")
    return 0
```

```text tests/programs/return_in_body.expected
got 41
```

Notice that `print("after resume")` did not run.
`eff.resume(41)` runs the rest of the body inside that call, and the body's `return` ends the function from there,
so the statements after a `resume()` run when the body completes without returning.

A suspended body can be resumed once.
A clause that calls `eff.resume()` twice gets a runtime error on the second call,
`Cannot resume a suspended body more than once`, from `tests/programs/double_resume.epy`.

### `finally` in an abandoned body

An abandoned body is not dropped where it stopped.
It is unwound, so a `try`/`finally` inside it runs its `finally` suite, as it would in Python when a generator is closed at a `yield`.

```python tests/programs/finally_in_body.epy
from effectpython import Effect, perform, handle

class Abort(Effect):
    def stop(reason: str) -> int: ...

def work() -> int / [Abort]:
    print("open")
    try:
        perform(Abort.stop("done early"))
        print("never printed")
        return 1
    finally:
        print("close")

def main() -> int / []:
    try:
        with handle(Abort):
            print(work())
    except Abort.stop as eff:
        print("aborted:", eff.reason)
    print("after")
    return 0
```

```text tests/programs/finally_in_body.expected
open
aborted: done early
close
after
```

The order of the output is the order of events.
The clause runs first and prints `aborted: done early`.
It ends without resuming, so the body is unwound from its `perform`: `print("never printed")` is skipped, the `finally` prints `close`, and `work()` ends there.
`print(work())` has nothing to print, and the program continues with `after`.
A `return` or an exception that leaves a clause unwinds the body the same way before the function returns or the exception travels on;
`tests/programs/finally_on_return_in_clause.epy` and `tests/programs/finally_on_raise_in_clause.epy` show both.

A `finally` suite is ordinary code, so it may perform an effect while the body is unwound,
and the handler for that effect answers it as usual (`tests/programs/finally_performs.epy`).
If it raises an exception or returns, that outcome replaces the unwinding, as Python's rule for a `finally` goes:
in `tests/programs/finally_raises.epy` the body's `finally` raises `Dirty`, which surfaces at the `with handle` statement and is caught by a `try` around it.
A `finally` may also follow the effect clauses of a handler statement.
It belongs to the function that installs the handler and runs when the block completes or a clause abandons the body (`tests/programs/handle_with_finally.epy`).

## 6. Handler classes

A clause handles one block.
A handler you want to reuse, or one that keeps state, is a class deriving from `Handler[E]`,
with one method per operation of `E`.

```python tests/programs/handler_class.epy
from effectpython import Effect, Handler, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

class Log(Effect):
    def note(text: str) -> int: ...

class FakeFileIO(Handler[FileIO]):
    files: dict[str, str] = {}
    def read(self, path: str) -> str:
        if path in self.files:
            return self.files[path]
        else:
            return "missing: " + path
    def write(self, path: str, content: str) -> int / [Log]:
        perform(Log.note("writing " + path))
        return 7

def read_config(path: str) -> str / [FileIO]:
    return perform(FileIO.read(path))

def load_app(name: str) -> int / [FileIO]:
    config = read_config(name + ".json")
    print(config)
    return perform(FileIO.write(name, config))

def main() -> int / []:
    try:
        with handle(Log):
            fake = FakeFileIO({"settings.json": "debug = true"})
            with handle(fake):
                print(load_app("settings"))
                print(load_app("other"))
    except Log.note as eff:
        print("log:", eff.text)
        eff.resume(0)
    return 0
```

```text tests/programs/handler_class.expected
debug = true
log: writing settings
7
missing: other.json
log: writing other
7
```

A method takes the operation's parameters after `self` and returns the operation's return type;
returning is how a method resumes the body.
`read` answers from `files`, a `dict[str, str]` field the constructor fills, which is how a fake handler stands in for a small filesystem;
`in` asks whether a key is present, and section 9 has the rest of the dict.
`with handle(FakeFileIO()):` installs an instance for the block, and no `try` is needed,
since the class supplies every clause.
A method that performs effects of its own declares them in a row, as `write` declares `Log`,
and those effects go to the handlers outside the block, as a clause's performs do.
A handler class missing a method is a static error:
`handler class 'Fake' has no method for FileIO.write`, from `tests/programs/rejected_handler_method.epy`.

Fields give a handler state that lasts for the whole block:

```python tests/programs/counting_handler.epy
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

```text tests/programs/counting_handler.expected
1
2
2
```

A field is declared like a dataclass field, `int` or `str` with an optional default, or a list or dict as section 9 shows,
and the constructor takes the fields positionally.
The instance outlives the block, so `main()` reads `fake.writes` after it.
A `handle()` may mix handler instances with bare effect names, which still need their clauses:
`tests/programs/handler_with_clause.epy` writes `with handle(FakeFileIO(), DBQuery):` inside a `try` with a clause for `DBQuery.execute`.

## 7. Exceptions

A function fails on purpose with `raise`, and the failure is part of its signature.

```python tests/programs/raise_caught.epy
class NotFound(Exception): ...

class Denied(Exception):
    pass

def find(path: str) -> str / [NotFound]:
    if path == "":
        raise NotFound()
    if path == "settings.json":
        raise NotFound(path)
    return "contents of " + path

def main() -> int / []:
    try:
        print(find("settings.json"))
    except Denied as e:
        print("denied:", e)
    except NotFound as e:
        print("missing:", e)
    try:
        print(find("notes.txt"))
        find("")
    except NotFound as e:
        print("empty:", e, "end")
    print("after")
    return 0
```

```text tests/programs/raise_caught.expected
missing: settings.json
contents of notes.txt
empty:  end
after
```

An exception class derives from `Exception` and has no body beyond `...` or `pass`.
Its constructor takes an optional `str` message, which `print(e)` prints;
`NotFound()` without a message prints an empty string, which is the double space in the third line.
A `try` whose clauses name exception classes is an ordinary Python `try`/`except`:
the first clause whose class matches runs, and `except Exception` matches every class.
A `finally` suite may follow the clauses, or stand alone after the `try` suite, and it runs however the `try` ends
(`tests/programs/try_finally.epy` shows the three cases without effects).

The exception class belongs in the row beside the effects.
`find` declares `/ [NotFound]` because it raises one,
and `main()` keeps its empty row because it catches the failure.
A function that raises a class without declaring it, or calls a function that does, is rejected,
so an exception nobody catches is a static error at `main()`:

```python tests/programs/rejected_uncaught.epy
class NotFound(Exception): ...

def find(path: str) -> str / [NotFound]:
    raise NotFound(path)

def main() -> int / []:
    print(find("settings.json"))
    return 0
```

```text tests/programs/rejected_uncaught.expected
error: line 10: function 'main' raises NotFound (line 11) without declaring it in its effect row
```

A clause may raise what it caught again with `raise e`, and the function then declares that class;
`tests/programs/raise_again.epy` does this.
A clause written `except Exception as e` cannot, since `e` has no class for the row.

### Exceptions and handlers

Where an exception is raised decides what it does to a handled body.

```python tests/programs/raise_in_body.epy
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

```text tests/programs/raise_in_body.expected
missing: settings.json
after
```

Raised in the body, the exception travels up through the body's calls, out of the `with handle` statement, and into the `try` around it.
The handler frame is gone by then, and `print("after")` runs.
Raised in a handler, the exception abandons the body instead:

```python tests/programs/raise_in_method.epy
from effectpython import Effect, Handler, perform, handle

class FileIO(Effect):
    def read(path: str) -> str: ...

class NotFound(Exception): ...

class MissingFiles(Handler[FileIO]):
    def read(self, path: str) -> str / [NotFound]:
        raise NotFound(path)

def load(path: str) -> str / [FileIO]:
    try:
        return perform(FileIO.read(path))
    except NotFound as e:
        print("caught in the body:", e)
    return ""

def main() -> int / []:
    try:
        with handle(MissingFiles()):
            print(perform(FileIO.read("settings.json")))
            print("never printed")
    except NotFound as e:
        print("missing:", e)
    try:
        with handle(MissingFiles()):
            print(load("other.json"))
            print("never printed")
    except NotFound as e:
        print("outside the body:", e)
    return 0
```

```text tests/programs/raise_in_method.expected
missing: settings.json
outside the body: other.json
```

The method runs outside the body, so its exception leaves the `with` statement with the body still suspended,
and the body's next statement does not run; the body is unwound first, as in section 5, so a `finally` inside it still runs.
The method's row carries `NotFound` to the function that installs the handler, which must catch or declare it.
The second block shows the consequence for the body:
`load` has a `try` around its `perform`, and that `try` does not catch what the handler raises,
because the exception does not enter the body.
This is how a reusable handler reports a failure the performer cannot recover from.
The next section is for failures the performer can.

## 8. Throwing into the body

`eff.throw(exc)` is the second way to resume a body:
the suspended `perform` raises `exc` where `eff.resume(value)` would make it return `value`.
Python has the same pair for generators, `gen.send()` and `gen.throw()`.

```python tests/programs/throw_caught.epy
from effectpython import Effect, perform, handle

class FileIO(Effect):
    def read(path: str) -> str / [NotFound]: ...

class NotFound(Exception): ...

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

```text tests/programs/throw_caught.expected
missing: settings.json
defaults
```

The operation's stub now has a row, `/ [NotFound]`: the exception classes a handler may throw into the body.
A `perform(FileIO.read(path))` therefore adds `NotFound` to the performer's effects as well as `FileIO`,
and `load` catches it at the `perform` or declares it.
The contract is the operation's, not the handler's:
`load` accounts for `NotFound` whichever handler is installed, as a Java caller accounts for a `throws` clause whichever class implements the interface.
A clause may throw a class the operation declares and no other;
`tests/programs/rejected_undeclared_throw.epy` throws `Denied` where the operation declares `NotFound`, and the checker reports
`FileIO.read does not declare Denied, so eff.throw() cannot deliver it`.

A handler class gets the same ability through `raise`:

```python tests/programs/throw_in_method.epy
from effectpython import Effect, Handler, perform, handle

class FileIO(Effect):
    def read(path: str) -> str / [NotFound]: ...

class NotFound(Exception): ...

class MissingFiles(Handler[FileIO]):
    failures: int = 0
    def read(self, path: str) -> str / [NotFound]:
        self.failures = self.failures + 1
        raise NotFound(path)

def load(path: str) -> str / [FileIO]:
    try:
        return perform(FileIO.read(path))
    except NotFound as e:
        print("missing:", e)
        return "defaults"

def main() -> int / []:
    missing = MissingFiles()
    with handle(missing):
        print(load("settings.json"))
        print(load("users.json"))
    print(missing.failures)
    return 0
```

```text tests/programs/throw_in_method.expected
missing: settings.json
defaults
missing: users.json
defaults
2
```

A method that raises a class its operation declares throws it into the body,
so `load` catches it, returns a default, and the body performs again.
A method that raises any other class abandons the body, as in section 7.
A method is then an ordinary implementation of the operation's signature:
`return` resumes the body with a value, and `raise` of a declared class resumes it with an exception.

The two forms side by side:

| In a clause | The body | The exception appears |
| :--- | :--- | :--- |
| `raise NotFound(p)` | is abandoned | at the `with handle` statement |
| `eff.throw(NotFound(p))` | is resumed | at the suspended `perform` |

A throw counts as the binding's one resumption, so a `resume()` or a second `throw()` after it is the one-shot error of section 5.
If the body does not catch the thrown exception, it ends the body and surfaces at the `with handle` statement, as a `raise` in the body does;
`tests/programs/throw_through_body.epy` shows that path.

## 9. Lists and the `for` loop

A list holds values of one type, written `list[int]`, `list[str]`, or `list[bool]` wherever a type is written,
and a `for` walks a list or a `range()`.
The handler below collects what it is told into a list field,
and the function it serves builds a list to return:

```python tests/programs/collector.epy
from effectpython import Effect, Handler, perform, handle

class Log(Effect):
    def note(text: str) -> int: ...

class Collector(Handler[Log]):
    entries: list[str] = []
    def note(self, text: str) -> int:
        self.entries.append(text)
        return len(self.entries)

def squares(n: int) -> list[int] / [Log]:
    result = []
    for i in range(n):
        result.append(i * i)
        perform(Log.note("squared " + str(i)))
    return result

def main() -> int / []:
    collector = Collector()
    with handle(collector):
        xs = squares(4)
    print(xs, len(xs), xs[0], xs[-1])
    for entry in collector.entries:
        print(entry)
    other = Collector()
    print(len(other.entries), len(collector.entries))
    return 0
```

```text tests/programs/collector.expected
[0, 1, 4, 9] 4 0 9
squared 0
squared 1
squared 2
squared 3
0 4
```

The list operations are the literal `[1, 2]` or `[]`, `len(xs)`, `xs[i]` with a negative index counting from the end, `xs[i] = v`, `xs.append(v)`, and `==` and `!=` element by element.
`print(xs)` shows the list as Python does, so a list of strings prints as `['a', 'b']`.
Lists are shared by reference, as Python's are:
`collector.entries` is the same list `note` appended to, and a function that appends to a parameter appends to the caller's list.
A list field's default is `[]`, and each instance gets a list of its own, which is why `other.entries` is empty.
`result = []` starts a list of no type yet; the first `append` settles it, and the checker holds the rest of the function to that type.

`for <name> in <list>:` binds the name to each element in turn, by index against the list's current length,
so an `append` inside the body lengthens the walk, as in Python,
and the name keeps the last element after the loop.
`for i in range(n):` and `range(start, stop)` count integers; `range()` is allowed there and nowhere else, so the checker rejects `xs = range(3)`.
`str(i)` turns an `int` or a `bool` into what `print` would show for it, which is how `squares` labels its log entries.
`break` and `continue` work in both loops as they do in Python, and the checker rejects either outside a loop;
`tests/programs/loop_exits.epy` runs through the cases.

A `perform` inside a loop suspends the loop where it is, and a clause that abandons the body leaves the loop as an exception would,
running a `finally` inside the suite once, for the pass in progress, and then any `finally` around the loop;
`tests/programs/perform_in_for.epy` shows both.

A `dict` maps `str` keys to values of one type, written `dict[str, int]`, `dict[str, str]`, or `dict[str, bool]`:

```python tests/programs/lookup.epy
from effectpython import Effect, Handler, perform, handle

class Count(Effect):
    def seen(word: str) -> int: ...

class Lookup(Effect):
    def get(key: str) -> int: ...

class Tally(Handler[Count]):
    counts: dict[str, int] = {}
    def seen(self, word: str) -> int:
        if word in self.counts:
            self.counts[word] = self.counts[word] + 1
        else:
            self.counts[word] = 1
        return self.counts[word]

def total(d: dict[str, int]) -> int:
    n = 0
    for k in d:
        n = n + d[k]
    return n

def main() -> int / []:
    squares = {}
    for i in range(4):
        squares[str(i)] = i * i
    print(squares, len(squares), total(squares))
    print("2" in squares, "9" in squares, "9" not in squares)
    tally = Tally()
    with handle(tally):
        for word in ["a", "b", "a", "c", "a"]:
            perform(Count.seen(word))
    print(tally.counts, tally.counts["a"])
    table = {"x": 1}
    try:
        with handle(Lookup):
            print(perform(Lookup.get("x")), "y" in table)
            print(perform(Lookup.get("y")), table)
    except Lookup.get as eff:
        if eff.key not in table:
            table[eff.key] = len(table) + 1
        eff.resume(table[eff.key])
    return 0
```

```text tests/programs/lookup.expected
{'0': 0, '1': 1, '2': 4, '3': 9} 4 14
True False True
{'a': 3, 'b': 1, 'c': 1} 3
1 False
2 {'x': 1, 'y': 2}
```

`{}` starts a dict of no value type yet, and the first store `d[k] = v` settles it, as the first `append` settles a `[]`.
`d[k]` reads, `d[k] = v` stores, `k in d` and `k not in d` test for a key, `len(d)` counts, and `for k in d` walks the keys in the order they were stored;
`in` also tests a list for an element.
A key the dict lacks is a runtime error, `key 'b' not found`, so a program tests with `in` first,
and a store that adds a key while a `for` walks the dict is the error Python raises for the same program, `dict changed size during iteration`.
A dict is shared by reference, as a list is: the clause above stores into `table` while the body is suspended, and the body's next read sees the key.
A dict field's default is `{}`, fresh for each instance.
A `break` in a handled body ends the loop around the `handle` statement, and a `break` in a clause abandons the suspended body before it ends the loop,
which `tests/programs/break_in_handled_body.epy` shows.

## 10. What the checker catches

Everything in this list is rejected before the program runs, with a line number:

- a function that performs an effect, raises an exception class, or calls a function that does, without the name in its row;
- a `main()` with parameters or a non-empty row;
- a `handle()` block missing a clause for an operation, or with a clause for an effect it does not handle;
- a handler class missing a method, with a method that is not an operation, or with a method whose signature differs from the operation's;
- a `perform()`, `resume()`, `throw()`, call, or constructor with the wrong number or types of arguments, as far as the checker can type them;
- `eff.<name>` that is not a parameter of the operation;
- a `raise` or `eff.throw()` of a value that is not a declared exception class, and a throw of a class the operation does not declare;
- a read of a name nothing has bound earlier in the function, and a read of an `except` clause's `as` name after the clause, which Python 3 leaves unbound;
- a list literal whose elements differ in type, an index or `append` on a value that is not a list, an `append` or an indexed assignment of the wrong element type, a `for` over a value that is neither a list nor `range()`, and `range()` anywhere else;
- a `return` whose value is not the declared return type, and a function that can reach its end without returning one;
- `Exception` in a row, since a row names the classes that can reach a caller.

A name that an `if`, a loop, a `try`, or a handled body can leave with two types has no type the checker can hold it to.
Such a value cannot be passed to a parameter, returned, stored in a field, or appended to a typed list
(`argument 1 of f() must be int, but 'x' has no known type`), since the receiver would then trust a type nobody checked;
an operator on it passes the checker and meets the runtime's check instead.
What remains for runtime is what the checker does not settle:
integer division or modulo by zero, a list index past either end, an operator whose operand types the checker could not both see, a name assigned in one branch of an `if` or in a loop that ran zero times and read after it, resuming twice, and a recursion that outgrows the stack (`maximum recursion depth exceeded`, from `tests/programs/deep_recursion.epy`).
Under `tests/programs/`, `runtime_*.epy` reaches each of these, and `unreachable_*.epy` shows the checker stopping each error it makes unreachable.
Those stop the program with an `error:` line and exit code 1, and no `try` catches them:

```python tests/programs/body_error.epy
from effectpython import Effect, perform, handle

class Log(Effect):
    def note(text: str) -> int: ...

def risky(n: int) -> int / [Log]:
    perform(Log.note("dividing"))
    return 100 // n

def main() -> int / []:
    try:
        with handle(Log):
            print(risky(0))
    except Log.note as eff:
        print("log:", eff.text)
        eff.resume(0)
    return 0
```

```text tests/programs/body_error.expected
log: dividing
error: integer division by zero
```

A runtime error reports a program the checker could not reject, not a failure the program planned for,
which is why it stays outside the exception system.

## 11. Reading further

`README.md` is the short version of this tutorial.
`effectpython_implementation_plan.md` has the language design (Phase 1), the checker's three passes (2.2),
how the interpreter suspends a body with RPython's `rstacklet` (3.2 to 3.4), and the milestone log.
`tests/programs/` holds every program in this tutorial and the rest of the acceptance programs,
each with its `.expected` output beside it.
