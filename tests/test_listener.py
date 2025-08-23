import unittest
import asyncio
import multiprocessing as mp
from unittest.mock import MagicMock, patch
from region import ListenerRegion


class TestListenerRegion(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Mock out_process that records queue items
        self.received_messages = []

        def mock_out_process(q):
            while True:
                msg = q.get()
                if msg is None:
                    break
                self.received_messages.append(msg)

        self.mock_out_process = MagicMock(side_effect=mock_out_process)
        self.region = ListenerRegion("test", self.mock_out_process, delay=0)

    async def asyncTearDown(self):
        # Ensure clean shutdown if tests leave region running
        if hasattr(self.region, 'p') and self.region.p:
            self.region.out_q.put(None)
            self.region.p.join(timeout=2.0)
            if self.region.p.is_alive():
                self.region.p.terminate()
            self.region.p.close()

    async def test_initialization_attributes_deleted(self):
        """Verify critical attributes were deleted during initialization"""
        with self.assertRaises(AttributeError):
            _ = self.region.connections
        with self.assertRaises(AttributeError):
            _ = self.region.outbox
        with self.assertRaises(NotImplementedError):
            self.region._post("dest", "content", "role")
        with self.assertRaises(NotImplementedError):
            self.region._ask("dest", "query")
        with self.assertRaises(NotImplementedError):
            self.region._reply("dest", "reply")
        with self.assertRaises(NotImplementedError):
            self.region._run_inbox()

    async def test_start_creates_process_and_task(self):
        """Verify start() initializes process and forwarding task"""
        await self.region.start()

        self.assertIsNotNone(self.region.p)
        self.assertIsNotNone(self.region.forward_task)
        self.assertTrue(self.region.p.is_alive())
        self.mock_out_process.assert_called_once()

    async def test_start_called_twice_raises_runtimeerror(self):
        """Verify calling start() twice raises RuntimeError"""
        await self.region.start()
        with self.assertRaises(RuntimeError):
            await self.region.start()

    async def test_stop_sends_sentinel_and_terminates(self):
        """Verify stop() sends sentinel and properly terminates resources"""
        await self.region.start()
        await self.region.stop()

        # Verify sentinel was sent
        self.region.out_q.put.assert_called_with(None)

        # Verify process termination
        self.region.p.join.assert_called_with(timeout=2.0)
        self.assertFalse(self.region.p.is_alive())

        # Verify task cleanup
        self.assertIsNone(self.region.forward_task)

    async def test_message_forwarding(self):
        """Verify messages are properly forwarded from inbox to output queue"""
        await self.region.start()

        # Add test messages to inbox
        test_messages = [
            {"source": "A", "destination": "B", "content": "msg1", "role": "request"},
            {"source": "C", "destination": "D", "content": "msg2", "role": "reply"}
        ]
        for msg in test_messages:
            self.region.inbox.put_nowait(msg)

        # Allow time for forwarding
        await asyncio.sleep(0.1)
        await self.region.stop()

        # Verify messages were forwarded
        self.assertEqual(len(self.received_messages), 2)
        self.assertEqual(self.received_messages, test_messages)

    async def test_stop_without_start(self):
        """Verify stop() works gracefully when called without start()"""
        await self.region.stop()  # Should not raise errors

        # Verify no operations were attempted
        self.assertIsNone(self.region.p)
        self.assertIsNone(self.region.forward_task)
        self.region.out_q.put.assert_not_called()

    async def test_cancellation_drains_inbox(self):
        """Verify inbox is drained during task cancellation"""
        await self.region.start()

        # Add message and cancel task
        test_msg = {"source": "X", "content": "urgent"}
        self.region.inbox.put_nowait(test_msg)
        self.region.forward_task.cancel()

        await self.region.stop()

        # Verify message was forwarded despite cancellation
        self.assertEqual(len(self.received_messages), 1)
        self.assertEqual(self.received_messages[0], test_msg)

    async def test_process_termination_timeout(self):
        """Verify forced termination when process doesn't stop promptly"""
        with patch.object(mp.Process, 'is_alive', return_value=True):
            await self.region.start()
            await self.region.stop()

            # Verify termination was forced
            self.region.p.terminate.assert_called()
            self.region.p.join.assert_called_with(timeout=2.0)

    async def test_multiple_stops_are_safe(self):
        """Verify multiple stop() calls don't cause errors"""
        await self.region.start()
        await self.region.stop()

        # Second stop should be safe
        await self.region.stop()

        # Verify resources were cleaned up only once
        self.region.out_q.put.assert_called_once_with(None)
        self.region.p.join.assert_called_once()

    async def test_empty_inbox_behavior(self):
        """Verify no messages are forwarded when inbox is empty"""
        await self.region.start()
        await asyncio.sleep(0.1)
        await self.region.stop()

        # Only sentinel should be sent
        self.assertEqual(len(self.received_messages), 0)
        self.region.out_q.put.assert_called_with(None)