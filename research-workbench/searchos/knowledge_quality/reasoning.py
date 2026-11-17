"""Finite ontology operators. Results explain compatibility, not external truth."""

import json
import math
import re

from .checks import units
from .ontology import Evidence, Fact, load_ontology


def result(outcome, reason, **details):
    return {"outcome": outcome, "reason": reason, **details}


def canonical(value):
    """Normalize explicit quantities, keeping unknown text and structured values distinct."""
    from pint.errors import PintError

    quantity = None
    if isinstance(value, dict) and set(value) == {"value", "unit"}:
        quantity = value
    elif isinstance(value, str):
        match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*([a-zA-Zµμ°]+)\s*", value)
        if match:
            quantity = {"value": float(match[1]), "unit": match[2]}
    if quantity and not isinstance(quantity["value"], bool):
        try:
            raw_unit = str(quantity["unit"])
            if not raw_unit.lower().startswith("db"):
                converted = units().Quantity(float(quantity["value"]), raw_unit).to_base_units()
                if math.isfinite(converted.magnitude):
                    return [
                        "quantity",
                        float(format(converted.magnitude, ".15g")),
                        str(converted.units),
                    ]
        except (PintError, ValueError, TypeError):
            pass
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value.strip() if isinstance(value, str) else value


def condition_map(conditions):
    aliases = load_ontology().condition_aliases
    normalized = {}
    for key, value in conditions.items():
        key = aliases.get(key, key)
        if key in normalized and normalized[key] != canonical(value):
            raise ValueError("同一条件的不同名称给出了矛盾取值")
        normalized[key] = canonical(value)
    return normalized


