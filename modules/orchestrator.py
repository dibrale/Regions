import asyncio
import json
import logging
import pathlib

from dataclasses import dataclass
from typing import List
from stringutils import sanitize_path

from dynamic_rag import DynamicRAGSystem
from llmlink import LLMLink
from region import BaseRegion, RAGRegion, Region
from region_registry import RegionRegistry, RegionEntry
from postmaster import Postmaster


class Orchestrator:
    """
    Execution planning and configuration class for region-based communication. Each registered region is assigned to at
    least one execution layer. Although regions sharing an execution layer are intended to run concurrently, subsets
    of the layer can be configured to run serially. Execution layers themselves run serially relative to one another
    in a preconfigured order.

    The **layer configuration** determines which chains run in a given layer as well as serial execution sequence
    position and membership. The **execution configuration** specifies what methods are called for each region, as well
    as the relative order in which these methods are called once a region is run.

    Side effects:

    - While links between regions within the same layer are permitted, they carry the potential of introducing undesirable race conditions

    - After a layer executes, the resources it was using (eg. LLMLink) are freed for use by other layers

    - Regions sharing the same resource within a layer must be grouped into chains to serialize utilization. This can be useful if a layer contains regions with mixed latencies – low-latency regions can run serially while a high-latency region blocks a dedicated resource.

    - The computation speed of each layer is determined by the speed of the slowest serial execution sequence within it.

    - A region may be called more than once while a layer is being executed. In such a case, all calls to one region are treated as a serial execution sequence that runs when the region is called.

    - There is nothing preventing a region from being assigned to more than one execution layer, provided the above considerations are taken into account.

    Note:
        Execution layers are concurrency groups. Within a layer, chains define serial execution sequences that run
        concurrently with other chains in the same layer.

        Execution layers differ from perceptron layers in a neural network. Conventional layer membership is determined
        by the position of a node in a network graph. Membership in an execution layer is determined by the relative
        state of a node with respect to the execution sequence – a dimension which maps one-to-one to a segment of runtime.

    Example 1:
        Layer configuration to execute "foo", then "bar" while "baz" runs in parallel

        >>> layer = {"chain1":["foo","bar"],"chain2":["baz"]}
        >>> layer = dict(
                        chain1=["foo","bar"],
                        chain2=["baz"]
                        )

    Example 2:
        Region execution configurations for the above layer that causes "foo" and "bar" to make_questions while
        "baz" runs make_answers, then ponder_deeply in parallel.

        >>> executions = [("foo", "make_questions"), ("bar", "make_questions"), ("baz", "make_answers"), ("baz", "ponder_deeply")]
        >>> executions = [("bar", "make_questions"), ("baz", "make_answers"), ("foo", "make_questions"), ("baz", "ponder_deeply")]

        **Incorrect** (ponder_deeply executes before make_answers):

        >>> executions = [("bar", "make_questions"), ("baz", "ponder_deeply"), ("foo", "make_questions"), ("baz", "make_answers")]
    """
    def __init__(self,
                 registry: RegionRegistry,
                 layer_config: list[dict] = None,
                 execution_config: list[tuple] = None,
                 ):
        self.registry = registry
        self.layer_config = layer_config
        self.execution_config = execution_config

    def __len__(self):
        return len(self.layer_config)

    def __getitem__(self, item):
        return self.layer_config[item]

    def __setitem__(self, key, value):
        self.layer_config[key] = value

    def __iter__(self):


dict()

rag = DynamicRAGSystem()
llm = LLMLink()

async def main():
    entry = RegionEntry()
    getattr(llm,'chat')

    return

if __name__ == "__main__":
    asyncio.run(main())