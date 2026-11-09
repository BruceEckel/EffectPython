"""Milestone 3 harness: every tests/programs/*.epy through the binary.

Stacklets cannot run untranslated on the PyPy host, so this module
runs each program through the binary that conftest.py's fixture
translates once per session (or names through EFFECTPYTHON_BINARY).
The expected output sits beside each program in <name>.expected: its
first line is "exit <code>", and the rest is the program's stdout.

Run with:  pypy2 -m pytest tests/test_runtime.py
Translation takes about 40 seconds, so the other test modules stay
separate for quick runs.

A program written ahead of its milestone is a strict xfail in NOT_YET
until the runtime runs it.
"""
import glob
import os
import subprocess
import pytest
from support import PROGRAMS

NOT_YET = {}

def read_expected(path):
    with open(path) as f:
        header = f.readline()
        stdout = f.read()
    return int(header.split()[1]), stdout

def program_cases():
    for path in sorted(glob.glob(os.path.join(PROGRAMS, '*.epy'))):
        name = os.path.basename(path)
        marks = []
        if name in NOT_YET:
            marks.append(pytest.mark.xfail(reason=NOT_YET[name],
                                           strict=True))
        yield pytest.param(path, id=name, marks=marks)

@pytest.mark.parametrize('program', program_cases())
def test_program(binary, program):
    exit_code, stdout = read_expected(program[:-4] + '.expected')
    proc = subprocess.Popen([binary, program], stdout=subprocess.PIPE)
    actual = proc.communicate()[0]
    assert (proc.returncode, actual) == (exit_code, stdout)
