import logging

import pytest
import asyncio
from unittest.mock import MagicMock, call
from postmaster import Postmaster
from region import Region


class TestPostmasterInitialization:
    def test_default_parameters(self):
        registry = MagicMock()
        pm = Postmaster(registry)
        assert pm.delay == 0.5
        assert pm.undeliverable == 'drop'
        assert pm.messages.qsize() == 0

    def test_reroute_without_destination_raises_error(self):
        registry = MagicMock()
        with pytest.raises(RuntimeError, match='Reroute destination not specified'):
            Postmaster(registry, undeliverable='reroute', reroute_destination='')

    def test_rts_warning_when_not_used(self, caplog):
        registry = MagicMock()
        Postmaster(registry, rts_source='test', rts_prepend=False, undeliverable='drop')
        assert "Return to sender arguments set, but not used" in caplog.text

    def test_rts_parameters_used_with_return_policy(self, caplog):
        # Set log level BEFORE creating the Postmaster instance
        caplog.set_level(logging.INFO)
        registry = MagicMock()
        pm = Postmaster(registry, undeliverable='return', rts_source='postmaster', rts_prepend=True)
        assert pm.rts_source == 'postmaster'
        assert pm.undeliverable == 'return'
        assert pm.rts_prepend is True
        # print("\n=== CAPLOG ===\n" + caplog.text +"\n=== END CAPLOG ===")
        assert "Undeliverable message behavior is 'return'" in caplog.text

    def test_reroute_destination_set(self, caplog):
        # Set log level BEFORE creating the Postmaster instance
        caplog.set_level(logging.INFO)
        registry = MagicMock()
        pm = Postmaster(registry, undeliverable='reroute', reroute_destination='new_region')
        assert pm.reroute_destination == 'new_region'
        assert pm.undeliverable == 'reroute'
        # print("\n=== CAPLOG ===\n" + caplog.text + "\n=== END CAPLOG ===")
        assert "Routing undeliverable messages to 'new_region'" in caplog.text


class TestPostmasterCollector:
    @pytest.fixture
    async def pm_with_regions(self):
        registry = MagicMock()
        region1 = MagicMock(name='region1', outbox=asyncio.Queue())
        region2 = MagicMock(name='region2', outbox=asyncio.Queue())
        registry.__iter__.return_value = [region1, region2]
        pm = Postmaster(registry, delay=0.01)
        await pm.start()
        yield pm, region1, region2
        pm.collect.cancel()
        pm.emit.cancel()

    @pytest.mark.asyncio
    async def test_collector_drains_outboxes(self, pm_with_regions):
        pm, region1, region2 = pm_with_regions

        # Isolate collector behavior
        pm.emit.cancel()

        # Add properly structured messages
        await region1.outbox.put({
            'source': 'test',
            'destination': 'nonexistent1',
            'content': 'msg1'
        })
        await region2.outbox.put({
            'source': 'test',
            'destination': 'nonexistent2',
            'content': 'msg2'
        })

        # Allow collector to run
        await asyncio.sleep(0.02)

        # Verify collector behavior
        assert pm.messages.qsize() == 2

        # Verify outboxes are empty
        assert region1.outbox.qsize() == 0
        assert region2.outbox.qsize() == 0

        # Restart emitter for other tests (optional)
        pm.emit = asyncio.create_task(pm.emitter())

    @pytest.mark.asyncio
    async def test_collector_respects_delay(self):
        registry = MagicMock()
        region = MagicMock(outbox=asyncio.Queue())
        registry.__iter__.return_value = [region]
        pm = Postmaster(registry, delay=0.1)
        await pm.start()

        # Isolate collector behavior
        pm.emit.cancel()

        # Add message
        await region.outbox.put({'content': 'test'})

        # Check queue empty immediately after
        assert pm.messages.qsize() == 0

        # Wait longer than delay
        await asyncio.sleep(0.15)
        assert pm.messages.qsize() == 1

    @pytest.mark.asyncio
    async def test_collector_yields_control(self, pm_with_regions):
        pm, region1, region2 = pm_with_regions

        # Isolate collector behavior
        pm.emit.cancel()

        await region1.outbox.put({'content': 'msg1'})

        # Short sleep should allow collector to yield
        await asyncio.sleep(0.01)
        assert pm.messages.qsize() == 1


