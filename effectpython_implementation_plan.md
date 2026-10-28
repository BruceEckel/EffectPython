# EffectPython: Architectural Proof of Concept Plan

This document outlines the architecture and implementation specification for **EffectPython**, a Python dialect that introduces native algebraic effect management using the RPython framework. The goal is to maintain 100% syntactically valid Python 3 code (allowing standard IDEs, formatters, and linters to parse it without errors) while leveraging RPython's `rlib.rstacklet.continulet` primitives for delimited stack suspension and resumption.

---

## Phase 1: Syntax and Semantics (The "Valid Python 3" Design)

To ensure every `.epy` file is valid Python 3 syntax (parsable by `ast.parse` and `rply`), EffectPython uses standard Python 3.10+ constructs (`class`, type annotations, `try`/`except`, or `with` + `match`) rather than invalid custom keywords.

### 1.1 Declaring Effects and Operations
Effects are declared as classes inheriting from `Effect`, where methods define effect operations and their argument/return type signatures:

```python
from effectpython import Effect, perform, handle, Resume

class FileIO(Effect):
    def read(path: str) -> str: ...
    def write(path: str, content: str) -> int: ...

class DBQuery(Effect):
    def execute(sql: str) -> str: ...
```

### 1.2 Declaring Effect Rows in Function Signatures
Function return annotations use the `/` binary operator over type hints to separate the return type from the effect row (`ReturnType / [Effect1, Effect2]`):

```python
def read_config(path: str) -> str / [FileIO]:
    return perform(FileIO.read(path))
```

*   **Pure functions:** Functions without `/ [...]` in their return annotation (e.g., `def add(a: int, b: int) -> int:`) have an implicit empty effect row `[]`.
*   **Effect granularity:** Effect rows track **Effect interfaces** (e.g., `FileIO`), while handlers must cover all operations of an effect interface to discharge that effect from the row.

### 1.3 Triggering Effects (`perform`)
`perform(EffectClass.operation(*args))` is a built-in runtime primitive. Evaluating `FileIO.read(path)` constructs an `EffectOperation` descriptor value, and `perform(...)` suspends the current delimited continuation up to the nearest enclosing handler for `FileIO`.

### 1.4 Handling Effects (Valid Python 3 Syntax)
To remain valid Python 3 syntax while supporting multi-clause effect handling and resumption, EffectPython uses a `try` / `except` handler block with `handle()` (or handler functions):

```python
def main() -> int / []:
    try:
        with handle(FileIO):
            config = read_config("settings.json")
            print(config)
    except FileIO.read as eff:
        # eff binds (.args, .resume) where eff.args = (path,)
        path = eff.path
        actual_data = read_host_file(path)
        eff.resume(actual_data)
    except FileIO.write as eff:
        written = write_host_file(eff.path, eff.content)
        eff.resume(written)
    return 0
```

> **Note on Execution Semantics:** Even though the surface syntax uses `try` / `except` with `with handle(...)` for Python 3 parser compatibility, the EffectPython AST evaluator compiles this construct into an **algebraic effect handler frame** (not a stack-unwinding exception). Calling `eff.resume(val)` returns control directly to the suspended `perform()` call site, and when the `with handle(...)` body completes normally, execution proceeds past the `try`/`except` block.

---

## Phase 2: The Frontend (Parser and Static Effect Checker)

The frontend guarantees at compile-time that no effect is triggered without a matching handler up the call stack, and that all handlers for an effect interface are exhaustive.

### 2.1 Minimal Grammar Subset (`rply`)
Because implementing the full Python 3 grammar in `rply` is out of scope for a PoC, the lexer and parser will target a strict, well-defined subset of Python 3:
*   **Lexer tokens:** Indentation tracking (`INDENT`, `DEDENT`, `NEWLINE`), identifiers (`NAME`), literals (`INT`, `STRING`), operators (`+`, `-`, `*`, `/`, `==`, `=`, `->`, `:`, `.`, `,`), and delimiters (`(`, `)`, `[`, `]`).
*   **Statements:**
    *   `class <Name>(Effect):` with method signature stubs (`def <op>(...) -> <Type>: ...`)
    *   `def <name>(<params>) -> <ReturnType> [/ [<Effects>]]: <suite>`
    *   `return <expr>`, `pass`, assignment `<name> = <expr>`, expression statements
    *   `if <expr>: <suite> else: <suite>`
    *   `try: with handle(<Effects>): <suite> except <Effect>.<op> as <name>: <suite>`
