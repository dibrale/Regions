"""
Test script for RAG functionality - FIXED VERSION
"""

import asyncio
import logging
import os
import statistics
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dynamic_rag import (
    DynamicRAGSystem,
    NoMatchingEntryError,
    DatabaseNotAccessibleError,
    ServiceUnavailableError,
    HTTPError,
    cosine_similarity
)
from testutils import remove_db


class TestDataGenerator:
    """Generate test data for precision/recall testing"""

    @staticmethod
    def get_test_documents() -> list[dict[str, str | list[str]]]:
        """Get test documents with known semantic relationships"""
        return [
            {
                "content": "Machine learning algorithms can learn patterns from data automatically.",
                "category": "machine_learning",
                "actors": ["researcher", "data_scientist"],
                "doc_id": "ml_doc_1"
            },
            {
                "content": "Deep neural networks are a powerful machine learning technique.",
                "category": "machine_learning",
                "actors": ["ai_engineer", "researcher"],
                "doc_id": "ml_doc_2"
            },
            {
                "content": "Artificial intelligence systems can perform complex reasoning tasks.",
                "category": "artificial_intelligence",
                "actors": ["ai_researcher", "engineer"],
                "doc_id": "ai_doc_1"
            },
            {
                "content": "AI models require large amounts of training data to perform well.",
                "category": "artificial_intelligence",
                "actors": ["data_scientist", "ml_engineer"],
                "doc_id": "ai_doc_2"
            },
            {
                "content": "SQL databases provide structured storage for relational data.",
                "category": "database",
                "actors": ["database_admin", "developer"],
                "doc_id": "db_doc_1"
            },
            {
                "content": "Database indexing improves query performance significantly.",
                "category": "database",
                "actors": ["dba", "backend_developer"],
                "doc_id": "db_doc_2"
            },
            {
                "content": "The weather is sunny today with clear blue skies.",
                "category": "weather",
                "actors": ["meteorologist", "observer"],
                "doc_id": "weather_doc_1"
            },
            {
                "content": "Cooking pasta requires boiling water and adding salt.",
                "category": "cooking",
                "actors": ["chef", "home_cook"],
                "doc_id": "cooking_doc_1"
            }
        ]

    @staticmethod
    def get_test_queries() -> list[dict[str, str | list[str] | int]]:
        """Get test queries with expected relevant categories"""
        return [
            {
                "query": "machine learning techniques",
                "expected_categories": ["machine_learning"],
                "min_results": 2
            },
            {
                "query": "artificial intelligence reasoning",
                "expected_categories": ["artificial_intelligence"],
                "min_results": 2
            },
            {
                "query": "database storage and indexing",
                "expected_categories": ["database"],
                "min_results": 2
            },
            {
                "query": "AI and ML systems",
                "expected_categories": ["machine_learning", "artificial_intelligence"],
                "min_results": 3
            },
            {
                "query": "cooking recipes",
                "expected_categories": ["cooking"],
                "min_results": 1
            }
        ]


@pytest.fixture
def test_rag_system(tmp_path):
    """Create a test RAG system with a temporary database"""
    db_path = str(tmp_path / "test_rag.db")
    rag_system = DynamicRAGSystem(
        db_path=db_path,
        embedding_server_url="http://localhost:10000",
        embedding_model="nomic-embed-text:latest",
        chunk_size=50,
        overlap=10
    )
    return rag_system


@pytest.fixture
def mock_embedding_client():
    """Properly mock the EmbeddingClient async context manager"""
    with patch('dynamic_rag.EmbeddingClient') as mock:
        # Create a mock instance that will be returned when the context manager is entered
        mock_instance = AsyncMock()

        # Set up the get_embedding method
        mock_instance.get_embedding.return_value = [0.1, 0.2, 0.3, 0.4]

        # Configure __aenter__ to return the mock instance when awaited
        mock_instance.__aenter__.return_value = mock_instance

        # Configure __aexit__ to return None when awaited
        mock_instance.__aexit__.return_value = None

        # Make the class itself return the mock instance when called
        mock.return_value = mock_instance

        yield mock_instance  # Yield the instance, not the patch


