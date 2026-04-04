import pytest
import httpx
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, Mock, patch

# Adjust sys.path to import from agent_fleet if needed
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_fleet.datahub_wrapper.main import app, _DYNAMIC_SCHEMA_CACHE

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.asyncio
async def test_lifespan_success():
    # Mock successful DataHub response
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json = Mock(return_value={
        "data": {
            "__type": {
                "enumValues": [
                    {"name": "DATASET"},
                    {"name": "DASHBOARD"},
                    {"name": "CHART"}
                ]
            }
        }
    })
    mock_response.raise_for_status = Mock()

    with patch("httpx.AsyncClient.post", return_value=mock_response):
        async with app.router.lifespan_context(app):
            # Check if the cache was updated correctly
            from agent_fleet.datahub_wrapper.main import _DYNAMIC_SCHEMA_CACHE
            assert "DATASET, DASHBOARD, CHART" in _DYNAMIC_SCHEMA_CACHE
            assert "Valid DataHub Entity Types" in _DYNAMIC_SCHEMA_CACHE

@pytest.mark.asyncio
async def test_lifespan_failure():
    # Mock failed DataHub response
    mock_response = AsyncMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Error", request=AsyncMock(), response=AsyncMock(status_code=500)
    )

    with patch("httpx.AsyncClient.post", side_effect=httpx.RequestError("Connection failed", request=AsyncMock())):
        async with app.router.lifespan_context(app):
            # Check if the cache falls back correctly
            from agent_fleet.datahub_wrapper.main import _DYNAMIC_SCHEMA_CACHE
            assert "Fallback: DATASET, DASHBOARD, CHART, DATA_FLOW, DATA_JOB" in _DYNAMIC_SCHEMA_CACHE
