"""Boxed runtime values (plan 3.1).

Every value the evaluator produces inherits from W_Root so eval_expr has a
single RPython return type. The classes declare _attrs_ so the annotator
rejects attributes added anywhere else.

RPython does not support __str__ or __repr__ on application objects, so the
text forms are ordinary methods: str() for print(), repr() for diagnostics.
"""

class W_Root(object):
    _attrs_ = []

    def str(self):
        return "<object>"

    def repr(self):
        return self.str()

    def is_true(self):
        return True

class W_None(W_Root):
    _attrs_ = []

    def str(self):
        return "None"

    def is_true(self):
        return False

class W_Bool(W_Root):
    _attrs_ = ['val']

    def __init__(self, val):
        self.val = val

    def str(self):
        if self.val:
            return "True"
        return "False"

    def is_true(self):
        return self.val

class W_Int(W_Root):
    _attrs_ = ['val']

    def __init__(self, val):
        self.val = val  # RPython machine int

    def str(self):
        return str(self.val)

    def is_true(self):
        return self.val != 0

class W_Str(W_Root):
    _attrs_ = ['val']

    def __init__(self, val):
        self.val = val  # RPython str

    def str(self):
        return self.val

    def repr(self):
        return "'" + self.val + "'"

    def is_true(self):
        return len(self.val) > 0

class W_EffectPayload(W_Root):
    """What evaluating FileIO.read(path) produces: the effect, the
    operation, and the evaluated arguments, ready for perform() (plan 1.3).
    Used from Milestone 3 on."""
    _attrs_ = ['effect_name', 'op_name', 'args_w']

    def __init__(self, effect_name, op_name, args_w):
        self.effect_name = effect_name
        self.op_name = op_name
        self.args_w = args_w  # list of W_Root

    def repr(self):
        parts = []
        for w in self.args_w:
            parts.append(w.repr())
        return "%s.%s(%s)" % (self.effect_name, self.op_name, ", ".join(parts))

class W_EffBinding(W_Root):
    """Bound to eff in `except Effect.op as eff:` (plan 3.1): the payload
    the body performed, the HandlerFrame that caught it, and the stacklet
    handle of the suspended body. resume() consumes the handle and leaves
    the null handle behind, so a second resume() finds it empty."""
    _attrs_ = ['payload', 'frame', 'h_body']

    def __init__(self, payload, frame, h_body):
        self.payload = payload
        self.frame = frame
        self.h_body = h_body

    def repr(self):
        return "<binding for %s>" % self.payload.repr()

# Prebuilt singletons. RPython allows prebuilt instances as module globals.
w_None = W_None()
w_True = W_Bool(True)
w_False = W_Bool(False)

def wrap_bool(b):
    if b:
        return w_True
    return w_False
