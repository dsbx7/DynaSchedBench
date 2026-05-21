from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence


Number = float


@dataclass
class _ConstNode:
    value: float

    def eval(self, attrs: Dict[str, float]) -> float:
        return float(self.value)


@dataclass
class _AttrNode:
    name: str

    def eval(self, attrs: Dict[str, float]) -> float:
        return float(attrs.get(self.name, 0.0))


@dataclass
class _OpNode:
    op: str
    children: Sequence["_Node"]

    def eval(self, attrs: Dict[str, float]) -> float:
        op = self.op
        if op == "if":
            cond = self.children[0].eval(attrs)
            if cond > 0.0:
                return self.children[1].eval(attrs)
            return self.children[2].eval(attrs)

        if len(self.children) != 2:
            # Defensive: unsupported arity, fall back to 0
            return 0.0

        a = self.children[0].eval(attrs)
        b = self.children[1].eval(attrs)

        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            # Protected division: when denominator == 0, return 1 (follow Java Div.java)
            return 1.0 if b == 0.0 else a / b
        if op == "max":
            return a if a >= b else b
        if op == "min":
            return a if a <= b else b

        # Unknown operator: treat as 0
        return 0.0


_Node = _ConstNode | _AttrNode | _OpNode


class LispRule:
    """Lightweight evaluator for GP Lisp rules.

    The syntax is aligned with yimei.util.lisp.LispParser:
    - Binary operators: +, -, *, /, max, min
    - Ternary operator: if
    - Terminals: numeric literals, attribute names (e.g. PT, WKR, SL, t)
    """

    def __init__(self, root: _Node, source: str) -> None:
        self._root = root
        self._source = source

    @property
    def source(self) -> str:
        return self._source

    def evaluate(self, attrs: Dict[str, float]) -> float:
        """Evaluate the rule given a mapping of attribute name -> value."""

        try:
            return float(self._root.eval(attrs))
        except Exception:
            # Defensive: never let a single candidate crash the agent
            return 0.0

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @classmethod
    def from_lisp(cls, expression: str) -> "LispRule":
        expr = expression.strip()
        tokens = _tokenize(expr)
        if not tokens:
            raise ValueError("Empty Lisp expression")
        node, next_pos = _parse_expr(tokens, 0)
        if next_pos != len(tokens):
            # Ignore trailing tokens but keep behaviour defined
            pass
        return cls(node, expression)


def _tokenize(expr: str) -> List[str]:
    # Insert spaces around parentheses and split by whitespace
    spaced = expr.replace("(", " ( ").replace(")", " ) ")
    return [t for t in spaced.split() if t]


def _parse_expr(tokens: List[str], pos: int) -> tuple[_Node, int]:
    if pos >= len(tokens):
        raise ValueError("Unexpected end of tokens while parsing Lisp expression")

    tok = tokens[pos]
    if tok == "(":
        if pos + 1 >= len(tokens):
            raise ValueError("Malformed Lisp expression: missing operator after '('")
        op = tokens[pos + 1]
        children: List[_Node] = []
        idx = pos + 2
        while idx < len(tokens) and tokens[idx] != ")":
            child, idx = _parse_expr(tokens, idx)
            children.append(child)
        if idx >= len(tokens) or tokens[idx] != ")":
            raise ValueError("Malformed Lisp expression: missing closing ')'")
        node: _Node = _OpNode(op=op, children=tuple(children))
        return node, idx + 1

    if tok == ")":
        raise ValueError("Unexpected ')' while parsing Lisp expression")

    # Atom: either number or attribute name
    try:
        value = float(tok)
        node = _ConstNode(value=value)
    except ValueError:
        node = _AttrNode(name=tok)
    return node, pos + 1
