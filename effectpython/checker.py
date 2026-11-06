"""The static effect checker (plan 2.2).

check() runs three passes over a parsed module before anything runs.
Pass 1 collects the effect declarations, the exception classes, the
handler classes, and the function signatures, so a function body can
call a function defined later or itself, and checks each handler
class against the effect it fulfills: one method per operation with
the operation's signature after self, and fields of type int or str
(plan 1.5).
Pass 2 walks each function and method body and infers the effects it
may perform: a perform() contributes its effect, a call contributes
the callee's declared row, and a handle block removes the effects it
names or fulfills from its body's set and adds whatever its clauses
and its handlers' methods perform. The result must be a subset of the
declared row, or the function fails with an UnhandledEffectError.
Pass 3 requires a main() with an empty row.

An exception class sits in the same set as an effect (plan 1.6). A
raise contributes the class of its value, a try/except removes the classes its
clauses catch from its suite's set and adds whatever the clauses
perform or raise, and a handler method's row carries its exceptions
to the function that installs the handler. A row may therefore name
exception classes beside effects, and main()'s empty row makes an
exception nobody catches a static error.

Along the way the checker types expressions far enough to check the
arguments of perform(), resume(), ordinary calls, and constructor
calls against the declared parameter types. A type is a type name; a
handler class name is the type of its instances, so a name holding
one may be passed to handle() and its fields read, and an exception
class name is the type of the name an except clause binds. The empty
string stands for a type the checker cannot determine, and an unknown
type matches anything.

The checker dispatches by isinstance over the ast_nodes classes, as the
evaluator does, so adding a node means adding a branch in both.
"""
from effectpython import ast_nodes as ast
from effectpython.errors import InvalidProgram, UnhandledEffectError

UNKNOWN = ""
FIELD_TYPES = ["int", "str"]
EXCEPTION = "Exception"

class EffectSet(object):
    """The effects a piece of code may perform and the exception classes
    it may raise, each with the line where it was first seen, in order
    of first appearance."""

    def __init__(self):
        self.names = []
        self.linenos = {}

    def add(self, name, lineno):
        if name not in self.linenos:
            self.names.append(name)
            self.linenos[name] = lineno

class Binding(object):
    """What an except clause's name stands for: one operation of one
    effect."""

    def __init__(self, effect, op):
        self.effect = effect  # str
        self.op = op          # OperationDef

class Scope(object):
    """The types of a function's variables and its clause bindings."""

    def __init__(self):
        self.types = {}     # variable name -> type name
        self.bindings = {}  # variable name -> Binding

class HandlerInfo(object):
    """A handler class as Pass 1 records it: its fields in declaration
    order, with the count that a constructor call must supply, and the
    union of its methods' effect rows."""

    def __init__(self, node):
        self.node = node
        self.name = node.name
        self.effect = node.effect
        self.field_names = []  # in declaration order
        self.field_types = {}  # field name -> type name
        self.required = 0      # leading fields without a default
        self.rows = []         # the names in the methods' rows

