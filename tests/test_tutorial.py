"""TUTORIAL.md quotes programs from tests/programs/ and their recorded
output. Each fenced block names its file in the info string, as in
```python tests/programs/fib.epy or ```text tests/programs/fib.expected,
and these tests hold the quoted text to the file: a listing is the
program without its leading comment, and an output block is the
.expected file without its exit line.
"""
import os
import re
import pytest
from support import PROGRAMS

TUTORIAL = os.path.join(os.path.dirname(PROGRAMS), '..', 'TUTORIAL.md')
BLOCK = re.compile(r'^```(\w+) (tests/programs/(\S+))\n(.*?)^```$',
                   re.MULTILINE | re.DOTALL)

def quoted_blocks():
    with open(TUTORIAL) as f:
        text = f.read()
    return [(m.group(3), m.group(4)) for m in BLOCK.finditer(text)]

def program_text(name):
    with open(os.path.join(PROGRAMS, name)) as f:
        lines = f.read().split('\n')
    while lines and (lines[0].startswith('#') or lines[0] == ''):
        lines.pop(0)
    return '\n'.join(lines).rstrip('\n') + '\n'

def output_text(name):
    with open(os.path.join(PROGRAMS, name)) as f:
        lines = f.read().split('\n')[1:]
    return '\n'.join(lines).rstrip('\n') + '\n'

def block_cases():
    for name, body in quoted_blocks():
        yield pytest.param(name, body, id=name)

@pytest.mark.parametrize('name, body', block_cases())
def test_quoted_block_matches_its_file(name, body):
    if name.endswith('.epy'):
        assert body == program_text(name)
    else:
        assert body == output_text(name)

def test_every_mentioned_program_exists():
    with open(TUTORIAL) as f:
        mentioned = set(re.findall(r'tests/programs/(\S+?\.epy)', f.read()))
    assert mentioned
    missing = [n for n in sorted(mentioned)
               if not os.path.exists(os.path.join(PROGRAMS, n))]
    assert missing == []

def test_every_listing_has_its_output():
    names = [name for name, body in quoted_blocks()]
    listings = [n for n in names if n.endswith('.epy')]
    assert len(listings) > 10
    for name in listings:
        assert name[:-4] + '.expected' in names