*   **Expressions:** Integer/string literals, variable references, binary arithmetic, function calls, attribute calls (`Effect.op(...)`), `perform(<expr>)`, and `<name>.resume(<expr>)`.

### 2.2 Static Effect Inference & Verification Algorithm
The static analyzer runs in three passes over the AST before execution:

1.  **Pass 1 — Effect & Function Signature Collection:**
    *   Collects all `Effect` subclasses and their declared operations (`op_name -> (arg_types, return_type)`).
    *   Collects all function signatures (`func_name -> (param_types, return_type, declared_effect_row)`).
    *   Allows recursive and mutually recursive functions by seeding the symbol table from explicit annotations before checking function bodies.
2.  **Pass 2 — Intra-Procedural Effect Verification:**
    *   For each function body, computes the active `inferred_effects: set[str]` of each AST node bottom-up:
        *   `PerformNode(Effect.op, args)`: produces `{Effect}`, verifies `args` match `Effect.op`'s parameter types, and types the `perform` expression with `Effect.op`'s return type.
        *   `CallNode(callee, args)`: looks up `callee` in the function table and unions `callee.declared_effect_row` into the current scope's `inferred_effects`.
        *   `HandleNode(handled_effects, body, clauses)`:
            1. Verifies that for every `E` in `handled_effects`, `clauses` provide an `except E.op as eff:` clause for **every** operation declared on `E` (exhaustiveness check).
            2. Verifies that inside each clause, `eff.resume(val)` is called with a `val` matching `E.op`'s return type.
            3. Computes the net effect of the `HandleNode` as:
               $$\text{Effects}(\text{HandleNode}) = (\text{Effects}(\text{body}) \setminus \text{handled\_effects}) \cup \bigcup_{c \in \text{clauses}} \text{Effects}(c)$$
    *   **Signature Check:** After checking a function's body, if $\text{Effects}(\text{body}) \not\subseteq \text{declared\_effect\_row}$, raise a compile-time `UnhandledEffectError` listing the undeclared effects and their source line numbers.
3.  **Pass 3 — Entrypoint Verification:**
    *   Verifies that `main()` exists and its `declared_effect_row` is empty (`[]`).

---

## Phase 3: The Backend Runtime (RPython Object Model & Continulets)

RPython is a statically typed subset of Python that compiles to C. The interpreter cannot pass untyped Python objects around; it requires a boxed object hierarchy and explicit side-channel mailboxes to transfer data across `continulet` stack switches.

### 3.1 Boxed Runtime Value Hierarchy (`W_Root`)
All runtime values inherit from a single base class `W_Root` so `eval_ast` has a uniform RPython return type:

```python
class W_Root(object):
    _attrs_ = []

class W_None(W_Root): pass
class W_Int(W_Root):
    def __init__(self, val): self.val = val  # rpython int

class W_Str(W_Root):
    def __init__(self, val): self.val = val  # rpython str

class W_EffectPayload(W_Root):
    def __init__(self, effect_name, op_name, args_w):
        self.effect_name = effect_name
        self.op_name = op_name
        self.args_w = args_w  # list[W_Root]

class W_EffBinding(W_Root):
    """Bound to `eff` in `except Effect.op as eff:`"""
    def __init__(self, payload, handler_frame):
        self.payload = payload          # W_EffectPayload
        self.handler_frame = handler_frame  # HandlerFrame
```

### 3.2 How `rlib.rstacklet.continulet` Actually Works
In RPython, `continulet` is a **one-shot delimited continuation** primitive that captures the C stack between a delimiter base and a suspension point:
1.  **Creation at `handle` (NOT at `perform`):** A `continulet` must be initialized **when entering the `with handle(...)` block**. `continulet.__init__(cont, body_thunk, ...)` starts running `body_thunk` in a new stacklet frame anchored at the handler.
2.  **No Payload in `switch()`:** `cont.switch()` only swaps C stack pointers; it does **not** pass `W_Root` values directly. Values are exchanged via a `HandlerFrame` mailbox object shared between the handler and the suspended `perform` site.

### 3.3 The `HandlerFrame` and Context Stack
The interpreter maintains `execution_context.handler_stack: list[HandlerFrame]`. Each `HandlerFrame` holds:

```python
class HandlerFrame(object):
    def __init__(self, handled_effects, clauses, env):
        self.handled_effects = handled_effects  # list[str]
        self.clauses = clauses                  # dict[(effect, op), ClauseAST]
        self.env = env                          # Environment
        self.cont = None                        # continulet instance
        # Mailbox fields for communicating across cont.switch():
        self.status = STATUS_RUNNING            # RUNNING | SUSPENDED | COMPLETED
        self.pending_payload = None             # W_EffectPayload set by perform()
        self.resume_value = None                # W_Root set by eff.resume(val)
        self.body_result = None                 # W_Root set when body finishes
        self.resumed_once = False               # Enforces one-shot resumption
```

### 3.4 Step-by-Step Control Flow (`handle` -> `perform` -> `resume`)

```mermaid
sequenceDiagram
    participant Caller as Outer eval_ast
    participant HFrame as HandlerFrame (with handle)
    participant Cont as Continulet (Body Stacklet)
    participant Clause as Handler Clause (except Effect.op)

    Caller->>HFrame: Push HandlerFrame to handler_stack
    HFrame->>Cont: new continulet(run_handler_body, HFrame)
    Note over Cont: Executes body AST inside stacklet
    Cont->>Cont: Hits perform(FileIO.read("cfg.json"))
    Cont->>HFrame: Lookup nearest HandlerFrame for FileIO
    Cont->>HFrame: Set HFrame.status = SUSPENDED
    Cont->>HFrame: Set HFrame.pending_payload = W_EffectPayload("FileIO", "read", ["cfg.json"])
    Cont->>HFrame: HFrame.cont.switch() (suspends C stack of body)
    HFrame->>Clause: Pop HFrame temporarily; bind `eff` = W_EffBinding
    Clause->>Clause: Compute actual_data
    Clause->>HFrame: Call eff.resume(actual_data)
    HFrame->>HFrame: Set HFrame.resume_value = actual_data, status = RUNNING
    HFrame->>Cont: Re-push HFrame; call HFrame.cont.switch()
    Cont->>Cont: Wakes up at perform(), returns HFrame.resume_value
    Cont->>HFrame: Body finishes: set HFrame.status = COMPLETED, HFrame.body_result = res
    Cont-->>Caller: Continulet finishes and returns to HFrame loop
```

1.  **Entering `with handle(...)`:**
    *   Instantiate `frame = HandlerFrame(...)` and push it onto `handler_stack`.
    *   Initialize `frame.cont = continulet(run_body_trampoline, frame)` which immediately enters `run_body_trampoline` and evaluates the `with` body AST.
2.  **Executing `perform(Effect.op(*args))`:**
    *   Evaluate `args` to `list[W_Root]`.
    *   Search `handler_stack` from top to bottom for the nearest `HandlerFrame` handling `Effect`.
    *   Store `frame.pending_payload = W_EffectPayload(Effect, op, args_w)` and `frame.status = STATUS_SUSPENDED`.
    *   Call `frame.cont.switch()` to pause the C stack slice (including any intermediate function calls between `handle` and `perform`) and return control to the `HandlerFrame` loop.
