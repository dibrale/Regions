"""
Demo script to demonstrate the usage of Regions and RAGRegions.
Reads embedding and text model server configurations from 'demo_params.json'.

Note: Hardcoded to http - change to https if SSL is truly desired for a demo
"""

import asyncio
import json
import os

from regions.region import Region
from regions.rag_region import RAGRegion
from modules.llmlink import LLMLink
from modules.dynamic_rag import DynamicRAGSystem
from utils import use_logging_standard


async def store(rag: DynamicRAGSystem, data: list[dict]):
    """
    Helper function to store documents presented as a list of strings into a RAG system.
    :param rag: (DynamicRAGSystem) RAG System to store the document into
    :param data: (list[dict]) The documents to be stored
    :return:
    """
    stored_chunks = []
    for doc in data:
        chunk_hashes = await rag.store_document(
            content=doc["content"],
            actors=doc["actors"],
        )
        stored_chunks.extend(chunk_hashes)
    print(f"{rag.name}: Total chunks stored: {len(stored_chunks)}\n")

async def main():
    """
    Example usage of Regions and RAGRegions
    :return:
    """
    use_logging_standard()

    # Load parameters and data

    print("Loading parameters from 'demo_params.json'")
    with open('../shared/demo_params.json', encoding="utf-8") as json_file:
        params = json.loads(json_file.read())

    print("Loading historical facts from 'demo_historical_docs.json'")
    with open('../shared/demo_historical_docs.json', encoding="utf-8") as json_file:
        historical_knowledge = json.loads(json_file.read())

    print("Loading biography facts from 'demo_biography_docs.json'")
    with open('../shared/demo_biography_docs.json', encoding="utf-8") as json_file:
        biography_knowledge = json.loads(json_file.read())

    # initialize the LLM
    llm = LLMLink(
        params=params['llm_params']
    )

    # Initialize RAG systems
    historical_rag = DynamicRAGSystem(
        db_path="historical_rag.db",
        embedding_server_url=f"http://{params['rag_host']}:{params['rag_port']}",
        embedding_model=params['rag_model'],
        chunk_size = 128,
        overlap = 24
    )

    biography_rag = DynamicRAGSystem(
        db_path="biography_rag.db",
        embedding_server_url=f"http://{params['rag_host']}:{params['rag_port']}",
        embedding_model=params['rag_model'],
        chunk_size = 128,
        overlap = 24
    )

    # Add data to RAG systems
    await asyncio.gather(
        store(historical_rag, historical_knowledge),
        store(biography_rag, biography_knowledge)
    )

    # Initialize two RAG regions - one for 'facts', the other for biography
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
        task='Synthesize historical information from multiple sources.' +
             'You are interested in the Zebra-Kiwia conflict and the leaders involved.',
        llm=llm,
        connections={
            'HistoricalFacts': 'Provide historical event information',
            'Biography': 'Provide historical figure information'
        }
    )

    # Update connections between regions
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

    # 6. Extract and print final answer
    if not historian_region.outbox.empty():
        final_answer = historian_region.outbox.get_nowait()['content']
        print(f"\nFinal synthesized answer: {final_answer}")
    else:
        print("\nNo answer generated by Historian")

    # 7. Clean up
    os.unlink('historical_rag.db')
    os.unlink('biography_rag.db')


if __name__ == "__main__":
    asyncio.run(main())
