"""Typed safe errors for the causal observation-event surface (H28-S06B2).

These errors cover the pure, read-only runtime-4 causal observation-event
derivation boundary (ADR-004 D28-02/D28-03): strict revalidation of the
caller-owned step draft, authority/integrity verification of the stored
campaign, world, scenario seed, adaptive policy, and observation
declarations, causal-order verification of caller-supplied prior
evidence, deterministic-noise derivation, and the frozen step result. The
service performs no store write and creates no activity event, so there
is no already-exists or not-found retrieval error here - every failure is
atomic and leaves the repository exactly unchanged.

Every public message is safe and generic: it never exposes tenant,
campaign, scenario, world, seed, policy, declaration, observation,
channel, state-model, or state-field identifiers, hashes, steps, values,
thresholds, counts, units, metadata, internal verification reasons, or
validator diagnostics. The validation and integrity error classes retain
an optional internal ``reason`` attribute (for diagnostics only) that is
never part of the public message and never crosses the API boundary. No
arbitrary exception is ever wrapped into a public message, so raw
``ValidationError``, ``TypeError``, ``AttributeError``, ``KeyError``,
``ValueError``, or assertion failures never escape the public surface.
"""

from __future__ import annotations

from kalhas.application.domain_errors import KalhasDomainError


class RuntimeObservationEventValidationError(KalhasDomainError):
    """A caller-owned observation-event derivation input is invalid.

    Raised when a caller-owned input violates a strict rule checked before
    any stored authority is trusted - a wrong-type, subclassed, or
    validator-bypassed step draft, a malformed decision step (bool, float,
    string, or negative), a malformed state collection (non-mapping,
    non-mapping state, wrong canonical state-model authority, a missing,
    extra, foreign, or duplicated state model, a state value that fails
    its declared kind or allowed values), a malformed or absent external
    bundle where one is required, or a stored authority that is missing
    (campaign, scenario, world, seed, adaptive policy, observation
    declaration, or state model). The public message stays generic; the
    optional internal ``reason`` names only the violated class of rule,
    never identifiers, hashes, steps, values, or thresholds.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("Runtime observation event derivation input is invalid")


class RuntimeObservationEventIntegrityError(KalhasDomainError):
    """A stored authority or supplied evidence failed independent verification.

    Raised when a stored record or caller-supplied authority fails its
    strict contract revalidation or its independent ownership/identifier/
    content-hash verification - a validator-bypassed or forged adaptive
    policy, observation declaration, external input bundle, state model,
    or prior observation event; a stored authority whose identity,
    provenance, or policy binding disagrees with the verified campaign,
    world, scenario seed, or policy catalog; or an external bundle entry
    whose declaration, channel, kind, or unit provenance disagrees with
    the stored declaration. Corruption is rejected, never repaired, and
    the public message stays safe and generic.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("Runtime observation event authority failed integrity verification")


class RuntimeObservationEventCausalOrderError(KalhasDomainError):
    """Caller-supplied prior evidence violates the frozen causal contract.

    Raised when prior observation evidence is not exactly the recorded,
    canonically ordered, contiguous decision history this decision step
    requires: future or late events, duplicate coordinates or identifiers,
    reordered or non-contiguous sequence positions, foreign-tenant,
    foreign-world, foreign-seed, undeclared, or forged evidence, terminal
    evidence that can never be decision input, or evidence whose delay,
    availability, source kind, value kind, or unit disagrees with its
    stored declaration. Prior evidence is never sorted, repaired, or
    silently accepted; the derivation fails atomically. The public message
    stays generic.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("Prior observation evidence violates the causal order contract")


class RuntimeObservationEventNoiseError(KalhasDomainError):
    """A deterministic observation-noise derivation failed a safety guard.

    Raised when an additive-uniform noise draw or the quantized
    source-plus-noise sum cannot be represented as an exact finite value
    under the repository's frozen Q64.64 semantics - an out-of-range
    fixed-point value, a noise draw outside the exact stored bounds, or a
    result beyond the finite recordable range. The failure is atomic and
    the public message stays generic; no value, bound, threshold, or hash
    is ever exposed.
    """

    def __init__(
        self,
        tenant_id: str,
        campaign_id: str,
        reason: str | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.campaign_id = campaign_id
        self.reason = reason
        super().__init__("Deterministic observation noise failed a derivation guard")


__all__ = [
    "RuntimeObservationEventCausalOrderError",
    "RuntimeObservationEventIntegrityError",
    "RuntimeObservationEventNoiseError",
    "RuntimeObservationEventValidationError",
]
