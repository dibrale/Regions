from dataclasses import dataclass
from typing import Any, Callable
from functools import partial

from region_types import *
from postmaster import Postmaster
from orchestrator import Orchestrator
from region_registry import RegionRegistry


async def execute_layer(
        registry: RegionRegistry,
        orchestrator: Orchestrator,
        layer: int,
) -> bool:
    """
    Execute a single layer of the distributed region execution plan.

    This function runs all chains within a specific execution layer concurrently,
    with each chain executing its region methods sequentially. Handles both
    synchronous and asynchronous region methods through proper coroutine wrapping.

    Parameters:
        registry: Region registry containing all registered regions
        orchestrator: Orchestrator defining the execution plan structure
        layer: Index of the layer to execute (0-based)

    Returns:
        True if all chains in the layer executed successfully, False otherwise

    Raises:
        ValueError: If layer index exceeds orchestrator's configuration

    Notes:
        - Each chain runs concurrently but methods within a chain run serially
        - Logs detailed errors for failed method executions
        - Returns False immediately upon any chain failure
    """
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
            loop = asyncio.get_running_loop()

            # Populate a list of futures for all method calls in this chain
            for region_name in regs:
                method_names = orchestrator.methods_in_layer(layer, region_name)
                for method_name in method_names:
                    try:
                        # Get method to be executed
                        method = getattr(registry[region_name], method_name)

                        # Determine whether method is sync or async
                        is_async_method = asyncio.iscoroutinefunction(method)

                        if is_async_method:
                            methods_in_chain.append((method_name, region_name, method))
                            # logging.info(
                            #     f"Scheduling '{method_name}' of region '{region_name}' for chain '{chain_name}' as async.")
                        else:

                            methods_in_chain.append((
                                method_name, region_name, loop.run_in_executor(None, method)
                            ))
                            # logging.info(
                            #     f"Scheduling '{method_name}' of region '{region_name}' for chain '{chain_name}' as sync in executor.")

                    except Exception as e:
                        logging.error(
                            f"Error setting up '{method_name}' of region '{region_name}' for chain '{chain_name}': {str(e)}")
                        return False

            # Execute chain methods sequentially
            logging.info(f"Starting chain '{chain_name}' with {len(methods_in_chain)} methods.")
            for method_name, region_name, method in methods_in_chain:
                try:
                    logging.info(f"Executing '{method_name}' of region '{region_name}'.")

                    if asyncio.isfuture(method):
                        await method
                    else:
                        task = asyncio.create_task(method())
                        await task

                except Exception as e:
                    logging.error(
                        f"Error awaiting '{method_name}' of region '{region_name}' in chain '{chain_name}': {str(e)}")
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
    """
    Execute a verified distributed region execution plan across all layers.

    Manages the full execution lifecycle including postmaster startup/shutdown,
    layer-by-layer execution, and failure handling. Executes layers according
    to the orchestrator's specified execution order.

    Parameters:
        registry: Region registry containing all registered regions
        orchestrator: Orchestrator defining the execution plan structure
        postmaster: Postmaster instance handling inter-region communication

    Returns:
        True if the entire execution plan completed successfully, False otherwise

    Notes:
        - Starts the postmaster before execution begins
        - Stops the postmaster regardless of execution success/failure
        - Aborts immediately upon first layer failure
        - Logs detailed error information at each failure point
    """
    # Determine execution order
    execution_order = orchestrator.execution_order or range(len(orchestrator.layer_config))
    success = True

    # Start the postmaster
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

    # Stop the postmaster
    try:
        stop_success = await postmaster.stop()
        if not stop_success:
            logging.error(f"Failed to stop Postmaster during cleanup.")
            success = False
    except Exception as e:
        logging.error(f"Failed to stop Postmaster during cleanup: {e}")
        success = False

    return success


@dataclass
class Executor:
    """
    Context manager for executing distributed region operations.

    Provides a structured interface for executing region execution plans,
    encapsulating the necessary components (registry, orchestrator, postmaster)
    and exposing execution methods through context management.

    Attributes:
        registry: Region registry containing all registered regions
        orchestrator: Orchestrator defining the execution plan structure
        postmaster: Postmaster instance handling inter-region communication

    Usage:
        with Executor(registry, orchestrator, postmaster) as executor:
            executor.run_layer(0)
            executor.run_plan()
    """
    registry: RegionRegistry = None
    orchestrator: Orchestrator = None
    postmaster: Postmaster = None

    def __enter__(self):
        """Initialize execution context by binding partial execution functions."""
        self.run_layer = partial(execute_layer, self.registry, self.orchestrator)
        self.run_plan = partial(execute_plan, self.registry, self.orchestrator, self.postmaster)
        return self

    def __exit__(self, *exc):
        """Clean up execution context (no-op in this implementation)."""
        pass  # nothing special to clean up


@dataclass
class Execute:
    """
    Decorator for injecting executor context into functions.

    Creates and injects an Executor instance into decorated functions,
    allowing them to execute region operations without direct dependency
    on execution infrastructure components.

    Attributes:
        registry: Region registry to be used in execution
        orchestrator: Orchestrator defining the execution plan
        postmaster: Postmaster handling communication
        executor_name: Keyword argument name for injected executor (default: 'ex')

    Usage:
        @Execute(registry, orchestrator, postmaster)
        async def my_function(ex):
            await ex.run_layer(0)

        @Execute(registry, orchestrator, postmaster, executor_name='executor')
        def sync_function(executor):
            executor.run_layer(0)
    """
    registry: RegionRegistry = None
    orchestrator: Orchestrator = None
    postmaster: Postmaster = None
    executor_name: str = 'ex'

    def __call__(self, func: Callable) -> Callable:
        """
        Wrap a function to inject executor context.

        Creates an Executor instance and injects it into the function's
        keyword arguments under the specified name.

        Parameters:
            func: The function to decorate (can be sync or async)

        Returns:
            Wrapped function with executor injection

        Notes:
            - Maintains original function signature
            - Handles both synchronous and asynchronous functions
            - Executor is created fresh for each function call
        """

        async def async_wrapper(*args, **kwargs) -> Any:
            # Create the executor
            executor = Executor(self.registry, self.orchestrator, self.postmaster).__enter__()

            # Add executor to kwargs under the specified name
            kwargs[self.executor_name] = executor

            # Call the function with the executor
            return await func(*args, **kwargs)

        def sync_wrapper(*args, **kwargs) -> Any:
            # Create the executor
            executor = Executor(self.registry, self.orchestrator, self.postmaster).__enter__()

            # Add executor to kwargs under the specified name
            kwargs[self.executor_name] = executor

            # Call the function with the executor
            return func(*args, **kwargs)

        # Determine if the function is async
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper