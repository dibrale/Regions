"""
This script demonstrates the usage of the DynamicRAGSystem class to store a document,
retrieve similar content based on a query, and get system statistics. It handles exceptions
specific to the RAG system and prints out the results or error messages.
"""

import asyncio
import json
import os

from dynamic_rag import DynamicRAGSystem
from exceptions import RAGException
from utils import use_logging_standard


async def main():
    """
    Example usage of DynamicRAGSystem class
    :return:
    """
    use_logging_standard()

    print("Loading parameters from 'demo_params.json'")
    with open('shared/demo_params.json', encoding="utf-8") as json_file:
        params = json.loads(json_file.read())

    rag_system = DynamicRAGSystem(
        embedding_server_url=f"http://{params['rag_host']}:{params['rag_port']}",
        embedding_model=params['rag_model'])

    try:
        # Store a document
        await rag_system.store_document(
            content="This is a sample document about machine learning and artificial intelligence.",
            actors=["user1", "system"],
            document_id="doc_001"
        )

        # Retrieve similar content
        results = await rag_system.retrieve_similar(
            query="machine learning",
            similarity_threshold=0.5,
            max_results=3
        )

        print(f"Found {len(results)} similar chunks:")
        for result in results:
            print(f"  Similarity: {result.similarity_score:.3f}")
            print(f"  Content: {result.chunk.content[:100]}...")
            print(f"  Actors: {result.chunk.metadata.actors}")
            print()

        # Get system stats
        stats = await rag_system.get_stats()
        print("System stats:", stats)

    except RAGException as e:
        print(f"RAG Error {e.code}: {e.description}")

    # Clean up after the example
    os.unlink('rag_storage.db')

if __name__ == "__main__":
    # Run example
    asyncio.run(main())
    