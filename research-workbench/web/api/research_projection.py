"""Adapt the published business database to the existing topic workspace UI."""

from collections import defaultdict

from api.research_assets import _connections
from api.research_database import snapshot


def topic_knowledge(store, slug):
    data = snapshot(store, slug, accepted_only=True, limit=None)
    by_entity, evidence = defaultdict(list), {}
    for record in data["records"]:
        by_entity[record["entity_id"]].append(record)
        for item in record["evidence"]:
            evidence[item["id"]] = {
                **item,
                "excerpt": item["quote"],
                "ref_id": "",
                "source_revision": item["revision_id"],
            }
    entities, fields = [], {}
    claim_evidence = {r["id"]: [e["id"] for e in r["evidence"]] for r in data["records"]}
    with store.connect() as db:
        aliases = defaultdict(list)
        for row in db.execute(
            "SELECT entity_id,name FROM entity_names WHERE valid_to IS NULL AND name_type<>'former'"
        ):
            aliases[row["entity_id"]].append(row["name"])
        relations = [
            {
                "id": r["claim_id"],
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "origin": "archive",
                "relation": r["predicate"],
                "predicate": r["predicate"],
                "status": "source_backed",
                "label": r["label"],
                "evidence_ids": claim_evidence.get(r["claim_id"], []),
            }
            for r in _connections(db, slug)
        ]
    for entity in data["entities"]:
        if entity["kind"] not in {"product", "technology", "route", "reference"}:
            continue
        rows = by_entity[entity["id"]]
        attrs = {"aliases": aliases[entity["id"]]}
        entities.append(
            {
                "id": entity["id"],
                "name": entity["canonical_name"],
                "kind": entity["kind"],
                "namespace": entity["namespace"],
                "attributes": attrs,
                "evidence_ids": list({ev["id"] for r in rows for ev in r["evidence"]}),
                "origin": "research_database",
                "status": "source_backed",
                "category": "",
                "summary": "",
            }
        )
        # Keep each observation and its conditions; do not synthesize empty legacy columns.
        grouped = {}
        for r in rows:
            if r["kind"] == "identity":
                continue
            field_key = r["field_id"] or r["kind"] + ":" + r["label"]
            field = grouped.setdefault(
                field_key,
                {
                    "key": field_key,
                    "label": r["label"],
                    "status": "known",
                    "value": r["value"],
                    "type": "text",
                    "group": "已入库字段",
                    "evidence_ids": [],
                    "source_keys": [],
                    "manual": False,
                    "observations": [],
                },
            )
            ids = [ev["id"] for ev in r["evidence"]]
            field["evidence_ids"].extend(ids)
            field["source_keys"].append(r["id"])
            field["observations"].append(
                {
                    "value": r["value"],
                    "manual": False,
                    "status": "known",
                    "source_key": r["id"],
                    "evidence_ids": ids,
                    "context": r["qualifiers"],
                }
            )
        fields[entity["id"]] = list(grouped.values())
        # Include record IDs, values and conditions in the existing change fingerprint.
        attrs["published_records"] = [
            {"id": r["id"], "value": r["value"], "conditions": r["qualifiers"]} for r in rows
        ]
    return {
        "entities": entities,
        "relations": relations,
        "evidence": list(evidence.values()),
        "entity_fields": fields,
        "gaps": [],
        "source": "research_database",
    }
