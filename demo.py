import asyncio

from modules.llamacpp_api import LLMLink
from modules.region import Region, RAGRegion
from modules.dynamic_rag import DynamicRAGSystem

async def store(rag: DynamicRAGSystem, data: list[dict]):
    stored_chunks = []
    for doc in data:
        await asyncio.sleep(0.5)  # Rate limiting delay
        chunk_hashes = await rag.store_document(
            content=doc["content"],
            actors=doc["actors"],
        )
        stored_chunks.extend(chunk_hashes)
        print(f"{rag.name}: Stored document with {len(chunk_hashes)} chunks")
    print(f"{rag.name}: Total chunks stored: {len(stored_chunks)}\n")

# Historical knowledge base
historical_knowledge = [
    {
        'content': 'The Great Kiwi Massacre occurred on July 21, 2021, marking the Zebra invasion of Kiwia.',
        'actors': ['Stripes', 'Mane']
    },
    {
        'content': 'Operation Razzle Dazzle was the Zebra code name for The Great Kiwi Massacre.',
        'actors': ['Zebra Forces']
    },
    {
        'content': 'Despite using a codename, the Zebras had trouble keeping their plans secret, on account of their bright stripes.',
        'actors': ['Zebra Forces']
    },
    {
        'content': 'The involvement of the Mustangs was what ultimately allowed the Zebra Forces to breach Kiwian defenses.',
        'actors': ['Zebra Forces','Mustangs']
    },
    {
        'content': 'Doggiestan remains rich in calcium deposits to this day.',
        'actors': ['Doggiestan']
    }
]

biography_knowledge = [
    {
        'content': 'Stripes was the leader of the Zebras at the time of the Zebra invasion of Kiwia, and was known for his surprisingly calm temperament and calculated, militaristic policies',
        'actors': ['Stripes']
    },
    {
        'content': 'Mane was the leader of the Mustangs, who were allied with the Zebras at the time of the Zebra invasion of Kiwia. He was a good friend of Mane and Patches.',
        'actors': ['Stripes', 'Mane', 'Patches']
    },
    {
        'content': 'Featherball was the leader of Kiwia, whose personal involvement turned the tide of battle and limited Kiwi casualties during the Great Kiwi Massacre.',
        'actors': ['Featherball']
    },
    {
        'content': 'Patches was a good boy. As the leader of Doggiestan, he brokered friendly relations with both Kiwia and the Zebra nation.',
        'actors': ['Patches']
    }
]

server_port = 10000
server_ip = "localhost"
model_name = "nomic-embed-text:latest"

async def main():
    # Initialize RAG regions
    historical_rag = DynamicRAGSystem(
        db_path="historical_rag.db",
        embedding_server_url=f"http://{server_ip}:{server_port}",
        embedding_model=model_name,
        name='historical_rag.db',
        chunk_size = 128,
        overlap = 24
    )
    biography_rag = DynamicRAGSystem(
        db_path="biography_rag.db",
        embedding_server_url=f"http://{server_ip}:{server_port}",
        embedding_model=model_name,
        name='biography_rag.db',
        chunk_size = 128,
        overlap = 24
    )

    # initialize the llm
    llm = LLMLink()

    # await store(historical_rag, historical_knowledge)
    # await store(biography_rag, biography_knowledge)

    await asyncio.gather(
        store(historical_rag, historical_knowledge),
        store(biography_rag, biography_knowledge)
    )

    historical_region = RAGRegion(
        name='HistoricalFacts',
        task='Provide historical event information',
        rag=historical_rag,
        connections={},
        reply_with_actors=True
    )

    biography_region = RAGRegion(
        name='Biography',
        task='Provide historical figure information',
        rag=biography_rag,
        connections={},
        reply_with_actors=True
    )

    # Initialize HistorianRegion
    historian_region = Region(
        name='Historian',
        task='Synthesize historical information from multiple sources. You are interested in the Zebra-Kiwia conflict and the leaders involved.',
        llm=llm,
        connections={
            'HistoricalFacts': 'Provide historical event information',
            'Biography': 'Provide historical figure information'
        }
    )

    # Update connections
    historical_region.connections = {'Historian': historian_region.task}
    biography_region.connections = {'Historian': historian_region.task}

    # 0. Historian is primed with a question
    await historian_region.inbox.put({
        "source": "control_region",
        "role": "request",
        "content": "Who were the Zebra leaders during Operation Razzle Dazzle?"
    })

    # 1. Historian generates questions
    await historian_region.make_questions()

    # 2. Route messages
    while not historian_region.outbox.empty():
        msg = historian_region.outbox.get_nowait()
        if msg['destination'] == 'HistoricalFacts':
            historical_region.inbox.put_nowait(msg)
        elif msg['destination'] == 'Biography':
            biography_region.inbox.put_nowait(msg)
        print(f"Routed message from {msg['source']} to {msg['destination']}")

    # 3. RAG regions process requests
    await historical_region.make_replies()
    await biography_region.make_replies()

    # 4. Route replies back to Historian
    while not historical_region.outbox.empty():
        msg = historical_region.outbox.get_nowait()
        historian_region.inbox.put_nowait(msg)
        print(f"Routed message from {msg['source']} to {msg['destination']}")
    while not biography_region.outbox.empty():
        msg = biography_region.outbox.get_nowait()
        historian_region.inbox.put_nowait(msg)
        print(f"Routed message from {msg['source']} to {msg['destination']}")

    # 5. Historian generates final answer
    await historian_region.make_replies()

    # Extract and print final answer
    if not historian_region.outbox.empty():
        final_answer = historian_region.outbox.get_nowait()['content']
        print(f"\nFinal synthesized answer: {final_answer}")
    else:
        print("\nNo answer generated by Historian")

if __name__ == "__main__":
    asyncio.run(main())