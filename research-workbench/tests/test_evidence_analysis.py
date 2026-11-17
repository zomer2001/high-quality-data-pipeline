"""Small, fully offline end-to-end proof and withdrawal scenarios."""

import hashlib
import sqlite3

import pytest

from searchos.knowledge_quality.analysis import analyze, read_run
from searchos.knowledge_quality.ledger import (
    inspect_claim,
    install,
    review_evidence,
    withdraw_review,
)
from searchos.knowledge_store.database import ResearchDatabase, encode, now

SLUG = "anduril"
TOPIC = "topic:anduril"
TEXT = (
    "Product A uses Detector. Product B uses Detector. "
    "Detector is a detection technology. Detection is computer vision."
)
CONTEXT = {
    "version": "v1",
    "valid_from": "2026-01-01",
    "valid_to": "2026-12-31",
    "nature": "source_statement",
}


@pytest.fixture
def case(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No network allowed"))
    store = ResearchDatabase(tmp_path / "business.sqlite")
    store.initialize()
    install(store)
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO source_documents VALUES(?,?,?,?,?)",
            ("doc", "https://example.invalid/source", "Fiction", "test", None),
        )
        db.execute(
            "INSERT INTO source_revisions VALUES(?,?,?,?,?,?)",
            (
                "revision",
                "doc",
                hashlib.sha256(TEXT.encode()).hexdigest(),
                "fiction.txt",
                None,
                now(),
            ),
        )
        db.execute(
            "INSERT INTO source_segments VALUES(?,?,?,?)",
            ("segment", "revision", "full_text", TEXT),
        )
    names = [
        ("a", "product"),
        ("b", "product"),
        ("detector", "technology"),
        ("detection", "technology"),
        ("vision", "technology"),
    ]
    entities = {
        n: store.create_entity(kind=k, name=n, namespace="anduril", identity_key=n, topic_id=TOPIC)
        for n, k in names
    }
    claims = {}
    for key, subject, relation, target in [
        ("a", "a", "uses_technology", "detector"),
        ("b", "b", "uses_technology", "detector"),
        ("parent", "detector", "subtechnology_of", "detection"),
        ("grandparent", "detection", "subtechnology_of", "vision"),
    ]:
        claims[key] = store.append_claim(
            topic_id=TOPIC,
            subject_id=entities[subject],
            kind="relation",
            detail={"relation_type_id": relation, "object_id": entities[target]},
            status="accepted",
            evidence=[{"segment_id": "segment", "quote": TEXT}],
            scope_note=encode({"ontology_context": CONTEXT}),
        )
    return store, entities, claims


def approve(store, claim, **changes):
    record = inspect_claim(store, SLUG, claim)
    data = {
        "claim_id": claim,
        "evidence_id": record["evidence"][0]["id"],
        "expected_claim_digest": record["claim_digest"],
        "reviewer": "offline-fixture-reviewer",
        "note": "Fictional evidence checked for this test",
        "kind": "source_record",
        "directness": "direct",
        "origin_revision_id": "revision",
        "scope_verified": True,
        "origin_verified": True,
        **changes,
    }
    return review_evidence(store, SLUG, data)


def test_owl_rules_make_explained_links_only_from_reviewed_facts(case):
    store, entities, claims = case
    empty = analyze(store, SLUG, as_of="2026-06-01")
    assert empty["counts"]["derived"] == 0 and empty["counts"]["gaps"] == 4
    for claim in claims.values():
        assert approve(store, claim)["assessment"]["outcome"] == "pass"
    result = analyze(store, SLUG, as_of="2026-06-01", persist=True)
    common = [c for c in result["conclusions"] if c["kind"] == "shared_technology"]
    assert {c["technology_id"] for c in common} == {
        entities[k] for k in ("detector", "detection", "vision")
    }
    upper = next(c for c in common if c["technology_id"] == entities["vision"])
    assert set(upper["premise_ids"]) == set(claims.values())
    assert len(upper["review_ids"]) == 4
    assert upper["premises"] and all(p["evidence"][0]["quote"] == TEXT for p in upper["premises"])
    assert read_run(store, SLUG, result["run_id"])["usable"]
    assert analyze(store, SLUG, as_of="2026-06-01", persist=True)["run_id"] == result["run_id"]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM claims").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM quality_analysis_runs").fetchone()[0] == 1


