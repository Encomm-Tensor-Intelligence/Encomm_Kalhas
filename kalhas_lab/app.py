"""Local development harness, outside the shipped KALHAS package.

The harness is not a KALHAS component or an integration surface.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.api.app import create_app
from kalhas.application.domain_errors import (
    CampaignNotPlanningStateError,
    TrajectoryPlansAlreadyPreparedError,
)
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode

from kalhas_lab.routes import router
from kalhas_lab.sequences import LAB_SEQUENCES


def create_lab_app() -> FastAPI:
    app = create_app()
    app.state.mock_legion = MockLegionAdapter(declared_transition_sequences=LAB_SEQUENCES)

    @app.exception_handler(CampaignNotPlanningStateError)
    async def campaign_not_planning(
        request: Request, exc: CampaignNotPlanningStateError
    ) -> JSONResponse:
        response = ApiErrorResponse(
            code=ErrorCode.INVALID_STATE,
            message=str(exc),
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))

    @app.exception_handler(TrajectoryPlansAlreadyPreparedError)
    async def plans_already_prepared(
        request: Request, exc: TrajectoryPlansAlreadyPreparedError
    ) -> JSONResponse:
        response = ApiErrorResponse(
            code=ErrorCode.CONFLICT,
            message=str(exc),
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))

    app.include_router(router)
    return app
