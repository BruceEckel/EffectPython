"""The module docstrings of interpreter.py and checker.py name the
programs under tests/programs/ that hold their claims to the code.
Two things can drift: a docstring can name a program that no longer
exists, and a program can be added, or renamed, without the docstring
that lists the cases knowing. Each test here reads the two docstrings
for names ending in .epy and holds them against the directory. A
name with a * in it is a pattern and stands for every program it
matches, except the two bare patterns unreachable_*.epy and
runtime_*.epy, which name the groups and not their members.

Run with:  pypy2 -m pytest tests/test_docstrings.py
"""
import fnmatch
import glob
import os
import re
import pytest
from support import PROGRAMS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ['interpreter.py', 'checker.py']
GROUPS = ['unreachable_*.epy', 'runtime_*.epy']

def docstring(module):
    with open(os.path.join(ROOT, 'effectpython', module)) as f:
        source = f.read()
    end = source.index('"""', 3)
    return source[3:end]

def cited_names():
    """Every .epy name the two docstrings mention, patterns included."""
    names = set()
    for module in MODULES:
        names.update(re.findall(r'[A-Za-z0-9_*]+\.epy', docstring(module)))
    return names

def program_names():
    return set(os.path.basename(path)
               for path in glob.glob(os.path.join(PROGRAMS, '*.epy')))

@pytest.mark.parametrize('name', sorted(cited_names()))
def test_a_cited_program_exists(name):
    assert fnmatch.filter(program_names(), name), (
        '%s is named in a docstring and not under tests/programs/'
        % name)

def grouped_programs():
    names = program_names()
    return sorted(name for name in names
                  if any(fnmatch.fnmatch(name, group) for group in GROUPS))

@pytest.mark.parametrize('name', grouped_programs())
def test_a_grouped_program_is_cited(name):
    patterns = cited_names() - set(GROUPS)
    assert any(fnmatch.fnmatch(name, pattern) for pattern in patterns), (
        '%s is under tests/programs/ and no docstring names it' % name)
