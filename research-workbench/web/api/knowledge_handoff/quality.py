"""Business adapter: extraction qualifiers can describe context, never approve evidence."""

from searchos.knowledge_quality.facts import as_fact, context_from  # noqa: F401
from searchos.knowledge_quality.materials import CollectionDelivery, Material
from searchos.knowledge_quality.reasoning import evidence_check, missing_context


def material_delivery(source, run_id):
    return CollectionDelivery(
        run_id=run_id,
        collector="business-source-adapter-v1",
        materials=(
            Material(
                document_id=source.document_key,
                revision_id=source.revision_key,
                source_url=source.url,
                title=source.title,
                text=source.text,
                text_sha256=source.digest,
                fetched_at=source.fetched_at,
            ),
        ),
    )


def add_ontology_checks(quality, fact):
    if fact is None:
        return
    missing = missing_context(fact)
    quality["fact"] = fact.model_dump(mode="json")
    # Structural completeness is separate from establishing its correspondence to the source.
    quality["checks"].append(
        {
            "rule": "ontology_context",
            "result": "unknown" if missing else "pass",
            "reason": "缺少可比条件：" + "、".join(missing)
            if missing
            else "本版要求的比较条件已提供；原文绑定仍需核验",
        }
    )
    # No extractor-supplied origin or verified flags are trusted here.
    quality["evidence_assessment"] = evidence_check(fact, [])
    quality["comparisons"] = []
