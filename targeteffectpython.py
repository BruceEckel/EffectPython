"""RPython translation entry point for EffectPython (plan Milestone 4).

Translate with:

    pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --batch --continuation \
        --output=effectpython-c targeteffectpython.py

Run untranslated with:

    PYTHONPATH=~/pypy/pypy2.7-v8.0.1-src pypy2 targeteffectpython.py program.epy

The binary parses the .epy file named on the command line and runs its
main(). Exit code 1 reports an error in the program, 2 a usage error.
"""
import sys

from rpython.rlib import rvmprof

from effectpython.errors import EffectError
from effectpython.interpreter import Interpreter
from effectpython.parser import parse


# --- vmprof workaround ------------------------------------------------------
# rstacklet calls rvmprof.save_stack(), which links rvmprof.c into the binary.
# That file references __vmprof_eval_vmprof, a symbol the translator emits
# only when some function decorated with vmprof_execute_code is reachable
# from the entry point. Without one, gcc fails with
# "'__vmprof_eval_vmprof' undeclared". The guard below depends on argv
# because the translator folds a NonConstant(False) guard to False after
# rtyping and removes the stub with it. See experiments/stacklet_mailbox.py
# and plan section 3.2.

class FakeVMProfCode(object):
    pass

rvmprof.register_code_object_class(FakeVMProfCode, lambda code: 'name')

@rvmprof.vmprof_execute_code("xcode1", lambda code, num: code)
def fake_vmprof_main(code, num):
    return 42


def read_source(path):
    f = open(path, 'r')
    try:
        return f.read()
    finally:
        f.close()


def entry_point(argv):
    if len(argv) == 0:  # never true; see the vmprof workaround above
        fake_vmprof_main(FakeVMProfCode(), 42)
    if len(argv) != 2:
        print "usage: %s program.epy" % argv[0]
        return 2
    try:
        source = read_source(argv[1])
    except IOError:
        print "error: cannot read %s" % argv[1]
        return 2
    try:
        interp = Interpreter(parse(source))
        return interp.run_main()
    except EffectError as e:
        print "error:", e.msg
        return 1


def target(driver, args):
    driver.exe_name = "effectpython-c"
    return entry_point, None


if __name__ == "__main__":
    sys.exit(entry_point(sys.argv))
