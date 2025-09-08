"""
### Literature Commentary Demo

This demo is intended to demonstrate how the system can be used to generate a literary commentary on a poem. The structure includes:

  - 5x Region instances
  - 1x RAGRegion instance
  - 1x ListenerRegion instance

The system runs in seven execution layers for two rounds of analysis. No messages are cleared from Region instance reply buffers between rounds.
The ListenerRegion will open a GUI to snoop on communications. Make sure to set your server details below.
If the execution plan is not suitable for your setup, import 'lit_demo_state.json' via the GUI and adjust these to your liking.
There are additional code blocks below that can be substituted in to run the 'Commentate' region alone to compare with one-shot output.
Huge thanks to Bardic Mechanism for providing human-written text that is both conceptually challenging and unlikely to be represented in training data.
Poetry and songbook database are copyright Bardic Mechanism and used with permission.
"""


import asyncio
import json
import logging

from executor import Executor
from injector import Injector
from modules.llmlink import LLMLink
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry
from modules.dynamic_rag import DynamicRAGSystem
from modules.verify import verify

# Set reasonable logging behavior
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)

logging.info("Loading parameters from 'demo_params.json'")
params = json.loads(open('demo_params.json').read())


async def main():

    # === SET YOUR SERVER CONFIGURATION HERE BEFORE RUNNING ===
    # Initialize RAG
    rag = DynamicRAGSystem(
        db_path="bm_rag.db",
        embedding_server_url=f"http://localhost:10000",
        embedding_model="nomic-embed-text:latest",
        name='LyricsRAG',
        chunk_size = 256,
        overlap = 48,
        max_results=30,
    )

    # Initialize the LLMs
    llm_4b_a = LLMLink('192.168.1.232:5001', name='Qwen3_4B-A', params=params['llm_params'])
    llm_4b_b = LLMLink('192.168.1.232:5002', name='Qwen3_4B-B', params=params['llm_params'])
    llm_30b_a3b = LLMLink('192.168.1.232:5000', name='Qwen3_30B-A3B', params=params['llm_params'])

    # Testing with the higher-end Qwen3 was not successful, with the system erroring silently - clean and seemingly unprovoked cancellation of LLM task mid-reply. May be due to hardware limitations. Does not appear to be due to connection timeouts. May need further investigation.
    llm_235b_a22b = LLMLink('192.168.1.232:8080',name='Qwen3_235B-A22B', params=params['llm_params'])

    # === END SERVER CONFIGURATION ===

    # Note: the original songbook is left out of the distributed code at the request of the artist, but they are happy for you to hack the included database if you wish.
    # This code is left here solely to demonstrate how indexing was initially performed.
    index = False
    if index:
        print("Indexing...")
        await rag.store({'songbook.txt': ['Bardic Mechanism']})


    with open('i_know_poem.txt') as f:
        poem = ''.join(f.readlines())

    # Initialize the infrastructure classes
    r = RegionRegistry()
    o = Orchestrator()
    p = Postmaster(r, cc="CC")

    # Load regions and execution plan from JSON
    r.load("lit_demo_regions.json")
    o.load("lit_demo_executions.json")

    # Assign RAGs and LLMs to regions
    r.regions[r.names.index('Commentate')].llm = llm_30b_a3b
    r.regions[r.names.index('Symbolism')].llm = llm_4b_a
    r.regions[r.names.index('Imagery')].llm = llm_4b_b
    r.regions[r.names.index('ArtistLore')].llm = llm_30b_a3b
    r.regions[r.names.index('Explain')].llm = llm_30b_a3b
    r.regions[r.names.index('Archive')].rag = rag

    # Build-verify the regions and verify the execution plan, then cross-verify the infrastructure instances
    verify(r, o, p)

    with Injector(p, "terminal") as i:
        i.request(
            "Commentate",
            """
            Provide a literary critique of 'I Know' by the artist 'Bardic Mechanism'. The poem has been sent via 'source_poem' for your attention. 
            Keep in mind that all of these sources also have access to the poem you are jointly reviewing, so you do not need to submit the full text to them.
            While the sources may provide helpful details you must also use your own judgement and analysis of the poem in creating the final critique.
            """
        )

    # Inject the main text into the context of each region
    with Injector(p, "source_poem") as i:
        i.reply("Commentate", poem)
        i.reply("Symbolism", poem)
        i.reply("Imagery", poem)
        i.reply("Explain", poem)
        i.reply("ArtistLore", poem)

    # Inject additional instructions
    with Injector(p, "additional_instructions") as i:
        i.reply("ArtistLore",
                "Do not quote the retrieved data when formulating your reply. Rather, summarize the relevant points from it.")
        i.reply("ArtistLore",
                "'Archive' acts only as a lookup service, and will not be able to narratively answer your questions. Formulate queries to to 'Archive' accordingly, keeping in mind that you can ask more than one at a time if necessary.")
        i.reply("Explain",
                "There is no need to cite knowledge sources by task designation, as this is a modified Delphi process.")
        i.reply("Symbolism",
                "The attribution of the poem to Bardic Mechanism has been verified by the user and is correct.")
        i.reply("Explain",
                "If you already have data from 'Symbolism' and 'Imagery', there is no need to re-request it, unless the data provided is insufficient.")
        i.reply("Commentate",
                "There is no need to cite knowledge sources by task designation, as this is a modified Delphi process.")
        i.reply("Imagery",
                "The attribution of the poem to Bardic Mechanism has been verified by the user and is correct.")
        i.reply("Commentate",
                "If you already have data from 'Symbolism' and 'Imagery', there is no need to re-request it, unless the data provided is insufficient.")

        # Message for use with the single-region test configuration
        # i.reply("Commentate", "Important: The other regions are not presently available – system is in testing mode. Generate your own reply as best you can.")


    with Executor(r, o, p) as ex:
        await ex.run_plan()

# Below is some single region test code. You can use it to compare one-shot output to output from the entire system. To run:
#   1. Comment out the executor block
#   2. Uncomment the code in the triple quotes
#   3. Uncomment the extra reply code in the injector block
'''
    await p.start()
    await until_empty(p.messages)
    await r['Commentate'].make_replies()
    await asyncio.sleep(4)
    await until_empty(p.messages)
    await p.stop()
'''

if __name__ == "__main__":
    asyncio.run(main())