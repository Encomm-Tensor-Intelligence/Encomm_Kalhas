"""Pure authoring-candidate identities for the PAN mechanism."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from kalhas.application.domain_pack_registry import manifest_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
)
from kalhas.contracts.v1.domain_pack import DomainPackManifest
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile
from kalhas.domain_packs.pan.mechanism import (
    PanDomainPackError,
    run_pan_step,
    validate_configuration_payload,
)
from kalhas.domain_packs.pan.pack import PanV01DomainPack, _self_covering_hash


class PanCandidateDomainPack:
    """A candidate with its own sealed authorities and the unchanged PAN transition."""

    __slots__ = ("manifest", "mechanism_spec", "release_profile", "mechanism_protocol_version")

    def __init__(
        self,
        manifest: DomainPackManifest,
        spec: DomainMechanismSpec,
        profile: ModelPackReleaseProfile,
    ) -> None:
        self.manifest = manifest
        self.mechanism_spec = spec
        self.release_profile = profile
        self.mechanism_protocol_version: Literal["1.0.0"] = "1.0.0"

    def step(self, request: DomainMechanismStepRequest) -> DomainMechanismStepResult:
        manifest, spec, profile = self.manifest, self.mechanism_spec, self.release_profile
        if (
            type(manifest) is not DomainPackManifest
            or type(spec) is not DomainMechanismSpec
            or type(profile) is not ModelPackReleaseProfile
        ):
            raise PanDomainPackError("candidate authority type invalid")
        try:
            valid = (
                self.mechanism_protocol_version == "1.0.0"
                and manifest_content_hash(manifest) == manifest.content_hash
                and _self_covering_hash(spec) == spec.content_hash
                and _self_covering_hash(profile) == profile.content_hash
                and profile.manifest == manifest
                and profile.mechanism_spec == spec
            )
        except Exception as exc:
            raise PanDomainPackError("candidate authority invalid") from exc
        if not valid:
            raise PanDomainPackError("candidate authority invalid")
        return run_pan_step(request, spec, profile)


def build_pan_candidate_pack(
    *,
    tenant_id: str,
    binding_id: str,
    binding_version: str,
    candidate_index: int,
    configuration: Mapping[str, int],
    declared_at: datetime,
) -> PanCandidateDomainPack:
    """Derive a validated candidate from fresh frozen-release authorities."""
    if type(candidate_index) is not int or candidate_index < 1:
        raise PanDomainPackError("candidate index invalid")
    if type(binding_id) is not str or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", binding_id) is None:
        raise PanDomainPackError("binding id invalid")
    if (
        type(binding_version) is not str
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", binding_version) is None
    ):
        raise PanDomainPackError("binding version invalid")
    validate_configuration_payload(configuration, configuration)
    configuration_data = dict(configuration)
    base = PanV01DomainPack()
    suffix = f"{binding_id}-{binding_version}-{candidate_index}"
    version = f"0.2.{candidate_index}"
    manifest_data = base.manifest.model_dump(mode="python")
    manifest_data.update(
        identifier=f"manifest-kalhas-pan-candidate-{suffix}",
        tenant_id=tenant_id,
        pack_version=version,
        created_at=declared_at,
        description="Authoring candidate; not catalogued.",
        metadata={"decision_support_only": True, "authoring_candidate": True},
        content_hash="0" * 64,
    )
    manifest = DomainPackManifest.model_validate(manifest_data)
    manifest_data["content_hash"] = manifest_content_hash(manifest)
    manifest = DomainPackManifest.model_validate(manifest_data)
    spec_data = base.mechanism_spec.model_dump(mode="python")
    spec_data.update(
        identifier=f"mechanism-spec-kalhas-pan-candidate-{suffix}",
        tenant_id=tenant_id,
        pack_version=version,
        manifest_id=manifest.identifier,
        manifest_content_hash=manifest.content_hash,
        configuration=configuration_data,
        configuration_hash=sha256_hex(canonical_json(configuration_data)),
        declared_at=declared_at,
        metadata={
            "stochastic_draws": 0,
            "exogenous_inputs": "declared_empty",
            "authoring_candidate": True,
        },
        content_hash="0" * 64,
    )
    spec = DomainMechanismSpec.model_validate(spec_data)
    spec_data["content_hash"] = _self_covering_hash(spec)
    spec = DomainMechanismSpec.model_validate(spec_data)
    profile_data = base.release_profile.model_dump(mode="python")
    scope = dict(profile_data["scope"])
    scope["validity_envelope"] = (
        "non_negative_integer_counts, exact_population_conservation, "
        "and occupancy_within_declared_capacity"
    )
    limitations = list(profile_data["limitations"])
    limitations.append(
        {
            "limitation_id": "authoring_candidate_only",
            "statement": "Not catalogued; no assurance, no maturity, and supports no claim.",
        }
    )
    profile_data.update(
        identifier=f"release-profile-kalhas-pan-candidate-{suffix}",
        tenant_id=tenant_id,
        pack_version=version,
        manifest_id=manifest.identifier,
        manifest_content_hash=manifest.content_hash,
        manifest=manifest.model_dump(mode="python"),
        mechanism_spec=spec.model_dump(mode="python"),
        configuration_identity=spec.configuration_hash,
        declared_at=declared_at,
        scope=scope,
        provenance={
            "author_id": "kalhas-authoring",
            "method": "deterministic_authoring_candidate",
            "statement": "Authoring candidate derived from the PAN release for evaluation.",
        },
        intended_uses=[
            {
                "use_id": "authoring_candidate_evaluation",
                "statement": "Evaluation of an authoring candidate.",
                "horizon": "exactly_one_declared_one_day_step",
            }
        ],
        limitations=limitations,
        metadata={
            "stochastic_draws": 0,
            "authoring_candidate": True,
            "binding_id": binding_id,
            "binding_version": binding_version,
            "candidate_index": candidate_index,
        },
        content_hash="0" * 64,
    )
    profile = ModelPackReleaseProfile.model_validate(profile_data)
    profile_data["content_hash"] = _self_covering_hash(profile)
    profile = ModelPackReleaseProfile.model_validate(profile_data)
    return PanCandidateDomainPack(manifest, spec, profile)
