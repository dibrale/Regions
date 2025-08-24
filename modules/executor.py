import logging
from dataclasses import dataclass
from typing import Any
import asyncio  # Critical addition for async operations
from functools import partial

from region_types import *
from region import *
from postmaster import Postmaster
from orchestrator import Orchestrator
from region_registry import RegionRegistry


async def execute_layer(
        registry: RegionRegistry,
        orchestrator: Orchestrator,
        postmaster: Postmaster,
        layer: int,
) -> bool:
    """Run one layer of a distributed region execution plan"""
    # Validate layer index
    if layer >= len(orchestrator.layer_config):
        logging.error(
            f"Layer {layer} out of orchestrator layer configuration range (max: {len(orchestrator.layer_config) - 1})")
        return False

    layer_config = orchestrator.layer_config[layer]
    chain_tasks = []

    # Process each chain concurrently
    for chain_name, regions in layer_config.items():
        # Create async task for this chain (executing regions serially)
        async def run_chain(regs=regions.copy()):  # Use copy to avoid late binding issues
            for region_name in regs:
                methods = orchestrator.methods_in_layer(layer, region_name)
                for method_name in methods:
                    try:
                        region = registry[region_name]
                        # Execute method
                        await getattr(region, method_name)()
                    except Exception as e:
                        logging.error(f"Error executing {method_name} for {region_name}: {str(e)}")
                        return False
            return True

        chain_tasks.append(run_chain())

    # Run all chains concurrently
    results = await asyncio.gather(*chain_tasks, return_exceptions=True)

    # Check if all chains succeeded
    success = all(isinstance(r, bool) and r for r in results)
    if not success:
        failed_chains = [i for i, r in enumerate(results) if not (isinstance(r, bool) and r)]
        logging.error(f"Layer {layer} failed in {len(failed_chains)} chains")

    return success


async def execute_plan(
        registry: RegionRegistry,
        orchestrator: Orchestrator,
        postmaster: Postmaster,
) -> bool:
    """Run a verified distributed region execution plan"""
    # Determine execution order
    execution_order = orchestrator.execution_order or range(len(orchestrator.layer_config))

    # Execute layers in order
    for layer_idx in execution_order:
        success = await execute_layer(registry, orchestrator, postmaster, layer_idx)
        if not success:
            logging.error(f"Execution failed at layer {layer_idx}")
            return False

    return True


@dataclass
class Executor:
    """Context for the execution of regions within a distributed system."""
    registry: RegionRegistry = None
    orchestrator: Orchestrator = None
    postmaster: Postmaster = None

    def __enter__(self):
        self.run_layer = partial(execute_layer, self.registry, self.orchestrator, self.postmaster)
        self.run_plan = partial(execute_plan, self.registry, self.orchestrator, self.postmaster)
        return self

    def __exit__(self, *exc):
        pass  # nothing special to clean up


@dataclass
class Execute:
    registry: RegionRegistry = None
    orchestrator: Orchestrator = None
    postmaster: Postmaster = None
    executor_name: str = 'ex'

    def __call__(self, func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs) -> Any:
            # Create the executor
            executor = Executor(self.registry, self.orchestrator, self.postmaster)

            # Add executor to kwargs under the specified name
            kwargs[self.executor_name] = executor

            # Call the function with the executor
            return await func(*args, **kwargs)

        def sync_wrapper(*args, **kwargs) -> Any:
            # Create the executor
            executor = Executor(self.registry, self.orchestrator, self.postmaster)

            # Add executor to kwargs under the specified name
            kwargs[self.executor_name] = executor

            # Call the function with the executor
            return func(*args, **kwargs)

        # Determine if the function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper