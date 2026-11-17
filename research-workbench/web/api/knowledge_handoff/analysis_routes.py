"""Local evidence review and explainable analysis; independent of DR scheduling."""

from datetime import date

from fastapi import APIRouter
from pydantic import Field

from searchos.knowledge_quality.analysis import analyze, read_run
from searchos.knowledge_quality.ledger import (
    ReviewInput,
    inspect_claim,
    review_evidence,
    withdraw_review,
)
from searchos.knowledge_quality.ontology import Strict

from .routes import local_call, service

router = APIRouter()


class AnalysisRequest(Strict):
    slug: str = "anduril"
    as_of: date | None = None


class EvidenceReview(Strict):
    slug: str = "anduril"
    review: ReviewInput


class Withdrawal(Strict):
    slug: str = "anduril"
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.get("/analysis")
async def analysis(slug: str = "anduril", as_of: date | None = None):
    return await local_call(analyze, service().store, slug, as_of=as_of)


@router.post("/analysis/runs")
async def create_run(request: AnalysisRequest):
    return await local_call(
        analyze, service().store, request.slug, as_of=request.as_of, persist=True
    )


@router.get("/analysis/runs/{run_id}")
async def get_run(run_id: str, slug: str = "anduril"):
    return await local_call(read_run, service().store, slug, run_id)


@router.get("/evidence/claims/{claim_id}")
async def claim_evidence(claim_id: str, slug: str = "anduril"):
    return await local_call(inspect_claim, service().store, slug, claim_id)


@router.post("/evidence/reviews")
async def review(request: EvidenceReview):
    store = service().store
    result = await local_call(review_evidence, store, request.slug, request.review)
    current = await local_call(analyze, store, request.slug, persist=True)
    return {**result, "analysis_run_id": current["run_id"], "analysis_counts": current["counts"]}


@router.post("/evidence/reviews/{review_id}/withdraw")
async def withdraw(review_id: str, request: Withdrawal):
    store = service().store
    result = await local_call(
        withdraw_review,
        store,
        request.slug,
        review_id,
        reviewer=request.reviewer,
        reason=request.reason,
    )
    current = await local_call(analyze, store, request.slug, persist=True)
    return {**result, "analysis_run_id": current["run_id"], "analysis_counts": current["counts"]}
