"""PAN v0.1 deterministic compartment-flow mechanism (H29-S04).

This module owns the actual PAN v0.1 transition algorithm: exact input
validation, the integer/rational transition-count arithmetic, and the
assembly of the verified ``DomainMechanismStepResult``. It is pack-owned
implementation data below ``kalhas/domain_packs/pan/``; the domain-neutral
kernel never imports it. The module is pure: no filesystem, network,
provider, database, environment, clock, subprocess, dynamic-import, RNG,
or mutable-global access exists anywhere in it, and no wall-clock or
platform value is read at any point.

Declared quantities and units
-----------------------------

State (all exact non-negative built-in integers, unit ``persons``):
``population_total`` N, ``susceptible`` S, ``exposed`` E,
``infectious`` I, ``hospitalized`` H, ``intensive_care`` C,
``recovered`` R, ``deceased`` D.  Exact conservation holds:
``N == S + E + I + H + C + R + D``.  ``D`` is absorbing.

Action: ``intervention_intensity_bps`` i, an exact built-in integer in
``[0, 10000]`` (unit ``basis-points``).  It is a declared conditional
input only; the pack never selects, recommends, or optimizes it.

Immutable configuration (exact built-in integers): rate parameters
``transmission_bps`` t, ``exposed_progression_bps`` p,
``hospital_admission_bps`` a_h, ``infectious_recovery_bps`` r_i,
``icu_admission_bps`` a_c, ``hospital_recovery_bps`` r_h,
``icu_mortality_bps`` m_c, ``icu_recovery_bps`` r_c and
``compliance_bps`` k, each in ``[0, 10000]``; capacities
``hospital_capacity`` K_h and ``icu_capacity`` K_c, non-negative.  The
configuration is fixed by the mechanism specification and copied exactly
into every request; a changed configuration under the same identity is
rejected.  The timestep is exactly one day.

Declared equations (exact integer/rational arithmetic only; no
authoritative value ever passes through binary floating point)
---------------------------------------------------------------

``R(x, y)`` denotes round-to-nearest with ties-to-even of the exact
rational ``x / y`` computed with pure integer arithmetic (positive
integer denominator, non-negative numerator), implemented by
:func:`round_half_even`.  Each named count quantization below is one
declared quantization boundary of the mechanism specification with
quantum ``1`` and unit ``persons``.

1. Effective intervention-adjusted transmission, with
   ``P = i * k`` (exact integer product bounded by ``10**8``)::

       E_tx = R(t * (10**8 - P), 10**8)

   ``E_tx`` is non-increasing as ``i`` increases (monotone numerator in
   a monotone rounding rule); ``k = 0`` gives ``E_tx == t`` exactly for
   every ``i``; ``i = k = 10000`` gives ``E_tx == 0``.

2. Transmission ``S -> E`` (mass-action on the pre-step infectious
   compartment), with denominator ``N * 10**4``::

       n_1 = min(S, R(S * I * E_tx, N * 10**4))

   If ``N == 0`` or ``E_tx == 0`` or ``S == 0`` or ``I == 0`` the count
   is declared to be ``0`` without evaluating the quotient, so a zero
   infectious population produces exactly zero new exposures and a
   zero susceptible population can never be exceeded.
3. Progression ``E -> I``::

       n_2 = min(E, R(E * p, 10**4))
4. Capacity-bounded hospital admission ``I -> H``::

       n_3 = min(I, R(I * a_h, 10**4), K_h - H)
5. Infectious recovery ``I -> R``, from the remaining infectious
   pool after admissions::

       n_4 = min(I - n_3, R(I * r_i, 10**4))
6. Capacity-bounded ICU escalation ``H -> C``::

       n_5 = min(H, R(H * a_c, 10**4), K_c - C)
7. Hospital recovery ``H -> R``, from the remaining hospitalized
   pool after escalation::

       n_6 = min(H - n_5, R(H * r_h, 10**4))
8. Intensive-care mortality ``C -> D``::

       n_7 = min(C, R(C * m_c, 10**4))
9. Intensive-care recovery ``C -> R``, from the remaining ICU pool
   after mortality::

       n_8 = min(C - n_7, R(C * r_c, 10**4))

Event and remaining-pool semantics
----------------------------------

The events run in exactly the declared order ``(transmission,
progression, hospital_admission, infectious_recovery, icu_escalation,
hospital_recovery, icu_mortality, icu_recovery)``.  Every candidate
count uses only the pre-step state and the explicitly documented
remaining-source pool of its own event: pools are ``(S, E, I, I - n_3,
H, H - n_5, C, C - n_7)`` in event order, and each count never exceeds
its pool.  Capacity bounds use pre-step occupancy (no earlier event of
this step adds to the hospital or ICU before its admission/escalation
event, and occupancy never exceeds capacity at input validation, so the
declared bounds ``K_h - H`` and ``K_c - C`` are non-negative).  New
inflows never cascade: newly exposed individuals do not progress, newly
infectious individuals are not admitted, and newly admitted individuals
do not escalate within the same step, because every candidate count is
sized from the pre-step source count only.  Capacity overflow remains
in its source compartment; nothing is deleted, clipped silently, or
repaired.

The next state is::

    S' = S - n_1
    E' = E - n_2 + n_1
    I' = I - n_3 - n_4 + n_2
    H' = H + n_3 - n_5 - n_6
    C' = C + n_5 - n_7 - n_8
    R' = R + n_4 + n_6 + n_8
    D' = D + n_7
    N' = N

so the population is exactly conserved, every compartment stays
non-negative, and the deceased compartment is absorbing.  No
stochastic draw exists anywhere: PAN v0.1 is fully deterministic and
``exogenous_inputs`` must be exactly empty.  There is no hidden
tolerance, floating-point epsilon, random tie-break, or unordered
reduction; the only reduction is the declared per-event
round-to-nearest ties-to-even count quantization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.domain_mechanism import (
    DomainMechanismSpec,
    DomainMechanismStepRequest,
    DomainMechanismStepResult,
    MechanismEmissionRecord,
    MechanismEvidenceRecord,
)
from kalhas.contracts.v1.model_pack import ModelPackReleaseProfile

#: Declared implementation identity of this mechanism (recorded in the
#: platform identity of the specification built by ``pack.py``).
IMPLEMENTATION_ID = "kalhas-pan-compartment-flow-implementation"
IMPLEMENTATION_VERSION = "0.1.0"

#: Declared solver identity: the integer sequential event solver below.
SOLVER_ID = "kalhas-pan-integer-sequential-solver"
SOLVER_VERSION = "0.1.0"

#: The declared output label carried in the step evidence.
DECLARED_OUTPUT_LABEL = "conditional_modeled_outcomes"

#: The declared unit of every emitted modeled quantity.
EMISSION_UNIT = "persons"

#: The exact declared state key set, in canonical declaration order.
STATE_KEYS: tuple[str, ...] = (
    "population_total",
    "susceptible",
    "exposed",
    "infectious",
    "hospitalized",
    "intensive_care",
    "recovered",
    "deceased",
)

#: The absorbing state key.
ABSORBING_KEY = "deceased"

#: The exact declared action key set.
ACTION_KEYS: tuple[str, ...] = ("intervention_intensity_bps",)

#: Basis-point configuration keys (rates and compliance), in order.
BASIS_POINT_CONFIGURATION_KEYS: tuple[str, ...] = (
    "transmission_bps",
    "exposed_progression_bps",
    "hospital_admission_bps",
    "infectious_recovery_bps",
    "icu_admission_bps",
    "hospital_recovery_bps",
    "icu_mortality_bps",
    "icu_recovery_bps",
    "compliance_bps",
)

#: Capacity configuration keys, in order.
CAPACITY_CONFIGURATION_KEYS: tuple[str, ...] = ("hospital_capacity", "icu_capacity")

#: The exact declared configuration key set, in canonical order.
CONFIGURATION_KEYS: tuple[str, ...] = (
    "transmission_bps",
    "exposed_progression_bps",
    "hospital_admission_bps",
    "infectious_recovery_bps",
    "icu_admission_bps",
    "hospital_recovery_bps",
    "icu_mortality_bps",
    "icu_recovery_bps",
    "hospital_capacity",
    "icu_capacity",
    "compliance_bps",
)

#: The declared event order of the v0.1 mechanism.
EVENT_IDS: tuple[str, ...] = (
    "transmission",
    "progression",
    "hospital_admission",
    "infectious_recovery",
    "icu_escalation",
    "hospital_recovery",
    "icu_mortality",
    "icu_recovery",
)

#: The frozen mechanism protocol version accepted by this pack.
MECHANISM_PROTOCOL_VERSION: Literal["1.0.0"] = "1.0.0"

#: Inclusive upper bound of every basis-point quantity.
BPS_MAX = 10_000

#: Scale of the intervention-adjusted transmission equation (10**8).
_TRANSMISSION_SCALE = BPS_MAX * BPS_MAX

#: Basis-point scale of the per-event rate equations.
_RATE_SCALE = BPS_MAX

#: Schema version stamped on every built v1 contract.
_SCHEMA_VERSION = "1.0.0"


class PanDomainPackError(ValueError):
    """The single typed rejection of the PAN v0.1 pack.

    Raised for every invalid request: wrong contract type, foreign or
    malformed identity, non-empty exogenous input, wrong schema
    identity, changed configuration, and any state/action value that
    fails exact-key, exact-type, range, conservation, or capacity
    validation.  Nothing is ever normalized, repaired, coerced, or
    silently corrected.
    """


@dataclass(frozen=True)
class PanTransition:
    """The complete deterministic outcome of one PAN v0.1 transition.

    ``counts`` are the eight declared transition counts in event order;
    ``source_pools`` are the eight remaining-source pool sizes the
    events were bound by, in the same order; ``next_state`` is the
    conserved next state in declared key order.
    """

    counts: tuple[int, ...]
    source_pools: tuple[int, ...]
    next_state: dict[str, int]


def round_half_even(numerator: int, denominator: int) -> int:
    """Round the exact rational ``numerator / denominator`` half-to-even.

    Pure integer arithmetic: no binary floating point participates at
    any point.  Requires a positive denominator and a non-negative
    numerator (every declared use site satisfies both); anything else
    fails closed with :class:`PanDomainPackError`.  Exact halves always
    resolve to the even neighbour, as declared.
    """
    if denominator <= 0:
        raise PanDomainPackError("rounding denominator must be positive")
    if numerator < 0:
        raise PanDomainPackError("rounding numerator must be non-negative")
    quotient, remainder = divmod(numerator, denominator)
    twice_remainder = remainder * 2
    if twice_remainder > denominator:
        return quotient + 1
    if twice_remainder < denominator:
        return quotient
    if quotient % 2 == 0:
        return quotient
    return quotient + 1


def effective_transmission_bps(
    transmission_bps: int, intervention_intensity_bps: int, compliance_bps: int
) -> int:
    """The declared intervention/compliance-adjusted transmission rate.

    ``R(t * (10**8 - i * k), 10**8)`` in exact integer arithmetic.
    Non-increasing in the intervention intensity for fixed compliance;
    exactly ``t`` when compliance is zero; exactly zero at maximum
    intervention with full compliance.
    """
    return round_half_even(
        transmission_bps * (_TRANSMISSION_SCALE - intervention_intensity_bps * compliance_bps),
        _TRANSMISSION_SCALE,
    )


def _require_exact_int(value: object, name: str) -> int:
    """Return ``value`` only when it is an exact built-in ``int``.

    Booleans are ``bool`` at exact type identity and are rejected, as
    are floats, strings, and arbitrary objects.  Nothing is coerced.
    """
    if type(value) is not int:
        raise PanDomainPackError(f"{name} must be an exact built-in integer")
    return value


def _require_non_negative_int(value: object, name: str) -> int:
    number = _require_exact_int(value, name)
    if number < 0:
        raise PanDomainPackError(f"{name} must be non-negative")
    return number


def _require_exact_key_set(payload: Mapping[str, object], keys: tuple[str, ...], name: str) -> None:
    """Fail closed unless the payload has exactly the declared keys."""
    if set(payload.keys()) != set(keys):
        raise PanDomainPackError(f"{name} must contain exactly the declared keys")


def validate_state_payload(
    payload: Mapping[str, object], configuration: Mapping[str, int]
) -> dict[str, int]:
    """Validate one PAN v0.1 state payload exactly and return its values.

    Rejects missing and extra keys, booleans used as integers, floats
    and strings, negative counts, broken population conservation, and
    hospital/ICU occupancy above the declared capacity.  The returned
    mapping is a fresh copy in declared key order; the input is never
    mutated.
    """
    _require_exact_key_set(payload, STATE_KEYS, "state payload")
    values = {key: _require_non_negative_int(payload[key], f"state {key}") for key in STATE_KEYS}
    compartment_sum = sum(values[key] for key in STATE_KEYS if key != "population_total")
    if values["population_total"] != compartment_sum:
        raise PanDomainPackError("state population conservation is broken")
    if values["hospitalized"] > configuration["hospital_capacity"]:
        raise PanDomainPackError("hospitalized exceeds declared hospital capacity")
    if values["intensive_care"] > configuration["icu_capacity"]:
        raise PanDomainPackError("intensive_care exceeds declared ICU capacity")
    return values


def validate_action_payload(payload: Mapping[str, object]) -> int:
    """Validate one PAN v0.1 action payload exactly and return its value.

    The action is exactly ``intervention_intensity_bps``: an exact
    built-in integer in ``[0, 10000]``.  Missing keys, extra keys,
    booleans, floats, strings, and out-of-range values are rejected.
    """
    _require_exact_key_set(payload, ACTION_KEYS, "action payload")
    intensity = _require_exact_int(
        payload["intervention_intensity_bps"], "action intervention_intensity_bps"
    )
    if intensity < 0 or intensity > BPS_MAX:
        raise PanDomainPackError("action intervention_intensity_bps must be in [0, 10000]")
    return intensity


def validate_configuration_payload(
    payload: Mapping[str, object], spec_configuration: Mapping[str, object]
) -> dict[str, int]:
    """Validate one PAN v0.1 configuration payload exactly.

    The payload must contain exactly the declared keys with exact
    built-in integer values (basis-point rates and compliance in
    ``[0, 10000]``, non-negative capacities) and must be canonically
    equal to the immutable configuration of the mechanism
    specification; a changed configuration under the same identity is
    rejected.  The returned mapping is a fresh validated copy.
    """
    _require_exact_key_set(payload, CONFIGURATION_KEYS, "configuration payload")
    values: dict[str, int] = {}
    for key in CONFIGURATION_KEYS:
        number = _require_exact_int(payload[key], f"configuration {key}")
        if key in BASIS_POINT_CONFIGURATION_KEYS and (number < 0 or number > BPS_MAX):
            raise PanDomainPackError(f"configuration {key} must be in [0, 10000]")
        if key in CAPACITY_CONFIGURATION_KEYS and number < 0:
            raise PanDomainPackError(f"configuration {key} must be non-negative")
        values[key] = number
    if canonical_json(dict(payload)) != canonical_json(dict(spec_configuration)):
        raise PanDomainPackError("configuration differs from the mechanism specification")
    return values


def validate_request_against_authorities(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    profile: ModelPackReleaseProfile,
) -> None:
    """Validate every request identity field against the pack authorities.

    Verifies the mechanism-spec and release-profile references, the six
    copied state/action/configuration schema identity fields, the
    recomputed state/action/configuration payload hashes, the
    self-covering request content hash, and that the exogenous input is
    exactly empty (PAN v0.1 declares no stochastic draw).  Any mismatch
    raises :class:`PanDomainPackError`; nothing is repaired.
    """
    if (
        request.mechanism_spec_id != spec.identifier
        or request.mechanism_spec_content_hash != spec.content_hash
    ):
        raise PanDomainPackError("request references a foreign mechanism specification")
    if (
        request.release_profile_id != profile.identifier
        or request.release_profile_content_hash != profile.content_hash
    ):
        raise PanDomainPackError("request references a foreign release profile")
    if (
        request.state_schema_id != spec.state_schema_id
        or request.state_schema_hash != spec.state_schema_hash
    ):
        raise PanDomainPackError("request state schema identity is foreign")
    if (
        request.action_schema_id != spec.action_schema_id
        or request.action_schema_hash != spec.action_schema_hash
    ):
        raise PanDomainPackError("request action schema identity is foreign")
    if (
        request.configuration_schema_id != spec.configuration_schema_id
        or request.configuration_schema_hash != spec.configuration_schema_hash
    ):
        raise PanDomainPackError("request configuration schema identity is foreign")
    if request.configuration_hash != spec.configuration_hash:
        raise PanDomainPackError(
            "request configuration hash is not the declared mechanism configuration identity"
        )
    if request.exogenous_inputs:
        raise PanDomainPackError("PAN v0.1 accepts no exogenous input")
    for name, payload, declared_hash in (
        ("state", request.state_payload, request.state_hash),
        ("action", request.action_payload, request.action_hash),
        ("configuration", request.configuration_payload, request.configuration_hash),
    ):
        if sha256_hex(canonical_json(dict(payload))) != declared_hash:
            raise PanDomainPackError(f"request {name} payload hash does not match its content")
    dumped: dict[str, object] = request.model_dump(mode="json")
    dumped.pop("content_hash")
    if sha256_hex(canonical_json(dumped)) != request.content_hash:
        raise PanDomainPackError("request content hash does not match its content")


def compute_transition(
    state: Mapping[str, int], action_value: int, configuration: Mapping[str, int]
) -> PanTransition:
    """Run the declared eight-event sequential compartment flow.

    Implements exactly the equations, event order, and remaining-pool
    semantics documented in this module's docstring, in pure integer
    arithmetic.  The inputs must already be validated (non-negative,
    conserved, within capacity); the returned next state is exactly
    conserved and non-negative.
    """
    susceptible = state["susceptible"]
    exposed = state["exposed"]
    infectious = state["infectious"]
    hospitalized = state["hospitalized"]
    intensive_care = state["intensive_care"]
    population_total = state["population_total"]

    effective_bps = effective_transmission_bps(
        configuration["transmission_bps"],
        action_value,
        configuration["compliance_bps"],
    )

    # Event 1: transmission S -> E, mass-action on the pre-step
    # infectious compartment; declared zero when any factor is zero
    # (this also avoids a zero population denominator).
    if population_total == 0 or effective_bps == 0 or susceptible == 0 or infectious == 0:
        new_exposed = 0
    else:
        new_exposed = min(
            susceptible,
            round_half_even(
                susceptible * infectious * effective_bps,
                population_total * _RATE_SCALE,
            ),
        )
    remaining_susceptible = susceptible - new_exposed

    # Event 2: progression E -> I, from the untouched pre-step exposed pool.
    new_infectious = min(
        exposed,
        round_half_even(exposed * configuration["exposed_progression_bps"], _RATE_SCALE),
    )
    remaining_exposed = exposed - new_infectious

    # Event 3: capacity-bounded hospital admission I -> H.
    hospital_admissions = min(
        infectious,
        round_half_even(infectious * configuration["hospital_admission_bps"], _RATE_SCALE),
        configuration["hospital_capacity"] - hospitalized,
    )
    remaining_infectious = infectious - hospital_admissions

    # Event 4: infectious recovery I -> R, from the remaining pool.
    infectious_recoveries = min(
        remaining_infectious,
        round_half_even(infectious * configuration["infectious_recovery_bps"], _RATE_SCALE),
    )
    remaining_infectious -= infectious_recoveries

    # Event 5: capacity-bounded ICU escalation H -> C, from the
    # untouched pre-step hospitalized pool (admissions entered H but
    # never cascade into escalation within the same step).
    icu_admissions = min(
        hospitalized,
        round_half_even(hospitalized * configuration["icu_admission_bps"], _RATE_SCALE),
        configuration["icu_capacity"] - intensive_care,
    )
    remaining_hospitalized = hospitalized - icu_admissions

    # Event 6: hospital recovery H -> R, from the remaining pool.
    hospital_recoveries = min(
        remaining_hospitalized,
        round_half_even(hospitalized * configuration["hospital_recovery_bps"], _RATE_SCALE),
    )
    remaining_hospitalized -= hospital_recoveries

    # Event 7: intensive-care mortality C -> D, from the untouched pool.
    icu_deaths = min(
        intensive_care,
        round_half_even(intensive_care * configuration["icu_mortality_bps"], _RATE_SCALE),
    )
    remaining_intensive_care = intensive_care - icu_deaths

    # Event 8: intensive-care recovery C -> R, from the remaining pool.
    icu_recoveries = min(
        remaining_intensive_care,
        round_half_even(intensive_care * configuration["icu_recovery_bps"], _RATE_SCALE),
    )

    counts = (
        new_exposed,
        new_infectious,
        hospital_admissions,
        infectious_recoveries,
        icu_admissions,
        hospital_recoveries,
        icu_deaths,
        icu_recoveries,
    )
    source_pools = (
        susceptible,
        exposed,
        infectious,
        infectious - hospital_admissions,
        hospitalized,
        hospitalized - icu_admissions,
        intensive_care,
        intensive_care - icu_deaths,
    )
    next_state = {
        "population_total": population_total,
        "susceptible": remaining_susceptible,
        "exposed": remaining_exposed + new_exposed,
        "infectious": remaining_infectious + new_infectious,
        "hospitalized": hospitalized + hospital_admissions - icu_admissions - hospital_recoveries,
        "intensive_care": intensive_care + icu_admissions - icu_deaths - icu_recoveries,
        "recovered": (
            state["recovered"] + infectious_recoveries + hospital_recoveries + icu_recoveries
        ),
        "deceased": state["deceased"] + icu_deaths,
    }
    return PanTransition(counts=counts, source_pools=source_pools, next_state=next_state)


def _finalize_self_hashed[ModelT: BaseModel](
    model_type: type[ModelT], payload: dict[str, object]
) -> ModelT:
    """Build one frozen content-hashed contract from a fresh payload.

    Validates provisionally with a placeholder digest, computes the
    canonical self-covering hash over the JSON-mode dump minus the
    ``content_hash`` field itself (the repository's single hash rule),
    and revalidates with the final digest.  The payload dictionary is
    consumed and mutated by this helper; callers always pass a fresh
    literal.  Purely in-memory and deterministic.
    """
    payload["content_hash"] = "0" * 64
    provisional = model_type.model_validate(payload)
    dumped: dict[str, object] = provisional.model_dump(mode="json")
    dumped.pop("content_hash")
    payload["content_hash"] = sha256_hex(canonical_json(dumped))
    return model_type.model_validate(payload)


def _build_emissions(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    state: Mapping[str, int],
    transition: PanTransition,
) -> tuple[MechanismEmissionRecord, ...]:
    """Build the ordered synthetic modeled-quantity emissions.

    Positions 0-7 carry the eight declared transition counts (the two
    admission emissions additionally carry the post-admission
    occupancies); position 8 carries the final hospital and ICU
    occupancies.  Identifiers derive only from the request identity and
    the sequence position.
    """
    (
        new_exposed,
        new_infectious,
        hospital_admissions,
        infectious_recoveries,
        icu_admissions,
        hospital_recoveries,
        icu_deaths,
        icu_recoveries,
    ) = transition.counts
    payloads: list[dict[str, object]] = [
        {"event_id": "transmission", "new_exposures": new_exposed},
        {"event_id": "progression", "new_infectious": new_infectious},
        {
            "event_id": "hospital_admission",
            "hospital_admissions": hospital_admissions,
            "hospital_occupancy_after_admission": (state["hospitalized"] + hospital_admissions),
        },
        {"event_id": "infectious_recovery", "infectious_recoveries": infectious_recoveries},
        {
            "event_id": "icu_escalation",
            "icu_admissions": icu_admissions,
            "icu_occupancy_after_escalation": state["intensive_care"] + icu_admissions,
        },
        {"event_id": "hospital_recovery", "hospital_recoveries": hospital_recoveries},
        {"event_id": "icu_mortality", "deaths": icu_deaths},
        {"event_id": "icu_recovery", "icu_recoveries": icu_recoveries},
        {
            "emission_kind": "occupancy",
            "hospital_occupancy": transition.next_state["hospitalized"],
            "icu_occupancy": transition.next_state["intensive_care"],
        },
    ]
    records: list[MechanismEmissionRecord] = []
    for position, payload in enumerate(payloads):
        records.append(
            _finalize_self_hashed(
                MechanismEmissionRecord,
                {
                    "identifier": f"pan-v01:{request.identifier}:emission:{position}",
                    "sequence_position": position,
                    "emission_schema_id": spec.emission_schema_id,
                    "emission_schema_hash": spec.emission_schema_hash,
                    "content_hash": "0" * 64,
                    "payload": payload,
                    "unit": EMISSION_UNIT,
                },
            )
        )
    return tuple(records)


def _build_evidence(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    state: Mapping[str, int],
    transition: PanTransition,
) -> tuple[MechanismEvidenceRecord, ...]:
    """Build the ordered deterministic mechanism evidence.

    Records the declared output label, the declared event-order
    identity, before/after conservation totals, one record per declared
    event with its transition count and remaining-source pool, and the
    zero stochastic-draw declaration.  Construction is observationally
    pure: nothing here mutates state, request, or configuration.
    """
    compartment_sum_before = sum(state[key] for key in STATE_KEYS if key != "population_total")
    next_state = transition.next_state
    compartment_sum_after = sum(next_state[key] for key in STATE_KEYS if key != "population_total")
    payloads: list[dict[str, object]] = [
        {
            "label": DECLARED_OUTPUT_LABEL,
            "mechanism_id": spec.mechanism_id,
            "step_index": request.step_index,
            "stochastic_draws": 0,
        },
        {
            "declared_event_order": list(EVENT_IDS),
            "event_count": len(EVENT_IDS),
        },
        {
            "population_total_before": state["population_total"],
            "population_total_after": next_state["population_total"],
            "compartment_sum_before": compartment_sum_before,
            "compartment_sum_after": compartment_sum_after,
            "conservation_delta": next_state["population_total"] - state["population_total"],
        },
    ]
    for position, event_id in enumerate(EVENT_IDS):
        pool = transition.source_pools[position]
        payloads.append(
            {
                "event_id": event_id,
                "event_position": position,
                "transition_count": transition.counts[position],
                "source_pool_before": pool,
                "source_pool_remaining": pool - transition.counts[position],
            }
        )
    records: list[MechanismEvidenceRecord] = []
    for position, payload in enumerate(payloads):
        records.append(
            _finalize_self_hashed(
                MechanismEvidenceRecord,
                {
                    "identifier": f"pan-v01:{request.identifier}:evidence:{position}",
                    "sequence_position": position,
                    "evidence_schema_id": spec.evidence_schema_id,
                    "evidence_schema_hash": spec.evidence_schema_hash,
                    "content_hash": "0" * 64,
                    "payload": payload,
                },
            )
        )
    return tuple(records)


def run_pan_step(
    request: DomainMechanismStepRequest,
    spec: DomainMechanismSpec,
    profile: ModelPackReleaseProfile,
) -> DomainMechanismStepResult:
    """Execute one verified PAN v0.1 mechanism step.

    Validates the request identity against the specification and
    release-profile authorities, validates the state, action, and
    configuration payloads exactly, runs the deterministic transition,
    and assembles the complete verified result with self-covering
    canonical hashes.  The request and every nested container are never
    mutated; the returned result shares no container with them.
    """
    if type(request) is not DomainMechanismStepRequest:
        raise PanDomainPackError("request must be the exact v1 step-request contract")
    validate_request_against_authorities(request, spec, profile)
    configuration = validate_configuration_payload(
        request.configuration_payload, spec.configuration
    )
    state = validate_state_payload(request.state_payload, configuration)
    action_value = validate_action_payload(request.action_payload)
    transition = compute_transition(state, action_value, configuration)
    emissions = _build_emissions(request, spec, state, transition)
    evidence = _build_evidence(request, spec, state, transition)
    next_state_payload = {key: transition.next_state[key] for key in STATE_KEYS}
    return _finalize_self_hashed(
        DomainMechanismStepResult,
        {
            "identifier": f"pan-v01:{request.identifier}:result",
            "tenant_id": profile.tenant_id,
            "schema_version": _SCHEMA_VERSION,
            "request_id": request.identifier,
            "request_content_hash": request.content_hash,
            "mechanism_spec_id": spec.identifier,
            "mechanism_spec_content_hash": spec.content_hash,
            "release_profile_id": profile.identifier,
            "release_profile_content_hash": profile.content_hash,
            "world_version_id": request.world_version_id,
            "world_content_hash": request.world_content_hash,
            "seed_id": request.seed_id,
            "seed_content_hash": request.seed_content_hash,
            "realization_id": request.realization_id,
            "realization_content_hash": request.realization_content_hash,
            "run_id": request.run_id,
            "step_index": request.step_index,
            "next_state_schema_id": spec.state_schema_id,
            "next_state_schema_hash": spec.state_schema_hash,
            "next_state_payload": next_state_payload,
            "next_state_hash": sha256_hex(canonical_json(next_state_payload)),
            "emissions": emissions,
            "evidence": evidence,
            "content_hash": "0" * 64,
        },
    )
