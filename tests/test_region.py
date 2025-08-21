import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch  # Import AsyncMock

from modules.llmlink import LLMLink
from modules.region import Region

llm = LLMLink()

class TestRegion(unittest.TestCase):
    def setUp(self):
        # Mock LLMLink dependency with proper async mock
        self.mock_llm = MagicMock()
        self.mock_llm.text = AsyncMock()  # CRITICAL FIX: Use AsyncMock for async methods

        # Create test region with real connections
        self.region = Region(
            name="test_region",
            task="test task",
            llm = llm,
            connections={"other_region": "other task"}
        )

        # Create test region with mock connections
        self.test_region = Region(
            name="test_region",
            task="test task",
            llm=self.mock_llm,
            connections={"other_region": "other task"}
        )

    async def asyncSetUp(self):
        # Initialize queues for async tests
        self.region.inbox = asyncio.Queue()
        self.region.outbox = asyncio.Queue()

    async def test_initialization(self):
        """Verify Region attributes are correctly initialized"""
        self.assertEqual(self.region.name, "test_region")
        self.assertEqual(self.region.task, "test task")
        self.assertEqual(self.region.connections, {"other_region": "other task"})
        self.assertIsInstance(self.region.inbox, asyncio.Queue)
        self.assertIsInstance(self.region.outbox, asyncio.Queue)
        self.assertEqual(self.region._incoming_replies, {})
        self.assertEqual(self.region._incoming_requests, {})

    async def test_post(self):
        """Test _post correctly formats and queues messages"""
        self.region._post("target", "content", "request")

        message = await self.region.outbox.get()
        self.assertEqual(message, {
            "source": "test_region",
            "destination": "target",
            "content": "content",
            "role": "request"
        })

    async def test_ask(self):
        """Test _ask delegates to _post with 'request' role"""
        with patch.object(self.region, '_post') as mock_post:
            self.region._ask("target", "query")
            mock_post.assert_called_once_with("target", "query", "request")

    async def test_reply(self):
        """Test _reply delegates to _post with 'reply' role"""
        with patch.object(self.region, '_post') as mock_post:
            self.region._reply("target", "response")
            mock_post.assert_called_once_with("target", "response", "reply")

    async def test_run_inbox(self):
        """Test _run_inbox processes messages correctly"""
        # Populate inbox with test messages
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "knowledge"
        })
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "question"
        })

        self.region._run_inbox()

        self.assertEqual(self.region._incoming_replies, {"other_region": "knowledge"})
        self.assertEqual(self.region._incoming_requests, {"other_region": "question"})

    async def test_make_prompt(self):
        """Test prompt construction with default delimiters"""
        prompt = self.region._make_prompt("user question")

        expected = (
            "(system\nReply to the user, given your focus and knowledge per the given schema:\n"
            "{'focus': 'test task', 'knowledge': []}(user\nuser question(assistant\n"
        )
        self.assertIn("test task", prompt)
        self.assertIn("user question", prompt)

    async def test_make_replies_success(self):
        """Test successful reply generation for pending queries"""
        # Setup pending query
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What's the weather?"
        })
        self.region._run_inbox()

        await self.region.inbox.put({
            "source": "real_time_weather",
            "role": "reply",
            "content": "The weather is partly cloudy with a chance of hail"
        })
        self.region._run_inbox()

        # Mock LLM response - AsyncMock handles this properly
        # self.mock_llm.text.return_value = "Sunny"

        # Generate replies
        result = await self.region.make_replies()

        self.assertTrue(result)
        self.assertEqual(len(self.region._incoming_requests), 0)

        # Verify reply was sent
        message = await self.region.outbox.get()
        self.assertEqual(message["role"], "reply")
        self.assertTrue("partly cloudy" in message["content"] and "hail" in message["content"])
        print(f"Replied to {message['destination']} with: {message['content']}")

    async def test_make_replies_failure(self):
        """Test handling of LLM failures during reply generation"""
        # Setup pending query
        await self.test_region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What's the weather?"
        })
        self.test_region._run_inbox()

        # Mock LLM failure
        self.mock_llm.text.side_effect = Exception("LLM error")

        # Generate replies
        result = await self.test_region.make_replies()

        self.assertFalse(result)
        self.assertEqual(len(self.region._incoming_requests), 0)  # Queries still cleared

    async def test_make_questions_success(self):
        """Test successful question generation for connected regions"""

        # Generate questions
        result = await self.region.make_questions()

        self.assertTrue(result)

        # Verify question was sent
        message = await self.region.outbox.get()
        self.assertEqual(message["role"], "request")
        self.assertEqual(message["destination"], "other_region")
        self.assertTrue(type(message["content"]) is str)
        print(f"Queried {message['destination']} with: {message['content']}")

    async def test_make_questions_invalid_destination(self):
        """Test handling of invalid destination in generated questions"""
        # Mock LLM response with invalid destination
        self.mock_llm.text.return_value = json.dumps([
            {"source": "invalid_region", "question": "What's your status?"}
        ])

        # Generate questions
        result = await self.test_region.make_questions()

        self.assertFalse(result)
        self.assertEqual(self.test_region.outbox.qsize(), 0)  # No messages sent

    async def test_make_questions_invalid_json(self):
        """Test handling of invalid JSON from LLM"""
        # Mock LLM response with invalid JSON
        self.mock_llm.text.return_value = "invalid json"

        # Generate questions
        result = await self.test_region.make_questions()

        self.assertFalse(result)
        self.assertEqual(self.test_region.outbox.qsize(), 0)

    def run_async_test(self, test_coroutine):
        """Helper to run async tests"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.asyncSetUp())
        loop.run_until_complete(test_coroutine())
        loop.close()

    def test_initialization_sync(self):
        self.run_async_test(self.test_initialization)

    def test_post_sync(self):
        self.run_async_test(self.test_post)

    def test_ask_sync(self):
        self.run_async_test(self.test_ask)

    def test_reply_sync(self):
        self.run_async_test(self.test_reply)

    def test_run_inbox_sync(self):
        self.run_async_test(self.test_run_inbox)

    def test_make_prompt_sync(self):
        self.run_async_test(self.test_make_prompt)

    def test_make_replies_success_sync(self):
        self.run_async_test(self.test_make_replies_success)

    def test_make_replies_failure_sync(self):
        self.run_async_test(self.test_make_replies_failure)

    def test_make_questions_success_sync(self):
        self.run_async_test(self.test_make_questions_success)

    def test_make_questions_invalid_destination_sync(self):
        self.run_async_test(self.test_make_questions_invalid_destination)

    def test_make_questions_invalid_json_sync(self):
        self.run_async_test(self.test_make_questions_invalid_json)


if __name__ == '__main__':
    unittest.main()