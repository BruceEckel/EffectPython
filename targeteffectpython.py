"""RPython translation entry point for EffectPython (plan Milestone 4).

Translate with:

    pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --batch --continuation \
        --output=effectpython-c targeteffectpython.py

Run untranslated with:

    PYTHONPATH=~/pypy/pypy2.7-v8.0.1-src pypy2 targeteffectpython.py [n]

Until the parser exists (Milestone 2) the binary runs one hand-built
program, the recursive Fibonacci from effectpython.samples, with n taken
from the command line (default 20).
"""
import sys

from rpython.rlib import rvmprof

from effectpython.errors import EffectError
from effectpython.interpreter import Interpreter
from effectpython.samples import build_fib_module


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


def usage(argv):
    print "usage: %s [n]    (prints fib(n); n defaults to 20)" % argv[0]


def entry_point(argv):
    if len(argv) == 0:  # never true; see the vmprof workaround above
        fake_vmprof_main(FakeVMProfCode(), 42)
    n = 20
    if len(argv) > 2:
        usage(argv)
        return 2
    if len(argv) == 2:
        try:
            n = int(argv[1])
        except ValueError:
            usage(argv)
            return 2
    try:
        interp = Interpreter(build_fib_module(n))
        return interp.run_main()
    except EffectError as e:
        print "error:", e.msg
        return 1


def target(driver, args):
    driver.exe_name = "effectpython-c"
    return entry_point, None


if __name__ == "__main__":
    sys.exit(entry_point(sys.argv))
