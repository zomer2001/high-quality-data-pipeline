"""Small, network-free checks of collection boundaries and conditional reasoning."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from searchos.corpus.archive import CorpusArchive
from searchos.knowledge_quality.materials import CollectionDelivery, Material, Span, from_archive
from searchos.knowledge_quality.ontology import Context, Evidence, Fact
from searchos.knowledge_quality.reasoning import (
    classification_path,
    compare,
    evidence_check,
    transition,
)


def context(**changes):
    return Context.model_validate(
        {
            "version": "v2",
            "conditions": {"bandwidth": "20 MHz"},
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "statistic": "maximum",
            "nature": "measurement",
            **changes,
        }
    )


def fact(**changes):
    return Fact.model_validate(
        {
            "id": "fact-x",
            "subject_id": "product-x",
            "kind": "metric",
            "predicate": "range",
            "value": 1000,
            "unit": "m",
            "context": context(),
            "cardinality": "one",
            **changes,
        }
    )


def evidence(for_fact, **changes):
    return Evidence.model_validate(
        {
            "id": "e-1",
            "fact_id": for_fact.id,
            "revision_id": "r-1",
            "subject_id": for_fact.subject_id,
            "predicate": for_fact.predicate,
            "context": for_fact.context,
            "stance": "supports",
            "kind": "test_report",
            "directness": "direct",
            "origin_id": "origin-1",
            "scope_verified": True,
            "origin_verified": True,
            **changes,
        }
    )


def test_collection_boundary_checks_hash_spans_and_preserves_originals(tmp_path):
    archive = CorpusArchive(tmp_path / "archive")
    archive.add(
        source_url="https://example.invalid/x",
        text="Product-X test data.",
        original=b"<html>Product-X test data.</html>",
    )
    archive.freeze(tmp_path / "bundle", dataset_id="fictional")
    before = {str(p): p.read_bytes() for p in (tmp_path / "bundle").rglob("*") if p.is_file()}
    delivery = from_archive(tmp_path / "bundle", run_id="offline")
    assert delivery.materials[0].original_sha256 != delivery.materials[0].text_sha256
    assert CollectionDelivery.model_validate_json(delivery.model_dump_json()) == delivery
    assert before == {
        str(p): p.read_bytes() for p in (tmp_path / "bundle").rglob("*") if p.is_file()
    }
    material = delivery.materials[0].model_dump()
    with pytest.raises(ValidationError, match="hash mismatch"):
        Material.model_validate({**material, "text": "replaced"})
    with pytest.raises(ValidationError, match="Span"):
        Material.model_validate({**material, "spans": [Span(id="s", start=0, end=9, text="wrong")]})
    with pytest.raises(ValidationError, match="Duplicate"):
        CollectionDelivery(run_id="x", collector="x", materials=delivery.materials * 2)
    with pytest.raises(ValidationError):
        Material.model_validate({**material, "knowledge_columns": {"anything": 1}})


def test_collection_rejects_fetch_errors_even_with_correct_hash():
    text = "[FETCH_ERROR] request failed"
    with pytest.raises(ValidationError, match="successfully"):
        Material(
            document_id="d",
            revision_id="r",
            source_url="https://example.invalid",
            text=text,
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        )


@pytest.mark.parametrize(
    ("changes", "outcome"),
    [
        ({"value": 1, "unit": "km"}, "equivalent"),
        ({"value": 2, "unit": "km"}, "different_value"),
        ({"value": [900, 1100], "operator": "range"}, "compatible_range"),
        ({"value": 1, "unit": "kg"}, "unknown"),
        ({"operator": ">="}, "unknown"),
        ({"context": context(conditions={"带宽": "0.02 GHz"})}, "equivalent"),
        ({"context": context(conditions={"bandwidth": "30 MHz"})}, "different_conditions"),
        ({"context": context(version="v3")}, "different_version"),
        ({"context": context(nature="vendor_claim")}, "different_nature"),
        ({"context": context(statistic="minimum")}, "different_conditions"),
        ({"context": context(valid_from="2027-01-01", valid_to="2027-12-31")}, "different_time"),
        ({"context": context(valid_from="2026-02-01")}, "unknown"),
        ({"context": Context(version="v2")}, "unknown"),
        ({"subject_id": "product-y"}, "separate_object"),
    ],
)
def test_comparison_is_conditional(changes, outcome):
    assert compare(fact(), fact(**changes))["outcome"] == outcome


def test_bad_context_is_not_silently_repaired():
    with pytest.raises(ValidationError):
        context(valid_from="2028-01-01")
    with pytest.raises(ValidationError):
        context(published_at="2026-01-01")  # Publication does not establish effective time.
    with pytest.raises(ValueError, match="矛盾"):
        compare(fact(), fact(context=context(conditions={"bandwidth": "20 MHz", "带宽": "30 MHz"})))


def test_reposts_are_one_origin_and_unverified_flags_cannot_prove_fact():
    target = fact(context=context(nature="independent_retest"))
    copies = [
        evidence(target, id=f"e-{n}", revision_id=f"r-{n}", kind="independent_test")
        for n in range(10)
    ]
    result = evidence_check(target, copies)
    assert result["outcome"] == "unknown" and len(result["origins"]) == 1
    independent = evidence(
        target, id="independent", origin_id="independent", kind="independent_test"
    )
    assert evidence_check(target, copies + [independent])["outcome"] == "pass"
    assert (
        evidence_check(target, [independent.model_copy(update={"origin_verified": False})])[
            "usable"
        ]
        == []
    )
    assert (
        evidence_check(target, [independent.model_copy(update={"fact_id": "other-fact"})])["usable"]
        == []
    )
    assert (
        evidence_check(target, [independent.model_copy(update={"context": context(version="v3")})])[
            "usable"
        ]
        == []
    )
    assert (
        evidence_check(target, [independent.model_copy(update={"directness": "attributed"})])[
            "usable"
        ]
        == []
    )


def test_vendor_claim_does_not_prove_measurement_and_conflicting_sources_remain_disputed():
    target = fact()
    assert (
        evidence_check(target, [evidence(target, kind="vendor_declaration")])["outcome"]
        == "unknown"
    )
    assert (
        evidence_check(
            target,
            [
                evidence(target),
                evidence(target, id="opposition", stance="refutes", origin_id="other"),
            ],
        )["outcome"]
        == "disputed"
    )


def test_event_completion_needs_explicit_event_and_evidence():
    previous = fact(
        kind="event",
        predicate="production",
        value="planned",
        context=context(event_id="plant-x", event_state="planned", nature="source_statement"),
    )
    current = fact(
        id="completed",
        kind="event",
        predicate="production",
        value="completed",
        context=context(
            event_id="plant-x",
            event_state="completed",
            nature="source_statement",
            valid_from="2027-01-01",
            valid_to="2027-12-31",
        ),
    )
    proof = evidence(current, kind="completion_record")
    assert transition(previous, current, [])["outcome"] == "unknown"
    assert transition(previous, current, [proof])["outcome"] == "pass"
    assert (
        transition(
            previous,
            current.model_copy(
                update={
                    "context": current.context.model_copy(update={"event_id": "different-event"})
                }
            ),
            [proof],
        )["outcome"]
        == "unknown"
    )
    assert (
        transition(
            previous,
            current.model_copy(
                update={
                    "context": current.context.model_copy(
                        update={"valid_from": None, "valid_to": None}
                    )
                }
            ),
            [proof],
        )["outcome"]
        == "unknown"
    )
    assert (
        evidence_check(
            current, [proof.model_copy(update={"context": previous.context})], "event_completed"
        )["outcome"]
        == "unknown"
    )


def test_taxonomy_is_classification_not_product_adoption():
    edges = [
        {"child": "YOLO", "parent": "object_detection", "relation": "subtype_of"},
        {"child": "object_detection", "parent": "computer_vision", "relation": "subtype_of"},
        {"child": "product-x", "parent": "YOLO", "relation": "uses"},
    ]
    assert classification_path("YOLO", "computer_vision", edges)["path"] == [
        "YOLO",
        "object_detection",
        "computer_vision",
    ]
    assert classification_path("product-x", "computer_vision", edges)["outcome"] == "unknown"
    edges.append({"child": "computer_vision", "parent": "YOLO", "relation": "subtype_of"})
    assert classification_path("YOLO", "computer_vision", edges)["outcome"] == "unknown"


def test_preview_records_boundary_context_and_blocks_only_same_scope_difference(tmp_path):
    from api.knowledge_handoff.review import build_plan, commit_plan
    from api.research_mapping import Source

    from searchos.knowledge_store.database import ResearchDatabase

    store = ResearchDatabase(tmp_path / "test.sqlite")
    store.initialize()
    original = Source(
        "https://example.invalid/x", "Fixture", "Product-X has range 1000 m.", "x.md", "doc"
    )

    def output(value, ctx, quote):
        return [
            {
                "entities": [
                    {
                        "entity_key": "x",
                        "kind": "product",
                        "name": "Product-X",
                        "identity_quote": quote,
                    }
                ],
                "records": [
                    {
                        "subject_key": "x",
                        "kind": "metric",
                        "label": "range",
                        "value": {"value": value, "unit": "m"},
                        "quote": quote,
                        "qualifiers": {"ontology_context": ctx.model_dump(mode="json")},
                    }
                ],
            }
        ]

    def preview(src, value, ctx, **kwargs):
        return build_plan(
            store,
            src,
            output(value, ctx, src.text),
            slug="test",
            artifact_root=tmp_path / "plans",
            **kwargs,
        )

    plan = preview(original, 1000, context())
    assert plan["collection_input"]["materials"][0]["text_sha256"] == original.digest
    assert "text" not in plan["collection_input"]["materials"][0]
    metric = next(r for r in plan["records"] if r["kind"] == "metric")
    assert metric["quality"]["evidence_assessment"]["outcome"] == "unknown"
    assert metric["quality"]["fact"]["context"]["version"] == "v2"
    assert (
        next(c for c in metric["quality"]["checks"] if c["rule"] == "ontology_context")["result"]
        == "pass"
    )
    commit_plan(store, original, plan["plan_id"], artifact_root=tmp_path / "plans")
    product = next(e["id"] for e in plan["entities"] if e["kind"] == "product")
    incoming = Source(original.url, "Fixture", "Product-X has range 2000 m.", "x.md", "doc")
    conflict = preview(incoming, 2000, context(), entity_choices={"x": product})
    assert conflict["conflicts"][0]["comparison"]["outcome"] == "different_value"
    separate = preview(
        incoming, 2000, context(conditions={"bandwidth": "30 MHz"}), entity_choices={"x": product}
    )
    assert not separate["conflicts"]
    metric = next(r for r in separate["records"] if r["kind"] == "metric")
    assert metric["quality"]["comparisons"][0]["outcome"] == "different_conditions"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM metric_observations").fetchone()[0] == 1
        release = json.loads(
            db.execute(
                "SELECT value FROM database_metadata WHERE key=?",
                ("ontology_release:" + plan["ontology_release"],),
            ).fetchone()[0]
        )
        assert release["snapshot"]["ontology"]["version"] == "product-technology-ontology-v1"


def test_extraction_metadata_cannot_approve_its_own_evidence():
    from api.knowledge_handoff.quality import add_ontology_checks, as_fact

    metadata = {
        "ontology_context": context().model_dump(mode="json"),
        "scope_verified": True,
        "origin_verified": True,
        "origin_id": "fabricated",
    }
    candidate = as_fact(
        "x", "metric", {"metric_id": "range", "numeric_value": 1000, "raw_unit": "m"}, metadata, {}
    )
    quality = {"checks": []}
    add_ontology_checks(quality, candidate)
    assert quality["evidence_assessment"]["outcome"] == "unknown"
    assert quality["evidence_assessment"]["usable"] == []


def test_subnanosecond_values_are_not_rounded_to_zero():
    left = fact(value=0.0000000000001, unit="s")
    right = fact(value=0.0000000000002, unit="s")
    assert compare(left, right)["outcome"] == "different_value"


def test_unknown_placeholders_and_nested_conditions_do_not_establish_scope():
    for ctx in [
        context(version="unknown"),
        context(conditions={"bandwidth": "未知"}),
        context(conditions={"bandwidth": {"value": None, "unit": "MHz"}}),
    ]:
        assert compare(fact(), fact(value=2000, context=ctx))["outcome"] == "unknown"


def test_approximate_interval_keeps_its_qualifier():
    from api.knowledge_handoff.quality import as_fact

    candidate = as_fact(
        "x",
        "metric",
        {
            "metric_id": "range",
            "min_value": 75,
            "max_value": 90,
            "comparator": "approx",
            "raw_unit": "min",
        },
        {"ontology_context": context().model_dump(mode="json")},
        {},
    )
    assert candidate.operator == "approx"
    assert candidate.value == [75, 90]
    assert compare(candidate, candidate)["outcome"] == "unknown"