@pytest.mark.asyncio
async def test_store_document(test_rag_system, mock_embedding_client, caplog):
    """Test document storage with chunking"""
    data = TestDataGenerator.get_test_documents()
    # Store documents
    stored_chunks = []
    for doc in data:
        chunk_hashes = await test_rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=doc["doc_id"],
            chunk_size=50,
            overlap=10
        )
        stored_chunks.extend(chunk_hashes)

    assert len(chunk_hashes) > 0, f"Failed to store document {doc['doc_id']}"
    assert len(stored_chunks) == len(data)  # Assuming 1 chunk per doc with these parameters
    assert "Stored document with 1 chunks" in caplog.text


@pytest.mark.asyncio
async def test_retrieve_similar(test_rag_system, mock_embedding_client):
    """Test similarity-based retrieval"""
    # First store some test documents
    data = TestDataGenerator.get_test_documents()
    for doc in data:
        await test_rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=doc["doc_id"],
            chunk_size=50,
            overlap=10
        )

    # Test retrieval
    results = await test_rag_system.retrieve_similar(
        query="machine learning",
        similarity_threshold=0.3,
        max_results=2
    )

    assert len(results) > 0, "No results found for machine learning query"
    assert all(result.similarity_score >= 0.3 for result in results)
    assert any("machine" in result.chunk.content.lower() for result in results)


@pytest.mark.asyncio
async def test_retrieve_by_actor(test_rag_system, mock_embedding_client):
    """Test actor-based retrieval"""
    # First store some test documents
    data = TestDataGenerator.get_test_documents()
    for doc in data:
        await test_rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=doc["doc_id"],
            chunk_size=50,
            overlap=10
        )

    # Test retrieval
    results = await test_rag_system.retrieve_by_actor(
        actors=["researcher"],
        similarity_threshold=0.1,
        max_results=2
    )

    assert len(results) > 0, "No results found for researcher actor"
    assert all(any("researcher" in actor for actor in result.chunk.metadata.actors)
              for result in results)


@pytest.mark.asyncio
async def test_stats(test_rag_system, mock_embedding_client):
    """Test system statistics"""
    # Store documents
    data = TestDataGenerator.get_test_documents()
    for doc in data:
        await test_rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=doc["doc_id"],
            chunk_size=50,
            overlap=10
        )

    # Get stats
    stats = await test_rag_system.get_stats()

    assert stats["total_chunks"] == len(data)
    assert stats["unique_documents"] == len(data)
    assert stats["unique_actors"] > 0
    assert "researcher" in stats["actors"]


@pytest.mark.asyncio
async def test_update_chunk(test_rag_system, mock_embedding_client):
    """Test chunk update functionality"""
    # Store a test chunk
    chunk_hashes = await test_rag_system.store_document(
        content="Original content",
        actors=["test_actor"],
        document_id="test_doc",
        chunk_size=50,
        overlap=10
    )
    original_hash = chunk_hashes[0]

    # Update the chunk
    updated = await test_rag_system.update_chunk(
        chunk_hash=original_hash,
        new_content="Updated content",
        actors=["updated_actor"]
    )

    assert updated, "Chunk update failed"

    # Verify update
    results = await test_rag_system.retrieve_similar(
        query="Updated content",
        similarity_threshold=0.3,
        max_results=1
    )
    assert len(results) == 1
    assert "Updated content" in results[0].chunk.content
    assert "updated_actor" in results[0].chunk.metadata.actors


@pytest.mark.asyncio
async def test_precision_recall(test_rag_system, mock_embedding_client):
    """Test retrieval precision and recall metrics"""
    test_queries = TestDataGenerator.get_test_queries()
    test_docs = TestDataGenerator.get_test_documents()

    # Store test documents
    for i, doc in enumerate(test_docs):
        await test_rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=f"{doc['category']}{i}",
            chunk_size=50,
            overlap=10
        )

    precision_scores = []
    recall_scores = []

    for query_data in test_queries:
        query = query_data["query"]
        expected_categories = query_data["expected_categories"]
        min_results = query_data["min_results"]

        results = await test_rag_system.retrieve_similar(
            query=query,
            similarity_threshold=0.3,
            max_results=5
        )

        # Calculate precision: relevant results / total results
        relevant_results = 0
        for result in results:
            content = result.chunk.content.lower()
            for category in expected_categories:
                if category == "machine_learning" and any(
                        word in content for word in ['machine', 'learning', 'neural']):
                    relevant_results += 1
                    break
                elif category == "artificial_intelligence" and any(
                        word in content for word in ['artificial', 'intelligence', 'ai']):
                    relevant_results += 1
                    break
                elif category == "database" and any(word in content for word in ['database', 'sql', 'storage']):
                    relevant_results += 1
                    break
                elif category == "cooking" and any(word in content for word in ['cooking', 'pasta']):
                    relevant_results += 1
                    break

        precision = relevant_results / len(results) if results else 0
        recall = min(relevant_results / min_results, 1.0)

        precision_scores.append(precision)
        recall_scores.append(recall)

    if precision_scores and recall_scores:
        avg_precision = statistics.mean(precision_scores)
        avg_recall = statistics.mean(recall_scores)

        assert avg_precision > 0.5, f"Average precision {avg_precision:.3f} below threshold"
        assert avg_recall > 0.5, f"Average recall {avg_recall:.3f} below threshold"


