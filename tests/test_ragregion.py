import asyncio
import unittest
import time
from unittest.mock import AsyncMock, patch

from regions.rag_region import RAGRegion
from dynamic_rag import RetrievalResult, DocumentChunk, ChunkMetadata


class TestRAGRegion(unittest.TestCase):
    def setUp(self):
        # Mock DynamicRAGSystem dependency with proper async mocks
        self.mock_rag = AsyncMock()
        self.mock_rag.retrieve_similar = AsyncMock()
        self.mock_rag.update_chunk = AsyncMock(return_value=True)
        self.mock_rag.delete_chunk = AsyncMock(return_value=True)

        # Create test RAGRegion with mock connections
        self.region = RAGRegion(
            name="test_rag_region",
            task="test knowledge task",
            rag=self.mock_rag,
            connections={"other_region": "other knowledge task"},
            reply_with_actors=True
        )

    async def asyncSetUp(self):
        # Initialize queues for async tests
        self.region.inbox = asyncio.Queue()
        self.region.outbox = asyncio.Queue()

    async def test_initialization(self):
        """Verify RAGRegion attributes are correctly initialized"""
        self.assertEqual(self.region.name, "test_rag_region")
        self.assertEqual(self.region.task, "test knowledge task")
        self.assertEqual(self.region.connections, {"other_region": "other knowledge task"})
        self.assertIsInstance(self.region.inbox, asyncio.Queue)
        self.assertIsInstance(self.region.outbox, asyncio.Queue)
        self.assertIsInstance(self.region._incoming_replies, asyncio.Queue)
        self.assertIsInstance(self.region._incoming_requests, asyncio.Queue)
        self.assertTrue(self.region.reply_with_actors)

        # Test initialization without reply_with_actors
        region_no_actors = RAGRegion(
            name="test_no_actors",
            task="test task",
            rag=self.mock_rag,
            connections=None
        )
        self.assertFalse(region_no_actors.reply_with_actors)
        self.assertEqual(region_no_actors.connections, {})

    async def test_post(self):
        """Test _post correctly formats and queues messages"""
        self.region._post("target", "content", "request")

        message = await self.region.outbox.get()
        self.assertEqual(message, {
            "source": "test_rag_region",
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
            "content": "knowledge update"
        })
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "question"
        })

        self.region._run_inbox()

        self.assertEqual([*self.region._incoming_replies.__dict__['_queue']], [{"other_region": "knowledge update"}])
        self.assertEqual([*self.region._incoming_requests.__dict__['_queue']], [{"other_region": "question"}])

    async def test_make_replies_success(self):
        """Test successful reply generation with matching fragments"""
        # Setup pending query
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What historical facts do you know?"
        })
        self.region._run_inbox()

        # Mock RAG retrieval results
        mock_chunk1 = DocumentChunk(
            content="The Roman Empire fell in 476 AD",
            metadata=ChunkMetadata(actors=["historian"], timestamp=int(time.time()))
        )
        mock_chunk2 = DocumentChunk(
            content="World War II ended in 1945",
            metadata=ChunkMetadata(actors=["historian", "archivist"], timestamp=int(time.time()))
        )
        self.mock_rag.retrieve_similar.return_value = [
            RetrievalResult(chunk=mock_chunk1, similarity_score=0.9),
            RetrievalResult(chunk=mock_chunk2, similarity_score=0.8)
        ]

        # Generate replies
        result = await self.region.make_replies()

        self.assertTrue(result)
        self.assertTrue(self.region._incoming_requests.empty())

        # Verify reply was sent
        message = await self.region.outbox.get()
        self.assertEqual(message["role"], "reply")

        # Check reply format with actors included
        expected_reply = (
                '{"memory_fragment": "The Roman Empire fell in 476 AD", "actors": [\"historian\"]},\n' +
                '{"memory_fragment": "World War II ended in 1945", "actors": [\"historian\", \"archivist\"]},\n'
        )
        self.assertEqual(message["content"], expected_reply)
        self.assertIn("other_region", self.region.connections.keys())

    async def test_make_replies_no_matches(self):
        """Test reply generation with no matching fragments"""
        # Setup pending query
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What historical facts do you know?"
        })
        self.region._run_inbox()

        # Mock RAG retrieval with no results
        self.mock_rag.retrieve_similar.return_value = []

        # Generate replies
        result = await self.region.make_replies()

        self.assertTrue(result)  # Should still return True even with empty reply
        self.assertTrue(self.region._incoming_requests.empty())

        # Check if outbox is empty (no reply was sent)
        self.assertTrue(self.region.outbox.empty(), "Expected no reply to be sent when no matches exist")

    async def test_make_replies_failure(self):
        """Test handling of RAG failures during reply generation"""
        # Setup pending query
        await self.region.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What historical facts do you know?"
        })
        self.region._run_inbox()

        # Mock RAG failure
        self.mock_rag.retrieve_similar.side_effect = Exception("RAG error")

        # Generate replies
        result = await self.region.make_replies()

        self.assertFalse(result)
        self.assertTrue(self.region._incoming_requests.empty())  # Queries still cleared

    async def test_make_replies_without_actors(self):
        """Test reply format when reply_with_actors=False"""
        # Create region without actors
        region_no_actors = RAGRegion(
            name="test_no_actors",
            task="test task",
            rag=self.mock_rag,
            connections={"other_region": "other task"},
            reply_with_actors=False
        )
        region_no_actors.inbox = asyncio.Queue()
        region_no_actors.outbox = asyncio.Queue()

        # Setup pending query
        await region_no_actors.inbox.put({
            "source": "other_region",
            "role": "request",
            "content": "What historical facts do you know?"
        })
        region_no_actors._run_inbox()

        # Mock RAG retrieval results
        mock_chunk = DocumentChunk(
            content="The Roman Empire fell in 476 AD",
            metadata=ChunkMetadata(actors=["historian"], timestamp=int(time.time()))
        )
        self.mock_rag.retrieve_similar.return_value = [
            RetrievalResult(chunk=mock_chunk, similarity_score=0.9)
        ]

        # Generate replies
        await region_no_actors.make_replies()

        # Verify reply was sent without actors
        message = await region_no_actors.outbox.get()
        expected_reply = '{"memory_fragment": "The Roman Empire fell in 476 AD"},\n'
        self.assertEqual(message["content"], expected_reply)

    async def test_make_updates_success(self):
        """Test successful knowledge update and consolidation"""
        # Setup incoming knowledge update
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "New historical fact: The Renaissance began in the 14th century"
        })
        self.region._run_inbox()

        # Mock RAG retrieval results for consolidation
        mock_chunk1 = DocumentChunk(
            chunk_hash="hash1",
            content="The Renaissance began in the 14th century",
            metadata=ChunkMetadata(actors=["historian"], timestamp=int(time.time()))
        )
        mock_chunk2 = DocumentChunk(
            chunk_hash="hash2",
            content="The Renaissance started around 1300",
            metadata=ChunkMetadata(actors=["historian", "archivist"], timestamp=int(time.time()))
        )
        mock_chunk3 = DocumentChunk(
            chunk_hash="hash3",
            content="Ancient Rome fell in 476 AD",
            metadata=ChunkMetadata(actors=["historian"], timestamp=int(time.time()))
        )

        self.mock_rag.retrieve_similar.return_value = [
            RetrievalResult(chunk=mock_chunk1, similarity_score=0.95),
            RetrievalResult(chunk=mock_chunk2, similarity_score=0.85),
            RetrievalResult(chunk=mock_chunk3, similarity_score=0.3)
        ]

        # Process updates
        result = await self.region.make_updates(consolidate_threshold=0.2)

        self.assertTrue(result)
        self.assertTrue(self.region._incoming_replies.empty())

        # Verify update_chunk was called with highest similarity
        self.mock_rag.update_chunk.assert_called_once_with(
            "hash1",
            "New historical fact: The Renaissance began in the 14th century",
            ["historian"]
        )

        # Verify delete_chunk was called for similar fragments
        self.mock_rag.delete_chunk.assert_any_call("hash2")

    async def test_make_updates_no_results(self):
        """Test handling when no retrieval results are found"""
        # Setup incoming knowledge update
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "New historical fact"
        })
        self.region._run_inbox()

        # Mock RAG retrieval with no results
        self.mock_rag.retrieve_similar.return_value = []

        # Process updates
        result = await self.region.make_updates()

        self.assertFalse(result)
        self.assertTrue(self.region._incoming_replies.empty())

    async def test_make_updates_failure(self):
        """Test handling of RAG failures during update processing"""
        # Setup incoming knowledge update
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "New historical fact"
        })
        self.region._run_inbox()

        # Mock RAG failure
        self.mock_rag.retrieve_similar.side_effect = Exception("RAG error")

        # Process updates
        result = await self.region.make_updates()

        self.assertFalse(result)
        self.assertTrue(self.region._incoming_replies.empty())

    async def test_make_updates_consolidation_threshold(self):
        """Test consolidation behavior with different thresholds"""
        # Setup incoming knowledge update
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "New historical fact: The Renaissance began in the 14th century"
        })
        self.region._run_inbox()

        # Mock RAG retrieval results
        mock_chunk1 = DocumentChunk(
            chunk_hash="hash1",
            content="The Renaissance began in the 14th century",
            metadata=ChunkMetadata(actors=["historian"], timestamp=int(time.time()))
        )
        mock_chunk2 = DocumentChunk(
            chunk_hash="hash2",
            content="The Renaissance started around 1300",
            metadata=ChunkMetadata(actors=["historian", "archivist"], timestamp=int(time.time()))
        )

        self.mock_rag.retrieve_similar.return_value = [
            RetrievalResult(chunk=mock_chunk1, similarity_score=0.95),
            RetrievalResult(chunk=mock_chunk2, similarity_score=0.85)
        ]

        # Process updates with higher threshold (won't consolidate)
        result = await self.region.make_updates(consolidate_threshold=0.05)

        self.assertTrue(result)
        # hash1 gets deleted and replaced as part of the update procedure
        # hash2 should not be deleted with lower threshold
        self.mock_rag.delete_chunk.assert_called_once_with("hash1")

        # Process updates with lower threshold (will consolidate)
        await self.region.inbox.put({
            "source": "other_region",
            "role": "reply",
            "content": "New historical fact: The Renaissance began in the 14th century"
        })
        self.region._run_inbox()

        result = await self.region.make_updates(consolidate_threshold=0.2)

        self.assertTrue(result)
        # hash2 should be deleted with higher threshold
        self.mock_rag.delete_chunk.assert_any_call("hash1")
        self.mock_rag.delete_chunk.assert_any_call("hash2")

    async def test_request_summaries_success(self):
        """Test sending summary requests to connected regions"""
        # Request summaries
        await self.region.request_summaries()

        # Verify requests were sent
        self.assertEqual(self.region.outbox.qsize(), 1)
        message = await self.region.outbox.get()
        self.assertEqual(message["role"], "request")
        self.assertEqual(message["content"], "Summarize the knowledge you have.")
        self.assertEqual(message["destination"], "other_region")

    async def test_request_summaries_no_connections(self):
        """Test error handling when no connections exist"""
        # Create region with no connections
        region_no_connections = RAGRegion(
            name="no_connections",
            task="test task",
            rag=self.mock_rag,
            connections=None
        )

        # Attempt to request summaries
        with self.assertRaises(ValueError) as context:
            await region_no_connections.request_summaries()

        self.assertIn("No valid connections for summarization.", str(context.exception))

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

    def test_make_replies_success_sync(self):
        self.run_async_test(self.test_make_replies_success)

    def test_make_replies_no_matches_sync(self):
        self.run_async_test(self.test_make_replies_no_matches)

    def test_make_replies_failure_sync(self):
        self.run_async_test(self.test_make_replies_failure)

    def test_make_replies_without_actors_sync(self):
        self.run_async_test(self.test_make_replies_without_actors)

    def test_make_updates_success_sync(self):
        self.run_async_test(self.test_make_updates_success)

    def test_make_updates_no_results_sync(self):
        self.run_async_test(self.test_make_updates_no_results)

    def test_make_updates_failure_sync(self):
        self.run_async_test(self.test_make_updates_failure)

    def test_make_updates_consolidation_threshold_sync(self):
        self.run_async_test(self.test_make_updates_consolidation_threshold)

    def test_request_summaries_success_sync(self):
        self.run_async_test(self.test_request_summaries_success)

    def test_request_summaries_no_connections_sync(self):
        self.run_async_test(self.test_request_summaries_no_connections)


if __name__ == '__main__':
    unittest.main()