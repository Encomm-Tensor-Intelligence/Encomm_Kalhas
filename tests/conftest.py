"""Shared fixtures for KALHAS tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from kalhas.api.app import create_app


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """A TestClient bound to the KALHAS application."""
    with TestClient(create_app()) as test_client:
        yield test_client