class Checker(object):

    def __init__(self, module):
        self.module = module
        self.effects = {}     # effect name -> {op name -> OperationDef}
        self.exceptions = {}  # exception class name -> ExceptionDef
        self.handlers = {}    # handler class name -> HandlerInfo
        self.functions = {}   # function name -> FunctionDef

    def check(self):
        self.collect_declarations()
        for fn in self.module.functions:
            self.check_function(fn, "function")
        for handler in self.module.handlers:
            for method in handler.methods:
                self.check_function(method, "method")
        self.check_entry_point()

    # --- pass 1 ------------------------------------------------------------

    def collect_declarations(self):
        for effect in self.module.effects:
            if effect.name in self.effects:
                raise InvalidProgram(
                    effect.lineno,
                    "effect '%s' is declared twice" % effect.name)
            ops = {}
            for op in effect.operations:
                if op.name in ops:
                    raise InvalidProgram(
                        op.lineno, "operation '%s' is declared twice in "
                        "effect '%s'" % (op.name, effect.name))
                ops[op.name] = op
            self.effects[effect.name] = ops
        for exc in self.module.exceptions:
            if (exc.name in self.exceptions or exc.name in self.effects
                    or exc.name == EXCEPTION):
                raise InvalidProgram(
                    exc.lineno,
                    "exception class '%s' is declared twice" % exc.name)
            self.exceptions[exc.name] = exc
        for handler in self.module.handlers:
            self.collect_handler(handler)
        for fn in self.module.functions:
            if (fn.name in self.functions or fn.name in self.handlers
                    or fn.name in self.exceptions):
                raise InvalidProgram(
                    fn.lineno,
                    "function '%s' is defined twice" % fn.name)
            self.functions[fn.name] = fn
            for name in fn.effect_row:
                self.require_row_name(name, fn.lineno)

    def collect_handler(self, handler):
        if (handler.name in self.handlers or handler.name in self.effects
                or handler.name in self.exceptions):
            raise InvalidProgram(
                handler.lineno,
                "handler class '%s' is declared twice" % handler.name)
        info = HandlerInfo(handler)
        ops = self.require_effect(handler.effect, handler.lineno)
        for field in handler.fields:
            self.collect_field(info, field)
        methods = {}
        for method in handler.methods:
            if method.name in methods:
                raise InvalidProgram(
                    method.lineno, "method '%s' is declared twice in "
                    "handler class '%s'" % (method.name, handler.name))
            methods[method.name] = method
            if method.name not in ops:
                raise InvalidProgram(
                    method.lineno, "method '%s' of handler class '%s' is "
                    "not an operation of %s" %
                    (method.name, handler.name, handler.effect))
            self.check_signature(handler, method, ops[method.name])
            for name in method.effect_row:
                self.require_row_name(name, method.lineno)
                if name not in info.rows:
                    info.rows.append(name)
        for op in ops.keys():
            if op not in methods:
                raise InvalidProgram(
                    handler.lineno, "handler class '%s' has no method for "
                    "%s.%s" % (handler.name, handler.effect, op))
        self.handlers[handler.name] = info

    def collect_field(self, info, field):
        if field.name in info.field_types:
            raise InvalidProgram(
                field.lineno, "field '%s' is declared twice in handler "
                "class '%s'" % (field.name, info.name))
        if field.type not in FIELD_TYPES:
            raise InvalidProgram(
                field.lineno, "field '%s' of handler class '%s' must be "
                "int or str, not %s" % (field.name, info.name, field.type))
        if field.default is None:
            if info.required < len(info.field_names):
                raise InvalidProgram(
                    field.lineno, "field '%s' without a default follows a "
                    "field with one" % field.name)
            info.required += 1
        elif isinstance(field.default, ast.IntLiteral):
            self.check_default(field, "int")
        else:
            self.check_default(field, "str")
        info.field_names.append(field.name)
        info.field_types[field.name] = field.type

    def check_default(self, field, actual):
        if actual != field.type:
            raise InvalidProgram(
                field.lineno, "default of field '%s' must be %s, not %s" %
                (field.name, field.type, actual))

    def check_signature(self, handler, method, op):
        """The parameters after self and the return type match the
        operation's."""
        what = "method '%s' of handler class '%s'" % (method.name,
                                                      handler.name)
        if (method.params[1:] != op.params
                or method.param_types[1:] != op.param_types):
            raise InvalidProgram(
                method.lineno, "%s must take (self, %s), as %s.%s does" %
                (what, signature(op), handler.effect, op.name))
        if method.return_type != op.return_type:
            raise InvalidProgram(
                method.lineno, "%s must return %s, as %s.%s does" %
                (what, op.return_type, handler.effect, op.name))

    def require_effect(self, name, lineno):
        if name not in self.effects:
            raise InvalidProgram(lineno, "unknown effect '%s'" % name)
        return self.effects[name]

    def require_row_name(self, name, lineno):
        """A row names the effects and the exception classes that can
        reach the caller, so the catch-all Exception has no place in it."""
        if name == EXCEPTION:
            raise InvalidProgram(
                lineno, "an effect row names exception classes, not "
                "Exception")
        if name not in self.effects and name not in self.exceptions:
            raise InvalidProgram(
                lineno,
                "'%s' is not an effect or an exception class" % name)

    def require_op(self, effect, op, lineno):
        ops = self.require_effect(effect, lineno)
        if op not in ops:
            raise InvalidProgram(
                lineno, "effect '%s' has no operation '%s'" % (effect, op))
        return ops[op]

    # --- pass 2 ------------------------------------------------------------

    def check_function(self, fn, what):
        scope = Scope()
        for i in range(len(fn.params)):
            scope.types[fn.params[i]] = fn.param_types[i]
        effects = EffectSet()
        self.check_block(fn.body, scope, effects)
        performed = []
        raised = []
        for name in effects.names:
            if name not in fn.effect_row:
                entry = "%s (line %d)" % (name, effects.linenos[name])
                if name in self.exceptions:
                    raised.append(entry)
                else:
                    performed.append(entry)
        undeclared = []
        if len(performed) > 0:
            undeclared.append("performs " + ", ".join(performed))
        if len(raised) > 0:
            undeclared.append("raises " + ", ".join(raised))
        if len(undeclared) > 0:
            raise UnhandledEffectError(
                fn.lineno, "%s '%s' %s without declaring it in its "
                "effect row" % (what, fn.name, ", ".join(undeclared)))

    def check_block(self, stmts, scope, effects):
        for stmt in stmts:
            self.check_stmt(stmt, scope, effects)

    def check_stmt(self, stmt, scope, effects):
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                self.type_of(stmt.value, scope, effects)
        elif isinstance(stmt, ast.If):
            self.type_of(stmt.test, scope, effects)
            self.check_block(stmt.body, scope, effects)
            self.check_block(stmt.orelse, scope, effects)
        elif isinstance(stmt, ast.While):
            self.type_of(stmt.test, scope, effects)
            self.check_block(stmt.body, scope, effects)
        elif isinstance(stmt, ast.Assign):
            scope.types[stmt.name] = self.type_of(stmt.value, scope, effects)
        elif isinstance(stmt, ast.AttrAssign):
            info = self.require_instance(scope, stmt.target, stmt.lineno)
            expected = self.require_field(info, stmt.attr, stmt.lineno)
            actual = self.type_of(stmt.value, scope, effects)
            if actual != UNKNOWN and actual != expected:
                raise InvalidProgram(
                    stmt.lineno, "field '%s' of handler class '%s' is %s; "
                    "cannot assign %s" % (stmt.attr, info.name, expected,
                                          actual))
        elif isinstance(stmt, ast.ExprStmt):
            self.type_of(stmt.expr, scope, effects)
        elif isinstance(stmt, ast.Pass):
            pass
        elif isinstance(stmt, ast.Handle):
            self.check_handle(stmt, scope, effects)
        elif isinstance(stmt, ast.Raise):
            self.check_raise(stmt, scope, effects)
        elif isinstance(stmt, ast.Try):
            self.check_try(stmt, scope, effects)
        else:
            raise InvalidProgram(stmt.lineno, "unknown statement node")

    def check_raise(self, stmt, scope, effects):
        """The row needs the class a raise contributes, so the value's
        type is a declared exception class: a constructor call, or a
        name an except clause bound to that class. A name caught as
        Exception has no class to contribute."""
        value = stmt.value
        if isinstance(value, ast.OpCall):
            actual = "%s.%s(...)" % (value.effect, value.op)
        elif isinstance(value, ast.Call) and value.func == EXCEPTION:
            actual = EXCEPTION
        else:
            actual = self.type_of(value, scope, effects)
        if actual in self.exceptions:
            effects.add(actual, stmt.lineno)
            return
        if actual == EXCEPTION:
            raise InvalidProgram(
                stmt.lineno, "raise needs a declared exception class, "
                "not Exception")
        if actual == UNKNOWN:
            actual = "a value of unknown type"
        raise InvalidProgram(
            stmt.lineno, "raise needs an exception, not %s" % actual)

    def check_try(self, stmt, scope, effects):
        """The suite's effects, less the classes the clauses catch, plus
        whatever the clauses perform or raise: the formula of a handle
        block with exception classes in place of handled effects."""
        body_effects = EffectSet()
        self.check_block(stmt.body, scope, body_effects)
        caught = {}
        for clause in stmt.clauses:
            if (clause.name != EXCEPTION
                    and clause.name not in self.exceptions):
                raise InvalidProgram(
                    clause.lineno,
                    "'%s' is not an exception class" % clause.name)
            caught[clause.name] = True
            binding = clause.binding
            if binding is None:
                self.check_block(clause.body, scope, effects)
            else:
                if binding in scope.bindings:
                    del scope.bindings[binding]
                scope.types[binding] = clause.name
                self.check_block(clause.body, scope, effects)
                if binding in scope.types:
                    del scope.types[binding]
        for name in body_effects.names:
            if name in self.exceptions and (name in caught
                                            or EXCEPTION in caught):
                continue
            effects.add(name, body_effects.linenos[name])

    def check_handle(self, stmt, scope, effects):
        """Sort the arguments into effects, which need clauses, and
        handlers, which fulfill their effect; then check the clauses
        cover the effects and nothing the handlers fulfill."""
        fulfilled = {}  # effect name -> handler class name
        handled = []
        for name in stmt.effects:
            if name in self.effects:
                handled.append(name)
            elif scope.types.get(name, UNKNOWN) in self.handlers:
                info = self.handlers[scope.types[name]]
                self.fulfill(fulfilled, info, stmt.lineno)
                stmt.instances.append(name)
            else:
                raise InvalidProgram(
                    stmt.lineno,
                    "'%s' is not an effect or a handler instance" % name)
        stmt.effects = handled
        for call in stmt.constructions:
            if call.func not in self.handlers:
                raise InvalidProgram(
                    call.lineno,
                    "'%s' is not a handler class" % call.func)
            self.type_of(call, scope, effects)
            self.fulfill(fulfilled, self.handlers[call.func], stmt.lineno)
        for name in handled:
            if name in fulfilled:
                raise InvalidProgram(
                    stmt.lineno, "handle() names %s and a handler class "
                    "for it" % name)
        if len(stmt.clauses) == 0 and len(handled) > 0:
            raise InvalidProgram(
                stmt.lineno, "with handle(%s) outside try needs except "
                "clauses for %s" % (", ".join(handled),
                                    ", ".join(handled)))
        for handler_name in fulfilled.values():
            for name in self.handlers[handler_name].rows:
                effects.add(name, stmt.lineno)
        body_effects = EffectSet()
        self.check_block(stmt.body, scope, body_effects)
        covered = {}
        for clause in stmt.clauses:
            if clause.effect in fulfilled:
                raise InvalidProgram(
                    clause.lineno, "clause for %s.%s, but %s fulfills %s" %
                    (clause.effect, clause.op, fulfilled[clause.effect],
                     clause.effect))
            if clause.effect not in stmt.effects:
                raise InvalidProgram(
                    clause.lineno, "clause for %s.%s, but handle(%s) does "
                    "not name %s" % (clause.effect, clause.op,
                                     ", ".join(stmt.effects), clause.effect))
            op = self.require_op(clause.effect, clause.op, clause.lineno)
            key = clause.effect + "." + clause.op
            if key in covered:
                raise InvalidProgram(
                    clause.lineno, "duplicate clause for %s" % key)
            covered[key] = True
            scope.bindings[clause.binding] = Binding(clause.effect, op)
            scope.types[clause.binding] = UNKNOWN
            self.check_block(clause.body, scope, effects)
        missing = []
        for name in stmt.effects:
            for op in self.effects[name].keys():
                if name + "." + op not in covered:
                    missing.append(name + "." + op)
        if len(missing) > 0:
            raise InvalidProgram(
                stmt.lineno, "handle(%s) is missing a clause for %s" %
                (", ".join(stmt.effects), ", ".join(missing)))
        for name in body_effects.names:
            if name not in stmt.effects and name not in fulfilled:
                effects.add(name, body_effects.linenos[name])

    def fulfill(self, fulfilled, info, lineno):
        if info.effect in fulfilled:
            raise InvalidProgram(
                lineno, "handle() has two handlers for %s" % info.effect)
        fulfilled[info.effect] = info.name

    # --- expressions -------------------------------------------------------

    def type_of(self, expr, scope, effects):
        if isinstance(expr, ast.IntLiteral):
            return "int"
        elif isinstance(expr, ast.StrLiteral):
            return "str"
        elif isinstance(expr, ast.Name):
            return scope.types.get(expr.id, UNKNOWN)
        elif isinstance(expr, ast.BinOp):
            left = self.type_of(expr.left, scope, effects)
            right = self.type_of(expr.right, scope, effects)
            if left == UNKNOWN:
                return right
            return left
        elif isinstance(expr, ast.Compare):
            self.type_of(expr.left, scope, effects)
            self.type_of(expr.right, scope, effects)
            return "bool"
        elif isinstance(expr, ast.Call):
            return self.check_call(expr, scope, effects)
        elif isinstance(expr, ast.Perform):
            op = self.require_op(expr.effect, expr.op, expr.lineno)
            self.check_args(op.params, op.param_types, expr.args,
                            expr.effect + "." + expr.op, expr.lineno,
                            scope, effects)
            effects.add(expr.effect, expr.lineno)
            return op.return_type
        elif isinstance(expr, ast.OpCall):
            raise InvalidProgram(
                expr.lineno, "%s.%s(...) must be the argument of perform()"
                % (expr.effect, expr.op))
        elif isinstance(expr, ast.AttrRead):
            if scope.types.get(expr.target, UNKNOWN) in self.handlers:
                info = self.handlers[scope.types[expr.target]]
                return self.require_field(info, expr.attr, expr.lineno)
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            op = binding.op
            for i in range(len(op.params)):
                if op.params[i] == expr.attr:
                    return op.param_types[i]
            raise InvalidProgram(
                expr.lineno, "operation %s.%s has no parameter '%s'" %
                (binding.effect, op.name, expr.attr))
        elif isinstance(expr, ast.Resume):
            binding = self.require_binding(scope, expr.target,
                                           expr.lineno)
            actual = self.type_of(expr.value, scope, effects)
            expected = binding.op.return_type
            if actual != UNKNOWN and actual != expected:
                raise InvalidProgram(
                    expr.lineno, "%s.resume() for %s.%s must pass %s, not %s"
                    % (expr.target, binding.effect, binding.op.name,
                       expected, actual))
            return "None"
        else:
            raise InvalidProgram(expr.lineno, "unknown expression node")

    def check_call(self, expr, scope, effects):
        if expr.func == "print":
            for arg in expr.args:
                self.type_of(arg, scope, effects)
            return "None"
        if expr.func in self.handlers:
            return self.check_construction(expr, scope, effects)
        if expr.func in self.exceptions:
            return self.check_exception_call(expr, scope, effects)
        if expr.func not in self.functions:
            raise InvalidProgram(
                expr.lineno, "name '%s' is not defined" % expr.func)
        fn = self.functions[expr.func]
        self.check_args(fn.params, fn.param_types, expr.args,
                        fn.name + "()", expr.lineno, scope, effects)
        for name in fn.effect_row:
            effects.add(name, expr.lineno)
        return fn.return_type

    def check_construction(self, expr, scope, effects):
        """A handler class's constructor takes its fields in order; the
        trailing ones with defaults may be left out."""
        info = self.handlers[expr.func]
        given = len(expr.args)
        total = len(info.field_names)
        if given < info.required or given > total:
            if info.required == total:
                count = "%d" % total
            else:
                count = "%d to %d" % (info.required, total)
            raise InvalidProgram(
                expr.lineno, "%s() takes %s arguments (%d given)" %
                (expr.func, count, given))
        types = []
        for name in info.field_names[:given]:
            types.append(info.field_types[name])
        self.check_args(info.field_names[:given], types, expr.args,
                        expr.func + "()", expr.lineno, scope, effects)
        return info.name

    def check_exception_call(self, expr, scope, effects):
        """An exception class's constructor takes an optional str
        message."""
        given = len(expr.args)
        if given > 1:
            raise InvalidProgram(
                expr.lineno, "%s() takes 0 to 1 arguments (%d given)" %
                (expr.func, given))
        self.check_args(["message"][:given], ["str"][:given], expr.args,
                        expr.func + "()", expr.lineno, scope, effects)
        return expr.func

    def check_args(self, params, param_types, args, what, lineno,
                   scope, effects):
        if len(args) != len(params):
            raise InvalidProgram(
                lineno, "%s takes %d arguments (%d given)" %
                (what, len(params), len(args)))
        for i in range(len(args)):
            actual = self.type_of(args[i], scope, effects)
            if actual != UNKNOWN and actual != param_types[i]:
                raise InvalidProgram(
                    lineno, "argument %d of %s must be %s, not %s" %
                    (i + 1, what, param_types[i], actual))

    def require_binding(self, scope, name, lineno):
        if name not in scope.bindings:
            raise InvalidProgram(
                lineno, "'%s' is not an except binding or a handler "
                "instance" % name)
        return scope.bindings[name]

    def require_instance(self, scope, name, lineno):
        type_name = scope.types.get(name, UNKNOWN)
        if type_name not in self.handlers:
            raise InvalidProgram(
                lineno, "'%s' is not a handler instance" % name)
        return self.handlers[type_name]

    def require_field(self, info, attr, lineno):
        if attr not in info.field_types:
            raise InvalidProgram(
                lineno, "handler class '%s' has no field '%s'" %
                (info.name, attr))
        return info.field_types[attr]

    # --- pass 3 ------------------------------------------------------------

    def check_entry_point(self):
        if "main" not in self.functions:
            raise InvalidProgram(0, "no main() function defined")
        main = self.functions["main"]
        if len(main.params) > 0:
            raise InvalidProgram(main.lineno, "main() takes no parameters")
        if len(main.effect_row) > 0:
            raise UnhandledEffectError(
                main.lineno, "main() must have an empty effect row, not "
                "[%s]" % ", ".join(main.effect_row))

def signature(op):
    """name: type, name: type for an operation's parameters."""
    parts = []
    for i in range(len(op.params)):
        parts.append("%s: %s" % (op.params[i], op.param_types[i]))
    return ", ".join(parts)

def check(module):
    """Run all three passes; raise on the first mistake found."""
    Checker(module).check()
