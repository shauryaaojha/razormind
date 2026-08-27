"""The restricted arithmetic interpreter.

Layer 4 of verification re-evaluates a tool's declared formula and demands the
same number back. That check is only worth something if the formula language is
too weak to *be* the tool -- a grammar that can call a function can call the
tool again, and layer 4 degrades into re-running the code under suspicion.

So most of this file is about what does **not** parse.
"""

from decimal import Decimal

import pytest

from evidence.formula import (
    MAX_EXPRESSION_LENGTH,
    MAX_NODES,
    FormulaError,
    evaluate,
    operand_names,
    parse,
)


class TestGrammar:
    """What a formula is allowed to be."""

    def test_the_bridge_identity(self) -> None:
        assert evaluate(
            "gross - refunds - fees - chargebacks",
            {"gross": 40626000, "refunds": 1178200, "fees": 260805, "chargebacks": 174700},
        ) == Decimal(39012295)

    def test_parentheses_and_precedence(self) -> None:
        assert evaluate("(a + b) * c", {"a": 2, "b": 3, "c": 4}) == Decimal(20)
        assert evaluate("a + b * c", {"a": 2, "b": 3, "c": 4}) == Decimal(14)

    def test_unary_minus_and_plus(self) -> None:
        assert evaluate("-a", {"a": 7}) == Decimal(-7)
        assert evaluate("+a", {"a": 7}) == Decimal(7)

    def test_integer_literals(self) -> None:
        assert evaluate("a * 2 - 1", {"a": 21}) == Decimal(41)

    def test_decimal_operands_stay_exact(self) -> None:
        """A ratio operand is a Decimal, and must not round-trip through a float."""
        result = evaluate("rate * amount", {"rate": Decimal("0.006420"), "amount": 40626000})
        assert result == Decimal("260818.92000")

    def test_division_produces_an_unrounded_ratio(self) -> None:
        """The interpreter never rounds. Rounding is one step, in runtime.money."""
        exact = evaluate("current / prior", {"current": 1, "prior": 3})
        assert str(exact).startswith("0.3333333333")

    def test_operand_names_are_reported(self) -> None:
        assert operand_names("(a + b) / a") == frozenset({"a", "b"})


class TestRejections:
    """The Phase 3 exit criterion: no imports, no attributes, no calls."""

    @pytest.mark.parametrize(
        "expression",
        [
            '__import__("os")',
            "open('/etc/passwd')",
            "a.b",
            "a.__class__",
            "a[0]",
            "a ** b",
            "a // b",
            "a % b",
            "lambda: 1",
            "[x for x in a]",
            "{a: b}",
            "a if b else c",
            "a and b",
            "not a",
            "a < b",
            "f(a)",
            "(a := 1)",
            "a, b",
        ],
    )
    def test_the_grammar_is_too_weak_to_do_anything_but_arithmetic(self, expression: str) -> None:
        with pytest.raises(FormulaError):
            evaluate(expression, {"a": 1, "b": 2, "c": 3, "f": 4, "x": 5})

    def test_a_bare_dunder_name_is_an_undeclared_operand_not_a_builtin(self) -> None:
        """``__import__`` parses as a Name and then fails for want of a value.

        It never resolves to the builtin, because the interpreter reads operands
        out of the supplied mapping and has no globals of any kind.
        """
        with pytest.raises(FormulaError, match="not supplied"):
            evaluate("__import__", {"a": 1})

    def test_float_literals_are_refused(self) -> None:
        """C-01: a float in a money path is the defect, not a convenience."""
        with pytest.raises(FormulaError, match="integer literals"):
            evaluate("a * 1.5", {"a": 2})

    def test_boolean_literals_are_refused(self) -> None:
        """``True`` is an int to isinstance, and never means the number 1 here."""
        with pytest.raises(FormulaError, match="integer literals"):
            evaluate("a * True", {"a": 2})

    def test_a_float_operand_is_refused(self) -> None:
        with pytest.raises(FormulaError, match="must be int or Decimal"):
            evaluate("a + b", {"a": 1, "b": 2.5})  # type: ignore[dict-item]

    def test_a_boolean_operand_is_refused(self) -> None:
        with pytest.raises(FormulaError, match="must be int or Decimal"):
            evaluate("a + b", {"a": 1, "b": True})

    def test_syntax_errors_are_formula_errors(self) -> None:
        with pytest.raises(FormulaError, match="not a valid arithmetic expression"):
            evaluate("a +", {"a": 1})

    def test_a_statement_is_not_an_expression(self) -> None:
        with pytest.raises(FormulaError):
            evaluate("a = 1", {"a": 1})

    def test_division_by_zero_is_an_error_never_an_infinity(self) -> None:
        """A zero denominator is a caller error, never a NaN that renders as a number."""
        with pytest.raises(FormulaError, match="division by zero"):
            evaluate("a / b", {"a": 1, "b": 0})

    def test_a_missing_operand_is_never_a_zero(self) -> None:
        """Invariant 6: incomplete input is an explicit failure, not an invented zero."""
        with pytest.raises(FormulaError, match="not supplied"):
            evaluate("gross - refunds", {"gross": 100})

    def test_an_overlong_expression_is_refused(self) -> None:
        with pytest.raises(FormulaError, match="over the"):
            parse("a + " * (MAX_EXPRESSION_LENGTH // 2) + "a")

    def test_an_expression_with_too_many_nodes_is_refused(self) -> None:
        with pytest.raises(FormulaError, match="nodes"):
            parse("+".join(["a"] * MAX_NODES))
