import asyncio
import json
import logging
import pathlib

from dataclasses import dataclass
from typing import List
from stringutils import sanitize_path

from dynamic_rag import DynamicRAGSystem
from llamacpp_api import LLMLink
from region import BaseRegion, RAGRegion, Region
from region_registry import RegionRegistry, RegionEntry
from postmaster import Postmaster

class Orchestrator:
    """
    Execution planning and configuration class for region-based communication. Each registered region is assigned to at
    least one execution layer. Regions sharing an execution layer are intended to run concurrently. Execution layers
    themselves run serially relative to one another in a preconfigured order.

    Side effects:
    - While links between regions within the same layer are permitted, they carry the potential of introducing
    undesirable race conditions
    - After a layer executes, the resources it was using (eg. LLMLink) are freed for use by other layers
    - Regions within a layer that share a resource must utilize this resource serially. This can be useful if a layer
    contains regions with mixed latencies – low-latency regions can run serially while a high-latency region blocks a
    dedicated resource.
    - The computation speed of each layer is determined by the speed of the slowest serial execution sequence within it
    - There is nothing preventing a region from being assigned to more than one execution layer, provided the above
    considerations are taken into account

    Note:
        Execution layers are concurrency groups. They differ from perceptron layers in a neural network. Conventional
        layer membership is determined by the position of a node in a network graph. Membership in an execution layer is
        determined by the relative state of a node with respect to the execution sequence – a dimension which maps
        one-to-one to a segment of runtime.
    """
    def __init__(self, registry: RegionRegistry, layer_plan):
        self.registry = registry


rag = DynamicRAGSystem()
llm = LLMLink()

async def main():
    entry = RegionEntry()

    return

if __name__ == "__main__":
    asyncio.run(main())