@pytest.mark.asyncio
async def test_hallucinations(test_rag_system, mock_embedding_client):
    """Test hallucination rate (returning irrelevant results)"""
    irrelevant_queries = [
        "quantum physics equations",
        "ancient roman history",
        "space exploration missions",
        "underwater basket weaving",
        "medieval castle architecture"
    ]

    hallucination_count = 0

    for query in irrelevant_queries:
        try:
            results = await test_rag_system.retrieve_similar(
                query=query,
                similarity_threshold=0.5,
                max_results=3
            )
            # Any results for irrelevant queries could be hallucinations
            if results:
                hallucination_count += len(results)
        except NoMatchingEntryError:
            # Expected behavior - no results found
            pass

    # Calculate hallucination rate
    total_possible_hallucinations = len(irrelevant_queries) * 3
    hallucination_rate = hallucination_count / total_possible_hallucinations if total_possible_hallucinations > 0 else 0

    assert hallucination_rate < 0.1, f"Hallucination rate {hallucination_rate:.2f} too high"


@pytest.mark.asyncio
async def test_cosine_similarity():
    """Test cosine similarity calculation"""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    assert cosine_similarity(vec1, vec2) == 1.0

    vec3 = [0.0, 1.0, 0.0]
    assert cosine_similarity(vec1, vec3) == 0.0

    vec4 = [-1.0, 0.0, 0.0]
    assert cosine_similarity(vec1, vec4) == -1.0

    vec5 = [0.5, 0.5, 0.0]
    assert abs(cosine_similarity(vec1, vec5) - 0.707) < 0.001


@pytest.mark.asyncio
async def test_rate_limiter():
    """Test proper rate limiting behavior"""
    # Patch the RateLimiter to test its functionality
    with patch('dynamic_rag.RateLimiter') as mock_rate_limiter:
        mock_rl = MagicMock()
        mock_rl.acquire = AsyncMock()
        mock_rate_limiter.return_value = mock_rl

        rag_system = DynamicRAGSystem()

        # Test store_document uses rate limiter
        await rag_system.store_document(
            content="Test content",
            actors=["test"],
            document_id="test_doc"
        )

        # Verify rate limiter was called
        assert mock_rl.acquire.called


@pytest.mark.asyncio
async def test_no_matching_entry_error(test_rag_system, mock_embedding_client):
    """Test NoMatchingEntryError handling"""
    # Store a document that won't match the query
    await test_rag_system.store_document(
        content="Completely unrelated content",
        actors=["test"],
        document_id="test_doc"
    )

    with pytest.raises(NoMatchingEntryError):
        await test_rag_system.retrieve_similar(
            query="machine learning",
            similarity_threshold=0.9,
            max_results=1
        )


@pytest.mark.asyncio
async def test_database_operations(test_rag_system, mock_embedding_client, caplog):
    """Test database operations with proper error handling"""
    # Test store document
    chunk_hashes = await test_rag_system.store_document(
        content="Test content",
        actors=["test"],
        document_id="test_doc"
    )
    assert len(chunk_hashes) == 1

    # Test retrieve
    results = await test_rag_system.retrieve_similar(
        query="Test content",
        similarity_threshold=0.3,
        max_results=1
    )
    assert len(results) == 1
    assert "Test content" in results[0].chunk.content

    # Test delete
    deleted = await test_rag_system.delete_chunk(chunk_hashes[0])
    assert deleted

    # Verify deletion
    with pytest.raises(NoMatchingEntryError):
        await test_rag_system.retrieve_similar(
            query="Test content",
            similarity_threshold=0.3,
            max_results=1
        )