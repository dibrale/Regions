"""
Script to demonstrate the usage of FeedForwardRegions to refine a reply from multiple drafts.

Note: Hardcoded to http - change to https if SSL is truly desired for a demo
"""

import asyncio
import json
import logging

from executor import Executor
from injector import Injector
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry
from utils import use_logging_standard
from verify import verify
from modules.llmlink import LLMLink

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

async def main():
    """
    Example usage of FeedForwardRegions
    :return:
    """
    use_logging_standard()

    # Load parameters and data
    print("Loading parameters from 'demo_params.json'")
    with open('../shared/demo_params.json', encoding="utf-8") as json_file:
        params = json.loads(json_file.read())

    # LLM configurations are not presently GUI configurable, so we just define them here
    # initialize the LLM
    llm = LLMLink(
        url=f"{params['llm_host']}:{params['llm_port']}",
        params=params['llm_params']
    )

    # Initialize the infrastructure classes
    r = RegionRegistry(default_llm=llm)
    o = Orchestrator()
    p = Postmaster(r, cc='CC')

    r.load("./refine_regions.json")
    o.load("./refine_executions.json")

    # Build-verify the regions and verify the execution plan,
    # then cross-verify the infrastructure instances
    verify(r,o,p)

    with Injector(p, "terminal") as i:
        i.request("BroadcastPrompt", "Discuss the origins of Western views on revenge.")
    with Executor(r, o, p) as ex:
        await ex.run_plan()

if __name__ == "__main__":
    asyncio.run(main())
