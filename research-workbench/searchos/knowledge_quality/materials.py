"""Versioned acquisition boundary. No knowledge columns, scheduling or model imports."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Span(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1)


class Material(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    title: str = ""
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    representation: str = "archived_text"
    original_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    fetched_at: str | None = None
    published_at: str | None = None
    spans: tuple[Span, ...] = ()

    @model_validator(mode="after")
    def verify_content(self):
        if not self.text.strip() or self.text.startswith("[FETCH_ERROR]"):
            raise ValueError("Material must contain successfully collected text")
        if hashlib.sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("Material text hash mismatch")
        ids = set()
        for span in self.spans:
            if span.id in ids or span.end > len(self.text) or span.end <= span.start:
                raise ValueError("Invalid or duplicate material span")
            if self.text[span.start : span.end] != span.text:
                raise ValueError("Span does not match its source revision")
            ids.add(span.id)
        return self


class CollectionDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["collection-delivery-v1"] = "collection-delivery-v1"
    run_id: str = Field(min_length=1)
    task_ids: tuple[str, ...] = ()
    collector: str = Field(min_length=1)
    materials: tuple[Material, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_revisions(self):
        keys = [(m.document_id, m.revision_id) for m in self.materials]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate source revision in collection delivery")
        return self


def from_archive(path, *, run_id, task_ids=()):
    """Consume an existing frozen corpus; never mutate or import it into a business DB."""
    from searchos.corpus.archive import load_bundle

    manifest, texts = load_bundle(path)
    return CollectionDelivery(
        run_id=run_id,
        task_ids=tuple(task_ids),
        collector="searchos-corpus-v1",
        materials=tuple(
            Material(
                document_id=r["document_id"],
                revision_id=r["document_id"],
                source_url=r["source_url"],
                title=r["title"],
                text=texts[r["document_id"]],
                text_sha256=r["text"]["sha256"],
                representation=r["representation"],
                original_sha256=(r.get("original") or {}).get("sha256"),
                fetched_at=r.get("fetched_at"),
            )
            for r in manifest["documents"]
        ),
    )
