"""Append-only, explicitly reviewed evidence. Extraction metadata cannot approve itself."""

import json
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import Field

from searchos.knowledge_store.database import DETAIL_TABLES, encode, now

from .facts import as_fact
from .ontology import Context, Evidence, Fact, Strict
from .reasoning import evidence_check, missing_context
from .registry import digest

EXPERIMENT_DIRS = {
    "widesearch_experiment",
    "widesearch_baselines",
    "widesearch_odr_lite",
    "widesearch_recovery",
    "widesearch_fetch_backup",
}


def business_only(store):
    if EXPERIMENT_DIRS.intersection(store.path.resolve().parts):
        raise ValueError("实验库不能接入业务核验与分析")


def installed(db):
    return bool(
        db.execute("SELECT 1 FROM sqlite_master WHERE name='quality_evidence_reviews'").fetchone()
    )


def install(store):
    business_only(store)
    sql = Path(__file__).with_name("ledger.sql").read_text()
    signature = digest(sql)
    with store.connect(write=True) as db:
        old = db.execute(
            "SELECT value FROM database_metadata WHERE key='quality_ledger_schema'"
        ).fetchone()
        if old and old[0] != signature:
            raise ValueError("核验台账结构已变化，需要显式迁移")
        statement = ""
        for line in sql.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ""
        db.execute(
            "INSERT OR IGNORE INTO database_metadata VALUES('quality_ledger_schema',?)",
            (signature,),
        )


class ReviewInput(Strict):
    claim_id: str = Field(min_length=1)
    evidence_id: str = Field(min_length=1)
    expected_claim_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1)
    note: str = Field(min_length=1)
    kind: str = "unknown"
    directness: Literal["direct", "attributed", "untraced"] = "untraced"
    origin_revision_id: str | None = None
    scope_verified: bool = False
    origin_verified: bool = False
    context: Context | None = None


def topic_id(db, slug):
    row = db.execute("SELECT id FROM topics WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise ValueError("专题不存在")
    return row[0]


def load_claim(db, identity, *, topic=None):
    row = db.execute(
        "SELECT c.*,e.kind AS subject_kind,e.canonical_name,e.state AS entity_state "
        "FROM claims c JOIN entities e ON e.id=c.subject_id WHERE c.id=?",
        (identity,),
    ).fetchone()
    if not row or topic and row["topic_id"] != topic:
        raise ValueError("事实不存在或不属于当前专题")
    claim = dict(row)
    detail = dict(
        db.execute(
            f'SELECT * FROM "{DETAIL_TABLES[row["claim_kind"]]}" WHERE claim_id=?', (identity,)
        ).fetchone()
    )
    fields = {}
    if row["claim_kind"] == "field":
        fields = {
            detail["field_id"]: dict(
                db.execute(
                    "SELECT * FROM field_definitions WHERE id=?", (detail["field_id"],)
                ).fetchone()
            )
        }
    error = None
    try:
        fact = as_fact(
            row["subject_id"],
            row["claim_kind"],
            detail,
            json.loads(row["scope_note"] or "{}"),
            fields,
            identity=identity,
        )
    except ValueError as exc:
        fact, error = None, str(exc)
    evidence = []
    for item in db.execute(
        "SELECT e.*,s.revision_id,s.locator,s.text_content,r.content_sha256 "
        "FROM claim_evidence e JOIN source_segments s ON s.id=e.segment_id "
        "JOIN source_revisions r ON r.id=s.revision_id WHERE e.claim_id=? ORDER BY e.id",
        (identity,),
    ):
        item = dict(item)
        text = item.pop("text_content")
        item["anchor_valid"] = bool(item["quote"] and item["quote"] in text)
        item["segment_digest"] = digest(text)
        evidence.append(item)
    base = {"claim": claim, "detail": detail, "evidence": evidence}
    return {
        **base,
        "claim_digest": digest(base),
        "fact": fact.model_dump(mode="json") if fact else None,
        "normalization_error": error,
    }


def reviews(db, identity):
    if not installed(db):
        return []
    rows = db.execute(
        "SELECT r.*,w.review_id AS withdrawn FROM quality_evidence_reviews r "
        "LEFT JOIN quality_review_withdrawals w ON w.review_id=r.id "
        "WHERE r.claim_id=? ORDER BY r.created_at,r.id",
        (identity,),
    )
    return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]


