"""Small offline acceptance suite, using fictional records and isolated databases."""

import asyncio
import json

import pytest
from api.knowledge_handoff.review import build_plan, commit_plan
from api.research_database import snapshot
from api.research_mapping import Source
from api.topic_research import TopicResearchManager, published_local_lookup
from api.topic_store import TopicStore

from searchos.knowledge_quality import registry
from searchos.knowledge_quality.checks import equivalent, verify
from searchos.knowledge_store.database import ResearchDatabase


@pytest.fixture
def case(tmp_path):
    db = ResearchDatabase(tmp_path / "business.sqlite")
    db.initialize()
    text = "Product-X transmits at 23 dBm at 20 MHz. Product-X supports publish-subscribe."
    source = Source(
        "https://example.invalid/x", "Fictional specification", text, "fixture.md", "doc-x"
    )
    outputs = [
        {
            "entities": [
                {
                    "entity_key": "x",
                    "kind": "product",
                    "name": "Product-X",
                    "identity_quote": text,
                    "fields": [
                        {
                            "field_id": "product_supports_publish_subscribe",
                            "value": True,
                            "quote": "Product-X supports publish-subscribe.",
                        }
                    ],
                }
            ],
            "records": [
                {
                    "subject_key": "x",
                    "kind": "metric",
                    "label": "输出功率",
                    "value": {"value": 23, "unit": "dBm"},
                    "quote": text,
                    "qualifiers": {"conditions": {"bandwidth": "20 MHz"}},
                }
            ],
        }
    ]
    return db, source, outputs, tmp_path


def preview(case):
    db, source, outputs, root = case
    return build_plan(db, source, outputs, slug="anduril", artifact_root=root)


def test_wrong_number_is_held_while_good_records_can_be_explicitly_published(case):
    db, source, outputs, root = case
    outputs[0]["records"][0]["value"]["value"] = 30
    plan = preview(case)
    assert any(q["status"] == "blocked" for q in plan["quality_checks"])
    assert not any(r["kind"] == "metric" for r in plan["records"])
    with pytest.raises(ValueError, match="仅提交"):
        commit_plan(db, source, plan["plan_id"], artifact_root=root)
    commit_plan(db, source, plan["plan_id"], artifact_root=root, allow_partial=True)
    assert not any(r["kind"] == "metric" for r in snapshot(db)["records"])


def test_release_checks_and_positions_survive_commit_without_claiming_semantic_truth(case):
    db, source, _, root = case
    plan = preview(case)
    assert not plan["unmapped"]
    commit_plan(db, source, plan["plan_id"], artifact_root=root)
    records = snapshot(db)["records"]
    assert records and all(r["quality"]["status"] == "needs_review" for r in records)
    for record in records:
        assert record["quality"]["ontology_release"] == plan["ontology_release"]
        for anchor in record["quality"]["anchors"]:
            assert source.text[anchor["start"] : anchor["end"]] == anchor["quote"]
    with db.connect() as conn:
        saved = conn.execute(
            "SELECT value FROM database_metadata WHERE key=?",
            ("ontology_release:" + plan["ontology_release"],),
        ).fetchone()
        assert json.loads(saved[0])["snapshot"]["fields"]
    assert commit_plan(db, source, plan["plan_id"], artifact_root=root)["reused"]


def test_changed_policy_invalidates_uncommitted_plan(case, monkeypatch):
    db, source, _, root = case
    plan = preview(case)
    monkeypatch.setattr(registry, "VERSION", "quality-a2")
    with pytest.raises(ValueError, match="核验规则"):
        commit_plan(db, source, plan["plan_id"], artifact_root=root)
    assert snapshot(db)["counts"]["records"] == 0


def test_units_and_ambiguous_quotes_preserve_unknown():
    assert equivalent(1000, "m", 1, "km") is True
    assert equivalent(1, "kg", 1, "m") is None
    assert equivalent(1, "not_a_unit", 1, "m") is None
    assert equivalent(23, "dBm", 23, "dBm") is None
    q = "Weight 5 g."
    result = verify(
        q + " " + q, "revision-x", "metric", {"numeric_value": 0.005, "raw_unit": "kg"}, [q], {}
    )
    assert result["status"] == "needs_review"
    assert len(result["anchors"]) == 2
    assert all(a["ambiguous"] for a in result["anchors"])
    assert next(c for c in result["checks"] if c["rule"] == "metric_literal")["result"] == "pass"
    wrong = "Output is 23 dBm at 30 MHz."
    result = verify(wrong, "r", "metric", {"numeric_value": 30, "raw_unit": "dBm"}, [wrong], {})
    assert (
        result["status"] == "blocked"
    )  # A number elsewhere in the quote cannot justify this unit.


def test_topic_reads_business_facts_without_touching_legacy_store(case, monkeypatch):
    db, source, _, root = case
    plan = preview(case)
    commit_plan(db, source, plan["plan_id"], artifact_root=root)
    from api.knowledge_database import KnowledgeDatabase

    monkeypatch.setattr(KnowledgeDatabase, "snapshot", lambda *a: pytest.fail("legacy read"))
    topics = TopicStore(
        root / "library", root / "topics.sqlite", root / "legacy.sqlite", research_database=db.path
    )
    topic = topics.create_topic("Anduril")
    data = topics.snapshot(topic["id"])
    identity = next(r["subject_id"] for r in plan["records"] if r["kind"] == "capability")
    assert identity in {e["id"] for e in data["knowledge"]["entities"]}
    assert data["knowledge"]["source"] == "research_database"
    assert not data["gaps"]  # Empty legacy template columns cannot create collection requests.
    assert any(f["label"] == "输出功率" for f in data["entity_fields"][identity])
    topics.remove_entity(topic["id"], identity)
    data = topics.snapshot(topic["id"])
    allowed = {e["id"] for e in data["knowledge"]["entities"]}
    assert identity not in allowed
    assert published_local_lookup(db, "anduril", "Product-X", [], allowed_ids=allowed) is None
    topics.sync_topic_changes(topic["id"])


def test_collection_keeps_running_with_new_raw_materials_and_extraction_disabled(monkeypatch):
    from api import field_extraction_policy
    from test_topic_research import FakeStore
    from test_topic_research import snapshot as fake_snapshot

    monkeypatch.setattr(field_extraction_policy, "MODEL_EXTRACTION_ENABLED", False)
    store = FakeStore()
    sources = []
    store.snapshot = lambda _: {**fake_snapshot(), "sources": list(sources)}
    manager = TopicResearchManager(store)

    async def collect(*args):
        return "test", True

    async def ingest(*args):
        sources.append({"id": str(len(sources)), "source_revision": str(len(sources))})
        return False, 1

    manager._collect, manager._ingest = collect, ingest
    asyncio.run(manager._execute(store.run.copy()))
    assert store.run["status"] == "completed"
    assert store.run["new_sources"] == 4
    assert store.run["processing_status"] == "awaiting_extraction"
    assert store.run["stop_reason"] == "plan_completed"
    assert all(t["status"] == "completed" for t in store.tasks.values())
