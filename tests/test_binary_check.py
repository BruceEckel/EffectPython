"""The staleness check conftest.py makes on EFFECTPYTHON_BINARY."""
import os
import time
from conftest import newer_source

def touch(path, when):
    with open(path, 'w') as f:
        f.write('')
    os.utime(path, (when, when))

def test_a_source_changed_after_the_binary_is_named(tmp_path):
    binary = os.path.join(str(tmp_path), 'bin')
    old = os.path.join(str(tmp_path), 'old.py')
    newer = os.path.join(str(tmp_path), 'newer.py')
    newest = os.path.join(str(tmp_path), 'newest.py')
    now = time.time()
    touch(old, now - 30)
    touch(binary, now - 20)
    touch(newer, now - 10)
    touch(newest, now)
    assert newer_source(binary, [old, newest, newer]) == newest

def test_a_binary_newer_than_every_source_passes(tmp_path):
    binary = os.path.join(str(tmp_path), 'bin')
    source = os.path.join(str(tmp_path), 'a.py')
    now = time.time()
    touch(source, now - 10)
    touch(binary, now)
    assert newer_source(binary, [source]) is None