class TestPostmasterEmitter:
    @pytest.fixture
    @pytest.mark.asyncio
    async def pm_no_delivery(self):
        # Registry with no matching regions
        registry = MagicMock()
        registry.__iter__.return_value = []
        registry.messages = asyncio.Queue()
        pm = Postmaster(registry)
        await pm.start()
        yield pm
        pm.collect.cancel()
        pm.emit.cancel()

    @pytest.mark.asyncio
    async def test_delivery_success(self):
        # Setup registry with matching region
        registry = MagicMock()
        region = Region('target','', MagicMock(), None)

        registry.__iter__.return_value = [region]

        pm = Postmaster(registry)
        await pm.start()

        pm.collect.cancel()

        # Send message
        await pm.messages.put({'source': 'sender', 'destination': 'target', 'content': 'test'})

        # Wait for emitter to process
        start_time = asyncio.get_event_loop().time()
        while region.inbox.qsize() == 0 and asyncio.get_event_loop().time() - start_time < 0.1:
            await asyncio.sleep(0.51)

        # Verify delivery
        assert region.inbox.qsize() == 1
        msg = await region.inbox.get()
        assert msg['content'] == 'test'

    @pytest.mark.asyncio
    async def test_undeliverable_drop(self, pm_no_delivery, caplog):
        await pm_no_delivery.messages.put({'source': 'sender', 'destination': 'unknown', 'content': 'test'})
        await asyncio.sleep(0.51)
        assert "could not be delivered" in caplog.text
        assert pm_no_delivery.messages.qsize() == 0  # Message dropped

    @pytest.mark.asyncio
    async def test_undeliverable_retry(self, pm_no_delivery, caplog):
        """Verifies retry policy creates multiple delivery attempts"""
        pm_no_delivery.undeliverable = 'retry'

        # Ensure log messages are captured
        caplog.set_level(logging.INFO)

        # Send undeliverable message
        await pm_no_delivery.messages.put({
            'source': 'sender',
            'destination': 'unknown_region',
            'content': 'test_message'
        })

        # Wait for multiple delivery attempts
        start_time = asyncio.get_event_loop().time()
        while True:
            # Count delivery failure logs
            failure_count = sum(
                1 for record in caplog.records
                if "could not be delivered" in record.message
            )

            # Stop when we've seen enough failures or timeout
            if failure_count >= 2 or asyncio.get_event_loop().time() - start_time > 1:
                break

            await asyncio.sleep(0.01)

        # Verify multiple retry attempts occurred
        assert failure_count >= 2, f"Expected ≥2 delivery failures, got {failure_count}"

    @pytest.mark.asyncio
    async def test_undeliverable_reroute(self, pm_no_delivery):
        pm_no_delivery.undeliverable = 'reroute'
        pm_no_delivery.reroute_destination = 'new_dest'
        await pm_no_delivery.messages.put({'source': 'sender', 'destination': 'unknown', 'content': 'test'})
        await asyncio.sleep(0.51)
        msg = await pm_no_delivery.messages.get()
        assert msg['destination'] == 'new_dest'

    @pytest.mark.asyncio
    async def test_undeliverable_return_with_modifications(self, pm_no_delivery):
        pm_no_delivery.undeliverable = 'return'
        pm_no_delivery.rts_source = 'postmaster'
        pm_no_delivery.rts_prepend = True

        original = {
            'source': 'sender',
            'destination': 'unknown',
            'content': 'test'
        }
        await pm_no_delivery.messages.put(original)
        await asyncio.sleep(0.51)

        msg = await pm_no_delivery.messages.get()
        assert msg['destination'] == 'sender'
        assert msg['source'] == 'postmaster'
        assert "Could not deliver message to 'unknown'" in msg['content']

    @pytest.mark.asyncio
    async def test_undeliverable_return_without_prepend(self, pm_no_delivery):
        pm_no_delivery.undeliverable = 'return'
        pm_no_delivery.rts_source = ''
        pm_no_delivery.rts_prepend = False

        original = {
            'source': 'sender',
            'destination': 'unknown',
            'content': 'test'
        }
        await pm_no_delivery.messages.put(original)
        await asyncio.sleep(0.51)

        msg = await pm_no_delivery.messages.get()
        assert msg['destination'] == 'sender'
        assert msg['source'] == 'sender'  # Original source preserved
        assert msg['content'] == 'test'  # No prepend

    @pytest.mark.asyncio
    async def test_undeliverable_error_raises_exception(self, pm_no_delivery):
        pm_no_delivery.undeliverable = 'error'
        await pm_no_delivery.messages.put({'source': 'sender', 'destination': 'unknown', 'content': 'test'})

        # Wait for emitter to process
        await asyncio.sleep(0.01)

        # Check if emitter task failed
        with pytest.raises(asyncio.CancelledError):
            pm_no_delivery.emit.cancel()
            await pm_no_delivery.emit


class TestPostmasterEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_registry(self):
        registry = MagicMock()
        registry.__iter__.return_value = []
        pm = Postmaster(registry)
        await pm.start()

        # Add message
        await pm.messages.put({'source': 'sender', 'destination': 'test', 'content': 'test'})
        await asyncio.sleep(0.51)

        # Should handle undeliverable (default 'drop' policy)
        assert pm.messages.qsize() == 0

    @pytest.fixture
    @pytest.mark.asyncio
    async def pm_no_delivery(self):
        # Registry with no matching regions
        registry = MagicMock()
        registry.__iter__.return_value = []
        registry.messages = asyncio.Queue()
        pm = Postmaster(registry)
        await pm.start()
        yield pm
        pm.collect.cancel()
        pm.emit.cancel()

    @pytest.mark.asyncio
    async def test_multiple_undeliverable_messages(self, pm_no_delivery):
        pm_no_delivery.undeliverable = 'reroute'
        pm_no_delivery.reroute_destination = 'new_dest'

        # Queue multiple messages
        for i in range(3):
            await pm_no_delivery.messages.put({
                'source': f'sender{i}',
                'destination': f'unknown{i}',
                'content': 'test'
            })

        await asyncio.sleep(0.51)
        assert pm_no_delivery.messages.qsize() == 3

        # Verify all were rerouted
        for _ in range(3):
            msg = await pm_no_delivery.messages.get()
            assert msg['destination'] == 'new_dest'

    @pytest.mark.asyncio
    async def test_mixed_delivery_scenarios(self):
        # Setup registry with one matching region
        registry = MagicMock()
        region = Region('target','', MagicMock(), None)
        registry.__iter__.return_value = [region]
        pm = Postmaster(registry, undeliverable='reroute', reroute_destination='new_dest')
        await pm.start()

        # Send mixed messages
        await pm.messages.put({'source': 'sender', 'destination': 'target', 'content': 'valid'})
        await pm.messages.put({'source': 'sender', 'destination': 'unknown', 'content': 'invalid'})
        await asyncio.sleep(0.02)

        # Verify valid message delivered
        assert region.inbox.qsize() == 1
        valid_msg = await region.inbox.get()
        assert valid_msg['content'] == 'valid'

        # Verify invalid message rerouted
        assert pm.messages.qsize() == 1
        rerouted_msg = await pm.messages.get()
        assert rerouted_msg['destination'] == 'new_dest'

    @pytest.mark.asyncio
    async def test_collector_drain_behavior(self):
        registry = MagicMock()
        region = Region('region','', MagicMock(), None)
        registry.__iter__.return_value = [region]
        pm = Postmaster(registry, delay=0.01)
        await pm.start()

        # Fill outbox with 5 messages
        for i in range(5):
            await region.outbox.put({'content': f'msg{i}'})

        # Wait for collector to drain
        await asyncio.sleep(0.03)
        assert pm.messages.qsize() == 5
        assert region.outbox.qsize() == 0

    @pytest.mark.asyncio
    async def test_task_cancellation(self):
        registry = MagicMock()
        pm = Postmaster(registry)
        await pm.start()

        # Cancel tasks
        pm.collect.cancel()
        pm.emit.cancel()

        # Verify tasks are cancelled
        with pytest.raises(asyncio.CancelledError):
            await pm.collect
        with pytest.raises(asyncio.CancelledError):
            await pm.emit