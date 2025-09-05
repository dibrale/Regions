"""
Test script for comprehensive error handling using pytest
"""
import pytest
from unittest.mock import AsyncMock, patch

from modules.dynamic_rag import (
    DynamicRAGSystem,
    ErrorCodes,
    NoMatchingEntryError,
    DatabaseNotAccessibleError,
    SchemaMismatchError,
    HTTPError
)
from database_manager import DatabaseManager
from embedding_client import EmbeddingClient


@pytest.fixture
def rag_system(tmp_path):
    """Fixture to create a DynamicRAGSystem instance with temporary database"""
    db_path = tmp_path / "test_rag.db"
    rag = DynamicRAGSystem(
        db_path=str(db_path),
        embedding_server_url="http://localhost:10000",
        embedding_model="nomic-embed-text:latest",
    )
    yield rag

@pytest.mark.asyncio
async def test_no_matching_entry_error(rag_system):
    """Test NoMatchingEntryError scenario"""
    with pytest.raises(NoMatchingEntryError) as exc_info:
        await rag_system.retrieve_similar(
            query='',
            similarity_threshold=1.1,  # Invalid threshold (>1.0)
            max_results=0
        )

    assert exc_info.value.code == ErrorCodes.NO_MATCHING_ENTRY
    assert "Error 1001: No matching entry found for similarity threshold 1.1" in str(exc_info.value)

@pytest.mark.parametrize("invalid_path", [
    "/nonexistent/directory/test.db",
    "C:\\nonexistent\\directory\\test.db"  # Windows-style path
])
def test_database_not_accessible_error(invalid_path):
    """Test DatabaseNotAccessibleError scenario"""
    with pytest.raises(DatabaseNotAccessibleError) as exc_info:
        DatabaseManager(invalid_path)

    assert exc_info.value.code == ErrorCodes.DATABASE_NOT_ACCESSIBLE
    assert "Error 1002: Database not accessible: Failed to initialize database: unable" in str(exc_info.value)

'''
@pytest.mark.asyncio
async def test_service_unavailable_error():
    """Test ServiceUnavailableError scenario"""
    rate_limiter = RateLimiter(min_interval=0.5)

    # First request should succeed
    await rate_limiter.acquire()

    # Immediate second request should fail
    with pytest.raises(ServiceUnavailableError) as exc_info:
        await rate_limiter.acquire()

    assert exc_info.value.code == ErrorCodes.SERVICE_UNAVAILABLE
    assert "rate limit exceeded" in str(exc_info.value)
'''
def test_schema_mismatch_error():
    """Test SchemaMismatchError scenario"""
    with pytest.raises(SchemaMismatchError) as exc_info:
        raise SchemaMismatchError("Invalid response format")

    assert exc_info.value.code == ErrorCodes.SCHEMA_MISMATCH
    assert "Invalid response format" in str(exc_info.value)

@pytest.mark.asyncio
async def test_http_error():
    """Test HTTPError scenario using mock"""
    # Mock EmbeddingClient to simulate connection failure
    with patch('modules.dynamic_rag.EmbeddingClient') as mock_class:
        mock_instance = AsyncMock()
        mock_instance.get_embedding.side_effect = HTTPError(
            ErrorCodes.HTTP_ERROR,
            "Connection refused"
        )
        mock_class.return_value = mock_instance

        with pytest.raises(HTTPError) as exc_info:
            async with EmbeddingClient("http://localhost:9999") as client:
                await client.get_embedding("test")

        assert exc_info.value.code == ErrorCodes.HTTP_ERROR
        assert "Error 1005: HTTP error 0: Connection error: Cannot connect to host localhost:9999" in str(exc_info.value)