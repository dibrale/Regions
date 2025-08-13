"""
Example Usage of Dynamic RAG System

This script demonstrates how to use the Dynamic RAG System
with a real llama.cpp embedding server.

Prerequisites:
1. Install llama.cpp and start embedding server on port 8080
2. Install required Python packages: aiohttp

Usage:
python example_usage.py
"""

import asyncio
import os
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

async def store(rag_system: DynamicRAGSystem, data: list[dict]):
    """Test document storage with chunking"""
    print("=== Document storage test ===")

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

    print("=== Document retrieval test ===")

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

    try:
        await asyncio.sleep(0.5)
        print("=== System statistics test ===")
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

    print("=== Document update test ===")
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
    await asyncio.sleep(0)
    raise AssertionError("Error raised by Dummy Test")
    try:
        assert 1==1
    except AssertionError as e:
        print(f"\n✗ Dummy test failed : {e}\n")
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

    # Initialize the system
    rag = DynamicRAGSystem(
        db_path="example_rag.db",
        embedding_server_url=f"http://{server_ip}:{server_port}",
        embedding_model=model_name,
    )

    """Run all RAG system tests"""

    suite = modules.testutils.TestSet('=== RAG System Tests ===',
                                      [
                                          #store(rag, documents),
                                          #retrieve(rag, questions),
                                          stats(rag),
                                          #update(rag, new_document),
                                          dummy_test()
                                      ],
                                      [
                                          #"Document Storage",
                                          #"Similarity Retrieval",
                                          "System Stats",
                                          #"Chunk Update",
                                          "Dummy Test"
                                      ]
                                      )

    await suite.run_sequential()
    suite.result()
    remove_db()

'''
    print(f"=== RAG System Tests ===\n")
    passed = []
    tests = [
        store(rag, documents),
        retrieve(rag, questions),
        stats(rag),
        update(rag, new_document),
    ]

    test_names = [
        "Document Storage",
        "Similarity Retrieval",
        "System Stats",
        "Chunk Update",
    ]
'''
'''
    for test in tests:
        passed.append(await test)

    total = len(tests)

    print(f"\n=== Results ===")
    print(f"Passed: {sum(passed)}/{total}")

    for i, (name, result) in enumerate(zip(test_names, passed)):
        status = "✓ PASS" if result is True else "✗ FAIL"
        print(f"  {status}: {name}")
        if result is not True and result is not False:
            print(f"    Error: {result}")

    if sum(passed) == total:
        print("\nAll tests passed!")
    else:
        print(f"\n⚠️  {total - sum(passed)} tests failed.")
'''


if __name__ == "__main__":
    asyncio.run(main())

