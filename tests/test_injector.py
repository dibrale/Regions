import pytest
from unittest.mock import MagicMock, patch, call  # Import call from unittest.mock
from injector import inject, Injector, Addressograph


@pytest.fixture
def mock_postmaster():
    """Fixture for a mock Postmaster instance."""
    postmaster = MagicMock()
    postmaster.messages = MagicMock()
    return postmaster


def test_inject_function(mock_postmaster):
    """Test that inject() correctly constructs and queues a message."""
    inject(mock_postmaster, "source", "role", "dest", "content")

    expected_msg = {
        "source": "source",
        "destination": "dest",
        "role": "role",
        "content": "content"
    }
    mock_postmaster.messages.put_nowait.assert_called_once_with(expected_msg)


def test_injector_context_manager(mock_postmaster):
    """Test that Injector context manager sets up send/request/reply methods correctly."""
    with patch('injector.inject') as mock_inject:
        with Injector(mock_postmaster, "source", role="test_role") as injector:
            injector.send("dest1", "content1")
            injector.request("dest2", "content2")
            injector.reply("dest3", "content3")

        mock_inject.assert_has_calls([
            call(mock_postmaster, "source", "test_role", "dest1", "content1"),
            call(mock_postmaster, "source", "request", "dest2", "content2"),
            call(mock_postmaster, "source", "reply", "dest3", "content3")
        ])


def test_addressograph_decorator(mock_postmaster):
    """Test that Addressograph decorator injects a configured Injector into the function."""
    with patch('injector.inject') as mock_inject:
        @Addressograph(mock_postmaster, "source", role="test_role", injector_name="my_injector")
        def test_func(my_injector):
            with my_injector:
                my_injector.send("dest1", "content1")
                my_injector.request("dest2", "content2")
                my_injector.reply("dest3", "content3")

        test_func()

        mock_inject.assert_has_calls([
            call(mock_postmaster, "source", "test_role", "dest1", "content1"),
            call(mock_postmaster, "source", "request", "dest2", "content2"),
            call(mock_postmaster, "source", "reply", "dest3", "content3")
        ])


def test_injector_exit_does_nothing(mock_postmaster):
    """Test that __exit__ of Injector does not perform any cleanup. This placeholder is here in case cleanup is
    implemented in the future."""
    with patch('injector.inject'):
        with Injector(mock_postmaster, "source") as injector:
            pass
        # No exception should be raised, and no operations performed