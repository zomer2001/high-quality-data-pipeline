"""Local OWL-RL projection with explicit, source-bound derivations. No model calls."""

import json
from datetime import date
from importlib.metadata import version
from itertools import combinations
from pathlib import Path
from urllib.parse import quote

import networkx as nx
from owlrl import DeductiveClosure, OWLRL_Semantics
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDFS

from searchos.knowledge_store.database import encode, now

from .ledger import assess, business_only, installed, load_claim, reviews, topic_id
from .ontology import Fact, load_ontology
from .registry import digest, policy_version

VERSION = "evidence-analysis-v1"
NS = Namespace("urn:widesearch:analysis:")


def policy():
    return (
        VERSION
        + ":"
        + digest(
            {
                "quality": policy_version(),
                "ontology": Path(__file__).with_name("analysis.ttl").read_text(),
                "engine": version("owlrl"),
            }
        )
    )


def node(identity):
    return URIRef("urn:widesearch:entity:" + quote(identity, safe=""))


def inputs(db, slug, as_of):
    topic = topic_id(db, slug)
    ids = [
        r[0]
        for r in db.execute(
            "SELECT c.id FROM claims c LEFT JOIN entity_relations r ON r.claim_id=c.id "
            "WHERE c.topic_id=? AND (c.claim_kind IN ('metric','capability') OR "
            "r.relation_type_id IN ('uses_technology','subtechnology_of')) ORDER BY c.id",
            (topic,),
        )
    ]
    records = [load_claim(db, identity, topic=topic) for identity in ids]
    review_state = {r["claim"]["id"]: reviews(db, r["claim"]["id"]) for r in records}
    entities = {
        r["id"]: dict(r)
        for r in db.execute(
            "SELECT e.id,e.kind,e.canonical_name,e.state FROM entities e "
            "JOIN topic_entities t ON t.entity_id=e.id WHERE t.topic_id=? ORDER BY e.id",
            (topic,),
        )
    }
    signature = digest(
        {
            "records": records,
            "reviews": review_state,
            "entities": entities,
            "as_of": as_of.isoformat(),
        }
    )
    return topic, records, entities, signature


def compute(db, slug, as_of):
    topic, records, entities, signature = inputs(db, slug, as_of)
    conclusions, eligible, assessments = [], [], {}

    def gap(record, reason, result=None):
        result = result or assessments.get(record["claim"]["id"], {})
        conclusions.append(
            {
                "kind": "evidence_gap",
                "rule_id": "evidence-sufficiency-v1",
                "status": "disputed" if result.get("outcome") == "disputed" else "unknown",
                "subject_id": record["claim"]["subject_id"],
                "reason": reason,
                "premise_ids": [record["claim"]["id"]],
                "review_ids": result.get("review_ids", []),
                "assessment": result,
            }
        )

    for record in records:
        claim = record["claim"]
        if claim["status"] != "accepted" or claim["subject_id"] not in entities:
            continue
        result = assess(db, record)
        assessments[claim["id"]] = result
        if result["outcome"] != "pass":
            gap(record, result["reason"], result)
            continue
        fact = Fact.model_validate(result["fact"])
        if not fact.context.valid_from or not fact.context.valid_to:
            gap(record, "缺少可用于分析的有效时间", result)
            continue
        if not fact.context.valid_from <= as_of <= fact.context.valid_to:
            gap(record, "证据有效时间未覆盖查询日期", result)
            continue
        if fact.kind != "relation":
            continue
        target = entities.get(str(fact.value))
        if not target or target["state"] != "active":
            gap(record, "关系目标不在专题的当前对象中", result)
            continue
        eligible.append((record, fact, result))

    taxonomy = nx.DiGraph()
    edge_proofs = {}
    for record, fact, result in eligible:
        if fact.predicate == "subtechnology_of":
            taxonomy.add_edge(fact.subject_id, str(fact.value))
            edge_proofs.setdefault((fact.subject_id, str(fact.value)), (record, fact, result))
    cyclic = set()
    for component in nx.strongly_connected_components(taxonomy):
        if len(component) > 1 or any(taxonomy.has_edge(n, n) for n in component):
            cyclic.update(component)
    for record, fact, result in eligible:
        if fact.predicate == "subtechnology_of" and (
            fact.subject_id in cyclic or fact.value in cyclic
        ):
            gap(record, "技术分类存在环，相关路径暂停推导", result)
    taxonomy.remove_nodes_from(cyclic)

    graph = Graph().parse(Path(__file__).with_name("analysis.ttl"), format="turtle")
    for child, parent in taxonomy.edges:
        graph.add((node(child), RDFS.subClassOf, node(parent)))
    products = []
    for record, fact, result in eligible:
        if fact.predicate == "uses_technology" and entities[fact.subject_id]["kind"] == "product":
            products.append((record, fact, result))
            graph.add((node(fact.subject_id), NS.usesTechnology, node(str(fact.value))))
    DeductiveClosure(OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False).expand(graph)

    def proof(items):
        return {
            "premise_ids": sorted({r["claim"]["id"] for r, _, _ in items}),
            "review_ids": sorted({i for _, _, a in items for i in a["review_ids"]}),
            "premises": [
                {
                    "claim_id": r["claim"]["id"],
                    "context": f.context.model_dump(mode="json"),
                    "evidence": [
                        {
                            "id": e["id"],
                            "revision_id": e["revision_id"],
                            "quote": e["quote"],
                            "locator": e["locator"],
                        }
                        for e in r["evidence"]
                        if e["id"] in a["evidence_ids"]
                    ],
                    "review_ids": a["review_ids"],
                    "origins": a.get("origins", []),
                    "review_provenance": a["review_provenance"],
                }
                for r, f, a in items
            ],
        }

    uses = {}
    for record, fact, result in products:
        leaf = str(fact.value)
        targets = {leaf} | (nx.descendants(taxonomy, leaf) if leaf in taxonomy else set())
        for target in sorted(targets):
            if (node(fact.subject_id), NS.usesTechnology, node(target)) not in graph:
                continue
            path = nx.shortest_path(taxonomy, leaf, target) if target != leaf else [leaf]
            items = [(record, fact, result)] + [edge_proofs[a, b] for a, b in zip(path, path[1:])]
            data = proof(items)
            # Keep one witness per pair; another path can replace it on recompute.
            uses.setdefault(target, {}).setdefault(fact.subject_id, data)
            if target != leaf:
                conclusions.append(
                    {
                        "kind": "technology_ancestry",
                        "rule_id": "uses-ancestor-v1",
                        "status": "derived",
                        "subject_id": fact.subject_id,
                        "object_id": target,
                        "technology_id": target,
                        "path": path,
                        "derived_relation": "uses_technology",
                        **data,
                    }
                )
    for technology, product_proofs in sorted(uses.items()):
        for left, right in combinations(sorted(product_proofs), 2):
            a, b = product_proofs[left], product_proofs[right]
            conclusions.append(
                {
                    "kind": "shared_technology",
                    "rule_id": "shared-technology-v1",
                    "status": "derived",
                    "subject_id": left,
                    "object_id": right,
                    "technology_id": technology,
                    "premise_ids": sorted(set(a["premise_ids"] + b["premise_ids"])),
                    "review_ids": sorted(set(a["review_ids"] + b["review_ids"])),
                    "premises": a["premises"] + b["premises"],
                    "meaning": "在所列版本、条件和证据性质下有共同技术记录；不表示性能相同",
                }
            )
    current_policy = policy()
    run_id = "qrun:" + digest([topic, as_of.isoformat(), signature, current_policy])
    for item in conclusions:
        item["id"] = "qconclusion:" + digest([run_id, item])
        item["labels"] = {
            k: entities[v]["canonical_name"]
            for k, v in item.items()
            if k in {"subject_id", "object_id", "technology_id"} and v in entities
        }
    return {
        "run_id": run_id,
        "topic_id": topic,
        "slug": slug,
        "as_of": as_of.isoformat(),
        "input_digest": signature,
        "policy": current_policy,
        "rules_snapshot": {
            "engine": "OWL-RL",
            "engine_version": version("owlrl"),
            "projection": Path(__file__).with_name("analysis.ttl").read_text(),
            "evidence_ontology": load_ontology().model_dump(),
        },
        "conclusions": conclusions,
        "counts": {
            "inspected_claims": len(records),
            "reviewed_usable": sum(a["outcome"] == "pass" for a in assessments.values()),
            "derived": sum(c["status"] == "derived" for c in conclusions),
            "gaps": sum(c["kind"] == "evidence_gap" for c in conclusions),
        },
        "model_calls": 0,
        "scope": "采用技术、技术上下位、指标和功能记录",
        "persisted": False,
    }


