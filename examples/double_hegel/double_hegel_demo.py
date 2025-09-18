"""
### Double Hegel Demo

An evaluation workflow that utilizes two dialectical steps to reduce
model sycophancy by obfuscating the agreement vector.
"""

import asyncio
import json

from executor import Executor
from injector import Injector
from utils import use_logging_standard
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry
from modules.llmlink import LLMLink
from modules.verify import verify


async def main():
    """
    Run the demo to critique the README.md file of this repository.
    """
    use_logging_standard()

    # === SET YOUR SERVER CONFIGURATION HERE BEFORE RUNNING ===
    print("Loading parameters from 'demo_params.json'")
    with open('../shared/demo_params.json', encoding="utf-8") as json_file:
        params = json.loads(json_file.read())

    # Initialize the LLMs
    llm_30b_a3b = LLMLink('192.168.1.232:5000', params=params['llm_params'])
    llm_235b_a22b = LLMLink('192.168.1.232:8080',params=params['llm_params'])

    with open('../../README.md', encoding="utf-8") as f:
        text = ''.join(f.readlines())

    # === END SERVER CONFIGURATION ===

    # 1. Initialize the infrastructure classes
    r = RegionRegistry()
    o = Orchestrator()
    p = Postmaster(r, cc="CC")

    # 2. Load regions and execution plan from JSON
    r.load("double_hegel_regions.json")
    o.load("double_hegel_executions.json")

    # 3. Build-verify the regions and verify execution plan, then cross-verify
    # infrastructure instances. This should produce five warnings, since we
    # have not specified LLMs yet.
    verify(r, o, p)

    # 4. Assign RAGs and LLMs to regions
    r['Judge'].llm = llm_235b_a22b
    r['Synthesis'].llm = llm_235b_a22b
    r['Analysis'].llm = llm_235b_a22b
    r['OpinionA'].llm = llm_30b_a3b
    r['OpinionB'].llm = llm_30b_a3b

    # 5. The Judge is given the text as a request, with copy to InstructionCache
    with Injector(p, "terminal") as i:
        i.request("Judge", text)
        i.request("InstructionCache", text)

    # 6. Inject the main text into MessageSubordinate for distribution to the
    # context of each subordinate region
    with Injector(p, "source_text") as i:
        i.reply("MessageSubordinate", text)

    # 7. Inject additional instructions
    delphi =  "This is a modified Delphi process. Do not cite knowledge sources by task " +\
              " designation or generated opinions by letter code."
    with Injector(p, "additional_instructions") as i:
        i.reply("OpinionA",
                "This README.md file has major organizational and clarity issues.")
        i.reply("OpinionB",
                "This README.md file has at most minor organizational and clarity issues.")
        i.reply("Synthesis",
                "Your focus is on organization and clarity. Solicit opinions via " +
                "'AnalysisRouter'. " + delphi)
        i.reply("Analysis",
                "Your focus is on organization and clarity. Solicit opinions via " +
                "'AnalysisRouter'. " + delphi)
        i.reply("Judge",
                "'Synthesis' and 'Analysis' are segregated units with different roles. " +
                "They do not have access to data from one another. Obtain their stances, " +
                "then reply to 'terminal' with your final impressions and suggested edits. " +
                delphi)

    # 8. Run the execution plan
    with Executor(r, o, p) as ex:
        await ex.run_plan()

if __name__ == "__main__":
    asyncio.run(main())
