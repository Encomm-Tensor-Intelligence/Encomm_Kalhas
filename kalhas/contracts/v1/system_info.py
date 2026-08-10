"""System information contract (v1)."""

from pydantic import BaseModel, ConfigDict

from kalhas.contracts.v1.common import RuntimeMode

_STANDALONE_NOTE = (
    "KALHAS is a standalone, integration-free foundation: no NEXUS or LEGION "
    "integrations, no databases, no external providers, and no live actions "
    "are wired in this phase."
)


class SystemInfoResponse(BaseModel):
    """Metadata about the running KALHAS instance."""

    model_config = ConfigDict(extra="forbid")

    service: str = "kalhas"
    application_version: str
    api_version: str
    runtime_mode: RuntimeMode
    standalone: bool = True
    note: str = _STANDALONE_NOTE
