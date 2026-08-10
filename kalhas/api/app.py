"""FastAPI application factory for KALHAS."""

from fastapi import FastAPI

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.api.errors import register_error_handlers, register_request_id_middleware
from kalhas.api.routes import router
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.version import __version__


def create_app() -> FastAPI:
    """Create and configure the KALHAS FastAPI application.

    The application is standalone and in-memory: a fresh store and fresh
    local mocks are created per app instance. No database, no network, no
    real NEXUS or LEGION integration.
    """
    store = InMemoryScenarioStore()
    app = FastAPI(
        title="KALHAS",
        description=(
            "KALHAS - domain-neutral kernel for versioned world models, uncertainty, "
            "deterministic simulation campaigns, evidence, and replay. Standalone "
            "integration-free foundation: no NEXUS/LEGION integrations, no databases, "
            "no external providers, no live actions. Phase 2 adds the in-memory "
            "scenario/world flow with local deterministic mocks."
        ),
        version=__version__,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.store = store
    app.state.mock_nexus = MockNexusAdapter(store)
    app.state.mock_legion = MockLegionAdapter()
    app.include_router(router)
    register_request_id_middleware(app)
    register_error_handlers(app)
    return app
