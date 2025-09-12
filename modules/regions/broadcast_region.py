import logging

from regions.base_region import BaseRegion


class BroadcastRegion(BaseRegion):
    """
        Specialized region that forwards received messages to all connected regions. Unlike other regions, it:
          - Only processes incoming messages (never initiates requests or replies)
          - Operates as a proxy for outgoing requests and replies

        Usage:
            Add multiple regions to the connections dictionary of the BroadcastRegion. All traffic directed at the
            BroadcastRegion will be mirrored to them, with no change to the message 'source' key.

        Notes:
            - Message metadata (including 'source' and 'destination') remains unchanged when sent through this region.
            - Intentionally lacks standard region capabilities (sorting and messaging methods) to prevent accidental
            use.
    """
    def __init__(self, name: str, task: str | None = None, connections: dict[str, str] | None = None):
        if not task:
            self.task = "Forward all incoming messages to connected regions"
        else:
            self.task = task
        super().__init__(name , task, connections)
        del self._incoming_requests
        del self._incoming_replies

    def _post(self, destination: str, content: str, role: str) -> None:
        raise NotImplementedError("ListenerRegion does not support outgoing messages addressed from itself.")

    def _ask(self, destination: str, message: str) -> None:
        raise NotImplementedError("ListenerRegion does not generate requests.")

    def _reply(self, source: str, content: str) -> None:
        raise NotImplementedError("ListenerRegion does not generate replies.")

    def _run_inbox(self):
        raise NotImplementedError("ListenerRegion does not need to sort messages.")

    def _pipe(self, source: str, destination: str, content: str, role: str):
        message = {
            "source": source,
            "destination": destination,
            "content": content,
            "role": role
        }
        self.outbox.put_nowait(message)

    def broadcast(self) -> None:
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