def absent(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {
            "",
            "unknown",
            "unspecified",
            "未知",
            "未说明",
            "未公开",
        }
    if isinstance(value, dict):
        return not value or any(absent(v) for v in value.values())
    if isinstance(value, list):
        return not value or any(absent(v) for v in value)
    return False


def missing_context(fact):
    required = load_ontology().comparison_requirements.get(fact.kind, [])
    missing = [k for k in required if absent(getattr(fact.context, k))]
    for key, value in fact.context.conditions.items():
        if absent(value):
            missing.append("conditions." + key)
    return missing


def compare_scope(left, right):
    if (
        left.subject_id != right.subject_id
        or left.predicate != right.predicate
        or left.kind != right.kind
    ):
        return result("separate_object", "对象或属性不同，分别保留")
    a, b = left.context, right.context
    if a.event_id and b.event_id and a.event_id != b.event_id:
        return result("different_event", "事件身份不同，分别保留")
    if a.event_state and b.event_state and a.event_state != b.event_state:
        return result("unknown", "事件状态不同，需要单独核验状态变化依据")
    if not absent(a.version) and not absent(b.version) and a.version != b.version:
        return result("different_version", "型号版本不同，不直接冲突")
    if a.nature != "unspecified" and b.nature != "unspecified" and a.nature != b.nature:
        return result("different_nature", "声明、测量或推导性质不同，分别保留")
    ca, cb = condition_map(a.conditions), condition_map(b.conditions)
    if any(
        not absent(ca[k]) and not absent(cb[k]) and ca[k] != cb[k] for k in ca.keys() & cb.keys()
    ):
        return result("different_conditions", "已有明确不同工况，分别保留")
    if not absent(a.statistic) and not absent(b.statistic) and a.statistic != b.statistic:
        return result("different_conditions", "统计口径不同，分别保留")
    if all((a.valid_from, a.valid_to, b.valid_from, b.valid_to)):
        if a.valid_to < b.valid_from or b.valid_to < a.valid_from:
            return result("different_time", "有效时间不重叠；不据此推定发生了演化")
        if (a.valid_from, a.valid_to) != (b.valid_from, b.valid_to):
            return result("unknown", "有效时间部分重叠，需限定比较范围")
    missing = sorted(set(missing_context(left) + missing_context(right)))
    if missing or ca.keys() != cb.keys():
        return result("unknown", "比较条件不完整，不能将不同取值判为已确认冲突", missing=missing)
    return result("comparable", "对象、版本、工况、有效时间和事实性质一致")


def _interval(fact, target_unit):
    from pint.errors import PintError

    if fact.operator not in {"=", "range"}:
        return None
    values = fact.value if fact.operator == "range" else [fact.value, fact.value]
    if not isinstance(values, list) or len(values) != 2:
        return None
    if any(
        isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
        for v in values
    ):
        return None
    if values[0] > values[1] or not fact.unit or not target_unit:
        return None
    if fact.unit == target_unit:
        return values
    if fact.unit.lower().startswith("db") or target_unit.lower().startswith("db"):
        return None
    try:
        return [units().Quantity(v, fact.unit).to(target_unit).magnitude for v in values]
    except (PintError, ValueError, TypeError):
        return None


def compare(left: Fact, right: Fact):
    scope = compare_scope(left, right)
    if scope["outcome"] != "comparable":
        return scope
    if left.kind == "metric":
        a, b = _interval(left, left.unit), _interval(right, left.unit)
        if a is None or b is None:
            return result("unknown", "单位、区间或比较符尚不支持直接比较")
        # Significant digits remove floating-point conversion noise, not small quantities.
        a, b = [float(format(v, ".15g")) for v in a], [float(format(v, ".15g")) for v in b]
        if a == b:
            return result("equivalent", "归一后数值和范围相同")
        if max(a[0], b[0]) <= min(a[1], b[1]):
            return result("compatible_range", "数值范围存在交集，不能直接认定冲突")
        return result("different_value", "相同条件下数值范围不相交，需要核验证据", conflict_level=1)
    if json.dumps(canonical(left.value), sort_keys=True) == json.dumps(
        canonical(right.value), sort_keys=True
    ):
        return result("equivalent", "相同条件下取值相同")
    if left.cardinality == right.cardinality == "many":
        return result("coexisting", "多值属性或关系可以同时成立")
    if left.cardinality == right.cardinality == "one":
        return result(
            "different_value", "相同条件下单值属性存在差异，需要核验证据", conflict_level=1
        )
    return result("unknown", "取值不同，但尚未规定该属性是否只能有一个值")


def evidence_check(fact: Fact, evidence: list[Evidence], requirement=None):
    requirement = requirement or fact.context.nature
    rule = load_ontology().evidence_requirements.get(requirement)
    if rule is None:
        return result("unknown", "该事实类型尚未配置完整证据要求", origins=[], usable=[])
    usable, origins, opposing = [], set(), []
    for ev in evidence:
        if not fact.id or ev.fact_id != fact.id:
            continue
        if not ev.scope_verified or not ev.origin_verified or not ev.origin_id:
            continue
        if ev.directness != "direct" or ev.kind not in rule.kinds:
            continue
        proxy = fact.model_copy(
            update={"subject_id": ev.subject_id, "predicate": ev.predicate, "context": ev.context}
        )
        if compare_scope(fact, proxy)["outcome"] != "comparable":
            continue
        if requirement == "event_completed" and (
            not fact.context.event_id
            or ev.context.event_id != fact.context.event_id
            or ev.context.event_state != "completed"
        ):
            continue
        if ev.stance == "refutes":
            opposing.append(ev.id)
        elif ev.stance == "supports":
            usable.append(ev.id)
            origins.add(ev.origin_id)
    if opposing and usable:
        return result(
            "disputed",
            "合格直接证据仍然相反，保留争议",
            usable=usable,
            opposing=opposing,
            origins=sorted(origins),
        )
    if opposing:
        return result(
            "unknown",
            "存在反证，需要核验并登记争议或撤回依据",
            usable=[],
            opposing=opposing,
            origins=[],
        )
    if len(origins) < rule.independent_origins:
        return result(
            "unknown",
            "尚未满足证据类型、适用范围或独立形成来源要求",
            usable=usable,
            origins=sorted(origins),
            required_origins=rule.independent_origins,
        )
    return result(
        "pass",
        "满足本版规则及已核验的证据要求；结论限于所标事实性质",
        usable=usable,
        origins=sorted(origins),
    )


def transition(previous: Fact, current: Fact, evidence: list[Evidence]):
    if previous.kind != "event" or current.kind != "event":
        return result("unknown", "该规则只适用于事件状态变化")
    if previous.subject_id != current.subject_id or previous.predicate != current.predicate:
        return result("unknown", "状态变化必须属于同一对象和事件属性")
    if not previous.context.event_id or previous.context.event_id != current.context.event_id:
        return result("unknown", "尚未确认是同一个事件")
    if previous.context.version != current.context.version or not current.context.version:
        return result("unknown", "状态变化的型号版本尚未对齐")
    if (
        previous.context.event_state not in {"planned", "underway"}
        or current.context.event_state != "completed"
    ):
        return result("unknown", "该状态转换尚未配置规则")
    if not current.context.valid_from or not current.context.valid_to:
        return result("unknown", "缺少实际发生时间；发布时间不能代替")
    if not previous.context.valid_from or current.context.valid_from < previous.context.valid_from:
        return result("unknown", "状态有效时间次序尚未成立")
    if condition_map(previous.context.conditions) != condition_map(current.context.conditions):
        return result("unknown", "事件成立条件尚未对齐")
    return evidence_check(current, evidence, requirement="event_completed")


def classification_path(child, parent, edges):
    """Only explicit subtype edges; no inference from a product to an implementation."""
    import networkx as nx

    graph = nx.DiGraph()
    graph.add_edges_from(
        (e["child"], e["parent"]) for e in edges if e.get("relation") == "subtype_of"
    )
    if not nx.is_directed_acyclic_graph(graph):
        return result("unknown", "分类关系存在环，需要先修订分类")
    if child in graph and parent in graph and nx.has_path(graph, child, parent):
        return result(
            "pass",
            "仅证明已有分类路径，不证明产品采用任何具体实现",
            path=nx.shortest_path(graph, child, parent),
        )
    return result("unknown", "缺少明确分类路径")
