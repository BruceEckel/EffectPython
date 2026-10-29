"""Experiment: does rlib.rstacklet behave as section 3.2 of the plan says?

This is RPython (Python 2 under RPython's restrictions). It has no parser
and no interpreter. It builds the smallest possible version of the plan's
HandlerFrame mailbox and checks, in a translated binary:

1. new() runs the body at once and returns when the body first switches
   away (a live handle) or finishes (an empty handle).
2. Every switch() returns a fresh handle for the side that switched in.
3. A finished body yields an empty handle, and the result travels in the
   mailbox, since nothing else crosses a switch.
4. An RPython exception raised in the body is carried to the handler side
   through the mailbox and re-raised there.
5. A body suspended three calls deep resumes with its locals intact, even
   after a GC collection ran while it was suspended.
6. A body abandoned mid-suspension (the handler never resumes it) does not
   crash the program, and GC afterwards is fine.

Translate and run:

    pypy2 ~/pypy/pypy2.7-v8.0.1-src/rpython/bin/rpython --continuation \
        --output=/path/to/stacklet_mailbox-c experiments/stacklet_mailbox.py
    PYPY_GC_NURSERY=2k /path/to/stacklet_mailbox-c
"""
from rpython.rlib import rstacklet, rgc, rvmprof
from rpython.rtyper.lltypesystem import llmemory


# --- vmprof workaround ------------------------------------------------------
# rstacklet calls rvmprof.save_stack(), which links rvmprof.c into the binary.
# That file references __vmprof_eval_vmprof, a symbol the translator emits
# only when some function decorated with vmprof_execute_code is annotated.
# Without one, gcc fails with "'__vmprof_eval_vmprof' undeclared". The same
# hack appears in rpython/rlib/test/test_rstacklet.py, guarded there by
# `if NonConstant(False)`. That test compiles without backend optimizations.
# The full translator folds NonConstant(False) to False after rtyping and
# removes the call, and the symbol with it, so the guard here depends on
# argv instead, which nothing can fold away.

class FakeVMProfCode(object):
    pass

rvmprof.register_code_object_class(FakeVMProfCode, lambda code: 'name')

@rvmprof.vmprof_execute_code("xcode1", lambda code, num: code)
def fake_vmprof_main(code, num):
    return 42


# --- Boxed values, as in plan section 3.1 ---------------------------------

class W_Root(object):
    _attrs_ = []

    def repr(self):
        return "<W_Root>"


class W_None(W_Root):
    def repr(self):
        return "None"


class W_Int(W_Root):
    def __init__(self, val):
        self.val = val

    def repr(self):
        return str(self.val)


class W_Str(W_Root):
    def __init__(self, val):
        self.val = val

    def repr(self):
        return "'" + self.val + "'"


class W_EffectPayload(W_Root):
    def __init__(self, op_name, arg_w):
        self.op_name = op_name
        self.arg_w = arg_w

    def repr(self):
        return "perform(%s, %s)" % (self.op_name, self.arg_w.repr())


class BodyError(Exception):
    def __init__(self, msg):
        self.msg = msg


# --- Mailbox, as in plan section 3.3 ---------------------------------------

STATUS_RUNNING = 0
STATUS_SUSPENDED = 1
STATUS_COMPLETED = 2


class Mailbox(object):
    def __init__(self, sthread, body_kind):
        self.body_kind = body_kind
        self.h_handler = sthread.get_null_handle()
        self.status = STATUS_RUNNING
        self.pending_payload = None
        self.resume_value = None
        self.body_result = None
        self.pending_exception = None


class GlobalState(object):
    def __init__(self):
        self.sthread = None
        self.mailbox = None


gs = GlobalState()


# --- Body side -------------------------------------------------------------

def perform(mb, op_name, arg_w):
    mb.pending_payload = W_EffectPayload(op_name, arg_w)
    mb.status = STATUS_SUSPENDED
    # Rule 2: the handle we hold is consumed; store the fresh one.
    mb.h_handler = gs.sthread.switch(mb.h_handler)
    mb.status = STATUS_RUNNING
    val = mb.resume_value
    mb.resume_value = None
    return val


