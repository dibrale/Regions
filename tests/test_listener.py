import unittest
import asyncio
import unittest.mock
import queue

from regions.listener_region import ListenerRegion


def real_out_process(q):
    """Real out_process implementation that records messages to a controlled queue"""
    while True:
        try:
            msg = q.get()
            if msg is None:
                break
        except EOFError:
            break


class TestListenerRegion(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Use the module-level function
        self.region = ListenerRegion("test", real_out_process, delay=0)

    async def asyncTearDown(self):
        # Clean shutdown if tests leave region running
        if hasattr(self.region, 'p') and self.region.p and self.region.p.is_alive():
            # Ensure sentinel is sent if region was started
            if self.region.out_q is not None:
                self.region.out_q.put(None)
            self.region.p.join(timeout=2.0)
            if self.region.p and self.region.p.is_alive():
                self.region.p.terminate()
            self.region.p.close()
            self.region.p = None

    async def drain_out_queue(self):
        """Safely drain the out_queue to collect messages for verification"""
        messages = []
        try:
            # Get all messages until we hit the sentinel (None)
            while True:
                msg = self.region.out_q.get(block=False)
                if msg is None:
                    break
                messages.append(msg)
        except (queue.Empty, ValueError, EOFError):
            pass
        return messages

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

    async def test_start_called_twice_raises_runtime_error(self):
        """Verify calling start() twice raises RuntimeError"""
        await self.region.start()
        with self.assertRaises(RuntimeError):
            await self.region.start()

    async def test_stop_sends_sentinel_and_terminates(self):
        """Verify stop() sends sentinel and properly terminates resources"""
        await self.region.start()
        await self.region.stop()

        # Verify process termination
        self.assertIsNone(self.region.p)

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

        await asyncio.sleep(0.1)     # Allow time for forwarding
        messages = await self.drain_out_queue()     # Drain messages
        await self.region.stop()

        # Verify all test messages were forwarded
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages, test_messages)

    async def test_stop_without_start(self):
        """Verify stop() works gracefully when called without start()"""
        # Should not raise errors
        await self.region.stop()

        # Verify no resources were created
        self.assertIsNone(self.region.p)
        self.assertIsNone(self.region.forward_task)

    async def test_cancellation_drains_inbox(self):
        """Verify inbox is drained during task cancellation"""
        await self.region.start()

        # Add message and cancel task
        test_msg = {"source": "X", "content": "urgent", "destination": "Y", "role": "request"}
        self.region.inbox.put_nowait(test_msg)

        # Wait for the forward task to process the message
        await asyncio.sleep(0.01)

        # Cancel the task
        self.region.forward_task.cancel()

        # Give extra time for messages to propagate
        await asyncio.sleep(0.01)

        # Drain and verify message was forwarded
        messages = await self.drain_out_queue()
        await self.region.stop()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0], test_msg)

    async def test_process_termination_timeout(self):
        """Verify forced termination when process doesn't stop promptly"""
        # Create a mock process that simulates being unresponsive
        mock_process = unittest.mock.MagicMock()
        mock_process.is_alive.return_value = True

        # Patch the multiprocessing.Process constructor to return our mock
        with unittest.mock.patch('multiprocessing.Process', return_value=mock_process):
            await self.region.start()
            await self.region.stop()

            # Verify termination was forced
            mock_process.join.assert_called_with(timeout=2.0)
            mock_process.terminate.assert_called()

    async def test_multiple_stops_are_safe(self):
        """Verify multiple stop() calls don't cause errors"""
        await self.region.start()
        await self.region.stop()

        # Second stop should be safe
        await self.region.stop()

        # Verify resources were cleaned up properly
        self.assertIsNone(self.region.p)
        self.assertIsNone(self.region.forward_task)

        # Verify queue is closed
        with self.assertRaises(ValueError):
            self.region.out_q.put("test")

    async def test_empty_inbox_behavior(self):
        """Verify no messages are forwarded when inbox is empty"""
        await self.region.start()
        await asyncio.sleep(0.01)
        messages = await self.drain_out_queue()
        await self.region.stop()

        # Drain queue - should only contain sentinel (None)
        self.assertEqual(len(messages), 0)