def test_withdrawn_review_invalidates_history_and_recomputation_removes_only_affected_links(case):
    store, entities, claims = case
    approvals = {key: approve(store, claim) for key, claim in claims.items()}
    old = analyze(store, SLUG, as_of="2026-06-01", persist=True)
    withdrawn = withdraw_review(
        store,
        SLUG,
        approvals["grandparent"]["review_id"],
        reviewer="test",
        reason="Premise unsupported",
    )
    assert withdrawn["affected_conclusions"]
    assert read_run(store, SLUG, old["run_id"])["stale"]
    updated = analyze(store, SLUG, as_of="2026-06-01", persist=True)
    assert updated["run_id"] != old["run_id"]
    common = [
        c["technology_id"] for c in updated["conclusions"] if c["kind"] == "shared_technology"
    ]
    assert entities["vision"] not in common and entities["detector"] in common
    with store.connect(write=True) as db:
        with pytest.raises(sqlite3.IntegrityError, match="history"):
            db.execute("DELETE FROM quality_evidence_reviews")


def test_claim_withdrawal_and_inactive_objects_cannot_leave_current_conclusions(case):
    store, _, claims = case
    for claim in claims.values():
        approve(store, claim)
    old = analyze(store, SLUG, as_of="2026-06-01", persist=True)
    store.review_claim(claims["b"], decision="withdraw", reviewer="test", reason="Wrong product")
    assert not read_run(store, SLUG, old["run_id"])["usable"]
    assert not any(
        c["kind"] == "shared_technology"
        for c in analyze(store, SLUG, as_of="2026-06-01")["conclusions"]
    )


def test_pending_reviews_expiry_and_unknown_conditions_do_not_establish_facts(case):
    store, _, claims = case
    approve(store, claims["a"], scope_verified=False)
    assert inspect_claim(store, SLUG, claims["a"])["assessment"]["outcome"] == "unknown"
    for claim in claims.values():
        approve(store, claim)
    assert analyze(store, SLUG, as_of="2027-01-01")["counts"]["derived"] == 0
    missing = dict(CONTEXT, valid_to=None)
    approve(store, claims["a"], context=missing, note="Conflicting context remains unresolved")
    assert inspect_claim(store, SLUG, claims["a"])["assessment"]["outcome"] == "disputed"


def test_reviews_bind_the_exact_fact_evidence_and_source(case):
    store, _, claims = case
    other = inspect_claim(store, SLUG, claims["b"])
    with pytest.raises(ValueError, match="绑定"):
        approve(store, claims["a"], evidence_id=other["evidence"][0]["id"])
    with pytest.raises(ValueError, match="变化"):
        approve(store, claims["a"], expected_claim_digest="0" * 64)
    with pytest.raises(ValueError, match="形成来源"):
        approve(store, claims["a"], origin_revision_id="invented-origin")
    with pytest.raises(ValueError, match="专题"):
        inspect_claim(store, "missing", claims["a"])
    with pytest.raises(ValueError):
        approve(store, claims["a"], kind="fake-material")


def test_cycles_do_not_disable_unrelated_direct_shared_technology(case):
    store, entities, claims = case
    cycle = store.append_claim(
        topic_id=TOPIC,
        subject_id=entities["vision"],
        kind="relation",
        detail={"relation_type_id": "subtechnology_of", "object_id": entities["detection"]},
        evidence=[{"segment_id": "segment", "quote": TEXT}],
        status="accepted",
        scope_note=encode({"ontology_context": CONTEXT}),
    )
    for claim in [*claims.values(), cycle]:
        approve(store, claim)
    result = analyze(store, SLUG, as_of="2026-06-01")
    common = [c for c in result["conclusions"] if c["kind"] == "shared_technology"]
    assert len(common) == 1 and common[0]["technology_id"] == entities["detector"]
    assert any("存在环" in c.get("reason", "") for c in result["conclusions"])


