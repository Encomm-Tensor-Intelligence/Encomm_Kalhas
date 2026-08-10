"""Pure semantic validation of scenarios.

A scenario may be structurally valid JSON/Pydantic yet semantically
incomplete. Validation never invents numeric values or assumptions: it only
reports blocking omissions as machine-readable issues and raises structured
clarification questions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from kalhas.contracts.v1.scenario import (
    ClarificationQuestion,
    ScenarioSpec,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from kalhas.contracts.v1.shared import AwareDatetime

_BLOCKING_CHECKS: tuple[
    tuple[str, str, str, tuple[str, ...], tuple[str, ...]],
    ...,
] = (
    (
        "missing_objectives",
        "No objectives are declared for this scenario.",
        "Which objectives should this scenario pursue?",
        ("objectives",),
        (),
    ),
    (
        "missing_time_horizon",
        "The declared time horizon has no resolution.",
        "Which temporal resolution should the scenario horizon use?",
        ("time_horizon.resolution",),
        ("step", "day", "week", "month", "year"),
    ),
    (
        "missing_success_metrics",
        "No success metrics are declared for this scenario.",
        "Which metrics define success for this scenario?",
        ("metrics",),
        (),
    ),
    (
        "missing_constraints",
        "No constraints are declared for this scenario.",
        "Which constraints apply to this scenario?",
        ("constraints",),
        (),
    ),
)


@dataclass(frozen=True)
class ScenarioValidationResult:
    """Validation report plus the structured clarification questions raised."""

    report: ValidationReport
    questions: list[ClarificationQuestion]


def validate_scenario(
    scenario: ScenarioSpec,
    *,
    validated_at: AwareDatetime | None = None,
) -> ScenarioValidationResult:
    """Validate a scenario semantically; never invents values.

    ``validated_at`` may be injected for determinism (the compiler passes
    the scenario's own creation time); defaults to the current UTC time.
    """
    issues: list[ValidationIssue] = []
    questions: list[ClarificationQuestion] = []
    now = validated_at if validated_at is not None else datetime.now(UTC)
    missing = _missing_checks(scenario)
    for code, message, prompt, targets, options in _BLOCKING_CHECKS:
        if code not in missing:
            continue
        issues.append(
            ValidationIssue(
                code=code,
                message=message,
                severity=ValidationSeverity.ERROR,
                loc=targets,
            )
        )
        questions.append(
            ClarificationQuestion(
                identifier=f"q-{code}",
                tenant_id=scenario.tenant_id,
                prompt=prompt,
                options=list(options),
                required=True,
                targets=list(targets),
            )
        )
    report = ValidationReport(
        identifier=f"validation-{scenario.identifier}",
        tenant_id=scenario.tenant_id,
        subject_id=scenario.identifier,
        valid=not issues,
        issues=issues,
        validated_at=now,
    )
    return ScenarioValidationResult(report=report, questions=questions)


def _missing_checks(scenario: ScenarioSpec) -> set[str]:
    """Return the codes of every blocking omission found in the scenario."""
    missing: set[str] = set()
    if not scenario.objectives:
        missing.add("missing_objectives")
    if scenario.time_horizon.resolution is None:
        missing.add("missing_time_horizon")
    if not scenario.metrics:
        missing.add("missing_success_metrics")
    if not scenario.constraints:
        missing.add("missing_constraints")
    return missing
