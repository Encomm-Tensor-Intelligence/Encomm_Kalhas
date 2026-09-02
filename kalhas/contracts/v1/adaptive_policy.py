"""Closed adaptive-policy contracts (Phase 28, D28-01).

Phase 28 adds the **closed adaptive-policy surface** for the additive
runtime version ``4.0.0``. ``AdaptivePolicyDraft`` is the **untrusted**
declarative input: logical action identifiers, initial/fallback choices,
ordered draft rules over a closed condition AST, and the frozen
state-machine declarations (minimum dwell, cooldown, global switch
budget). It carries no authority of any kind - no tenant or identifier,
no schema/runtime version, no campaign/scenario/world identity, no
hashes, no trajectory-plan or strategy identity, no timestamps, no
metadata, no state values, and no callback/expression/provider surface.
``AdaptivePolicy`` is the immutable KALHAS-bound ``VersionedContract``
authority: the same closed language resolved against an immutable
observation-binding catalog and immutable trajectory-plan bindings, with
campaign/world/scenario provenance, a stable logical ``policy_id``, a
semantic ``policy_version``, a self-covering ``content_hash``, the
deterministic caller-supplied ``bound_at``, and finite JSON-compatible
metadata.

The condition language is a **closed AST**: leaves compare one logical
observation reference with one exact finite threshold using exactly the
operators ``lt``, ``lte``, ``eq``, ``gte``, ``gt`` (equality is exact -
no tolerance, coercion, clipping, negation, or approximate comparison is
expressible), and compound nodes are only bounded ``all``/``any``
fan-outs of 2 through 8 children. Every condition carries a non-empty
condition identifier; identifiers are globally unique within one tree;
direct children are canonically ordered by condition identifier; depth
is at most 4 and a tree holds at most 64 nodes. Unknown node kinds fail
through the discriminated union. Nothing in this module evaluates any
condition: evaluation, the policy state machine, and binding services
belong to later Phase 28 slices.

Frozen ADR-004/D28-01 state-machine semantics, **declared here and
executed nowhere**: initialization is not a switch and consumes no
budget; with minimum dwell ``N`` an action installed at decision ``d``
first permits a different action at ``d + N``; cooldown ``N`` after a
switch at ``s`` permits the next switch at ``s + N + 1``; global and
per-rule budgets decrement only on an actual action change; the
fallback action cannot bypass dwell, cooldown, or budgets; exhausted
eligibility retains the current action with deterministic evidence; the
first matching *eligible* rule wins; and an ineligible match never
prevents deterministic evaluation of later rules. Hysteresis is always
two explicit mandatory trees - structurally equivalent ``enter`` and
``retain`` trees express "no hysteresis", and neither tree is ever
inferred or synthesized from the other.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, Strict, model_validator

from kalhas.contracts.v1.shared import AwareDatetime, JsonValue, VersionedContract
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.world_realization import (
    IdentifierString,
    Sha256Hex,
    _is_exact_finite_numeric,
)

#: A strict non-negative integer: floats, strings, and booleans are
#: rejected before any coercion, and the value must be >= 0.
StrictNonNegativeInt = Annotated[int, Strict(), Field(ge=0)]

#: The closed set of comparison operators; equality is exact.
ComparisonOperator = Literal["lt", "lte", "eq", "gte", "gt"]

#: The closed set of numeric value kinds a comparison can observe.
NumericValueKind = Literal["integer", "number"]

#: The closed set of missing-value behaviors; never inferred from truthiness.
MissingBehaviorLiteral = Literal["false", "error"]

#: Maximum condition-AST depth (root counts as depth 1).
MAX_CONDITION_DEPTH = 4

#: Maximum total node count per condition tree.
MAX_CONDITION_NODES = 64

#: Closed compound fan-out bounds, inclusive.
MIN_COMPOUND_FAN_OUT = 2
MAX_COMPOUND_FAN_OUT = 8

#: Maximum rules per policy and maximum logical actions per catalog.
MAX_POLICY_RULES = 64
MAX_ACTION_COUNT = 64

_SEMANTIC_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


class ConditionComparisonLeaf(BaseModel):
    """One closed numeric comparison against one logical observation.

    Compares the referenced observation's value with one exact finite
    ``threshold`` using exactly one closed operator. ``missing_behavior``
    is explicit (exactly ``"false"`` or ``"error"``) and is never
    inferred. Integer comparisons require an exact ``int`` threshold;
    number comparisons accept an exact finite ``int`` or ``float``.
    Booleans, strings, containers, NaN, and Infinity fail before any
    coercion. No tolerance, clipping, negation, or callback is
    expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["comparison"]
    condition_id: IdentifierString
    observation_id: IdentifierString
    observed_value_kind: NumericValueKind
    unit: str | None = None
    operator: ComparisonOperator
    threshold: int | float
    missing_behavior: MissingBehaviorLiteral

    @model_validator(mode="before")
    @classmethod
    def _raw_threshold_matches_value_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_threshold = data.get("threshold")
        if not _is_exact_finite_numeric(raw_threshold):
            raise ValueError("threshold must be an exact finite numeric value")
        if data.get("observed_value_kind") == "integer" and not isinstance(raw_threshold, int):
            raise ValueError("integer comparisons require an exact int threshold")
        return data


