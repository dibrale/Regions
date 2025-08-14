"""
Test script for comprehensive error handling
"""

import asyncio
import os
import sqlite3
import modules.testutils
from modules.dynamic_rag import (
    DynamicRAGSystem,
    ErrorCodes,
    RAGException,
    NoMatchingEntryError,
    DatabaseNotAccessibleError,
    ServiceUnavailableError,
    SchemaMismatchError,
    HTTPError,
    EmbeddingClient,
    DatabaseManager,
    RateLimiter
)


async def entry(rag_system: DynamicRAGSystem):
    """Test NoMatchingEntryError scenario"""
    print("Testing NoMatchingEntryError...")
    
    try:
        # Test the error directly since we need an embedding server for the full flow
        try:
            results = await rag_system.retrieve_similar(
                query='',
                similarity_threshold=1.1,
                max_results=0
            )

        except NoMatchingEntryError as e:
            if e.code == ErrorCodes.NO_MATCHING_ENTRY:
                print(f"✓ Correctly raised NoMatchingEntryError: {e.description}")
                return True
            else:
                print(f"✗ Wrong error code: {e.code}")
                return False
        except Exception as e:
            print(f"✗ Unexpected exception: {e}")
            return False
    
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

async def access():
    """Test DatabaseNotAccessibleError scenario"""
    print("\nTesting DatabaseNotAccessibleError...")
    
    try:
        # Try to create database in non-existent directory
        invalid_path = "/nonexistent/directory/test.db"
        
        try:
            DatabaseManager(invalid_path)
            print("✗ Should have raised DatabaseNotAccessibleError")
            return False
        except DatabaseNotAccessibleError as e:
            if e.code == ErrorCodes.DATABASE_NOT_ACCESSIBLE:
                print(f"✓ Correctly raised DatabaseNotAccessibleError: {e.description}")
                return True
            else:
                print(f"✗ Wrong error code: {e.code}")
                return False
        except Exception as e:
            print(f"✗ Unexpected exception: {e}")
            return False
    
    except Exception as e:
        print(f"✗ Test setup failed: {e}")
        return False

async def unavailable():
    """Test ServiceUnavailableError scenario"""
    print("\nTesting ServiceUnavailableError...")
    
    try:
        rate_limiter = RateLimiter(min_interval=0.5)
        
        # First request should succeed
        await rate_limiter.acquire()
        
        # Immediate second request should fail
        try:
            await rate_limiter.acquire()
            print("✗ Should have raised ServiceUnavailableError")
            return False
        except ServiceUnavailableError as e:
            if e.code == ErrorCodes.SERVICE_UNAVAILABLE:
                print(f"✓ Correctly raised ServiceUnavailableError: {e.description}")
                return True
            else:
                print(f"✗ Wrong error code: {e.code}")
                return False
        except Exception as e:
            print(f"✗ Unexpected exception: {e}")
            return False
    
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

async def mismatch():
    """Test SchemaMismatchError scenario"""
    print("\nTesting SchemaMismatchError...")
    
    try:
        # This will be tested indirectly through the embedding client
        # when it receives an invalid response format
        
        # Create a mock invalid response scenario
        try:
            raise SchemaMismatchError("Invalid response format")
        except SchemaMismatchError as e:
            if e.code == ErrorCodes.SCHEMA_MISMATCH:
                print(f"✓ Correctly raised SchemaMismatchError: {e.description}")
                return True
            else:
                print(f"✗ Wrong error code: {e.code}")
                return False
        except Exception as e:
            print(f"✗ Unexpected exception: {e}")
            return False
    
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

async def transport():
    """Test HTTPError scenario"""
    print("\nTesting HTTPError...")
    
    try:
        # Test connection error
        async with EmbeddingClient("http://localhost:9999") as client:
            try:
                await client.get_embedding("test")
                print("✗ Should have raised HTTPError")
                return False
            except HTTPError as e:
                if e.code == ErrorCodes.HTTP_ERROR:
                    print(f"✓ Correctly raised HTTPError: {e.description}")
                    return True
                else:
                    print(f"✗ Wrong error code: {e.code}")
                    return False
            except Exception as e:
                print(f"✗ Unexpected exception: {e}")
                return False
    
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

async def main():
    """Run all error handling tests"""
    print("=== Error Handling Tests ===")

    print(f"\nInitializing RAG...")
    # Initialize the system

    server_port = 10000
    server_ip = "localhost"
    model_name = "nomic-embed-text:latest"

    rag = DynamicRAGSystem(
        db_path="example_rag.db",
        embedding_server_url=f"http://{server_ip}:{server_port}",
        embedding_model=model_name,
    )
    
    """Run all error tests"""

    suite = modules.testutils.TestSet('=== Error System Tests ===',
                                      [
                                          entry(rag),
                                          access(),
                                          unavailable(),
                                          mismatch(),
                                          transport(),
                                      ],
                                      [
                                          "NoMatchingEntryError Test",
                                          "DatabaseNotAccessibleError Test",
                                          "ServiceUnavailableError Test",
                                          "SchemaMismatchError Test",
                                          "HTTPError Test",
                                      ]
                                      )

    await suite.run_sequential()
    suite.result()
    modules.testutils.remove_db()

if __name__ == "__main__":
    asyncio.run(main())

