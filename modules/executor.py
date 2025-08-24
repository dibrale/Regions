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
            methods_in_chain = []

            # Populate a list of futures for all method calls in this chain
            for region_name in regs:
                method_names = orchestrator.methods_in_layer(layer, region_name)
                for method_name in method_names:
                    try:
                        # Get method to be executed
                        method = getattr(registry[region_name], method_name)

                        #Determine whether method is sync or async
                        is_async_method = asyncio.iscoroutinefunction(method)

                        if is_async_method:
                            methods_in_chain.append((method_name, region_name, method))
                        else:
                            loop = asyncio.get_running_loop()
                            methods_in_chain.append(loop.run_in_executor(None, method))

                    except Exception as e:
                        logging.error(
                            f"Error setting up '{method_name}' of region '{region_name}' for chain '{chain_name}': {str(e)}")
                        return False

            # Execute chain methods sequentially
            for method_name, region_name, method in methods_in_chain:
                try:
                    await method
                except Exception as e:
                    logging.error(
                        f"Error awaiting '{method_name}' of region '{region_name} in chain '{chain_name}': {str(e)}")
                    return False

            return True

        chain_tasks.append(run_chain())

    # Run all chains concurrently
    results = await asyncio.gather(*chain_tasks, return_exceptions=True)

    # Check if all chains succeeded
    success = all(isinstance(r, bool) and r for r in results)
    if not success:
        failed_chains = [i for i, r in enumerate(results) if not (isinstance(r, bool) and r)]
        logging.error(
            f"Layer {layer} failed in {len(failed_chains)} chains: {', '.join([str(chain) for chain in failed_chains])}")

    return success


async def execute_plan(
        registry: RegionRegistry,
        orchestrator: Orchestrator,
        postmaster: Postmaster,
) -> bool:
    """Run a verified distributed region execution plan"""
    # Determine execution order
    execution_order = orchestrator.execution_order or range(len(orchestrator.layer_config))
    success = True

    try:
        await postmaster.start()
    except Exception as e:
        logging.error(f"Failed to start Postmaster: {e}")
        try:
            await postmaster.stop()
        except Exception as e2:
            logging.error(f"Failed to stop Postmaster after failure: {e2}")
        logging.info(f"Aborting execution.")
        return False

    # Execute layers in order
    for layer_idx in execution_order:
        try:
            success = await execute_layer(registry, orchestrator, layer_idx)
        except Exception as e:
            logging.error(f"{e}")
            success = False
        if not success:
            logging.error(f"Execution failed at layer {layer_idx}")
            logging.info(f"Aborting execution.")
            break

    try:
        stop_success = await postmaster.stop()
        if not stop_success:
            logging.error(f"Failed to stop Postmaster during cleanup.")
            success = False
    except Exception as e:
        logging.error(f"Failed to stop Postmaster during cleanup: {e}")

    return success


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