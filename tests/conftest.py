"""The translated binary, shared by the modules that run programs.

Stacklets cannot run untranslated on the PyPy host, so the binary
fixture translates targeteffectpython.py once per session into a
scratch directory. Translation takes about 40 seconds. Setting
EFFECTPYTHON_BINARY to the path of a binary translated earlier skips
the translation and uses that binary instead, unless a host source
file is newer than it: pytest translates into a temporary directory
and leaves ./effectpython-c as it was, so a binary older than the
source would test the code before the change (newer_source).
"""
import glob
import os
import subprocess
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RPYTHON = os.path.expanduser(
    '~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython')
SOURCES = (glob.glob(os.path.join(ROOT, 'effectpython', '*.py'))
           + [os.path.join(ROOT, 'targeteffectpython.py')])

def newer_source(binary_path, sources):
    """The source file last changed after the binary, or None."""
    newest = None
    latest = os.path.getmtime(binary_path)
    for path in sources:
        if os.path.getmtime(path) > latest:
            latest = os.path.getmtime(path)
            newest = path
    return newest

@pytest.fixture(scope='session')
def binary(tmp_path_factory):
    prebuilt = os.environ.get('EFFECTPYTHON_BINARY')
    if prebuilt:
        stale = newer_source(prebuilt, SOURCES)
        if stale is not None:
            pytest.fail('%s is older than %s; translate again' %
                        (prebuilt, os.path.relpath(stale, ROOT)))
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