class ConditionAllNode(BaseModel):
    """Bounded ``all`` compound node: conjunction over 2-8 children."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["all"]
    condition_id: IdentifierString
    children: tuple[ConditionNode, ...] = Field(
        min_length=MIN_COMPOUND_FAN_OUT, max_length=MAX_COMPOUND_FAN_OUT
    )

    @model_validator(mode="after")
    def _children_canonical(self) -> ConditionAllNode:
        _check_direct_children_canonical(self)
        return self


class ConditionAnyNode(BaseModel):
    """Bounded ``any`` compound node: disjunction over 2-8 children."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["any"]
    condition_id: IdentifierString
    children: tuple[ConditionNode, ...] = Field(
        min_length=MIN_COMPOUND_FAN_OUT, max_length=MAX_COMPOUND_FAN_OUT
    )

    @model_validator(mode="after")
    def _children_canonical(self) -> ConditionAnyNode:
        _check_direct_children_canonical(self)
        return self


def _check_direct_children_canonical(node: ConditionAllNode | ConditionAnyNode) -> None:
    """Direct compound children are canonically ordered and unique."""
    child_ids = [child.condition_id for child in node.children]
    if child_ids != sorted(child_ids):
        raise ValueError("compound children must be canonically ordered ascending by condition_id")
    if len(set(child_ids)) != len(child_ids):
        raise ValueError("duplicate condition_id among direct compound children")


#: The closed discriminated union of condition nodes. Unknown node kinds
#: fail through the discriminator; there is no escape hatch.
type ConditionNode = Annotated[
    ConditionComparisonLeaf | ConditionAllNode | ConditionAnyNode,
    Field(discriminator="kind"),
]

#: Mandatory rule condition roles. Both trees are always explicit; the
#: contract never infers or synthesizes either one from the other.
type EnterCondition = ConditionNode
type RetainCondition = ConditionNode


def _condition_depth(node: ConditionNode) -> int:
    if isinstance(node, ConditionComparisonLeaf):
        return 1
    return 1 + max(_condition_depth(child) for child in node.children)


def _condition_node_count(node: ConditionNode) -> int:
    if isinstance(node, ConditionComparisonLeaf):
        return 1
    return 1 + sum(_condition_node_count(child) for child in node.children)


def _collect_condition_ids(node: ConditionNode, into: list[str]) -> None:
    """Visit every node and record its condition identifier in visit order."""
    into.append(node.condition_id)
    if not isinstance(node, ConditionComparisonLeaf):
        for child in node.children:
            _collect_condition_ids(child, into)


def _validate_condition_tree(root: ConditionNode) -> None:
    """Closed-resource invariants for one whole condition tree."""
    _check_children_canonical_recursive(root)
    if _condition_depth(root) > MAX_CONDITION_DEPTH:
        raise ValueError(f"condition tree depth exceeds {MAX_CONDITION_DEPTH}")
    if _condition_node_count(root) > MAX_CONDITION_NODES:
        raise ValueError(f"condition tree exceeds {MAX_CONDITION_NODES} nodes")
    visited: list[str] = []
    _collect_condition_ids(root, visited)
    if len(visited) != len(set(visited)):
        raise ValueError(
            "condition identifiers must be globally unique within one tree: "
            f"{len(visited)} nodes carry {len(set(visited))} distinct identifiers"
        )


