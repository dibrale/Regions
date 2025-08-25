import asyncio
import logging

from regions.base_region import BaseRegion


# Mock region classes for testing
class MockRegion(BaseRegion):
    def __init__(self, name, task = 'things', connections=None, **kwargs):
        super().__init__(name, task, connections)
        self.kwargs = kwargs

    async def mock_method(self):
        await asyncio.sleep(0)
        logging.info("MockRegion method called")
        pass

class MockRAGRegion(BaseRegion):
    def __init__(self, name, task, rag=None, connections=None, **kwargs):
        super().__init__(name, task, connections)
        self.rag = rag
        self.kwargs = kwargs

class MockListenerRegion(MockRegion):
    def __init__(self, name='CC'):
        super().__init__(name)

    def verify(self, orchestrator):
        # Mock verification logic
        profile = orchestrator.region_profile(self.name)
        layers = list(profile.keys())
        last_layer = len(orchestrator.execution_config) - 1
        return layers == [0, last_layer] and profile[0] == ['start'] and profile[last_layer] == ['stop']