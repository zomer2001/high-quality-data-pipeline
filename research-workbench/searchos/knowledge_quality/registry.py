"""Freeze the existing field catalog; it remains the single schema authority."""

import hashlib
import json

VERSION = "quality-c1"
RULES = {
    "quote_anchor": "Exact spans in the supplied source revision; ambiguity retained",
    "metric_literal": "Check explicit numeric quantities without inferring their subject",
    "conditions": "Unspecified conditions never establish comparability",
    "semantics": "Semantic entailment and independent corroboration require review",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def policy_version():
    from .ontology import load_ontology

    return VERSION + ":" + digest({"basic_checks": RULES, "ontology": load_ontology().model_dump()})


def release(db):
    from .ontology import load_ontology

    snapshot = {
        "policy": policy_version(),
        "rules": RULES,
        "ontology": load_ontology().model_dump(),
        "fields": [dict(r) for r in db.execute("SELECT * FROM field_definitions ORDER BY id")],
        "mappings": [
            dict(r) for r in db.execute("SELECT * FROM field_storage_mappings ORDER BY field_id")
        ],
        "relations": [dict(r) for r in db.execute("SELECT * FROM relation_types ORDER BY id")],
    }
    return {"id": digest(snapshot), "snapshot": snapshot}
