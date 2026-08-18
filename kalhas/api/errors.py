"""Typed error handling for the KALHAS API.

Every failure is returned as the single ``ApiErrorResponse`` shape, so
clients always parse one contract. Domain errors from the application
layer are mapped to typed HTTP responses here.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from kalhas.application.campaign_decision_errors import (
    CampaignDecisionBriefIntegrityError,
    CampaignDecisionComparisonIntegrityError,
    CampaignDecisionPolicyAlreadyExistsError,
    CampaignDecisionPolicyIntegrityError,
    CampaignDecisionPolicyNotFoundError,
    CampaignDecisionPolicyValidationError,
)
from kalhas.application.campaign_lifecycle import CampaignTransitionError
from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.domain_errors import (
    CampaignAlreadyExistsError,
    CampaignMetricObservationMatrixIntegrityError,
    CampaignMetricStatisticsIntegrityError,
    CampaignNotCompleteError,
    CampaignNotFoundError,
    CampaignNotRunningError,
    CampaignPreparationError,
    CampaignTrajectoryMatrixIntegrityError,
    DomainCapabilityDeclarationAlreadyExistsError,
    DomainCapabilityDeclarationIntegrityError,
    DomainCapabilityDeclarationNotFoundError,
    DomainCapabilityInputKeyMismatchError,
    DomainCapabilityNotFoundError,
    DomainMetricObservationAlreadyExistsError,
    DomainMetricObservationIntegrityError,
    DomainMetricObservationMetricNotFoundError,
    DomainMetricObservationNonNumericFieldError,
    DomainMetricObservationNotFoundError,
    DomainMetricObservationStateFieldNotFoundError,
    DomainPackAlreadyExistsError,
    DomainPackBindingAlreadyExistsError,
    DomainPackBindingNotFoundError,
    DomainPackNotFoundError,
    DomainStateModelAlreadyExistsError,
    DomainStateModelIntegrityError,
    DomainStateModelNotFoundError,
    DomainStateTransitionAlreadyExistsError,
    DomainStateTransitionIntegrityError,
    DomainStateTransitionNotFoundError,
    DomainStateTransitionValuesError,
    InvalidScenarioError,
    InvalidTrajectoryDraftError,
    KalhasDomainError,
    MalformedWorldError,
    ReplayHashMismatchError,
    RunInputIntegrityError,
    RunMetricObservationAlreadyExistsError,
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
    RunNotCompleteError,
    RunNotFoundError,
    RunNotPlannedError,
    RunTrajectoryExecutionAlreadyExistsError,
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryExecutionNotFoundError,
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
    ScenarioAlreadyExistsError,
    ScenarioNotFoundError,
    TrajectoryPlansRequiredError,
    TrajectoryReplayMismatchError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldScenarioMismatchError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.objective_evaluation_errors import (
    CampaignObjectiveEvaluationMatrixIntegrityError,
    EvaluationProfileAlreadyExistsError,
    EvaluationProfileDeclarationAfterCompilationError,
    EvaluationProfileIncompleteCoverageError,
    EvaluationProfileIntegrityError,
    EvaluationProfileInvalidScaleError,
    EvaluationProfileMetricNotFoundError,
    EvaluationProfileNotFoundError,
    EvaluationProfileObjectiveNotFoundError,
    EvaluationProfileReachTargetRequiredError,
    EvaluationProfileToleranceRuleError,
    EvaluationProfileValidationError,
)
from kalhas.application.realization_errors import (
    RealizationCampaignMetricObservationMatrixIntegrityError,
    RealizationCampaignMetricStatisticsIntegrityError,
    RealizationCampaignTrajectoryMatrixIntegrityError,
    RealizationReplayManifestConflictError,
    RealizationRunMetricObservationAlreadyExistsError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionAlreadyExistsError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.world_uncertainty_errors import (
    CampaignWorldRealizationMatrixIntegrityError,
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
    WorldUncertaintyModelAlreadyExistsError,
    WorldUncertaintyModelDeclarationAfterCompilationError,
    WorldUncertaintyModelIntegrityError,
    WorldUncertaintyModelNotFoundError,
    WorldUncertaintyModelValidationError,
)
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode, ErrorDetail

logger = logging.getLogger("kalhas.api")

_HTTP_CODE_TO_ERROR: dict[int, ErrorCode] = {
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
}


def _error_response(
    code: ErrorCode,
    message: str,
    request_id: str | None,
    details: list[ErrorDetail] | None = None,
) -> ApiErrorResponse:
    return ApiErrorResponse(
        code=code, message=message, request_id=request_id, details=details or []
    )


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_request_id_middleware(app: FastAPI) -> None:
    """Attach a request id to every request and response."""

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


def register_error_handlers(app: FastAPI) -> None:
    """Wire the single typed error shape into the application."""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_TO_ERROR.get(exc.status_code, ErrorCode.HTTP_ERROR)
        response = _error_response(code, str(exc.detail), _request_id(request))
        return JSONResponse(status_code=exc.status_code, content=response.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[ErrorDetail] = []
        for err in exc.errors():
            loc = tuple(str(part) for part in err.get("loc", ()))
            message = str(err.get("msg", "invalid value"))
            details.append(ErrorDetail(loc=loc, message=message))
        response = _error_response(
            ErrorCode.VALIDATION_ERROR, "Request validation failed", _request_id(request), details
        )
        return JSONResponse(status_code=422, content=response.model_dump(mode="json"))

    @app.exception_handler(KalhasDomainError)
    async def handle_domain_error(request: Request, exc: KalhasDomainError) -> JSONResponse:
        details: list[ErrorDetail] = []
        if isinstance(exc, InvalidScenarioError):
            status, code, message = (
                422,
                ErrorCode.VALIDATION_ERROR,
                "Scenario is semantically invalid",
            )
            details = [
                ErrorDetail(loc=issue.loc, message=issue.message) for issue in exc.report.issues
            ]
        elif isinstance(
            exc,
            (
                ScenarioNotFoundError,
                WorldNotFoundError,
                CampaignNotFoundError,
                RunNotFoundError,
                RunTrajectoryExecutionNotFoundError,
                RunTrajectoryReplayManifestNotFoundError,
                RunMetricObservationNotFoundError,
                DomainPackNotFoundError,
                DomainPackBindingNotFoundError,
                DomainCapabilityDeclarationNotFoundError,
                DomainMetricObservationNotFoundError,
                DomainStateModelNotFoundError,
                DomainStateTransitionNotFoundError,
                EvaluationProfileNotFoundError,
                WorldUncertaintyModelNotFoundError,
                CampaignDecisionPolicyNotFoundError,
                RealizationRunTrajectoryExecutionNotFoundError,
                RealizationRunTrajectoryReplayManifestNotFoundError,
                RealizationRunMetricObservationNotFoundError,
            ),
        ):
            status, code, message = 404, ErrorCode.NOT_FOUND, str(exc)
        elif isinstance(
            exc,
            (
                ScenarioAlreadyExistsError,
                CampaignAlreadyExistsError,
                DomainPackAlreadyExistsError,
                DomainPackBindingAlreadyExistsError,
                DomainCapabilityDeclarationAlreadyExistsError,
                DomainMetricObservationAlreadyExistsError,
                DomainStateModelAlreadyExistsError,
                DomainStateTransitionAlreadyExistsError,
                RunTrajectoryExecutionAlreadyExistsError,
                RunTrajectoryReplayManifestConflictError,
                RunMetricObservationAlreadyExistsError,
                UnsupportedRuntimeVersionError,
                TrajectoryPlansRequiredError,
                EvaluationProfileAlreadyExistsError,
                EvaluationProfileDeclarationAfterCompilationError,
                WorldUncertaintyModelAlreadyExistsError,
                WorldUncertaintyModelDeclarationAfterCompilationError,
                CampaignDecisionPolicyAlreadyExistsError,
                WorldRealizationSamplingError,
                RealizationRunTrajectoryExecutionAlreadyExistsError,
                RealizationRunTrajectoryReplayManifestConflictError,
                RealizationReplayManifestConflictError,
                RealizationRunMetricObservationAlreadyExistsError,
            ),
        ):
            status, code, message = 409, ErrorCode.CONFLICT, str(exc)
        elif isinstance(
            exc,
            (
                WorldScenarioMismatchError,
                CampaignPreparationError,
                MalformedWorldError,
                DomainCapabilityNotFoundError,
                DomainCapabilityInputKeyMismatchError,
                DomainMetricObservationMetricNotFoundError,
                DomainMetricObservationStateFieldNotFoundError,
                DomainMetricObservationNonNumericFieldError,
                DomainStateTransitionValuesError,
                EvaluationProfileObjectiveNotFoundError,
                EvaluationProfileMetricNotFoundError,
                EvaluationProfileIncompleteCoverageError,
                EvaluationProfileReachTargetRequiredError,
                EvaluationProfileToleranceRuleError,
                EvaluationProfileInvalidScaleError,
                EvaluationProfileValidationError,
                WorldUncertaintyModelValidationError,
                CampaignDecisionPolicyValidationError,
                InvalidTrajectoryDraftError,
            ),
        ):
            status, code, message = 422, ErrorCode.VALIDATION_ERROR, str(exc)
        elif isinstance(
            exc,
            (
                CampaignNotRunningError,
                CampaignNotCompleteError,
                RunNotPlannedError,
                RunNotCompleteError,
            ),
        ):
            status, code, message = 409, ErrorCode.INVALID_STATE, str(exc)
        elif isinstance(exc, ReplayHashMismatchError):
            status, code, message = 409, ErrorCode.CONFLICT, str(exc)
        elif isinstance(
            exc,
            (
                RunInputIntegrityError,
                DomainCapabilityDeclarationIntegrityError,
                DomainMetricObservationIntegrityError,
                DomainStateModelIntegrityError,
                DomainStateTransitionIntegrityError,
                WorldSnapshotIntegrityError,
                RunTrajectoryExecutionIntegrityError,
                TrajectoryReplayMismatchError,
                CampaignTrajectoryMatrixIntegrityError,
                RunMetricObservationIntegrityError,
                CampaignMetricObservationMatrixIntegrityError,
                CampaignMetricStatisticsIntegrityError,
                EvaluationProfileIntegrityError,
                CampaignObjectiveEvaluationMatrixIntegrityError,
                CampaignOutcomeDistributionMatrixIntegrityError,
                WorldUncertaintyModelIntegrityError,
                WorldRealizationIntegrityError,
                CampaignDecisionBriefIntegrityError,
                CampaignDecisionComparisonIntegrityError,
                CampaignDecisionPolicyIntegrityError,
                CampaignWorldRealizationMatrixIntegrityError,
                RealizationRunTrajectoryExecutionIntegrityError,
                RealizationRunMetricObservationIntegrityError,
                RealizationCampaignTrajectoryMatrixIntegrityError,
                RealizationCampaignMetricObservationMatrixIntegrityError,
                RealizationCampaignMetricStatisticsIntegrityError,
            ),
        ):
            status, code, message = 409, ErrorCode.INTEGRITY_ERROR, str(exc)
        else:
            status, code, message = 500, ErrorCode.INTERNAL_ERROR, "Internal server error"
        response = _error_response(code, message, _request_id(request), details)
        return JSONResponse(status_code=status, content=response.model_dump(mode="json"))

    @app.exception_handler(CampaignTransitionError)
    async def handle_campaign_transition(
        request: Request, exc: CampaignTransitionError
    ) -> JSONResponse:
        response = _error_response(ErrorCode.INVALID_STATE, str(exc), _request_id(request))
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error while serving %s %s", request.method, request.url.path)
        response = _error_response(
            ErrorCode.INTERNAL_ERROR, "Internal server error", _request_id(request)
        )
        return JSONResponse(status_code=500, content=response.model_dump(mode="json"))
