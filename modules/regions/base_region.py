import asyncio


class BaseRegion:
    """
    Base class for region-based communication units in distributed systems.

    Provides standardized message routing and inbox processing while allowing
    child classes to implement domain-specific knowledge handling.

    Attributes:
        name (str): Unique identifier for the region
        task (str): Functional description of the region's purpose
        connections (dict[str, str]): Mapping of region names to task descriptions
        inbox (asyncio.Queue): Incoming message queue
        outbox (asyncio.Queue): Outgoing message queue
        _incoming_requests (dict): Stores pending requests (keyed by source)
        _incoming_replies (dict): Stores received replies (keyed by source)
    """

    def __init__(self, name: str, task: str, connections: dict[str, str] | None = None, **kwargs):
        """
        Initialize common communication infrastructure.

        Args:
            name (str): Unique identifier for the region
            task (str): Functional description of the region's purpose
            connections (dict[str, str] | None): Region-to-task mapping
            **kwargs: Additional parameters for child classes

        Note:
            - Initializes inbox/outbox queues for message handling
            - Standardizes storage for incoming requests/replies
            - Connections default to empty dict if None
        """
        self.name = name
        self.task = task
        self.connections = connections if connections is not None else {}
        self.inbox = asyncio.Queue()
        self.outbox = asyncio.Queue()
        self._incoming_requests = {}  # Stores requests (keyed by source)
        self._incoming_replies = {}  # Stores replies (keyed by source)

    def _post(self, destination: str, content: str, role: str) -> None:
        """
        Internal method to send formatted messages to other regions.

        Args:
            destination (str): Target region name
            content (str): Message payload
            role (str): Message type ('request' or 'reply')

        Note:
            - Constructs standardized message dictionary
            - Non-blocking queue insertion
        """
        message = {
            "source": self.name,
            "destination": destination,
            "content": content,
            "role": role
        }
        self.outbox.put_nowait(message)

    def _ask(self, destination: str, query_text: str) -> None:
        """
        Send request query to another region.

        Args:
            destination (str): Target region name
            query_text (str): Question to ask
        """
        self._post(destination, query_text, 'request')

    def _reply(self, destination: str, reply_text: str) -> None:
        """
        Send reply to a requesting region.

        Args:
            destination (str): Target region name
            reply_text (str): Response content
        """
        self._post(destination, reply_text, 'reply')

    def _run_inbox(self) -> None:
        """
        Process all pending messages in inbox queue.

        Note:
            - Categorizes messages into requests/replies
            - Stores messages in standardized dictionaries
            - Handles unknown roles via AssertionError
        """
        while not self.inbox.empty():
            message = self.inbox.get_nowait()
            if message['role'] == 'request':
                self._incoming_requests[message['source']] = message['content']
            elif message['role'] == 'reply':
                self._incoming_replies[message['source']] = message['content']
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")
