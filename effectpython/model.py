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

class W_List(W_Root):
    """A list (plan 1.9): mutable and shared by reference, as Python's
    is, so two names or a parameter and an argument may hold one list.
    str() gives Python's form, which quotes a str element with single
    quotes; the dialect's strings have no escapes, so that is the
    whole rule."""
    _attrs_ = ['items_w']

    def __init__(self, items_w):
        self.items_w = items_w  # list of W_Root

    def str(self):
        parts = []
        for w in self.items_w:
            parts.append(w.repr())
        return "[" + ", ".join(parts) + "]"

    def is_true(self):
        return len(self.items_w) > 0

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

class W_HandlerInstance(W_Root):
    """An instance of a handler class (plan 1.5): the class's name, its
    field names in declaration order, and one value per field. A
    handle(...) statement holds it in the frame for the whole body, so
    a field keeps its value from one perform to the next."""
    _attrs_ = ['class_name', 'field_names', 'fields_w']

    def __init__(self, class_name, field_names, fields_w):
        self.class_name = class_name
        self.field_names = field_names  # list of str, shared with the class
        self.fields_w = fields_w        # list of W_Root, parallel to it

    def index_of(self, attr):
        for i in range(len(self.field_names)):
            if self.field_names[i] == attr:
                return i
        return -1

    def str(self):
        parts = []
        for i in range(len(self.field_names)):
            parts.append("%s=%s" % (self.field_names[i],
                                    self.fields_w[i].repr()))
        return "%s(%s)" % (self.class_name, ", ".join(parts))

class W_Exception(W_Root):
    """An instance of an exception class (plan 1.6): the class's name
    and the message, which is empty when the constructor had no
    argument. print() shows the message, as print(str(e)) does in
    Python 3."""
    _attrs_ = ['class_name', 'message']

    def __init__(self, class_name, message):
        self.class_name = class_name
        self.message = message  # RPython str

    def str(self):
        return self.message

    def repr(self):
        if self.message == "":
            return self.class_name + "()"
        return "%s('%s')" % (self.class_name, self.message)

# Prebuilt singletons. RPython allows prebuilt instances as module globals.
w_None = W_None()
w_True = W_Bool(True)
w_False = W_Bool(False)

def wrap_bool(b):
    if b:
        return w_True
    return w_False
