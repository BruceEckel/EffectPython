"""`epy`: the EffectPython task runner.

    epy                    list the tasks
    epy fib                run tests/programs/fib.epy
    epy path/to/file.epy   run a program of your own
    epy check fib          parse and check a program without running it
    epy test -k none       a task; the words after it are its own

Running a program or a test needs the translated binary, so those
tasks translate first when a host source file is newer than
./effectpython-c, and say so. Each command is echoed before it runs,
and the first one to fail ends the run with its exit status. A
task that takes a second or more ends with a line giving its time.

This is the one part of the repository written in Python 3. The
interpreter it drives is RPython and runs under pypy2, which `epy
setup` installs and `epy doctor` reports on.

Install the command with `uv tool install --editable .` at the
repository root, or run it in place with `uv run epy`.
"""
import difflib
import hashlib
import os
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
PROGRAMS: Final[Path] = ROOT / "tests" / "programs"
BINARY: Final[Path] = ROOT / "effectpython-c"
TARGET: Final[Path] = ROOT / "targeteffectpython.py"
LOCAL_BIN: Final[Path] = Path.home() / ".local" / "bin"
PYPY_HOME: Final[Path] = Path.home() / "pypy"
RELEASE: Final[str] = "pypy2.7-v8.0.1"
RPYTHON: Final[Path] = (
    PYPY_HOME / f"{RELEASE}-src" / "rpython" / "bin" / "rpython")
DOWNLOADS: Final[str] = "https://downloads.python.org/pypy/"
# From https://pypy.org/checksums.html, read on 2026-11-11
SHA256: Final[dict[str, str]] = {
    f"{RELEASE}-linux64.tar.gz":
        "78674cdf95eb4cb1dd5a9b68a70200387111cb29"
        "467f8a472ab7cf07a251653c",
    f"{RELEASE}-src.tar.gz":
        "1397c303c46fdb6eb28091377668bf2bf89909fd"
        "f5824dfe067f9b47da31844a",
}
PACKAGES: Final[tuple[str, ...]] = ("pytest==4.6.11", "rply==0.7.8")
APT: Final[str] = (
    "sudo apt-get install -y build-essential libffi-dev pkg-config")
CHECK: Final[str] = """\
import sys
from effectpython.checker import Checker, KINDS
from effectpython.errors import EffectError
from effectpython.parser import parse
try:
    checker = Checker(parse(open(sys.argv[1]).read()))
    checker.check()
except EffectError as e:
    print "error:", e.msg
    sys.exit(1)
print "ok"
for line in sorted(set(site // KINDS for site in checker.unknowns)):
    print "line %d: an operand of unknown type, left to the runtime" % line
"""
INTERRUPTED: Final[int] = 130

type Recipe = Callable[[Sequence[str]], None]

class StepFailed(Exception):
    def __init__(self, code: int, why: str = "") -> None:
        super().__init__(why)
        self.code = code
        self.why = why

@dataclass(frozen=True, slots=True)
class Task:
    name: str
    doc: str
    recipe: Recipe
    usage: str = ""

TASKS: Final[dict[str, Task]] = {}

def task(
    name: str, doc: str, usage: str = "",
) -> Callable[[Recipe], Recipe]:
    """Register a recipe under a name, with the line the listing
    shows."""
    def register(recipe: Recipe) -> Recipe:
        TASKS[name] = Task(name, doc, recipe, usage)
        return recipe
    return register

def environment() -> dict[str, str]:
    """This environment with ~/.local/bin first on PATH, where setup
    puts pypy2."""
    path = f"{LOCAL_BIN}{os.pathsep}{os.environ.get('PATH', '')}"
    return {**os.environ, "PATH": path}

def run(argv: Sequence[str | Path],
        extra: dict[str, str] | None = None,
        echo: bool = True) -> None:
    """Run a command from the repository root, echoing it first
    unless its output is the whole point."""
    words = [str(word) for word in argv]
    if echo:
        print("$", shlex.join(words), flush=True)
    env = environment() | (extra or {})
    try:
        code = subprocess.run(
            words, cwd=ROOT, env=env, check=False).returncode
    except FileNotFoundError:
        raise StepFailed(
            127, f"{words[0]} is not installed; try `epy doctor`"
        ) from None
    if code:
        raise StepFailed(code)

def sources() -> list[Path]:
    return [*(ROOT / "effectpython").glob("*.py"), TARGET]

def stale() -> bool:
    """Whether the binary is missing or older than a host source."""
    if not BINARY.exists():
        return True
    built = BINARY.stat().st_mtime
    return any(path.stat().st_mtime > built for path in sources())

def find_program(word: str) -> Path | None:
    """A path as given, or a sample under tests/programs by name."""
    for path in (Path(word), PROGRAMS / word, PROGRAMS / f"{word}.epy"):
        if path.is_file():
            return path.resolve()
    return None

def program(args: Sequence[str], name: str) -> Path:
    if not args:
        raise StepFailed(2, f"usage: epy {name} PROGRAM")
    path = find_program(args[0])
    if path is None:
        samples = [p.stem for p in PROGRAMS.glob("*.epy")]
        near = difflib.get_close_matches(args[0], samples, n=3)
        hint = f" Did you mean {', '.join(near)}?" if near else ""
        raise StepFailed(
            2, f"no program named {args[0]!r}.{hint} "
            "`epy programs` lists the samples.")
    return path

@task("run", "Run a program: a path, or a sample's name", "PROGRAM")
def run_program(args: Sequence[str]) -> None:
    path = program(args, "run")
    build([])
    run([BINARY, path], echo=False)

@task("check", "Parse and check a program without running it",
      "PROGRAM")