def read_config(mb):
    # Three calls deep: main -> load_app -> read_config -> perform.
    # Keep live GC objects on this frame across the suspension.
    kept = [W_Int(i * 7) for i in range(50)]
    w_a = perform(mb, "read", W_Str("config.toml"))
    w_b = perform(mb, "read", W_Str("secrets.toml"))
    total = 0
    for w in kept:
        assert isinstance(w, W_Int)
        total += w.val
    assert total == 7 * (49 * 50 // 2)
    assert isinstance(w_a, W_Int)
    assert isinstance(w_b, W_Int)
    print "  body: resumed twice with", w_a.repr(), "and", w_b.repr()
    return W_Int(w_a.val + w_b.val)


def load_app(mb):
    w = read_config(mb)
    assert isinstance(w, W_Int)
    return W_Int(w.val * 10)


def run_body(mb):
    kind = mb.body_kind
    if kind == "deep":
        return load_app(mb)
    elif kind == "raises":
        perform(mb, "read", W_Str("before-error"))
        raise BodyError("body failed after one perform")
    elif kind == "abandoned":
        perform(mb, "ask", W_Str("never answered"))
        print "  body: THIS MUST NOT PRINT (abandoned body resumed)"
        return W_None()
    elif kind == "silent":
        return W_Str("finished without performing")
    else:
        assert False, "unknown body kind"
        return W_None()


def body_callback(h, arg):
    # Rule 1: new() entered us immediately; h is the handler side.
    mb = gs.mailbox
    mb.h_handler = h
    try:
        mb.body_result = run_body(mb)
    except BodyError as e:
        # Rule 4: an exception cannot cross the switch; mail it.
        mb.pending_exception = e
    mb.status = STATUS_COMPLETED
    # Rule 3: returning this handle finishes the stacklet; the handler
    # side's switch() (or new()) returns an empty handle.
    return mb.h_handler


# --- Handler side ----------------------------------------------------------

def run_handled(body_kind, max_resumes):
    sthread = gs.sthread
    mb = Mailbox(sthread, body_kind)
    gs.mailbox = mb
    print "handler: new() for body", body_kind
    h = sthread.new(body_callback, llmemory.NULL)
    resumes = 0
    while not sthread.is_empty_handle(h):
        assert mb.status == STATUS_SUSPENDED
        payload = mb.pending_payload
        assert payload is not None
        print "handler: body suspended on", payload.repr()
        if resumes >= max_resumes:
            print "handler: abandoning the body (dropping its handle)"
            gs.mailbox = None
            return None
        # Rule 5: collect while the body's stack is suspended.
        rgc.collect()
        resumes += 1
        mb.resume_value = W_Int(100 * resumes)
        print "handler: resume(%d)" % (100 * resumes)
        h = sthread.switch(h)
    assert mb.status == STATUS_COMPLETED
    gs.mailbox = None
    if mb.pending_exception is not None:
        print "handler: body raised; re-raising on the handler side"
        raise mb.pending_exception
    return mb.body_result


def check(name, body_kind, max_resumes):
    print "-----", name, "-----"
    try:
        w = run_handled(body_kind, max_resumes)
    except BodyError as e:
        print "handler: caught BodyError:", e.msg
        return
    if w is None:
        print "handler: no result (body abandoned)"
    else:
        print "handler: body result =", w.repr()


def entry_point(argv):
    if len(argv) == 0:  # never true; see the vmprof workaround above
        fake_vmprof_main(FakeVMProfCode(), 42)
    gs.sthread = rstacklet.StackletThread()
    check("deep chain, two performs", "deep", 10)
    check("body raises after one perform", "raises", 10)
    check("body abandoned mid-suspension", "abandoned", 0)
    rgc.collect()
    check("body never performs", "silent", 10)
    rgc.collect()
    print "----- all done -----"
    return 0


def target(driver, args):
    return entry_point, None


if __name__ == "__main__":
    import sys
    entry_point(sys.argv)