def assess(db, record):
    raw = record["fact"]
    if raw is None:
        return {
            "outcome": "unknown",
            "reason": "当前记录尚不能转为可计算事实",
            "usable": [],
            "origins": [],
        }
    valid_reviews, evidence = [], []
    evidence_by_id = {e["id"]: e for e in record["evidence"] if e["anchor_valid"]}
    for review in reviews(db, record["claim"]["id"]):
        if review["withdrawn"] or review["claim_digest"] != record["claim_digest"]:
            continue
        source = evidence_by_id.get(review["evidence_id"])
        if not source:
            continue
        ev = Evidence.model_validate(review["payload"]["evidence"])
        if not ev.scope_verified or not ev.origin_verified:
            continue
        valid_reviews.append(review)
        evidence.append(ev)
    contexts = {encode(e.context.model_dump(mode="json")) for e in evidence}
    if len(contexts) > 1:
        return {
            "outcome": "disputed",
            "reason": "同一事实的核验条件尚未统一",
            "usable": [],
            "origins": [],
            "review_ids": [r["id"] for r in valid_reviews],
        }
    fact = Fact.model_validate(raw)
    if contexts:
        fact.context = Context.model_validate_json(next(iter(contexts)))
    result = evidence_check(fact, evidence)
    if not evidence:
        result["reason"] = "原文已保存，尚无有效的证据核验记录"
    result["missing_context"] = missing_context(fact)
    if record["claim"]["status"] != "accepted" or record["claim"]["entity_state"] != "active":
        result = {
            "outcome": "unknown",
            "reason": "事实或对象不在当前可用状态",
            "usable": [],
            "origins": [],
        }
    used = set(result.get("usable", []) + result.get("opposing", []))
    selected = [r for r in valid_reviews if r["id"] in used]
    return {
        **result,
        "fact": fact.model_dump(mode="json"),
        "review_ids": [r["id"] for r in selected],
        "evidence_ids": sorted({r["evidence_id"] for r in selected}),
        "review_provenance": [
            {k: r[k] for k in ("id", "evidence_id", "origin_revision_id", "reviewer", "note")}
            for r in selected
        ],
    }


def inspect_claim(store, slug, identity):
    business_only(store)
    with store.connect() as db:
        db.execute("BEGIN")
        record = load_claim(db, identity, topic=topic_id(db, slug))
        return {
            **record,
            "reviews": reviews(db, identity),
            "assessment": assess(db, record),
            "model_calls": 0,
        }


def review_evidence(store, slug, value):
    business_only(store)
    value = ReviewInput.model_validate(value)
    if not value.reviewer.strip() or not value.note.strip():
        raise ValueError("需要填写核验人和核验依据")
    with store.connect(write=True) as db:
        if not installed(db):
            raise ValueError("请先安装核验台账扩展")
        record = load_claim(db, value.claim_id, topic=topic_id(db, slug))
        if value.expected_claim_digest != record["claim_digest"]:
            raise ValueError("事实或证据已变化，请重新读取后核验")
        if record["claim"]["status"] != "accepted" or not record["fact"]:
            raise ValueError("需要先完成候选事实的入库复核")
        source = next((e for e in record["evidence"] if e["id"] == value.evidence_id), None)
        if not source or not source["anchor_valid"]:
            raise ValueError("证据必须绑定当前事实并能定位到原文")
        origin = None
        if value.origin_revision_id:
            origin = db.execute(
                "SELECT document_id FROM source_revisions WHERE id=?", (value.origin_revision_id,)
            ).fetchone()
            if not origin:
                raise ValueError("形成来源必须指向已有原文版本")
        if value.origin_verified and origin is None:
            raise ValueError("确认来源时必须选择已有原始材料版本")
        fact = Fact.model_validate(record["fact"])
        payload = value.model_dump(mode="json")
        identity = "qreview:" + digest(payload)
        ev = Evidence(
            id=identity,
            fact_id=fact.id,
            revision_id=source["revision_id"],
            subject_id=fact.subject_id,
            predicate=fact.predicate,
            context=value.context or fact.context,
            stance=source["stance"],
            kind=value.kind,
            directness=value.directness,
            origin_id=origin[0] if origin else None,
            scope_verified=value.scope_verified,
            origin_verified=value.origin_verified,
        )
        payload["evidence"] = ev.model_dump(mode="json")
        if db.execute(
            "SELECT 1 FROM quality_review_withdrawals WHERE review_id=?", (identity,)
        ).fetchone():
            raise ValueError("该核验已撤回；重新核验需给出新的核验依据")
        db.execute(
            "INSERT OR IGNORE INTO quality_evidence_reviews VALUES(?,?,?,?,?,?,?,?,?)",
            (
                identity,
                value.claim_id,
                value.evidence_id,
                value.origin_revision_id,
                record["claim_digest"],
                value.reviewer,
                value.note,
                encode(payload),
                now(),
            ),
        )
        result = assess(db, record)
    return {"review_id": identity, "assessment": result, "model_calls": 0}


def withdraw_review(store, slug, identity, *, reviewer, reason):
    business_only(store)
    if not reviewer.strip() or not reason.strip():
        raise ValueError("撤回核验需要核验人和理由")
    with store.connect(write=True) as db:
        row = db.execute(
            "SELECT r.claim_id FROM quality_evidence_reviews r JOIN claims c ON c.id=r.claim_id "
            "WHERE r.id=? AND c.topic_id=?",
            (identity, topic_id(db, slug)),
        ).fetchone()
        if not row:
            raise ValueError("核验不存在或不属于当前专题")
        db.execute(
            "INSERT OR IGNORE INTO quality_review_withdrawals VALUES(?,?,?,?)",
            (identity, reviewer, reason, now()),
        )
        affected = [
            r[0]
            for r in db.execute(
                "SELECT conclusion_id FROM quality_conclusion_premises WHERE review_id=?",
                (identity,),
            )
        ]
    return {"review_id": identity, "affected_conclusions": affected, "model_calls": 0}
