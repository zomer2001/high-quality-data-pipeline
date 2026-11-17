"""Typed, executable ontology contracts; candidate metadata is not verified evidence."""

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Context(Strict):
    version: str | None = None
    conditions: dict[str, JsonValue] = Field(default_factory=dict)
    valid_from: date | None = None
    valid_to: date | None = None
    statistic: str | None = None
    nature: Literal[
        "vendor_claim",
        "measurement",
        "independent_retest",
        "source_statement",
        "reported_statement",
        "derived",
        "unspecified",
    ] = "unspecified"
    event_id: str | None = None
    event_state: Literal["planned", "underway", "completed", "cancelled"] | None = None

    @model_validator(mode="after")
    def ordered_time(self):
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("有效时间起点不能晚于终点")
        return self


class Fact(Strict):
    id: str = ""
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    kind: Literal["metric", "capability", "field", "relation", "event"]
    value: JsonValue
    unit: str | None = None
    operator: Literal["=", "range", ">", ">=", "<", "<=", "approx"] = "="
    context: Context = Field(default_factory=Context)
    cardinality: Literal["one", "many", "unknown"] = "unknown"


class Evidence(Strict):
    id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    subject_id: str
    predicate: str
    context: Context
    stance: Literal["supports", "refutes", "context"] = "context"
    kind: Literal[
        "vendor_declaration",
        "test_report",
        "independent_test",
        "completion_record",
        "secondary",
        "source_record",
        "unknown",
    ] = "unknown"
    directness: Literal["direct", "attributed", "untraced"] = "untraced"
    origin_id: str | None = None
    # These are reviewer/verified-ledger inputs, never read from extraction qualifiers.
    scope_verified: bool = False
    origin_verified: bool = False


class EvidenceRequirement(Strict):
    kinds: list[str]
    independent_origins: int = Field(ge=1)


class Ontology(Strict):
    version: str
    comparison_requirements: dict[str, list[str]]
    evidence_requirements: dict[str, EvidenceRequirement]
    condition_aliases: dict[str, str]
    rules: dict[str, str]

    @model_validator(mode="after")
    def known_context_fields(self):
        if any(
            set(keys) - set(Context.model_fields) for keys in self.comparison_requirements.values()
        ):
            raise ValueError("比较规则引用了未定义的条件字段")
        return self


def load_ontology():
    return Ontology.model_validate(
        json.loads(Path(__file__).with_name("ontology_v1.json").read_text())
    )
