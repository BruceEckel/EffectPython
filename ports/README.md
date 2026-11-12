# Python originals

Three sample programs were written in ordinary Python first and then ported to the dialect, to see what the port had to give up.
Each file here is the original of the port with the same name under `tests/programs/`, and `tools/test_ports.py` holds its output to the port's recorded output.

- `settings_layers.py` is the original of `settings_layers.epy`; `settings_none.epy` is a second port of it with an operation that returns `None`, and its output differs.
- `build_plan.py` is the original of `build_plan.epy`.

The original of `shop_orders.epy` was not kept.

These run under Python 3.12 or later: `python3 ports/build_plan.py`.
