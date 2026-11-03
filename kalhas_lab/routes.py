"""Local development harness routes outside the shipped package.

The harness is not a KALHAS component or integration surface.
"""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans

router = APIRouter()
_UI = Path(__file__).resolve().parent / "ui"


@router.get("/lab/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_UI / "index.html", media_type="text/html")


@router.get("/lab/styles.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(_UI / "styles.css", media_type="text/css")


@router.get("/lab/app.js", include_in_schema=False)
def javascript() -> FileResponse:
    return FileResponse(_UI / "app.js", media_type="text/javascript")


@router.get("/lab/demo_flow.json", include_in_schema=False)
def flow() -> FileResponse:
    return FileResponse(_UI / "demo_flow.json", media_type="application/json")


@router.post("/lab/api/campaigns/{campaign_id}/trajectory-plans", include_in_schema=False)
def prepare_plans(
    campaign_id: str, request: Request, tenant: Annotated[str, Header(alias="X-Tenant-ID")]
) -> dict[str, list[dict[str, str]]]:
    plans = prepare_strategy_trajectory_plans(
        store=request.app.state.store,
        legion=request.app.state.mock_legion,
        tenant_id=tenant,
        campaign_id=campaign_id,
    )
    return {"plans": [{"identifier": p.identifier, "content_hash": p.content_hash} for p in plans]}
