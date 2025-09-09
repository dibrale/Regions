import logging
import pytest

from modules.regions.base_region import BaseRegion

@pytest.mark.asyncio
class TestBaseRegion:
    @pytest.fixture
    def region(self):
        return BaseRegion("test_region", "test_task")

    @pytest.fixture
    def mock_logger(self, caplog):
        # Mock logger to capture logs for verification
        logger = logging.getLogger("BaseRegion")
        logger.setLevel(logging.INFO)
        return logger

    async def test_keep_last_reply_per_source(self, region, caplog):
        # Add replies to the queue
        region._incoming_replies.put_nowait({"source1": "reply1"})
        region._incoming_replies.put_nowait({"source1": "reply2"})
        region._incoming_replies.put_nowait({"source2": "reply3"})

        # Test the method
        region._keep_last_reply_per_source()

        # Verify only the last reply per source remains
        assert region._incoming_replies.qsize() == 2
        assert region._incoming_replies.get_nowait() == {"source1": "reply2"}
        assert region._incoming_replies.get_nowait() == {"source2": "reply3"}

        # Verify logs
        assert "Pruned 1 replies" in caplog.text

    async def test_consolidate_replies(self, region, caplog):
        # Add multiple replies from same source
        region._incoming_replies.put_nowait({"source1": "reply1"})
        region._incoming_replies.put_nowait({"source1": "reply2"})
        region._incoming_replies.put_nowait({"source2": "reply3"})

        # Test the method
        region._consolidate_replies()

        # Verify consolidated replies
        assert region._incoming_replies.qsize() == 2
        assert region._incoming_replies.get_nowait() == {"source1": "reply1\nreply2"}
        assert region._incoming_replies.get_nowait() == {"source2": "reply3"}

        # Verify logs
        assert "Consolidated 3 replies" in caplog.text

    async def test_clear_replies(self, region, caplog):
        # Add replies to the queue
        region._incoming_replies.put_nowait({"source1": "reply1"})
        region._incoming_replies.put_nowait({"source2": "reply2"})

        # Test the method
        region.clear_replies()

        # Verify queue is empty
        assert region._incoming_replies.empty()

        # Verify logs
        assert "All replies cleared" in caplog.text

    async def test_keep_last_no_replies(self, region, caplog):
        # Test with empty queue
        region._keep_last_reply_per_source()
        assert "No incoming replies to prune" in caplog.text

    async def test_consolidate_no_replies(self, region, caplog):
        # Test with empty queue
        region._consolidate_replies()
        assert "No incoming replies to consolidate" in caplog.text

    async def test_clear_already_empty(self, region, caplog):
        # Test with empty queue
        region.clear_replies()
        assert "Reply queue already empty" in caplog.text

    async def test_keep_last_with_different_sources(self, region, caplog):
        # Add replies from multiple sources
        region._incoming_replies.put_nowait({"source1": "reply1"})
        region._incoming_replies.put_nowait({"source2": "reply2"})
        region._incoming_replies.put_nowait({"source1": "reply3"})
        region._incoming_replies.put_nowait({"source2": "reply4"})

        # Test the method
        region._keep_last_reply_per_source()

        # Verify only the last reply per source remains
        assert region._incoming_replies.qsize() == 2
        assert region._incoming_replies.get_nowait() == {"source1": "reply3"}
        assert region._incoming_replies.get_nowait() == {"source2": "reply4"}

    async def test_consolidate_multiple_sources(self, region, caplog):
        # Add replies from same source
        region._incoming_replies.put_nowait({"source1": "reply1"})
        region._incoming_replies.put_nowait({"source1": "reply2"})
        region._incoming_replies.put_nowait({"source1": "reply3"})
        region._incoming_replies.put_nowait({"source2": "reply4"})

        # Test the method
        region._consolidate_replies()

        # Verify consolidated replies
        assert region._incoming_replies.qsize() == 2
        assert region._incoming_replies.get_nowait() == {"source1": "reply1\nreply2\nreply3"}
        assert region._incoming_replies.get_nowait() == {"source2": "reply4"}