def _check_children_canonical_recursive(node: ConditionNode) -> None:
    if isinstance(node, ConditionComparisonLeaf):
        return
    _check_direct_children_canonical(node)
    for child in node.children:
        _check_children_canonical_recursive(child)


def _validate_enter_retain_pair(
    enter_condition: ConditionNode, retain_condition: ConditionNode
) -> None:
    """Both mandatory trees are independent; neither implies the other."""
    _validate_condition_tree(enter_condition)
    _validate_condition_tree(retain_condition)


class ObservationBinding(BaseModel):
    """One authoritative copied observation-catalog entry.

    Binds one stable logical ``observation_id`` to one immutable
    ``RuntimeObservationDeclaration`` (identifier and content hash) with
    the copied observed value kind, optional unit, and explicit missing
    behavior. Provenance is copied verbatim from stored records;
    cross-checking these values against the stored declaration belongs
    to the later binding-authority service, never to this contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: IdentifierString
    runtime_observation_declaration_id: IdentifierString
    runtime_observation_declaration_content_hash: Sha256Hex
    observed_value_kind: NumericValueKind
    unit: str | None = None
    missing_behavior: MissingBehaviorLiteral


class TrajectoryPlanBinding(BaseModel):
    """One immutable trajectory-plan binding behind a bound action.

    Carries only authoritative references copied from stored immutable
    records: the ``StrategyTrajectoryPlan`` identifier and content hash
    plus the manifest and state-model identity/hash quadruple. No
    transition or state values, outcomes, callbacks, or executable
    content is expressible.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trajectory_plan_id: IdentifierString
    trajectory_plan_content_hash: Sha256Hex
    manifest_id: IdentifierString
    state_model_identifier: IdentifierString
    state_model_id: IdentifierString
    state_model_content_hash: Sha256Hex


class BoundAdaptiveAction(BaseModel):
    """One immutable bound action of an ``AdaptivePolicy``.

    The logical ``action_id`` together with the exact strategy candidate
    identity/hash and a non-empty canonically ordered tuple of immutable
    trajectory-plan bindings. Bindings are ordered ascending by
    ``(state_model_identifier, trajectory_plan_id)``, hold at most one
    binding per state-model identifier, and never repeat a plan
    identifier.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: IdentifierString
    strategy_candidate_id: IdentifierString
    strategy_content_hash: Sha256Hex
    trajectory_plan_bindings: tuple[TrajectoryPlanBinding, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _bindings_canonical_and_unique(self) -> BoundAdaptiveAction:
        ordering = [
            (binding.state_model_identifier, binding.trajectory_plan_id)
            for binding in self.trajectory_plan_bindings
        ]
        if ordering != sorted(ordering):
            raise ValueError(
                "trajectory-plan bindings must be canonically ordered ascending by "
                "(state_model_identifier, trajectory_plan_id)"
            )
        state_models = [binding.state_model_identifier for binding in self.trajectory_plan_bindings]
        if len(set(state_models)) != len(state_models):
            raise ValueError("at most one trajectory-plan binding per state_model_identifier")
        plan_ids = [binding.trajectory_plan_id for binding in self.trajectory_plan_bindings]
        if len(set(plan_ids)) != len(plan_ids):
            raise ValueError("trajectory-plan identifiers must be unique within one action")
        return self


class AdaptivePolicyRuleDraft(BaseModel):
    """One untrusted draft rule over the closed condition language.

    A non-empty rule identifier, a strict non-negative unique priority,
    the targeted logical action, the two mandatory explicit condition
    trees (entry and retention - structurally equivalent trees express
    "no hysteresis"; neither is ever inferred from the other), and a
    strict non-negative per-rule switch budget.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: IdentifierString
    priority: StrictNonNegativeInt
    target_action_id: IdentifierString
    enter_condition: EnterCondition
    retain_condition: RetainCondition
    per_rule_switch_budget: StrictNonNegativeInt

    @model_validator(mode="after")
    def _condition_trees_bounded(self) -> AdaptivePolicyRuleDraft:
        _validate_enter_retain_pair(self.enter_condition, self.retain_condition)
        return self


