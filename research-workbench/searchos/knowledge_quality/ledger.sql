-- Additive extension: the immutable seven-dimension v1 schema is unchanged.
CREATE TABLE IF NOT EXISTS quality_evidence_reviews (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    evidence_id TEXT NOT NULL REFERENCES claim_evidence(id),
    origin_revision_id TEXT REFERENCES source_revisions(id),
    claim_digest TEXT NOT NULL,
    reviewer TEXT NOT NULL CHECK(length(trim(reviewer))>0),
    note TEXT NOT NULL CHECK(length(trim(note))>0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS quality_reviews_claim ON quality_evidence_reviews(claim_id);
CREATE TABLE IF NOT EXISTS quality_review_withdrawals (
    review_id TEXT PRIMARY KEY REFERENCES quality_evidence_reviews(id),
    reviewer TEXT NOT NULL CHECK(length(trim(reviewer))>0),
    reason TEXT NOT NULL CHECK(length(trim(reason))>0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_analysis_runs (
    id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES topics(id),
    as_of TEXT NOT NULL, input_digest TEXT NOT NULL, policy TEXT NOT NULL,
    summary_json TEXT NOT NULL CHECK(json_valid(summary_json)), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_conclusions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES quality_analysis_runs(id),
    rule_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('technology_ancestry','shared_technology','evidence_gap')),
    status TEXT NOT NULL CHECK(status IN ('derived','unknown','disputed')),
    subject_id TEXT REFERENCES entities(id), object_id TEXT REFERENCES entities(id),
    technology_id TEXT REFERENCES entities(id),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE TABLE IF NOT EXISTS quality_conclusion_premises (
    conclusion_id TEXT NOT NULL REFERENCES quality_conclusions(id),
    claim_id TEXT NOT NULL REFERENCES claims(id),
    review_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(conclusion_id,claim_id,review_id)
);
CREATE INDEX IF NOT EXISTS quality_premise_claim ON quality_conclusion_premises(claim_id);
CREATE TRIGGER IF NOT EXISTS quality_review_immutable BEFORE UPDATE ON quality_evidence_reviews
BEGIN SELECT RAISE(ABORT,'append a new review; withdraw the old review separately'); END;
CREATE TRIGGER IF NOT EXISTS quality_review_keep BEFORE DELETE ON quality_evidence_reviews
BEGIN SELECT RAISE(ABORT,'retain evidence review history'); END;
CREATE TRIGGER IF NOT EXISTS quality_withdrawal_immutable BEFORE UPDATE ON quality_review_withdrawals
BEGIN SELECT RAISE(ABORT,'retain withdrawal history'); END;
CREATE TRIGGER IF NOT EXISTS quality_withdrawal_keep BEFORE DELETE ON quality_review_withdrawals
BEGIN SELECT RAISE(ABORT,'retain withdrawal history'); END;
