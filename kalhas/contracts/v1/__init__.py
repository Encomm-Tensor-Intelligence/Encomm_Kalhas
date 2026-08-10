"""KALHAS public contracts, version 1.

Contracts in this module are immutable. Any change that breaks wire
compatibility (renamed fields, removed fields, changed types, new required
fields) requires a new ``kalhas.contracts.v2`` module and a new API version
segment.
"""

from kalhas.contracts.v1.activity import OperationalActivityEvent, OperationalActivityKind
from kalhas.contracts.v1.campaign import (
    CampaignSpec,
    CampaignState,
    CampaignStatus,
)
from kalhas.contracts.v1.campaign_trajectory import (
    CampaignTrajectoryMatrix,
    CampaignTrajectoryRunCell,
)
from kalhas.contracts.v1.common import ApiErrorResponse, ErrorCode, ErrorDetail, RuntimeMode
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunState, RunStatus
from kalhas.contracts.v1.health import HealthResponse
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import (
    ClarificationQuestion,
    ContextBundle,
    ScenarioSeed,
    ScenarioSpec,
    ValidationReport,
)
from kalhas.contracts.v1.shared import SCHEMA_VERSION, VersionedContract
from kalhas.contracts.v1.simulation import (
    DecisionBrief,
    EvidenceReference,
    OutcomeVector,
    RunEvent,
)
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.strategy import StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.system_info import SystemInfoResponse
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
    StrategyTrajectoryTransitionReference,
)
from kalhas.contracts.v1.trajectory_execution import (
    RunStateTrajectoryResult,
    RunTrajectoryAttemptRecord,
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import (
    UncertaintyDefinition,
    WorldManifest,
    WorldVersion,
)

API_VERSION = "1"

PUBLIC_CONTRACTS: tuple[type[VersionedContract], ...] = (
    ScenarioSpec,
    ContextBundle,
    ClarificationQuestion,
    ValidationReport,
    WorldManifest,
    WorldVersion,
    UncertaintyDefinition,
    StrategyRequest,
    StrategyCandidate,
    CampaignSpec,
    CampaignStatus,
    ScenarioSeed,
    RunEvent,
    OutcomeVector,
    EvidenceReference,
    DecisionBrief,
    RunPlan,
    RunStatus,
    ReplayManifest,
    RunInputIntegrityManifest,
    DomainPackManifest,
    DomainPackBinding,
    DomainCapabilityDeclaration,
    DomainStateModel,
    DomainStateTransition,
    OperationalActivityEvent,
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanRequest,
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
    CampaignTrajectoryMatrix,
    DomainMetricObservationBinding,
)
__all__ = [
    "API_VERSION",
    "ApiErrorResponse",
    "CampaignSpec",
    "CampaignState",
    "CampaignStatus",
    "CampaignTrajectoryMatrix",
    "CampaignTrajectoryRunCell",
    "ClarificationQuestion",
    "ContextBundle",
    "DecisionBrief",
    "DomainCapabilityDeclaration",
    "DomainMetricObservationBinding",
    "DomainPackBinding",
    "DomainPackManifest",
    "DomainStateFieldDefinition",
    "DomainStateModel",
    "DomainStateTransition",
    "ErrorCode",
    "ErrorDetail",
    "EvidenceReference",
    "HealthResponse",
    "OperationalActivityEvent",
    "OperationalActivityKind",
    "OutcomeVector",
    "PUBLIC_CONTRACTS",
    "ReplayManifest",
    "RunEvent",
    "RunInputIntegrityManifest",
    "RunPlan",
    "RunState",
    "RunStateTrajectoryResult",
    "RunStatus",
    "RunTrajectoryAttemptRecord",
    "RunTrajectoryExecution",
    "RunTrajectoryReplayManifest",
    "RuntimeMode",
    "SCHEMA_VERSION",
    "ScenarioSeed",
    "ScenarioSpec",
    "StateValueKind",
    "StrategyCandidate",
    "StrategyRequest",
    "StrategyTrajectoryPlan",
    "StrategyTrajectoryPlanDraft",
    "StrategyTrajectoryPlanRequest",
    "StrategyTrajectoryTransitionReference",
    "SystemInfoResponse",
    "UncertaintyDefinition",
    "ValidationReport",
    "VersionedContract",
    "WorldManifest",
    "WorldVersion",
]
