"""Handled-body programs for the checker's soundness, generated from a
small alphabet and run through the checker and then the binary.

A typed slot refuses a value of unknown type, so a program the
checker accepts had every take_int(x) and take_list(xs) at a known
type, and take_int adding 1 turns a wrong known type into a runtime
error (plan 2.2, retyping at the performs). triples() yields every
ordering of an assignment, a perform point, and a typed read with one
Log clause, which test_enumeration.py runs with the suite; bodies(n)
yields every body of n statements from the wider alphabet with a Log
and an Ask clause, which this module runs as a script:

    pypy2 tests/enumerate_programs.py 2 4

The lengths are inclusive; 2 to 4 is 130,816 programs and took eight
minutes on 2026-11-09, with none failing. The binary is
./effectpython-c, which must be translated from the source being
checked.
"""
import itertools
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from effectpython.checker import check
from effectpython.errors import InvalidProgram, UnhandledEffectError
from effectpython.parser import parse

PRELUDE = '''from effectpython import Effect, perform, handle

class Log(Effect):
    def note(text: str) -> int: ...

class Ask(Effect):
    def get() -> int: ...

def take_int(n: int) -> int:
    return n + 1

def take_list(xs: list[int]) -> int:
    if len(xs) > 0:
        return xs[0] + 1
    return 0

def f() -> int / [Log]:
    return perform(Log.note("f"))

def main() -> int / []:
    x = 0
    xs = []
    try:
        with handle(Log, Ask):
'''
ASSIGNS = ['x = 1', 'x = "s"', 'xs.append(1)']
POINTS = ['perform(Log.note("a"))', 'f()']
READS = ['take_int(x)', 'take_list(xs)']
BODY = ASSIGNS + POINTS + READS + ['perform(Ask.get())']
CLAUSE_ASSIGNS = [None, 'x = "s"', 'x = 1', 'xs = ["s"]']
TYPE_ERRORS = ['unsupported operand', 'is not a list']

def clause(name, op, assign, resume_first):
    lines = ['    except %s as %s:' % (op, name)]
    body = []
    if assign is not None:
        body.append('        ' + assign)
    resume = '        %s.resume(0)' % name
    if resume_first:
        body.insert(0, resume)
    else:
        body.append(resume)
    return '\n'.join(lines + body)

def log_clauses():
    for assign in CLAUSE_ASSIGNS:
        yield clause('eff', 'Log.note', assign, False)
        if assign is not None:
            yield clause('eff', 'Log.note', assign, True)

def program(stmts, clauses):
    body = '\n'.join('            ' + s for s in stmts)
    return PRELUDE + body + '\n' + '\n'.join(clauses) + '\n    return 0\n'

def triples():
    ask = clause('e', 'Ask.get', None, False)
    for triple in itertools.product(ASSIGNS, POINTS, READS):
        for stmts in itertools.permutations(triple):
            for log in log_clauses():
                yield program(stmts, [log, ask])

def bodies(n):
    for stmts in itertools.product(BODY, repeat=n):
        for log in log_clauses():
            for assign in CLAUSE_ASSIGNS:
                ask = clause('e', 'Ask.get', assign, False)
                yield program(stmts, [log, ask])

def accepted(text):
    try:
        check(parse(text))
    except (InvalidProgram, UnhandledEffectError):
        return False
    return True

def run(binary, texts, directory):
    """The accepted programs and, among them, the ones the binary
    rejects with a type error, each with its output."""
    passed = []
    failures = []
    for i, text in enumerate(texts):
        if not accepted(text):
            continue
        path = os.path.join(directory, 'p%d.epy' % i)
        with open(path, 'w') as f:
            f.write(text)
        proc = subprocess.Popen([binary, path], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        output = proc.communicate()[0]
        passed.append(text)
        if proc.returncode != 0 and any(
                words in output for words in TYPE_ERRORS):
            failures.append(text + output)
    return passed, failures

def main(argv):
    low, high = int(argv[1]), int(argv[2])
    texts = itertools.chain(*[bodies(n) for n in range(low, high + 1)])
    directory = tempfile.mkdtemp()
    passed, failures = run('./effectpython-c', texts, directory)
    print 'accepted %d, type errors %d' % (len(passed), len(failures))
    for failure in failures:
        print failure
    return len(failures)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