class AdaptivePolicyRule(BaseModel):
    """One bound rule of an ``AdaptivePolicy``.

    Same closed shape as the draft rule, but constructed only inside the
    KALHAS-bound immutable policy whose observation-binding catalog gives
    its condition leaves complete exact authority coverage. Deliberately
    a separate class from the draft rule so trusted and untrusted rules
    never share a type surface.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: IdentifierString
    priority: StrictNonNegativeInt
    target_action_id: IdentifierString
    enter_condition: EnterCondition
    retain_condition: RetainCondition
    per_rule_switch_budget: StrictNonNegativeInt

    @model_validator(mode="after")
    def _condition_trees_bounded(self) -> AdaptivePolicyRule:
        _validate_enter_retain_pair(self.enter_condition, self.retain_condition)
        return self


def _comparison_leaf_observation_refs(
    node: ConditionNode, into: list[ConditionComparisonLeaf]
) -> None:
    if isinstance(node, ConditionComparisonLeaf):
        into.append(node)
        return
    for child in node.children:
        _comparison_leaf_observation_refs(child, into)


def _rules_canonically_ordered(rules: tuple[Any, ...]) -> None:
    priorities = [rule.priority for rule in rules]
    if priorities != sorted(priorities):
        raise ValueError("rules must be stored ascending by priority")
    if len(set(priorities)) != len(priorities):
        raise ValueError("rule priorities must be unique")
    rule_ids = [rule.rule_id for rule in rules]
    if len(set(rule_ids)) != len(rule_ids):
        raise ValueError("rule identifiers must be unique")


class AdaptivePolicyDraft(BaseModel):
    """Untrusted declarative draft of one adaptive policy.

    Exactly the authoring intent and nothing more: a request identifier,
    the canonical non-empty tuple of logical action identifiers (at most
    64, ascending, unique), the initial and fallback action choices, the
    priority-ordered draft rules (at most 64), and the strict
    non-negative minimum-dwell/cooldown/global-switch-budget
    declarations. It cannot carry tenant or contract identity, schema or
    runtime versions, campaign/scenario/world identity, hashes,
    trajectory-plan or strategy identity, timestamps, metadata, state
    values, or any callback/expression/provider surface. The future
    binding service must revalidate draft payloads even when an instance
    arrived through a validator-bypassing path.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: IdentifierString
    actions: tuple[IdentifierString, ...] = Field(min_length=1, max_length=MAX_ACTION_COUNT)
    initial_action_id: IdentifierString
    fallback_action_id: IdentifierString
    rules: tuple[AdaptivePolicyRuleDraft, ...] = Field(max_length=MAX_POLICY_RULES)
    minimum_dwell_steps: StrictNonNegativeInt
    cooldown_steps: StrictNonNegativeInt
    global_switch_budget: StrictNonNegativeInt

    @model_validator(mode="after")
    def _actions_rules_and_membership(self) -> AdaptivePolicyDraft:
        if list(self.actions) != sorted(self.actions):
            raise ValueError("logical action identifiers must be canonically ordered ascending")
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("logical action identifiers must be unique")
        if self.initial_action_id not in self.actions:
            raise ValueError("initial_action_id must exist in the action catalog")
        if self.fallback_action_id not in self.actions:
            raise ValueError("fallback_action_id must exist in the action catalog")
        _rules_canonically_ordered(self.rules)
        for rule in self.rules:
            if rule.target_action_id not in self.actions:
                raise ValueError("rule target_action_id must exist in the action catalog")
        return self


