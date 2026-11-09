"""Every ordering of an assignment, a perform point, and a typed read
in a handled body, with a clause that may retype a name, through the
checker and then the binary (plan 2.2, retyping at the performs).

The programs and the oracle are enumerate_programs.py's. The entry
rule of 2026-11-08 accepted `x = 1`, a perform, `take_int(x)` with a
clause `x = "s"`, four of this module's 648 programs, which then
fail at runtime; the rule in force rejects them.

Run with:  EFFECTPYTHON_BINARY=./effectpython-c pypy2 -m pytest tests/test_enumeration.py
"""
from enumerate_programs import run, triples

def test_no_accepted_program_fails_with_a_type_error(binary, tmp_path):
    passed, failures, runtime_only = run(binary, triples(),
                                         str(tmp_path))
    assert failures == []
    assert len(passed) > 200
