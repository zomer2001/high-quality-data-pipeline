"""Source-bound checks, deliberately distinct from proving a real-world fact."""

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

from .registry import policy_version


class Check(BaseModel):
    rule: str
    result: Literal["pass", "fail", "unknown", "not_applicable"]
    reason: str


@lru_cache(maxsize=1)
def units():
    from pint import UnitRegistry

    return UnitRegistry()


def equivalent(left, left_unit, right, right_unit):
    from pint.errors import PintError

    # Logarithmic levels and ratios require domain-specific comparison policies.
    if (
        not left_unit
        or not right_unit
        or any(str(u).casefold().startswith("db") or "%" in str(u) for u in (left_unit, right_unit))
    ):
        return None
    try:
        value = units().Quantity(float(left), left_unit).to(right_unit).magnitude
        return abs(value - float(right)) <= max(abs(value), abs(float(right)), 1) * 1e-9
    except (ValueError, TypeError, LookupError, PintError):
        return None


NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def verify(text, revision, kind, detail, quotes, qualifiers):
    checks, anchors = [], []
    for quote in quotes:
        starts = [m.start() for m in re.finditer(re.escape(quote), text)] if quote else []
        checks.append(
            Check(
                rule="quote_anchor",
                result="pass" if starts else "fail",
                reason="引文已定位；多处出现时保留全部位置" if starts else "当前正文没有该引文",
            )
        )
        anchors.extend(
            {
                "revision_id": revision,
                "start": start,
                "end": start + len(quote),
                "quote": quote,
                "ambiguous": len(starts) > 1,
            }
            for start in starts
        )
    if kind == "metric":
        raw_unit = detail.get("raw_unit")
        numbers = [detail.get(k) for k in ("numeric_value", "min_value", "max_value")]
        for number in (n for n in numbers if n is not None):
            found = any(
                float(m.group()) == float(number) for q in quotes for m in re.finditer(NUMBER, q)
            )
            converted = False
            if not found and raw_unit:
                for q in quotes:
                    for m in re.finditer(r"(" + NUMBER + r")\s*([A-Za-zµμ]+)\b", q):
                        if equivalent(m[1], m[2], number, raw_unit):
                            converted = True
            # Only a clearly conflicting single same-unit value is a deterministic failure.
            same_unit = [
                float(m[1])
                for q in quotes
                for m in re.finditer(
                    r"(" + NUMBER + r")\s*" + re.escape(raw_unit or "__no_unit__") + r"(?!\w)", q
                )
            ]
            if len(same_unit) == 1 and same_unit[0] != float(number) and not converted:
                result = "fail"
            else:
                result = "pass" if found or converted else "unknown"
            checks.append(
                Check(
                    rule="metric_literal",
                    result=result,
                    reason="数值或等价单位值在引文中；对象和工况仍需核对"
                    if result == "pass"
                    else "候选数值与引文中的唯一同单位数值不符"
                    if result == "fail"
                    else "无法从引文确定数值对应关系",
                )
            )
    checks.append(
        Check(
            rule="conditions",
            result="unknown",
            reason="条件已保留，尚未完成原文语义核对" if qualifiers else "原文适用条件尚未明确",
        )
    )
    checks.append(
        Check(
            rule="semantics",
            result="unknown",
            reason="已检查结构与引文；语义、对象绑定和独立证据尚待核验",
        )
    )
    return {
        "policy": policy_version(),
        "status": "blocked" if any(c.result == "fail" for c in checks) else "needs_review",
        "assertion_type": "source_statement",
        "checks": [c.model_dump() for c in checks],
        "anchors": anchors,
        "conditions": qualifiers,
        "model_calls": 0,
    }