def analyze(store, slug, *, as_of=None, persist=False):
    business_only(store)
    as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of or date.today()
    with store.connect(write=persist) as db:
        if not persist:
            db.execute("BEGIN")
        if persist and not installed(db):
            raise ValueError("请先安装核验台账扩展")
        result = compute(db, slug, as_of)
        if persist:
            db.execute(
                "INSERT OR IGNORE INTO quality_analysis_runs VALUES(?,?,?,?,?,?,?)",
                (
                    result["run_id"],
                    result["topic_id"],
                    result["as_of"],
                    result["input_digest"],
                    result["policy"],
                    encode({k: v for k, v in result.items() if k != "conclusions"}),
                    now(),
                ),
            )
            for item in result["conclusions"]:
                db.execute(
                    "INSERT OR IGNORE INTO quality_conclusions VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        item["id"],
                        result["run_id"],
                        item["rule_id"],
                        item["kind"],
                        item["status"],
                        item.get("subject_id"),
                        item.get("object_id"),
                        item.get("technology_id"),
                        encode(item),
                    ),
                )
                for identity in item["premise_ids"]:
                    matching = [
                        r[0]
                        for r in db.execute(
                            "SELECT id FROM quality_evidence_reviews WHERE claim_id=?", (identity,)
                        )
                        if r[0] in item["review_ids"]
                    ] or [""]
                    db.executemany(
                        "INSERT OR IGNORE INTO quality_conclusion_premises VALUES(?,?,?)",
                        [(item["id"], identity, review) for review in matching],
                    )
            result["persisted"] = True
        return result


def read_run(store, slug, identity):
    business_only(store)
    with store.connect() as db:
        db.execute("BEGIN")
        if not installed(db):
            raise ValueError("分析记录不存在")
        row = db.execute(
            "SELECT * FROM quality_analysis_runs WHERE id=? AND topic_id=?",
            (identity, topic_id(db, slug)),
        ).fetchone()
        if not row:
            raise ValueError("分析记录不存在或不属于当前专题")
        result = json.loads(row["summary_json"])
        _, _, _, current_digest = inputs(db, slug, date.fromisoformat(row["as_of"]))
        stale = current_digest != row["input_digest"] or policy() != row["policy"]
        result.update(
            persisted=True,
            stale=stale,
            usable=not stale,
            conclusions=[
                {**json.loads(r[0]), "current_status": "stale" if stale else "current"}
                for r in db.execute(
                    "SELECT payload_json FROM quality_conclusions WHERE run_id=? ORDER BY id",
                    (identity,),
                )
            ],
        )
        return result
