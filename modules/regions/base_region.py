import asyncio
import logging


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
        self._incoming_requests = asyncio.Queue()  # Stores requests (keyed by source)
        self._incoming_replies = asyncio.Queue()  # Stores replies (keyed by source)

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
                logging.info(f"{self.name}: Received request from {message['source']}: {message['content']}")
                self._incoming_requests.put_nowait({message['source']: message['content']})
            elif message['role'] == 'reply':
                logging.debug(f"{self.name}: Received reply from {message['source']}: {message['content']}")
                self._incoming_replies.put_nowait({message['source']: message['content']})
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")

    def _keep_last_reply_per_source(self) -> None:
        """
                Prune incoming replies to retain only the most recent reply per source.

                This method processes all replies in the `_incoming_replies` queue, keeping only the last reply received from each unique source.
                The queue is then repopulated with the pruned replies.

                Note:
                    - Operates on the entire `_incoming_replies` queue
                    - Overwrites previous replies from the same source with the latest one
                    - Logs the number of pruned replies
        """
        if self._incoming_replies.empty():
            logging.info(f"{self.name}: No incoming replies to prune.")
            return
        replies = {}
        original_length = self._incoming_replies.qsize()
        while not self._incoming_replies.empty():
            replies.update(self._incoming_replies.get_nowait())
            self._incoming_replies.task_done()
        for source in replies:
            self._incoming_replies.put_nowait({source, replies[source]})
        logging.info(
            f"{self.name}: Pruned {original_length - self._incoming_replies.qsize()} replies. {self._incoming_replies.qsize()} replies remaining.")

    def _consolidate_replies(self) -> None:
        """
                Consolidate multiple replies from the same source into a single reply.

                For each source, combines all replies into one message by concatenating their content with newline separators.
                The queue is then repopulated with the consolidated replies.

                Note:
                    - Processes all replies in `_incoming_replies` queue
                    - Maintains source-specific reply grouping
                    - Logs the consolidation statistics
        """
        if self._incoming_replies.empty():
            logging.info(f"{self.name}: No incoming replies to consolidate.")
            return
        replies = {}
        original_length = self._incoming_replies.qsize()
        while not self._incoming_replies.empty():
            item = self._incoming_replies.get_nowait()
            source = next(iter(item.keys()))
            content = item[source]
            if source in replies.keys():
                new_content = replies[source] + '\n' + content
            else:
                new_content = content
            replies.update({source: new_content})
        for source in replies:
            self._incoming_replies.put_nowait({source, replies[source]})
        logging.info(
            f"{self.name}: Consolidated {original_length} replies into {self._incoming_replies.qsize()} replies total.")

    def clear_replies(self) -> None:
        """
        Clear all replies from the incoming replies queue.

        Empties the `_incoming_replies` queue by removing all replies.

        Note:
            - Does not affect request queues
            - Logs confirmation if queue was empty
        """
        if self._incoming_replies.empty():
            logging.info(f"{self.name}: Reply queue already empty.")
            return
        while not self._incoming_replies.empty():
            self._incoming_replies.get_nowait()
            self._incoming_replies.task_done()
        logging.info(f"{self.name}: All replies cleared.")