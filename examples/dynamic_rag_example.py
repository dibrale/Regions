import asyncio

from dynamic_rag import DynamicRAGSystem
from exceptions import RAGException


async def main():
    rag_system = DynamicRAGSystem(embedding_server_url="http://localhost:10000",
                                  embedding_model="nomic-embed-text:latest")

    try:
        # Store a document
        chunk_hashes = await rag_system.store_document(
            content="This is a sample document about machine learning and artificial intelligence.",
            actors=["user1", "system"],
            document_id="doc_001"
        )
        # await asyncio.sleep(0.5)

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
        await asyncio.sleep(0.5)
        stats = await rag_system.get_stats()
        print("System stats:", stats)

    except RAGException as e:
        print(f"RAG Error {e.code}: {e.description}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    # print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")

if __name__ == "__main__":
    # Example usage

    # Run example
    asyncio.run(main())