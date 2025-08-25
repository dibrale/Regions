import pytest
import asyncio
import time

from modules.dynamic_rag import (
    DatabaseManager,
    DocumentChunk,
    ChunkMetadata,
)


@pytest.fixture
def db_manager(tmp_path):
    """Fixture to create a temporary database for each test"""
    db_file = tmp_path / "test.db"
    manager = DatabaseManager(str(db_file))
    yield manager
    if db_file.exists():
        db_file.unlink()


@pytest.mark.asyncio
async def test_database_operations(db_manager):
    """Test basic database operations"""
    # Create test chunk
    metadata = ChunkMetadata(
        timestamp=int(time.time()),
        actors=["test_user", "system"],
        chunk_id="test_chunk_1",
        document_id="test_doc_1"
    )
    
    chunk = DocumentChunk(
        content="This is a test chunk for database operations.",
        metadata=metadata,
        embedding=[0.1, 0.2, 0.3, 0.4, 0.5]  # Mock embedding
    )
    
    # Test storing chunk
    assert await db_manager.store_chunk(chunk)
    
    # Test retrieving chunks
    chunks = await db_manager.get_all_chunks()
    assert len(chunks) == 1, "Failed to retrieve chunks"
    
    # Verify chunk data
    retrieved_chunk = chunks[0]
    assert retrieved_chunk.content == chunk.content
    assert retrieved_chunk.metadata.actors == chunk.metadata.actors
    assert retrieved_chunk.embedding == chunk.embedding
    
    # Test deleting chunk
    assert chunk.chunk_hash is not None
    assert await db_manager.delete_chunk(chunk.chunk_hash)
    
    # Verify deletion
    assert len(await db_manager.get_all_chunks()) == 0
