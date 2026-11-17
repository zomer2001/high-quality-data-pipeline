"""Normalize existing database details without importing the web application."""

import json

from .ontology import Context, Fact
from .reasoning import condition_map


def context_from(qualifiers, detail):
    explicit = qualifiers.get("ontology_context")
    if explicit is not None:
        if not isinstance(explicit, dict):
            raise ValueError("ontology_context 必须是明确的条件对象")
        context = Context.model_validate(explicit)
    else:
        # Preserve legacy qualifiers elsewhere; do not invent missing temporal roles.
        values = {k: qualifiers[k] for k in Context.model_fields if k in qualifiers}
        if "conditions" not in values:
            conditions = qualifiers.get("condition") or qualifiers.get("test_conditions")
            if conditions:
                values["conditions"] = conditions
        if isinstance(values.get("conditions"), str):
            values["conditions"] = {"source_text": values["conditions"]}
        if "statistic" not in values and detail.get("statistic") not in (None, "unspecified"):
            values["statistic"] = detail["statistic"]
        context = Context.model_validate(values)
    condition_map(context.conditions)  # Reject conflicting aliases, without rewriting raw text.
    return context


def as_fact(subject, kind, detail, qualifiers, fields, *, identity=""):
    if kind not in {"metric", "capability", "field", "relation", "event"}:
        return None
    context = context_from(qualifiers, detail)
    predicate, value, cardinality, operator, unit = kind, None, "unknown", "=", None
    if kind == "metric":
        predicate, value, unit = (
            detail["metric_id"],
            detail.get("numeric_value"),
            detail.get("raw_unit"),
        )
        operator = detail.get("comparator") or "="
        if (
            value is None
            and detail.get("min_value") is not None
            and detail.get("max_value") is not None
        ):
            value = [detail["min_value"], detail["max_value"]]
            if operator == "=":
                operator = "range"
        cardinality = "one"
    elif kind == "capability":
        predicate, value, cardinality = detail["capability_id"], detail["support_status"], "one"
    elif kind == "field":
        predicate, value = detail["field_id"], json.loads(detail["value_json"])
        value_type = fields.get(predicate, {}).get("value_type", "text")
        if value_type in {"boolean", "number", "integer", "enum"}:
            cardinality = "one"
        elif value_type.endswith("_list"):
            cardinality = "many"
    elif kind == "relation":
        predicate, value, cardinality = detail["relation_type_id"], detail["object_id"], "many"
    elif kind == "event":
        predicate, value = "event:" + detail.get("description", ""), detail.get("occurred_at")
    return Fact(
        id=identity,
        subject_id=subject,
        kind=kind,
        predicate=predicate,
        value=value,
        unit=unit,
        operator=operator,
        context=context,
        cardinality=cardinality,
    )
