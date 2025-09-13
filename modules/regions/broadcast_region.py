import logging

from regions.base_region import BaseRegion


class BroadcastRegion(BaseRegion):
    """
    Specialized region that stores incoming messages, then forwards them to all connected regions without modification.

    This region acts as a message distributor that:

    - Only processes incoming messages (never initiates requests or replies)
    - Maintains original message metadata (source, destination and role unchanged)
    - Requires manual setup of connections via the 'connections' parameter

    Usage:

    >>>    broadcast_region = BroadcastRegion(
    >>>        name="message_hub",
    >>>        connections={
    >>>            "foo": "does things",
    >>>            "bar": "does stuff"
    >>>        }
    >>>    )
    >>>    broadcast_region.broadcast()
    >>>    # All messages sent to broadcast_region will be copied to "foo" and "bar" in broadcast_region.outbox

    Notes:
        - Message 'source' field remains unchanged during forwarding
        - Does not support standard region operations (sorting, outgoing messages)
        - Intended for broadcast, caching and synchronized message injection use cases
        - Has an entirely synchronous implementation, since it operates quickly
    """
    def __init__(self, name: str, task: str | None = None, connections: dict[str, str] | None = None):
        """
        Initialize a BroadcastRegion instance.

        Args:
            name (str): Unique identifier for the region
            task (str): Optional description of the region's purpose (defaults to "Forward all incoming messages to connected regions")
            connections (dict[str, str]): Mapping of region names to task descriptions
        """
        if not task:
            self.task = "Forward all incoming messages to connected regions"
        else:
            self.task = task
        super().__init__(name, task, connections)
        del self._incoming_requests
        del self._incoming_replies

    def _post(self, destination: str, content: str, role: str) -> None:
        raise NotImplementedError("BroadcastRegion does not support outgoing messages")

    def _ask(self, destination: str, message: str) -> None:
        raise NotImplementedError("BroadcastRegion cannot generate requests")

    def _reply(self, source: str, content: str) -> None:
        raise NotImplementedError("BroadcastRegion cannot generate replies")

    def _run_inbox(self):
        raise NotImplementedError("BroadcastRegion does not need to sort messages")

    def _pipe(self, source: str, destination: str, content: str, role: str):
        """
        Internal method to forward a message from a configurable source to a specific recipient.

        Args:
            source (str): Source region name
            destination (str): Target region name
            content (str): Message content to forward
            role (str): Message type ('request' or 'reply')
        """
        message = {
            "source": source,
            "destination": destination,
            "content": content,
            "role": role
        }
        self.outbox.put_nowait(message)

    def broadcast(self) -> None:
        """
        Process all messages in the inbox and broadcast them to all connected regions.

        This method:
        1. Processes messages until inbox is empty
        2. Logs each message with appropriate level (INFO for requests, DEBUG for replies)
        3. Forwards each message to all regions specified in 'connections'
        4. Preserves all original message metadata (source, destination, role)
        """
        while not self.inbox.empty():
            message = self.inbox.get_nowait()
            if message['role'] == 'request':
                logging.info(f"{self.name}: Broadcasting request from {message['source']}: {message['content']}")
            elif message['role'] == 'reply':
                logging.debug(f"{self.name}: Broadcasting reply from {message['source']}: {message['content']}")
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")
            for recipient in [*self.connections.keys()]:
                self._pipe(message['source'], recipient, message['content'], message['role'])