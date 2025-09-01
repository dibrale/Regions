import logging
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from executor import execute_layer, execute_plan, Executor, Execute
from orchestrator import Orchestrator
from postmaster import Postmaster
from region_registry import RegionRegistry, RegionEntry
from region_types import *


# Mock registry implementation for testing
class MockRegionRegistry:
    def __init__(self, regions):
        self.regions = regions
        self.names = list(regions.keys())

    def __getitem__(self, name):
        return self.regions[name]

    def __iter__(self):
        return iter(self.regions.values())

@pytest.fixture
def test_registry():
    # Setup mock regions
    region1 = MockRegion('region1')
    region2 = MockRegion('region2')
    entry1 = RegionEntry()
    entry2 = RegionEntry()
    entry1.from_region(region1)
    entry2.from_region(region2)
    registry = RegionRegistry()
    registry.register(entry1)
    registry.register(entry2)
    return registry

@pytest.mark.asyncio
async def test_execute_layer_success(caplog, test_registry):
    """Test successful execution of a valid layer"""
    # Setup mock regions
    registry = test_registry

    # Configure orchestrator
    layer_config = [{'chain1': ['region1', 'region2']}]
    execution_config = [[('region1', 'mock_method'), ('region2', 'mock_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    # Execute layer
    result = await execute_layer(registry, orchestrator, 0)

    # Verify success
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is True
    assert "MockRegion method called" in caplog.text
    assert "Layer 0 failed" not in caplog.text
    assert "Message sent" not in caplog.text  # No postmaster involved in execute_layer


@pytest.mark.asyncio
async def test_execute_layer_out_of_range(caplog):
    """Test layer index beyond orchestrator configuration"""
    # Setup minimal orchestrator
    orchestrator = Orchestrator(layer_config=[{}], execution_config=[[]])

    # Execute out-of-range layer
    result = await execute_layer(MagicMock(), orchestrator, 1)

    # Verify failure and logging
    assert result is False
    assert "Layer 1 out of orchestrator layer configuration range" in caplog.text


@pytest.mark.asyncio
async def test_execute_layer_chain_failure(caplog, test_registry):
    """Test chain failure handling"""

    class FailingRegion(MockRegion):
        async def mock_method(self):
            await asyncio.sleep(0.1)
            raise RuntimeError("Test failure")

    region_dictionary.append({"name": "FailingRegion", "class": FailingRegion})

    # Setup regions with failing method
    region2 = FailingRegion('region2')
    registry = test_registry
    registry.update(RegionEntry.make(region2))

    # Configure orchestrator
    layer_config = [{'chain1': ['region1', 'region2']}]
    execution_config = [[('region1', 'mock_method'), ('region2', 'mock_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    # Execute layer
    result = await execute_layer(registry, orchestrator, 0)

    # Verify failure and logging
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False
    assert "Layer 0 failed in 1 chains" in caplog.text
    assert "Error awaiting 'mock_method' of region 'region2'" in caplog.text


@pytest.mark.asyncio
async def test_execute_plan_success(caplog, test_registry):
    """Test full successful execution plan"""
    # Setup mock components
    registry = test_registry

    layer_config = [{'chain1': ['region1']}]
    execution_config = [[('region1', 'mock_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    postmaster = Postmaster(registry)
    postmaster.start = AsyncMock()
    postmaster.stop = AsyncMock(return_value=True)

    # Execute plan
    result = await execute_plan(registry, orchestrator, postmaster)

    # Verify success
    assert result is True
    assert "Aborting execution" not in caplog.text
    postmaster.start.assert_awaited_once()
    postmaster.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_plan_postmaster_start_failure(caplog):
    """Test postmaster startup failure handling"""
    # Setup failing postmaster
    postmaster = MagicMock(spec=Postmaster)
    postmaster.start = AsyncMock(side_effect=RuntimeError("Startup failed"))
    postmaster.stop = AsyncMock()

    # Execute plan
    result = await execute_plan(MagicMock(), MagicMock(), postmaster)

    # Verify failure handling
    assert result is False
    assert "Failed to start Postmaster" in caplog.text
    postmaster.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_plan_layer_failure(caplog, test_registry):
    """Test layer failure abort behavior"""

    # Setup failing region
    class FailingRegion(MockRegion):
        async def mock_method(self):
            raise RuntimeError("Layer failure")

    region_dictionary.append({"name": "FailingRegion", "class": FailingRegion})

    region1 = FailingRegion('region1')
    registry = test_registry
    registry.update(RegionEntry.make(region1))

    layer_config = [{'chain1': ['region1']}]
    execution_config = [[('region1', 'mock_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    postmaster = MagicMock(spec=Postmaster, delay=0.5, messages=asyncio.Queue())
    postmaster.start = AsyncMock()
    postmaster.stop = AsyncMock()

    # Execute plan
    result = await execute_plan(registry, orchestrator, postmaster)

    # Verify abort behavior
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False
    assert "Execution failed at layer 0" in caplog.text
    assert "Aborting execution" in caplog.text
    postmaster.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_plan_postmaster_stop_failure(caplog, test_registry):
    """Test postmaster shutdown failure handling"""
    # Setup mock components
    registry = test_registry

    layer_config = [{'chain1': ['region1']}]
    execution_config = [[('region1', 'mock_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    postmaster = MagicMock(spec=Postmaster, delay=0.5, messages=asyncio.Queue())
    postmaster.start = AsyncMock()
    postmaster.stop = AsyncMock(side_effect=RuntimeError("Shutdown failed"))

    # Execute plan
    result = await execute_plan(registry, orchestrator, postmaster)

    # Verify cleanup behavior
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False
    assert "Failed to stop Postmaster during cleanup" in caplog.text


def test_executor_context_manager():
    """Test Executor context manager behavior"""
    registry = MagicMock()
    orchestrator = MagicMock()
    postmaster = MagicMock()

    with Executor(registry, orchestrator, postmaster) as executor:
        # Verify bound execution methods
        assert callable(executor.run_layer)
        assert callable(executor.run_plan)

        # Verify partial binding
        assert executor.run_layer.func == execute_layer
        assert executor.run_layer.args == (registry, orchestrator)
        assert executor.run_plan.func == execute_plan
        assert executor.run_plan.args == (registry, orchestrator, postmaster)


@pytest.mark.asyncio
async def test_execute_async_function():
    """Test Execute decorator with async functions"""
    registry = MagicMock()
    orchestrator = MagicMock()
    postmaster = MagicMock()

    @Execute(registry, orchestrator, postmaster)
    async def test_func(ex):
        """Test function with injected executor"""
        assert ex.run_layer(0) is not None
        return "success"

    # Verify decorator behavior
    result = await test_func()
    assert result == "success"


def test_execute_sync_function():
    """Test Execute decorator with sync functions"""
    registry = MagicMock()
    orchestrator = MagicMock()
    postmaster = MagicMock()

    @Execute(registry, orchestrator, postmaster)
    def test_func(ex):
        """Test function with injected executor"""
        assert ex.run_layer(0) is not None
        return "success"

    # Verify decorator behavior
    result = test_func()
    assert result == "success"


def test_execute_custom_executor_name():
    """Test custom executor name injection"""
    registry = MagicMock()
    orchestrator = MagicMock()
    postmaster = MagicMock()

    @Execute(registry, orchestrator, postmaster, executor_name='custom_executor')
    def test_func(custom_executor):
        """Test function with custom named executor"""
        assert custom_executor.run_layer(0) is not None
        return "success"

    # Verify custom name injection
    result = test_func()
    assert result == "success"


@pytest.mark.asyncio
async def test_execute_layer_async_sync_methods(caplog):
    """Test handling of both async and sync region methods"""

    class MixedRegion(MockRegion):
        async def async_method(self):
            await asyncio.sleep(0)
            logging.info("Async method called")
            return True

        def sync_method(self):
            logging.info("Sync method called")
            return True

    regions = {'region1': MixedRegion('region1')}
    registry = MockRegionRegistry(regions)

    layer_config = [{'chain1': ['region1']}]
    execution_config = [[('region1', 'async_method'), ('region1', 'sync_method')]]
    orchestrator = Orchestrator(layer_config, execution_config)

    # Execute layer
    result = await execute_layer(registry, orchestrator, 0)
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    # Verify both method types executed successfully
    assert result is True