class AdaptivePolicy(VersionedContract):
    """Immutable KALHAS-bound adaptive-policy authority for runtime 4.0.0.

    Binds the closed condition language to complete immutable authority:
    campaign/scenario/world provenance with the world content hash, the
    exact runtime literal ``4.0.0``, a stable logical ``policy_id`` with
    a semantic ``policy_version``, the non-empty canonically ordered
    observation-binding catalog, the non-empty canonically ordered tuple
    of immutable bound actions, the initial and fallback choices, the
    priority-ordered bound rules, the frozen state-machine declarations,
    a self-covering ``content_hash``, the deterministic caller-supplied
    ``bound_at``, and finite JSON-compatible metadata. Every condition
    leaf resolves through the observation-binding catalog with exact
    value-kind/unit/missing-behavior agreement, and every binding is
    used, so policy identity contains only complete used authority. The
    policy holds no mutable runtime state, observations, decisions,
    switches, outcomes, recommendations, or evaluation results; stored-
    declaration verification and execution belong to later slices.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    campaign_id: IdentifierString
    scenario_id: IdentifierString
    world_version_id: IdentifierString
    world_content_hash: Sha256Hex
    runtime_version: Literal["4.0.0"]
    policy_id: IdentifierString
    policy_version: str = Field(pattern=_SEMANTIC_VERSION_PATTERN)
    observation_bindings: tuple[ObservationBinding, ...] = Field(min_length=1)
    actions: tuple[BoundAdaptiveAction, ...] = Field(min_length=1, max_length=MAX_ACTION_COUNT)
    initial_action_id: IdentifierString
    fallback_action_id: IdentifierString
    rules: tuple[AdaptivePolicyRule, ...] = Field(max_length=MAX_POLICY_RULES)
    minimum_dwell_steps: StrictNonNegativeInt
    cooldown_steps: StrictNonNegativeInt
    global_switch_budget: StrictNonNegativeInt
    content_hash: Sha256Hex
    bound_at: AwareDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _catalogs_rules_and_complete_coverage(self) -> AdaptivePolicy:
        binding_ids = [binding.observation_id for binding in self.observation_bindings]
        if binding_ids != sorted(binding_ids):
            raise ValueError("observation bindings must be canonically ordered ascending")
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("observation_binding observation_id values must be unique")
        declaration_ids = [
            binding.runtime_observation_declaration_id for binding in self.observation_bindings
        ]
        if len(set(declaration_ids)) != len(declaration_ids):
            raise ValueError("runtime_observation_declaration_id values must be unique")

        action_ids = [action.action_id for action in self.actions]
        if action_ids != sorted(action_ids):
            raise ValueError("bound actions must be canonically ordered ascending by action_id")
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("bound action identifiers must be unique")

        if self.initial_action_id not in action_ids:
            raise ValueError("initial_action_id must exist in the bound action catalog")
        if self.fallback_action_id not in action_ids:
            raise ValueError("fallback_action_id must exist in the bound action catalog")

        _rules_canonically_ordered(self.rules)
        catalog = {binding.observation_id: binding for binding in self.observation_bindings}
        referenced: set[str] = set()
        for rule in self.rules:
            if rule.target_action_id not in action_ids:
                raise ValueError("rule target_action_id must exist in the bound action catalog")
            leaves: list[ConditionComparisonLeaf] = []
            _comparison_leaf_observation_refs(rule.enter_condition, leaves)
            _comparison_leaf_observation_refs(rule.retain_condition, leaves)
            for leaf in leaves:
                binding = catalog.get(leaf.observation_id)
                if binding is None:
                    raise ValueError(
                        f"condition leaf references unknown observation_id {leaf.observation_id!r}"
                    )
                if leaf.observed_value_kind != binding.observed_value_kind:
                    raise ValueError(
                        f"condition leaf value kind disagrees with the observation binding "
                        f"{leaf.observation_id!r}"
                    )
                if leaf.unit != binding.unit:
                    raise ValueError(
                        f"condition leaf unit disagrees with the observation binding "
                        f"{leaf.observation_id!r}"
                    )
                if leaf.missing_behavior != binding.missing_behavior:
                    raise ValueError(
                        f"condition leaf missing behavior disagrees with the observation "
                        f"binding {leaf.observation_id!r}"
                    )
                referenced.add(leaf.observation_id)
        unused = set(catalog) - referenced
        if unused:
            raise ValueError(f"observation bindings unused by any condition leaf: {sorted(unused)}")
        return self

    @model_validator(mode="after")
    def _metadata_contains_no_non_finite(self) -> AdaptivePolicy:
        """Metadata must hold only finite JSON-compatible values."""
        if _contains_non_finite(self.metadata):
            raise ValueError("metadata must contain only finite JSON-compatible values")
        return self