def test_extension_is_additive_and_no_write_analysis_is_readonly(case):
    store, _, _ = case
    install(store)
    store.initialize()  # Original immutable schema checksum still matches.
    with store.connect() as db:
        before = list(db.iterdump())
    analyze(store, SLUG, as_of="2026-06-01")
    with store.connect() as db:
        assert list(db.iterdump()) == before
    experiment = ResearchDatabase(store.path.parent / "widesearch_experiment" / "x.sqlite")
    with pytest.raises(ValueError, match="实验"):
        install(experiment)


def test_ledger_deduplicates_versions_of_one_origin_and_preserves_opposition(case):
    store, _, claims = case
    claim = claims["a"]
    with store.connect(write=True) as db:
        db.execute(
            "INSERT INTO source_documents VALUES(?,?,?,?,?)",
            ("doc-other", "https://example.invalid/other", "Independent", "test", None),
        )
        for suffix, document, stance in [
            ("copy", "doc", "supports"),
            ("other", "doc-other", "supports"),
            ("refute", "doc-other", "refutes"),
        ]:
            db.execute(
                "INSERT INTO source_revisions VALUES(?,?,?,?,?,?)",
                (
                    "r-" + suffix,
                    document,
                    hashlib.sha256((TEXT + suffix).encode()).hexdigest(),
                    "fixture.txt",
                    None,
                    now(),
                ),
            )
            db.execute(
                "INSERT INTO source_segments VALUES(?,?,?,?)",
                ("s-" + suffix, "r-" + suffix, "paragraph", TEXT + suffix),
            )
            db.execute(
                "INSERT INTO claim_evidence VALUES(?,?,?,?,?)",
                ("e-" + suffix, claim, "s-" + suffix, TEXT, stance),
            )
    info = inspect_claim(store, SLUG, claim)
    original_evidence = next(e["id"] for e in info["evidence"] if e["segment_id"] == "segment")
    metadata = {"context": {**CONTEXT, "nature": "independent_retest"}, "kind": "independent_test"}
    approve(store, claim, evidence_id=original_evidence, **metadata)
    copies = approve(store, claim, evidence_id="e-copy", origin_revision_id="r-copy", **metadata)
    assert copies["assessment"]["outcome"] == "unknown"
    assert copies["assessment"]["origins"] == ["doc"]
    separate = approve(
        store, claim, evidence_id="e-other", origin_revision_id="r-other", **metadata
    )
    assert separate["assessment"]["outcome"] == "pass"
    opposed = approve(
        store, claim, evidence_id="e-refute", origin_revision_id="r-refute", **metadata
    )
    assert opposed["assessment"]["outcome"] == "disputed"
    assert opposed["review_id"] in opposed["assessment"]["review_ids"]


def test_api_review_and_analysis_are_local_and_separate_from_extraction(case, monkeypatch):
    from api.routes import research_database as routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    store, _, claims = case
    monkeypatch.setattr(routes, "DATABASE_PATH", store.path)
    monkeypatch.setattr(routes, "LOCAL_DATA_ROOT", store.path.parent / "library")
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    base = "/api/research-database/handoff"
    record = client.get(base + "/evidence/claims/" + claims["a"]).json()
    data = {
        "claim_id": claims["a"],
        "evidence_id": record["evidence"][0]["id"],
        "expected_claim_digest": record["claim_digest"],
        "reviewer": "API-test",
        "note": "Fictional",
        "kind": "source_record",
        "directness": "direct",
        "origin_revision_id": "revision",
        "scope_verified": True,
        "origin_verified": True,
    }
    response = client.post(base + "/evidence/reviews", json={"review": data})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["assessment"]["outcome"] == "pass" and saved["model_calls"] == 0
    result = client.get(base + "/analysis", params={"as_of": "2026-06-01"})
    assert result.status_code == 200 and result.json()["model_calls"] == 0
    assert client.get(base + "/analysis", params={"slug": "missing"}).status_code == 422
    old = client.get(base + "/analysis/runs/" + saved["analysis_run_id"])
    assert old.status_code == 200 and not old.json()["stale"]
    response = client.post(
        base + "/evidence/reviews/" + saved["review_id"] + "/withdraw",
        json={"reviewer": "API-test", "reason": "Recheck needed"},
    )
    assert response.status_code == 200, response.text
    assert client.get(base + "/analysis/runs/" + saved["analysis_run_id"]).json()["stale"]
