"""Milestone 3 harness: every tests/programs/*.epy through the binary.

Stacklets cannot run untranslated on the PyPy host, so this module
translates targeteffectpython.py once per session into a scratch
directory and runs each program through the result. The expected
output sits beside each program in <name>.expected: its first line
is "exit <code>", and the rest is the program's stdout.

Run with:  pypy2 -m pytest tests/test_runtime.py
Translation takes about a minute, so the other test modules stay
separate for quick runs. Setting EFFECTPYTHON_BINARY to the path of a
binary translated earlier skips the translation and runs the
programs through that binary instead.
"""
import glob
import os
import subprocess
import sys
import pytest
from support import PROGRAMS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPYTHON = os.path.expanduser(
    '~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython')
RUNTIME = 'perform and handle need the Milestone 3 runtime'
NOT_YET = {
    'read_config.epy': RUNTIME,
    'sequential.epy': RUNTIME,
    'nested.epy': RUNTIME,
    'double_resume.epy': RUNTIME,
    'abort.epy': RUNTIME,
    'body_error.epy': RUNTIME,
}

@pytest.fixture(scope='session')
def binary(tmp_path_factory):
    prebuilt = os.environ.get('EFFECTPYTHON_BINARY')
    if prebuilt:
        return prebuilt
    # The driver copies the binary into the working directory under the
    # --output name, so the scratch directory must be the cwd
    scratch = str(tmp_path_factory.mktemp('translate'))
    proc = subprocess.Popen(
        [sys.executable, RPYTHON, '--batch', '--continuation',
         '--output=effectpython-c',
         os.path.join(ROOT, 'targeteffectpython.py')],
        cwd=scratch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = proc.communicate()[0]
    if proc.returncode != 0:
        pytest.fail('translation failed:\n' + log[-4000:])
    return os.path.join(scratch, 'effectpython-c')

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
