from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/evals", tags=["evals"])


@router.post("/run")
async def run_eval(payload: dict):
    title = payload.get("title", "")
    body = payload.get("body", "")
    text = f"{title} {body}".lower()
    violations = [word for word in ["guarantee", "overnight", "稳赚", "疗效"] if word in text]
    structure_complete = "CTA:" in body
    return {
        "passed": not violations and structure_complete,
        "violations": violations,
        "fact_uncertainty": "medium",
        "style_fit": "good",
        "structure_complete": structure_complete,
    }
