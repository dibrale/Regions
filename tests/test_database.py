"""
Test script for database layer functionality
"""

import asyncio
import time
import json
import modules.testutils
from modules.dynamic_rag import (
    DatabaseManager, 
    DocumentChunk, 
    ChunkMetadata, 
    ServiceUnavailableError,
    DatabaseNotAccessibleError,
    RateLimiter
)
from modules.testutils import remove_db


async def rate():
    """Test rate limiting functionality"""
    print("Testing rate limiter...")
    
    rate_limiter = RateLimiter(min_interval=0.5)
    
    # First request should succeed
    try:
        await rate_limiter.acquire()
        print("✓ First request succeeded")
    except ServiceUnavailableError:
        print("✗ First request failed unexpectedly")
        return False
    
    # Immediate second request should fail
    try:
        await rate_limiter.acquire()
        print("✗ Second immediate request succeeded (should have failed)")
        return False
    except ServiceUnavailableError:
        print("✓ Second immediate request correctly failed with rate limit")
    
    # Wait and try again
    await asyncio.sleep(0.6)
    try:
        await rate_limiter.acquire()
        print("✓ Request after waiting succeeded")
    except ServiceUnavailableError:
        print("✗ Request after waiting failed unexpectedly")
        return False
    
    return True

async def operations():
    """Test basic database operations"""
    print("\nTesting database operations...")
    
    # Initialize database manager
    db_manager = DatabaseManager("example_rag.db")
    
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
    
    try:
        # Test storing chunk
        success = await db_manager.store_chunk(chunk)
        if success:
            print("✓ Chunk stored successfully")
        else:
            print("✗ Failed to store chunk")
            return False
        
        # Wait for rate limit
        await asyncio.sleep(0.6)
        
        # Test retrieving chunks
        chunks = await db_manager.get_all_chunks()
        if chunks and len(chunks) > 0:
            print(f"✓ Retrieved {len(chunks)} chunks")
            
            # Verify chunk data
            retrieved_chunk = chunks[0]
            if (retrieved_chunk.content == chunk.content and 
                retrieved_chunk.metadata.actors == chunk.metadata.actors and
                retrieved_chunk.embedding == chunk.embedding):
                print("✓ Chunk data integrity verified")
            else:
                print("✗ Chunk data integrity check failed")
                return False
        else:
            print("✗ Failed to retrieve chunks")
            return False
        
        # Wait for rate limit
        await asyncio.sleep(0.6)
        
        # Test deleting chunk
        if chunk.chunk_hash:
            deleted = await db_manager.delete_chunk(chunk.chunk_hash)
            if deleted:
                print("✓ Chunk deleted successfully")
            else:
                print("✗ Failed to delete chunk")
                return False
        
        return True
        
    except Exception as e:
        print(f"✗ Database operation failed: {e}")
        return False

async def concurrent():
    """Test that concurrent requests are properly denied"""
    print("\nTesting concurrent request denial...")
    
    db_manager = DatabaseManager("example_rag.db")
    
    # Create test chunk
    metadata = ChunkMetadata(
        timestamp=int(time.time()),
        actors=["test_user"],
    )
    
    chunk = DocumentChunk(
        content="Concurrent test chunk",
        metadata=metadata,
        embedding=[0.1, 0.2, 0.3]
    )
    
    # Try to make concurrent requests
    async def store_chunk_task():
        try:
            await db_manager.store_chunk(chunk)
            return "success"
        except ServiceUnavailableError:
            return "rate_limited"
        except Exception as e:
            return f"error: {e}"
    
    # Launch multiple concurrent tasks
    tasks = [store_chunk_task() for _ in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Count results
    success_count = sum(1 for r in results if r == "success")
    rate_limited_count = sum(1 for r in results if r == "rate_limited")
    
    print(f"Results: {success_count} success, {rate_limited_count} rate limited")
    
    if success_count == 1 and rate_limited_count == 2:
        print("✓ Concurrent request denial working correctly")
        return True
    else:
        print("✗ Concurrent request denial not working as expected")
        return False

async def main():
    """Run all DB layer tests"""

    suite = modules.testutils.TestSet('=== Database Layer Tests ===',
                                      [
                                          rate(),
                                          operations(),
                                          concurrent()
                                      ],
                                      [
                                          "Rate Limit Test",
                                          "Basic Database Operations Test",
                                          "Concurrent Requests Test"
                                      ]
                                      )

    await suite.run_sequential()
    suite.result()
    remove_db()

if __name__ == "__main__":
    asyncio.run(main())

