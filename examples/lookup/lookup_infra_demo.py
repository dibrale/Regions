"""
Script to demonstrate the usage of Regions and RAGRegions with an orchestrator, registry and postmaster.
Functions similarly to the base demo script. Reads embedding and text model server configurations from 'demo_params.json'.
These can be loaded via the GUI for inspection.

Note: Hardcoded to http - change to https if SSL is truly desired for a demo
"""

import asyncio
import json
import logging
import os

from executor import Executor
from injector import Injector
from modules.llmlink import LLMLink
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry
from modules.dynamic_rag import DynamicRAGSystem
from utils import use_logging_standard
from verify import verify


async def store(rag: DynamicRAGSystem, data: list[dict]):
    """
    Method to load data into the RAG
    :param rag:
    :param data:
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
    Run lookup demo with infrastructure classes
    :returns:
    """
    use_logging_standard()
    # Load parameters and data

    print("Loading parameters from 'demo_params.json'")
    params = json.loads(open('../shared/demo_params.json', 'r').read())

    print("Loading historical facts from 'demo_historical_docs.json'")
    historical_knowledge = json.loads(open('../shared/demo_historical_docs.json', 'r').read())

    print("Loading biography facts from 'demo_biography_docs.json'")
    biography_knowledge = json.loads(open('../shared/demo_biography_docs.json', 'r').read())

    # RAG and LLM configurations are not presently GUI configurable, so we just define them here
    # initialize the LLM
    llm = LLMLink(
        params=params['llm_params']
    )

    # Initialize RAG systems
    historical_rag = DynamicRAGSystem(
        db_path="historical_rag.db",
        embedding_server_url=f"http://{params['rag_host']}:{params['rag_port']}",
        embedding_model=params['rag_model'],
        name='historical_rag.db',
        chunk_size = 128,
        overlap = 24
    )

    biography_rag = DynamicRAGSystem(
        db_path="biography_rag.db",
        embedding_server_url=f"http://{params['rag_host']}:{params['rag_port']}",
        embedding_model=params['rag_model'],
        name='biography_rag.db',
        chunk_size = 128,
        overlap = 24
    )

    # Initialize the infrastructure classes
    r = RegionRegistry()
    o = Orchestrator()
    p = Postmaster(r)

    # Load regions and execution plan from JSON
    r.load("lookup_regions.json")
    o.load("lookup_executions.json")

    # Assign RAGs to regions.
    r.regions[r.names.index('Biography')].rag = biography_rag
    r.regions[r.names.index('HistoricalFacts')].rag = historical_rag

    '''
    Alternative code:
    
        region=r['Biography']
        region.rag=biography_rag
        r['Biography']=region
    
    '''

    # Assign LLM to HistorianRegion.
    r.regions[r.names.index('Historian')].llm = llm

    # Build-verify the regions and verify the execution plan, then cross-verify the infrastructure instances
    verify(r,o,p)

    # Add data to RAG systems
    await asyncio.gather(
        store(historical_rag, historical_knowledge),
        store(biography_rag, biography_knowledge)
    )

    with Injector(p, "terminal") as i:
        i.request("Historian", "Who were the Zebra leaders during Operation Razzle Dazzle?")
    with Executor(r, o, p) as ex:
        await ex.run_plan()

    # Clean up
    os.unlink('historical_rag.db')
    os.unlink('biography_rag.db')


if __name__ == "__main__":
    asyncio.run(main())