"""The restricted arithmetic interpreter.

Layer 4 of verification (docs/06-trust-layer.md#verification) does not trust a
tool's output: it re-evaluates the tool's own declared formula against the
tool's own declared inputs and demands the same number. That check is only
worth something if the formula language is too weak to *be* the tool. A
grammar that can call a function can call the tool again, and layer 4 would
degrade into re-running the code that is under suspicion.

So the grammar is: named operands, integer literals, unary minus, ``+ - * /``,
and parentheses. Nothing else parses. No attribute access, no calls, no
subscripts, no comprehensions, no ``**``, no floats. ``__import__`` is not
special-cased -- it is a call, and calls do not exist here.

Evaluation is in :class:`~decimal.Decimal` at raised precision, never float:
``+ - *`` over integral Decimals are exact, and ``/`` is the one place a
formula can produce a fraction. The result is returned exact and unrounded;
rounding to paise or to a scale-6 ratio is a separate, single step in
``runtime.money`` (docs/decisions.md#d-01--money-is-integer-paise-everywhere).
"""

import ast
from collections.abc import Mapping
from decimal import Decimal, localcontext

__all__ = [
    "MAX_EXPRESSION_LENGTH",
    "MAX_NODES",
    "FormulaError",
    "evaluate",
    "operand_names",
    "parse",
]

#: Bounds on the expression itself. A formula is a handful of terms; anything
#: larger is a sign that something is being expressed here that should not be.
MAX_EXPRESSION_LENGTH = 512
MAX_NODES = 128

#: The whole grammar. ``ast.Load`` is here because every ``Name`` in an
#: expression carries one; it is not a construct a formula can write.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.UAdd,
    ast.USub,
)


class FormulaError(ValueError):
    """The expression is outside the grammar, or cannot be evaluated.

    Raised rather than returning a sentinel: a formula that will not evaluate
    means the metric it belongs to cannot be verified, and an unverifiable
    metric must never reach prose (Invariant 1).
    """


def parse(expression: str) -> ast.expr:
    """Parse and validate. Returns the expression body, or raises."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise FormulaError(
            f"expression is {len(expression)} characters, over the {MAX_EXPRESSION_LENGTH} limit"
        )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise FormulaError(f"not a valid arithmetic expression: {error.msg}") from error

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise FormulaError(f"expression has {len(nodes)} nodes, over the {MAX_NODES} limit")
    for node in nodes:
        _reject_unless_allowed(node)
    return tree.body


def _reject_unless_allowed(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        # ``True`` is an int to isinstance, and a literal boolean in an
        # arithmetic formula is always a mistake rather than the number 1.
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise FormulaError(
                f"only integer literals are allowed in a formula, got {node.value!r}"
            )
        return
    if not isinstance(node, _ALLOWED_NODES):
        raise FormulaError(
            f"{type(node).__name__} is not part of the formula grammar "
            "(named operands, integer literals, + - * / and parentheses)"
        )


def operand_names(expression: str) -> frozenset[str]:
    """Every operand the expression reads."""
    return frozenset(node.id for node in ast.walk(parse(expression)) if isinstance(node, ast.Name))


def evaluate(expression: str, operands: Mapping[str, int | Decimal]) -> Decimal:
    """Evaluate exactly. The result is unrounded, by design.

    Every name in the expression must be supplied. An unsupplied operand is an
    error and never a zero: a formula quietly evaluated with a missing term is
    exactly the failure mode layer 4 exists to catch.

    >>> evaluate("gross - refunds - fees - chargebacks",
    ...          {"gross": 40626000, "refunds": 1178200, "fees": 260805, "chargebacks": 174700})
    Decimal('39012295')
    """
    body = parse(expression)
    missing = sorted(operand_names(expression) - set(operands))
    if missing:
        raise FormulaError(f"operand(s) not supplied: {', '.join(missing)}")
    with localcontext() as context:
        context.prec = 60
        return _evaluate(body, operands)


def _evaluate(node: ast.expr, operands: Mapping[str, int | Decimal]) -> Decimal:
    if isinstance(node, ast.Constant):
        # ``parse`` already rejected non-integer literals. Re-checked here so
        # the narrowing is real rather than an assumption about a caller.
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise FormulaError(f"only integer literals are allowed, got {node.value!r}")
        return Decimal(node.value)
    if isinstance(node, ast.Name):
        return _as_decimal(operands[node.id], node.id)
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, operands)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        return _apply(node.op, _evaluate(node.left, operands), _evaluate(node.right, operands))
    raise FormulaError(f"{type(node).__name__} is not part of the formula grammar")


def _apply(op: ast.operator, left: Decimal, right: Decimal) -> Decimal:
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if right == 0:
        # Never an infinity, never a NaN. A zero denominator is a caller error
        # in exactly the sense runtime.money.ZeroDenominatorError means it.
        raise FormulaError("division by zero in a formula")
    return left / right


def _as_decimal(value: int | Decimal, name: str) -> Decimal:
    """Operands are ints (paise, counts) or Decimals (ratios). Never floats."""
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise FormulaError(f"operand {name!r} must be int or Decimal, got {type(value).__name__}")
    return Decimal(value)
