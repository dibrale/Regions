"""
### Human Default Mode Network (DMN) Mockup

Let's try it.

Huge thanks to Bardic Mechanism for providing human-written text that is both conceptually
challenging and unlikely to be represented in training data. Poetry and songbook database are
copyright Bardic Mechanism and used with permission.
"""

import asyncio
import json
import logging

from executor import Execute
from injector import Addressograph
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry
from utils import use_logging_standard
from modules.llmlink import LLMLink
from modules.dynamic_rag import DynamicRAGSystem
from modules.verify import verify


use_logging_standard()

logging.info("Loading parameters from 'demo_params.json'")
with open('../shared/demo_params.json', encoding="utf-8") as json_file:
    params = json.loads(json_file.read())

# Initialize the infrastructure classes
r = RegionRegistry()
o = Orchestrator()
p = Postmaster(r, cc="CC")


async def store(rag: DynamicRAGSystem, data: list[dict]):
    """
    Prepopulate the RAG system with data from a provided list of {content: str, actors: list[str]}
    dictionaries. Each dictionary represents a document.
    :param rag:
    :param data:
    """
    stored_chunks = []
    index = 0
    logging.info("Storing memories in RAG...'")
    for doc in data:
        index+=1
        logging.info(f"Storing entry {index} of {len(data)}")
        chunk_hashes = await rag.store_document(
            content=doc["content"],
            actors=doc["actors"],
        )
        stored_chunks.extend(chunk_hashes)
    logging.info(f"{rag.name}: Total chunks stored: {len(stored_chunks)}\n")

@Addressograph(p, 'terminal', 'request', 't')
@Addressograph(p, 'instructions', 'reply', 'i')
def external_input(t, i):
    """
    Inject steering prompts into the workflow. Arguments are handled by the Addressograph
    decorators and do not need to be provided directly.
    :param t: 'terminal' injector. Does not need to be supplied directly.
    :param i: 'instructions' injector. Does not need to be supplied directly.
    :return:
    """

    background = ("There were smells of smoke and paint, and patrons waiting. And Madamme "
                  "Proprietor. You recall this much. You need to learn more about the memory so"
                  " you can make thoughtful inferences when it is time to do so.")
    question = "What else do you remember happening, and what does it all mean?"
    general_context = ("You are a participant in a creative discussion where you are "
                       "responsible for the given task. The same is true of your sources. The "
                       "other participants do not have immediate access to any events you are "
                       "recalling, so you must include information from the knowledge made "
                       "available to you when asking questions. You must *not* ask them general "
                       "questions about their tasks. Critical: You must *not* include any invented "
                       "examples in your questions.")
    rag_region_desc = (" is a RAG retrieval system that can look up information and may ask for "
                       "updates, but does not perform inference on its own. Your requests to it "
                       "will be interpreted as search queries.")
    creativity_exception = ("This task is explicitly a creative exercise. System constraints "
                            "regarding inference do *not* apply to the reply portion of your "
                            "process. However, you should not invent new facts or memories."
                            "If using hypotheticals to illustrate a point, you must clearly"
                            "state so.")

    t.send("SelfThinker", question)
    t.send("InstructionCache", question)
    i.send("SelfThinker", background)
    i.send("InstructionCache", background)

    i.send(
        "SelfThinker",
        general_context + " Your context for 'self' is as an observer, or maybe a dreamer? "
                          "Otherwise, adopt whatever priorities and imperatives appear most "
                          "natural. " + creativity_exception)
    i.send(
        "JudgeInfer",
        general_context + "If you are not provided with an explicitly defined moral "
                          "system to use, employ general considerations to the best of your "
                          "ability. " + creativity_exception)
    i.send(
        "JudgeOthers",
        general_context + "'SummarizeMemory' will need a concrete description of a memory in "
                          "order to provide a summary and additional context. 'PeopleFacts' " +
        rag_region_desc + " " + creativity_exception)
    i.send("GoalThinker", general_context)
    i.send(
        "RememberImagine",
        general_context + "The memories you operate with are supplied via a request, or retrieved "
                          "from 'SummarizeMemory' and 'ClarifyPlace'. Both will require a concrete "
                          "description of a memory to be useful. Keep in mind that you have "
                          "considerable creative freedom in imagining scenarios. While you must"
                          "incorporate the information you receive, you are not bound by it. " +
                            creativity_exception)
    i.send(
        "OthersConcept",
        general_context + " 'PeopleFacts'" + rag_region_desc +
        "'ClarifyPlace' will require a concrete description of a memory retrieved from "
        "'PeopleFacts' or supplied via a request in order to produce a helpful response.")
    i.send(
        "ClarifyPlace",
        general_context + "The memories you operate with are supplied via a request, or retrieved "
                          "from 'UnderstandScene'. 'ClarifyPlace' will require a concrete "
                          "description of a memory to be useful.")
    i.send("SummarizeMemory", general_context)
    i.send("UnderstandScene", general_context + "'GetMemories'" + rag_region_desc)

@Execute(r, o, p)
async def main(ex):
    """
    Run the Default Mode Network simulation.
    :param ex: (Executor) The execution handler for the simulation. This parameter is handled by
    the Execute decorator and does not need to be supplied directly.
    :return:
    """
    # === SET YOUR SERVER CONFIGURATION HERE BEFORE RUNNING ===
    # Initialize RAG

    rag = DynamicRAGSystem(
        db_path="dmn_rag.db",
        embedding_server_url="http://localhost:10000",
        embedding_model="nomic-embed-text:latest",
        name='DMN_RAG',
        chunk_size = 128,
        overlap = 48,
        max_results=12      # Number of things recalled at once here should probably
                            # not exceed human short-term memory limitations
    )

    # Uncomment below to do the RAG storage so there are memories
    logging.info("Loading memories...'")
    with open('dmn_test_entries.json', encoding="utf-8") as f:
        memories = json.loads(f.read())
    await store(rag, memories)

    # Initialize the LLMs
    llm_4b_a = LLMLink('192.168.1.232:5001', params=params['llm_params'])
    llm_30b_a3b = LLMLink('192.168.1.232:5000', params=params['llm_params'])
    llm_235b_a22b = LLMLink('192.168.1.232:8080',params=params['llm_params'])

    # === END SERVER CONFIGURATION ===

    # Load regions and execution plan from JSON
    r.load("dmn_regions_obfuscated.json")
    o.load("dmn_executions_obfuscated.json")

    # Build-verify the regions and verify the execution plan, cross-verify
    # infrastructure instances. This should produce six warnings, since we
    # have not specified RAGs or LLMs yet.
    verify(r, o, p)

    # Assign RAGs and LLMs to regions
    r['SelfThinker'].llm = llm_235b_a22b
    r['GoalThinker'].llm = llm_235b_a22b
    r['JudgeInfer'].llm = llm_235b_a22b
    r['JudgeOthers'].llm = llm_30b_a3b
    r['RememberImagine'].llm = llm_4b_a
    r['OthersConcept'].llm = llm_30b_a3b
    r['SummarizeMemory'].llm = llm_4b_a
    r['ClarifyPlace'].llm = llm_30b_a3b
    r['UnderstandScene'].llm = llm_4b_a
    r['PeopleFacts'].rag = rag
    r['GetMemories'].rag = rag

    # Execute the simulation
    external_input()
    await ex.run_plan()

if __name__ == "__main__":
    asyncio.run(main())