def check(args: Sequence[str]) -> None:
    path = program(args, "check")
    run(["pypy2", "-c", CHECK, path], {"PYTHONPATH": str(ROOT)},
        echo=False)

@task("programs", "List the sample programs under tests/programs",
      "[WORD]")
def programs(args: Sequence[str]) -> None:
    names = sorted(p.stem for p in PROGRAMS.glob("*.epy"))
    wanted = [n for n in names if not args or args[0] in n]
    print("\n".join(wanted))

@task("build", "Translate ./effectpython-c if it is stale (a minute)",
      "[--force]")
def build(args: Sequence[str]) -> None:
    if "--force" not in args and not stale():
        return
    print("epy: translating, since the host source is newer than "
          "the binary", flush=True)
    run(["pypy2", RPYTHON, "--batch", "--continuation",
         f"--output={BINARY.name}", TARGET.name])

@task("test", "Run the tests through the translated binary",
      "[PYTEST ARGS]")
def test(args: Sequence[str]) -> None:
    build([])
    run(["pypy2", "-m", "pytest", *args],
        {"EFFECTPYTHON_BINARY": str(BINARY)})

@task("enumerate",
      "Run the checker's soundness enumeration (four minutes)",
      "[LOW HIGH]")
def enumerate_programs(args: Sequence[str]) -> None:
    build([])
    sizes = list(args) or ["2", "3"]
    run(["pypy2", "tests/enumerate_programs.py", *sizes])

@task("verify",
      "What a commit to the host needs: build, test, enumerate")
def verify(args: Sequence[str]) -> None:
    test([])
    enumerate_programs([])

def probe(argv: Sequence[str | Path]) -> str | None:
    """The first line a command prints, or None if it cannot run."""
    try:
        done = subprocess.run(
            [str(word) for word in argv], env=environment(),
            capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    if done.returncode:
        return None
    lines = (done.stdout + done.stderr).strip().splitlines()
    return lines[0] if lines else ""

def findings() -> dict[str, str | None]:
    """Each part of the toolchain with what was found, or None."""
    modules = "import pytest, rply; print pytest.__version__, " \
              "rply.__version__"
    return {
        "pypy2": probe(["pypy2", "--version"]),
        "pytest and rply": probe(["pypy2", "-c", modules]),
        "RPython": str(RPYTHON) if RPYTHON.exists() else None,
        "gcc": probe(["gcc", "--version"]),
        "binary": (None if not BINARY.exists()
                   else "stale" if stale() else "up to date"),
    }

@task("doctor", "Report which parts of the toolchain are installed")
def doctor(args: Sequence[str]) -> None:
    found = findings()
    for part, value in found.items():
        print(f"{part:16}{value if value is not None else 'MISSING'}")
    if found["gcc"] is None:
        print(f"\ngcc needs your password:\n  {APT}")
    missing = [p for p in ("pypy2", "pytest and rply", "RPython")
               if found[p] is None]
    if missing:
        print("\n`epy setup` installs", ", ".join(missing))
    if found["binary"] != "up to date":
        print("\n`epy build` translates the binary")

def fetch(name: str) -> Path:
    """Download a release file into ~/pypy and hold it to its
    checksum."""
    path = PYPY_HOME / name
    if not path.exists():
        print("epy: downloading", DOWNLOADS + name, flush=True)
        urllib.request.urlretrieve(DOWNLOADS + name, path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SHA256[name]:
        path.unlink()
        raise StepFailed(1, f"{name} failed its checksum; removed")
    return path

def unpack(name: str) -> Path:
    """Fetch and extract a release file unless its directory is
    there."""
    directory = PYPY_HOME / name.removesuffix(".tar.gz")
    if not directory.exists():
        with tarfile.open(fetch(name)) as archive:
            archive.extractall(PYPY_HOME, filter="data")
    return directory

@task("setup",
      "Install PyPy 2.7, its source, pytest, and rply in your home")
def setup(args: Sequence[str]) -> None:
    PYPY_HOME.mkdir(parents=True, exist_ok=True)
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    pypy = unpack(f"{RELEASE}-linux64.tar.gz") / "bin" / "pypy"
    unpack(f"{RELEASE}-src.tar.gz")
    link = LOCAL_BIN / "pypy2"
    if not link.exists():
        link.symlink_to(pypy)
    if findings()["pytest and rply"] is None:
        run(["pypy2", "-m", "ensurepip"])
        run(["pypy2", "-m", "pip", "install", "-q", *PACKAGES])
    doctor([])

def listing() -> str:
    lines = ["epy PROGRAM runs a program; the tasks are:", ""]
    for entry in TASKS.values():
        head = f"{entry.name} {entry.usage}".strip()
        lines.append(f"  {head:24}{entry.doc}")
    return "\n".join(lines)

def report(goal: str, code: int, seconds: float) -> str:
    minutes, rest = divmod(round(seconds), 60)
    took = f"{minutes}m {rest}s" if minutes else f"{rest}s"
    if code:
        return (f"epy {goal}: failed with exit status {code} "
                f"after {took}")
    return f"epy {goal}: {took}"

def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("help", "-h", "--help"):
        print(listing())
        return 0
    goal, rest = args[0], args[1:]
    if goal not in TASKS:
        goal, rest = "run", args
    start = time.monotonic()
    try:
        TASKS[goal].recipe(rest)
        code = 0
    except StepFailed as e:
        if e.why:
            print("epy:", e.why, file=sys.stderr)
        code = e.code
    except KeyboardInterrupt:
        code = INTERRUPTED
    seconds = time.monotonic() - start
    if goal != "run" and seconds >= 1:
        print(report(goal, code, seconds))
    return code

if __name__ == "__main__":
    raise SystemExit(main())