3.  **Dispatching the Handler Clause & `eff.resume(val)`:**
    *   Back in the `HandlerFrame` loop, observe `frame.status == STATUS_SUSPENDED`.
    *   Temporarily pop `frame` (and any inner frames above it stays encapsulated inside the suspended stacklet) so effects performed *inside* the handler clause resolve to outer handlers.
    *   Bind `eff = W_EffBinding(frame.pending_payload, frame)` in the clause's local environment and evaluate the matching `except Effect.op as eff:` suite.
    *   When the clause evaluates `eff.resume(val_w)`:
        *   Check `if frame.resumed_once:` -> raise runtime `OneShotContinuationError("Cannot resume a continulet more than once")`.
        *   Set `frame.resumed_once = True` (for this suspension), `frame.resume_value = val_w`, `frame.status = STATUS_RUNNING`.
        *   Call `frame.cont.switch()` to swap the C stack back to the paused `perform()` site.
4.  **Returning from `perform()`:**
    *   Execution inside the stacklet resumes immediately after `frame.cont.switch()`.
    *   Reset `frame.resumed_once = False` (so subsequent `perform()` calls inside the same `handle` block can suspend again), extract `val_w = frame.resume_value`, and return `val_w` as the result of `perform(...)`.
5.  **Non-Resuming Handlers (Abort / Early Exit):**
    *   If a handler clause finishes without calling `eff.resume(...)`, the `with handle(...)` block terminates early and returns the handler clause's result.

---

## Phase 4: Project Layout, Milestones, and Verification

### 4.1 Planned Directory Structure
```text
effectpython/
├── targeteffectpython.py   # RPython translation entry_point(argv) and target()
├── effectpython/
│   ├── __init__.py
│   ├── lexer.py            # rply Lexer + INDENT/DEDENT post-processor
│   ├── parser.py           # rply Parser -> AST nodes
│   ├── ast_nodes.py        # RPython-compatible AST node classes
│   ├── checker.py          # Static effect row inference & exhaustiveness checker
│   ├── model.py            # W_Root, W_Int, W_Str, W_EffectPayload, W_EffBinding
│   ├── interpreter.py      # AST evaluator, HandlerFrame, continulet integration
│   └── errors.py           # EffectError, UnhandledEffectError, OneShotContinuationError
└── tests/
    ├── test_parser.py
    ├── test_checker.py
    └── test_runtime.py
```

### 4.2 Implementation Milestones & Acceptance Criteria

1.  **Milestone 1: The Core Evaluator (`ast_nodes.py`, `model.py`, `interpreter.py`)**
    *   Build the `W_Root` hierarchy and an RPython-compliant AST evaluator supporting functions, local lexical environments, arithmetic, conditionals, and `print`.
    *   *Acceptance test:* Run a recursive Fibonacci `.epy` script untranslated under pytest.
2.  **Milestone 2: The Frontend & Static Effect Checker (`lexer.py`, `parser.py`, `checker.py`)**
    *   Implement the `rply` parser for the EffectPython grammar subset and the 3-pass static effect analyzer.
    *   *Acceptance test:*
        *   Reject a function that calls `perform(FileIO.read("a"))` without `/ [FileIO]` in its signature (`UnhandledEffectError`).
        *   Reject a `with handle(FileIO):` block missing an `except` clause for one of `FileIO`'s declared operations.
        *   Accept a valid program where `main() -> int / []` handles all effects of its callees.
3.  **Milestone 3: Delimited Suspension & Resumption (`rlib.rstacklet.continulet`)**
    *   Implement `HandlerFrame`, the handler context stack, `perform` suspension across nested function calls, and `eff.resume(val)` resumption.
    *   *Acceptance test:*
        *   Single `perform` and `resume` across a 3-function-deep call chain (`main` -> `load_app` -> `read_config` -> `perform`).
        *   Multiple sequential `perform` calls inside the same `with handle(...)` block.
        *   Nested `with handle(DBQuery):` inside `with handle(FileIO):` routing effects to the correct handler frame.
        *   Raising `OneShotContinuationError` if a handler calls `eff.resume()` twice.
4.  **Milestone 4: RPython Translation (`targeteffectpython.py`)**
    *   Write `entry_point(argv)` and `target(driver, args)` conforming to RPython's static typing constraints (no dynamic attribute creation, homogeneous lists, uniform `W_Root` returns).
    *   *Acceptance test:* Translate with `rpython targeteffectpython.py` into a standalone native executable (`effectpython-c`) and execute sample `.epy` programs natively.