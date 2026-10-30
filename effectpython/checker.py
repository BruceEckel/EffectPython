"""The static effect checker (plan 2.2).

check() runs three passes over a parsed module before anything runs.
Pass 1 collects the effect declarations and the function signatures,
so a function body can call a function defined later or itself.
Pass 2 walks each function body and infers the effects it may perform:
a perform() contributes its effect, a call contributes the callee's
declared row, and a handle block removes the effects it names from its
body's set and adds whatever its clauses perform. The result must be a
subset of the declared row, or the function fails with an
UnhandledEffectError. Pass 3 requires a main() with an empty row.

Along the way the checker types expressions far enough to check the
arguments of perform(), resume(), and ordinary calls against the
declared parameter types. A type is a type name; the empty string
stands for a type the checker cannot determine, and an unknown type
matches anything.

The checker dispatches by isinstance over the ast_nodes classes, as the
evaluator does, so adding a node means adding a branch in both.
"""
from effectpython import ast_nodes as ast
from effectpython.errors import InvalidProgram, UnhandledEffectError

UNKNOWN = ""

class EffectSet(object):
    """The effects a piece of code may perform, each with the line where
    it was first seen, in order of first appearance."""

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

class Checker(object):

    def __init__(self, module):
        self.module = module
        self.effects = {}    # effect name -> {op name -> OperationDef}
        self.functions = {}  # function name -> FunctionDef

    def check(self):
        self.collect_declarations()
        for fn in self.module.functions:
            self.check_function(fn)
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
        for fn in self.module.functions:
            if fn.name in self.functions:
                raise InvalidProgram(
                    fn.lineno,
                    "function '%s' is defined twice" % fn.name)
            self.functions[fn.name] = fn
            for name in fn.effect_row:
                self.require_effect(name, fn.lineno)

    def require_effect(self, name, lineno):
        if name not in self.effects:
            raise InvalidProgram(lineno, "unknown effect '%s'" % name)
        return self.effects[name]

    def require_op(self, effect, op, lineno):
        ops = self.require_effect(effect, lineno)
        if op not in ops:
            raise InvalidProgram(
                lineno, "effect '%s' has no operation '%s'" % (effect, op))
        return ops[op]

    # --- pass 2 ------------------------------------------------------------

    def check_function(self, fn):
        scope = Scope()
        for i in range(len(fn.params)):
            scope.types[fn.params[i]] = fn.param_types[i]
        effects = EffectSet()
        self.check_block(fn.body, scope, effects)
        undeclared = []
        for name in effects.names:
            if name not in fn.effect_row:
                undeclared.append(
                    "%s (line %d)" % (name, effects.linenos[name]))
        if len(undeclared) > 0:
            raise UnhandledEffectError(
                fn.lineno, "function '%s' performs %s without declaring it "
                "in its effect row" % (fn.name, ", ".join(undeclared)))

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
        elif isinstance(stmt, ast.ExprStmt):
            self.type_of(stmt.expr, scope, effects)
        elif isinstance(stmt, ast.Pass):
            pass
        elif isinstance(stmt, ast.Handle):
            self.check_handle(stmt, scope, effects)
        else:
            raise InvalidProgram(stmt.lineno, "unknown statement node")

    def check_handle(self, stmt, scope, effects):
        for name in stmt.effects:
            self.require_effect(name, stmt.lineno)
        body_effects = EffectSet()
        self.check_block(stmt.body, scope, body_effects)
        covered = {}
        for clause in stmt.clauses:
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
            if name not in stmt.effects:
                effects.add(name, body_effects.linenos[name])

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
        if expr.func not in self.functions:
            raise InvalidProgram(
                expr.lineno, "name '%s' is not defined" % expr.func)
        fn = self.functions[expr.func]
        self.check_args(fn.params, fn.param_types, expr.args,
                        fn.name + "()", expr.lineno, scope, effects)
        for name in fn.effect_row:
            effects.add(name, expr.lineno)
        return fn.return_type

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
                lineno, "'%s' is not bound by an except clause" % name)
        return scope.bindings[name]

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

def check(module):
    """Run all three passes; raise on the first mistake found."""
    Checker(module).check()
