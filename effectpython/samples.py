"""Hand-built ASTs for programs the parser cannot read yet.

Until Milestone 2 there is no parser, so the acceptance programs are built
directly from ast_nodes. Each builder's docstring shows the .epy source it
stands for; when the parser exists, these become .epy files under tests/.
"""
from effectpython import ast_nodes as ast

def build_fib_module(n):
    """
    def fib(n: int) -> int:
        if n < 2:
            return n
        return fib(n - 1) + fib(n - 2)

    def main() -> int / []:
        print(fib(<n>))
        return 0
    """
    fib = ast.FunctionDef(
        "fib", ["n"], ["int"], "int", [],
        [
            ast.If(ast.Compare("<", ast.Name("n"), ast.IntLiteral(2)),
                   [ast.Return(ast.Name("n"))],
                   []),
            ast.Return(ast.BinOp(
                "+",
                ast.Call("fib", [ast.BinOp("-", ast.Name("n"), ast.IntLiteral(1))]),
                ast.Call("fib", [ast.BinOp("-", ast.Name("n"), ast.IntLiteral(2))]))),
        ])
    main = ast.FunctionDef(
        "main", [], [], "int", [],
        [
            ast.ExprStmt(ast.Call("print", [ast.Call("fib", [ast.IntLiteral(n)])])),
            ast.Return(ast.IntLiteral(0)),
        ])
    return ast.Module([fib, main])
