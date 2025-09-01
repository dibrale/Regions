# Regions


[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![CodeFactor](https://www.codefactor.io/repository/github/dibrale/regions/badge)](https://www.codefactor.io/repository/github/dibrale/regions)

Modular framework for building message‑passing "regions" that collaborate through configurable execution plans. It includes:

- **Regions**: autonomous units built to accommodate an LLM interface, exchanging messages through inbox/outbox queues
- **Orchestrator**: defines layered execution plans and chains of region methods
- **Executor**: runs the plan layer‑by‑layer and handles async/sync region methods
- **Postmaster**: background message transport between regions
- **RegionRegistry**: builds and manages region instances (with defaults)
- **Dynamic RAG**: simple, local, sqlite‑backed store/retrieve pipeline with an external embedding server
- **LLMLink**: lightweight HTTP client for text generation/health/model endpoints

This repo also provides examples and a pytest suite to help you get started quickly.


## Features
- Compose systems from Regions (Region, RAGRegion, ListenerRegion)
- Configure layered execution with Orchestrator (methods per region per layer)

```python
# Execute agents in coordinated layers
orchestrator = Orchestrator()
orchestrator.add_to_layer(0, "preprocessing", ["data_ingestion", "validation"])
orchestrator.add_to_layer(1, "analysis", ["sentiment_analyzer", "topic_extractor"])
orchestrator.add_to_layer(2, "response", ["response_generator", "quality_checker"])
```
- Understand and optimize your agent coordination patterns.

```python
# Analyze execution patterns
profile = orchestrator.region_profile("sentiment_analyzer")
# Returns: {0: ["preprocess"], 1: ["analyze_sentiment", "extract_entities"]}
```

- Execute plans with async concurrency where possible (Executor)
- Layer-by-layer execution for debugging
```python
with Executor(registry, orchestrator, postmaster) as executor:
    await executor.run_layer(0)  # Test individual layers
    # Analyze results before proceeding
    await executor.run_layer(1)
```
- Full control over agent communication with explicit routing.
- Message injection for testing and debugging
```python
from modules.injector import Addressograph
from modules.postmaster import Postmaster
from modules.region_registry import RegionRegistry

registry = RegionRegistry()
# Initialize with the appropriate parameters
postmaster = Postmaster(registry)

@Addressograph(postmaster, "test_user", role="request", injector_name="user")
def test_scenario(user):
    user.send("customer_service", "I need help with my order")
    user.send("billing", "What's my current balance?")
```

- Decouple communication via queues and a Postmaster relay loop
- Store/retrieve/update document chunks with DynamicRAGSystem
- Pluggable LLM via LLMLink (text(), chat(), health(), model())
- Extensive unit tests for core components


## Requirements
- Python 3.10 or newer (tested with modern type hints like list[str], | unions)
- Windows, macOS, or Linux (examples below use Windows PowerShell)

Install dependencies:

```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional runtime services:
- An embedding server for DynamicRAGSystem. You can change host/model in your code or in example params.
- An LLM HTTP endpoint for LLMLink (configurable via parameters).


## Quick-ish Start
There is a basic example under examples\demo.py. It initializes two RAG stores, two RAG regions, and one synthesizing LLM-powered Region, then routes messages to produce a final answer.

Before running examples or tests, add the project’s modules directory to PYTHONPATH so imports like `from regions.region import Region` and `from llmlink import LLMLink` work:

```powershell
# From the project root
$env:PYTHONPATH = ".;.\modules"
```

Then run the demo:

```powershell
cd examples
# Adjust demo_params.json to point to your LLM and embedding servers if needed
python .\demo.py
```

You should see logs about chunk storage, message routing, and a synthesized final answer about the leader of the Zebras. 
The demo also cleans up the sqlite files it created.

Minimal code sketch (for reference only):

```python
import asyncio
from llmlink import LLMLink
from regions.region import Region
from regions.rag_region import RAGRegion
from dynamic_rag import DynamicRAGSystem

async def main():
    llm = LLMLink(params={"host": "127.0.0.1:5000"})

    rag = DynamicRAGSystem(db_path="example.db", embedding_server_url="http://localhost:8080")
    await rag.store_document("A short note about zebras.", actors=["facts"])  # store a doc

    facts = RAGRegion(name="Facts", task="Provide factual info", rag=rag, connections={}, reply_with_actors=True)
    user = Region(name="User", task="Answer user questions", llm=llm, connections={"Facts": "Provide factual info"})
    facts.connections = {"User": user.task}

    await user.inbox.put({"source": "control", "role": "request", "content": "Tell me about zebras"})
    await user.make_questions()   # ask connected regions
    await facts.make_replies()    # reply from RAG
    while not facts.outbox.empty():
        user.inbox.put_nowait(facts.outbox.get_nowait())
    await user.make_replies()     # synthesize final answer

asyncio.run(main())
```


## GUI: Visual Flow Editor
A React-based editor for composing Regions, configuring connections, and assigning methods to layered execution plans. You can load and save JSON plans to use with the Python orchestrator/executor.

![GUI Screenshot](gui/gui_screenshot.png)

Install and run the GUI (React + Vite):

```powershell
# From the project root
cd gui

# Option A: pnpm (recommended)
# If pnpm isn't installed, install once:
npm install -g pnpm
pnpm install
pnpm dev

# Option B: npm
npm install
npm run dev
```

Then open http://localhost:5173 in your browser. To build a production bundle:

```powershell
pnpm build
```

## Architecture Overview
- Region (modules\regions\region.py):
  - Core async methods: `make_questions()`, `make_replies()`
  - Queues: `inbox`, `outbox` with `_ask()`, `_reply()`, `_run_inbox()` helpers
- RAGRegion / ListenerRegion (modules\regions): specialized Regions
- Orchestrator (modules\orchestrator.py):
  - Maintains `layer_config`, exposes helpers like `methods_in_layer()`, `append_to_layer()`, `verify()`, `save()/load()`
- Executor (modules\executor.py):
  - `execute_plan(registry, orchestrator, postmaster)` runs layers in order
  - `execute_layer(...)` schedules sync/async region methods and awaits completion
- Postmaster (modules\postmaster.py): background loops to collect/resend/emit messages between regions
- RegionRegistry (modules\region_registry.py): builds/updates regions from RegionEntry descriptors
- DynamicRAGSystem (modules\dynamic_rag.py): sqlite storage, chunking, retrieval, update/delete, simple cosine similarity re‑ranking
- LLMLink (modules\llmlink.py): text/chat/model/health calls against an HTTP LLM server


## Running Tests
This project ships with pytest unit tests covering the core framework and components.

```powershell
# From the project root
$env:PYTHONPATH = ".;.\modules"
python -m pytest -q
```

Note that test_params.json may need to be moved to the project directory for some configurations. Some tests interact with async code; pytest.ini already sets `asyncio_mode = auto`.


## Configuration & Examples
- See examples\demo_params.json for LLM and embedding server settings used by examples\demo.py
- Additional example datasets: examples\demo_historical.json, examples\demo_biography.json
- A prebuilt registry example: examples\regions.json
- Execution plan example: examples\demo_executions.json (used by the infrastructure demo)
- Full infrastructure demo: examples\demo_with_infrastructure.py (loads params, regions, executions; wires two RAGs and an LLM; can be edited/inspected via the GUI)

Run the infrastructure demo:
```powershell
# From the project root
$env:PYTHONPATH = ".;.\modules"
cd examples
python .\demo_with_infrastructure.py
```


## Project Structure
- modules\: core framework (orchestrator, executor, postmaster, registry, RAG, LLM link)
- modules\regions\: Region implementations (base, region, rag_region, listener_region)
- examples\: runnable demo and params
- tests\: unit tests for core modules


## Notes
- The demo uses HTTP (not HTTPS) for simplicity. Configure SSL in your own deployments if required.
- The Dynamic RAG system uses sqlite files in the working directory; demos will create and (often) clean them up.


## Contributing
Issues and PRs are welcome! I've only been able to test the components of this framework on a limited number of machines. Any bug reports and feedback - both positive and negative - are heartily appreciated. If you are having difficulty running the framework, please let me know and I will do my best to help you. Consider running the test suite before submitting changes.
