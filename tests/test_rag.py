"""
Test script for RAG functionality
"""

import asyncio
import os
import statistics
import unittest

import modules.testutils
from modules.dynamic_rag import (
    DynamicRAGSystem,
    NoMatchingEntryError,
    DatabaseNotAccessibleError,
    ServiceUnavailableError,
    HTTPError
)
from modules.testutils import remove_db
from tests.test_error import (
    access,
    unavailable,
    mismatch,
    transport
)
from tests.test_database import (
    rate,
    operations,
    concurrent
)


class TestDataGenerator:
    """Generate test data for precision/recall testing"""

    @staticmethod
    def get_test_documents() -> list[dict[str, str | list[str]]]:
        """Get test documents with known semantic relationships"""
        return [
            {
                "content": "Machine learning algorithms can learn patterns from data automatically.",
                "category": "machine_learning",
                "actors": ["researcher", "data_scientist"]
            },
            {
                "content": "Deep neural networks are a powerful machine learning technique.",
                "category": "machine_learning",
                "actors": ["ai_engineer", "researcher"]
            },
            {
                "content": "Artificial intelligence systems can perform complex reasoning tasks.",
                "category": "artificial_intelligence",
                "actors": ["ai_researcher", "engineer"]
            },
            {
                "content": "AI models require large amounts of training data to perform well.",
                "category": "artificial_intelligence",
                "actors": ["data_scientist", "ml_engineer"]
            },
            {
                "content": "SQL databases provide structured storage for relational data.",
                "category": "database",
                "actors": ["database_admin", "developer"]
            },
            {
                "content": "Database indexing improves query performance significantly.",
                "category": "database",
                "actors": ["dba", "backend_developer"]
            },
            {
                "content": "The weather is sunny today with clear blue skies.",
                "category": "weather",
                "actors": ["meteorologist", "observer"]
            },
            {
                "content": "Cooking pasta requires boiling water and adding salt.",
                "category": "cooking",
                "actors": ["chef", "home_cook"]
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

async def store(rag_system: DynamicRAGSystem, data: list[dict]):
    """Test document storage with chunking"""
    print("=== Document Storage ===")

    try:
        # Test document storage with smaller chunks to reduce embedding calls

        stored_chunks = []
        for doc in data:
            await asyncio.sleep(0.5)    # Rate limiting delay
            chunk_hashes = await rag_system.store_document(
                content=doc["content"],
                actors=doc["actors"],
                document_id=doc["doc_id"],
                chunk_size=50,
                overlap=10
            )
            stored_chunks.extend(chunk_hashes)
            print(f" ✓ Stored '{doc['doc_id']}' with {len(chunk_hashes)} chunks")


        print(f"\nTotal chunks stored: {len(stored_chunks)}")
        print(f"\n✓ Document storage test succeeded\n")
        return True

    except Exception as e:
        print(f"✗ Document storage test failed: {e}\n")
        return False

async def retrieve(rag_system: DynamicRAGSystem, queries: list[str]):

    print("=== Document Retrieval ===")

    success = []

    try:

        for query in queries:
            # Rate limiting delay
            await asyncio.sleep(0.5)

            try:
                print(f"\nQuery: '{query}'")
                results = await rag_system.retrieve_similar(
                    query=query,
                    similarity_threshold=0.3,
                    max_results=2
                )

                if results:
                    for j, result in enumerate(results, 1):
                        print(f"  Result {j} (similarity: {result.similarity_score:.3f}):")
                        print(f"    Content: {result.chunk.content[:100]}...")
                        print(f"    Actors: {result.chunk.metadata.actors}")
                        print(f"    Timestamp: {result.chunk.metadata.timestamp}")
                else:
                    print("  No results found")

            except NoMatchingEntryError:
                print("  No matching entries found")
                success.append(False)

            success.append(True)

        # Rate limiting delay
        await asyncio.sleep(0.5)
        print(f"\n✓ Document retrieval test succeeded\n")
        return True

    except Exception as e:
        print(f"✗ Document retrieval test failed: {e}\n")
        return False

    finally:
        print(f"  Matching entries: {sum(success)}/{len(queries)}\n")

async def stats(rag_system: DynamicRAGSystem):
    print("=== System statistics test ===")

    try:
        await asyncio.sleep(0.5)
        stats = await rag_system.get_stats()
        print(f"   Total chunks: {stats['total_chunks']}")
        print(f"   Unique documents: {stats['unique_documents']}")
        print(f"   Unique actors: {stats['unique_actors']}")
        print(f"   All actors: {', '.join(stats['actors'])}")
        print(f"\n✓ Statistics retrieval test succeeded\n")
        return True

    except Exception as e:
        print(f"✗ Statistics retrieval test failed: {e}\n")
        return False

async def update(rag_system: DynamicRAGSystem, entry: dict):

    print("=== Document Update ===")
    await asyncio.sleep(0.5)
    info = await rag_system.get_stats()
    print(f"   Total chunks: {info['total_chunks']}")

    # Try to update a non-existent chunk
    try:
        await asyncio.sleep(0.5)
        updated = await rag_system.update_chunk(
            chunk_hash="nonexistent_hash",
            new_content="Test content",
            actors=["test"]
        )
        if not updated:
            print("  ✓ Correctly handled non-existent chunk update")
        else:
            print("  ✗ Should not have updated non-existent chunk")
            print(f"\n✗ Document update test failed\n")
            return False

    except Exception as e:
        print(f"\n✗ Document update test failed : {e}\n")
        return False

    # Store a fresh chunk
    await asyncio.sleep(0.5)
    print("    Storing test chunk...")
    try:
        chunk_hash = await rag_system.store_document(
            content="foo",
            actors=["bar"],
            document_id="test_update",
            chunk_size=50,
            overlap=10
        )
    except Exception as e:
        print("  ✗ Failed to store test chunk")
        print(f"\n✗ Document update test failed : {e}\n")
        return False

    # Try updating the test chunk
    try:
        # Rate limiting delay
        await asyncio.sleep(0.5)

        updated = await rag_system.update_chunk(
            chunk_hash=chunk_hash[0],
            new_content=entry["content"],
            actors=entry["actors"],
        )
        if updated:
            print("  ✓ Update method returned success")
            print(f"\n✓ Document update test succeeded")
            return True
        else:
            print("   ✗ Update method failed")
            print(f"\n✗ Document update test failed")
            return False
    except Exception as e:
        print(f"\n✗ Document update test failed : {e}\n")
        return False

async def dummy_test():
    print("=== Dummy Test ===")
    await asyncio.sleep(0)
    raise AssertionError("Error raised by Dummy Test")
    try:
        assert 1==1
    except AssertionError as e:
        print(f"\n✗ Dummy test failed : {e}\n")
        return False

async def precision_recall(rag_system: DynamicRAGSystem, similarity: float = 0.55):
    """Test retrieval precision and recall metrics"""

    test_queries = TestDataGenerator.get_test_queries()
    test_docs = TestDataGenerator.get_test_documents()
    precision_scores = []
    recall_scores = []

    print("=== Precision/Recall ===")
    print("\nStoring test chunks...")

    i = 0
    for doc in test_docs:
        i+=1
        await asyncio.sleep(0.5)  # Rate limiting delay
        chunk_hashes = await rag_system.store_document(
            content=doc["content"],
            actors=doc["actors"],
            document_id=f"{doc['category']}{i}",
            chunk_size=50,
            overlap=10
        )
        print(f" ✓ Stored '{doc['category']}{i}' with {len(chunk_hashes)} chunks")

    print("\nTesting retrieval precision/recall...")

    try:

        for query_data in test_queries:
            query = query_data["query"]
            expected_categories = query_data["expected_categories"]
            min_results = query_data["min_results"]

            try:
                await asyncio.sleep(0.5)
                results = await rag_system.retrieve_similar(
                    query=query,
                    similarity_threshold=similarity,
                    max_results=5
                )

                if len(results) == 0:
                    print(f"  ✗ Query '{query}': no results")
                    continue

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
                recall = min(relevant_results / min_results, 1.0)  # Simplified recall calculation

                precision_scores.append(precision)
                recall_scores.append(recall)

                print(f"  Query '{query}': results={len(results)}, precision={precision:.2f}, recall={recall:.2f}")

                # await asyncio.sleep(0.5)

            except NoMatchingEntryError:
                print(f"  ✗ Query '{query}': no matching entries")

        if precision_scores and recall_scores:
            avg_precision = statistics.mean(precision_scores)
            avg_recall = statistics.mean(recall_scores)

            print(f"✓ Average precision: {avg_precision:.3f}")
            print(f"✓ Average recall: {avg_recall:.3f}")

            # Consider test passed if precision > 0.5 and recall > 0.5
            if avg_precision > 0.5 and avg_recall > 0.5:
                return True
            else:
                print("✗ Precision/recall below acceptable thresholds")
                return False
        else:
            print("✗ No precision/recall data collected")
            return False

    except Exception as e:
        print(f"✗ Precision/recall test failed: {e}")
        return False

async def hallucinations(rag_system: DynamicRAGSystem, query: list[str] | str, similarity: float=0.55):
    """Test hallucination rate (returning irrelevant results)"""
    print("=== Hallucinations ===")
    print("\nTesting hallucination rate...")

    try:

        if isinstance(query, str):
            irrelevant_queries = [query]
        elif isinstance(query, list):
            irrelevant_queries = query
        else:
            raise AssertionError(f"Query type '{query}' not supported")

        # Test queries that should have very few or no relevant results

        hallucination_count = 0
        total_queries = 0

        for query in irrelevant_queries:
            try:
                await asyncio.sleep(0.5)
                results = await rag_system.retrieve_similar(
                    query=query,
                    similarity_threshold=similarity,
                    max_results=3
                )

                # Any results for these irrelevant queries could be considered hallucinations
                if len(results) > 0:
                    hallucination_count += len(results)
                    print(f"  Query '{query}': {len(results)} potentially irrelevant results")
                else:
                    print(f"  Query '{query}': correctly returned no results")

                total_queries += 1

            except NoMatchingEntryError:
                print(f"  Query '{query}': correctly returned no results")
                total_queries += 1

            finally:
                await asyncio.sleep(0.5)

        # Calculate hallucination rate
        total_possible_hallucinations = total_queries * 3  # Max results per query
        hallucination_rate = hallucination_count / total_possible_hallucinations
        print(
            f"✓ Hallucination rate: {hallucination_rate:.1f} ({hallucination_count}/{total_possible_hallucinations})")

        # Consider acceptable if hallucination rate < 0.1 (10%)
        if hallucination_rate < 0.1:
            print("✓ Hallucination rate within acceptable limits")
            return True
        else:
            print("✗ Hallucination rate too high")
            return False

    except Exception as e:
        print(f"✗ Hallucination test failed: {e}")
        return False

async def main():
    server_port = 10000
    server_ip = "localhost"
    model_name = "nomic-embed-text:latest"

    documents = [
        {
            "content": "Machine learning is a method of data analysis that automates analytical model building. It is a branch of artificial intelligence based on the idea that systems can learn from data, identify patterns and make decisions with minimal human intervention.",
            "actors": ["data_scientist", "ml_engineer"],
            "doc_id": "ml_overview"
        },
        {
            "content": "Deep learning is part of a broader family of machine learning methods based on artificial neural networks. Learning can be supervised, semi-supervised or unsupervised. Deep learning architectures such as deep neural networks have been applied to fields including computer vision and natural language processing.",
            "actors": ["ai_researcher", "deep_learning_expert"],
            "doc_id": "deep_learning_intro"
        },
        {
            "content": "Natural language processing (NLP) is a subfield of linguistics, computer science, and artificial intelligence concerned with the interactions between computers and human language. NLP combines computational linguistics with statistical, machine learning, and deep learning models.",
            "actors": ["nlp_researcher", "computational_linguist"],
            "doc_id": "nlp_basics"
        }
    ]

    new_document = {
        "content": "Machine learning has evolved significantly with the advent of big data and powerful computing resources. Modern ML algorithms can process vast amounts of information to discover complex patterns.",
        "actors": ["updated_researcher", "ai_engineer"],
        "doc_id": "ml_evolved"
    }

    # Query examples
    questions = [
        "What is machine learning?",
        "Tell me about deep learning neural networks",
        "How does natural language processing work?",
        "AI and machine learning applications"
    ]

    # Irrelevant Queries
    irrelevant_queries = [
        "quantum physics equations",
        "ancient roman history",
        "space exploration missions",
        "underwater basket weaving",
        "medieval castle architecture"
    ]

    # Initialize the system
    rag = DynamicRAGSystem(
        db_path="example_rag.db",
        embedding_server_url=f"http://{server_ip}:{server_port}",
        embedding_model=model_name,
    )

    """Run all RAG system tests"""

    suite = modules.testutils.TestSet('=== RAG System Tests ===',
                                      [
                                          store(rag, documents),
                                          retrieve(rag, questions),
                                          stats(rag),
                                          update(rag, new_document),
                                          precision_recall(rag),
                                          hallucinations(rag, irrelevant_queries)
                                      ],
                                      [
                                          "Document Storage",
                                          "Similarity Retrieval",
                                          "System Stats",
                                          "Chunk Update",
                                          "Precision and Recall",
                                          "Hallucinations"
                                      ]
                                      )

    await suite.run_sequential()
    suite.result()
    remove_db()

if __name__ == "__main__":
    asyncio.run(main())

