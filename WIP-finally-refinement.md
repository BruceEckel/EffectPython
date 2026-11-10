# Work in progress: the finally rule, refined (2026-11-10)

This branch holds uncommitted-on-main work from the session after `3366da2`.
Nothing here is reviewed; `main` is unchanged.
Delete this file when the work is merged or dropped.

## What changed

- `effectpython/checker.py`: the refined second rule of plan 1.15.
  `3366da2` absorbed the first check of every `finally` under a loop into `loop_exits[-1]`.
  That first check starts from every boundary, mid-clause ones included,
  and only an exception (which leaves the loop) reaches the `finally` from there,
  so the rule rejected 154 size-4 loop programs with no `break` or `continue` that run cleanly.
  Now a `try` with a `finally` under a loop pushes a `Leaving` accumulator;
  `leave_loop` (called by `break` and `continue`) absorbs into `loop_exits[-1]` as before
  and into every `Leaving` of the same loop;
  the `finally` gets a third check from those types, and `leave_loop` takes what it leaves.
- `tests/enumerate_programs.py`: the second generator, `loop_bodies(n)`,
  run as `pypy2 tests/enumerate_programs.py loop LOW HIGH`.
  Its alphabet has 14 statements; the last two are the guarded compounds
  `if i == 1:` over `z = "s"` and `continue` (or `break`),
  which put the finally hole at size 4.

## Results so far

Loop generator, sizes 2 to 4 (1,203,636 programs), checker in process and each accepted program through the binary:

| Build | Accepted | Typed-slot failures | Other runtime errors |
|---|---|---|---|
| A: `6d3fea3`, before any fix | 590,383 | 4 | 0 |
| B: `3366da2`, HEAD of `main` | 590,213 | 0 | 0 |
| C: this branch, refined | 590,375 | 0 | 0 |

- C accepts nothing that A rejects.
- C rejects 8 programs that A accepts: the 4 typed-slot failures (the hole, all size 4, for example a suite of the guarded `z = "s"` and `continue` then `z = 1`, a clause `z = 1`, `x = z` in the `finally`, and `take_int(x)` after the loop),
  and 4 that run cleanly because their clause, which holds the guarded `continue`, never runs (no `risky(i)` in the suite).
- B rejects 170 programs that A accepts; at the old 12-statement alphabet it was 154.
- The first enumeration at sizes 2 and 3 on C: 39,831 accepted, 0 typed-slot failures, 172 unknown-operand type errors, 18,515 other runtime errors, the counts of every earlier run.

## Open before committing to main

1. `tests/programs/runtime_finally_break.epy` fails in `tests/test_runtime.py`.
   The third check sees `x` as `str` on the `break` path,
   so the checker now rejects `print(x + 1)` with "line 15: unsupported operand types for +: str and int",
   where the program expects the runtime's message without a line.
   The binary does fail there on that path, so the rejection is right;
   the program becomes an `unreachable_` case or gets rewritten so its point stays runtime-only. Bruce's decision.
2. The accept test for the false rejections of `3366da2` is not written.
   They are the programs in B's rejections and not in C's, at sizes 2 to 4 of `loop_bodies`;
   a few representatives per shape in `tests/test_checker.py` would cover them.
3. The plan's Milestone 15 entry and the 1.15 paragraph on the `finally` describe the `3366da2` rule;
   they need the third check and the 154/170 finding
   (the 1.15 text says limiting the rule "is a refinement the samples give no reason to make").
4. Translate, run `pypy2 tests/enumerate_programs.py 2 3`, and put its counts in the commit message, per CLAUDE.md.
