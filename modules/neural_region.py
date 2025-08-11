import asyncio

class NeuralRegion:
    """
    Base class for neural regions that can communicate with each other.
    Each region has a specific function and can process requests from other regions.
    """

    def __init__(self, name: str, description: str = None, connections: dict[str, str] = None):
        """
        Initialize a neural region.

        Args:
            name (str), description (str), connections (dict)

        :param name: A string with the name of the region
        :param description: A string describing region function
        :param connections: A dict in the form of {"name": str, "function": str} with query templates keyed by region name
        """
        if description is None:
            description = ''
        if connections is None:
            connections = {}

        self.name = name
        self.description = description
        self.connections = connections or {}
        self.memory = {}  # Internal memory storage
        self.inbox = asyncio.Queue()  # Queue for incoming requests
        self.replies = asyncio.Queue()  # Queue for outgoing replies
        self.queries = asyncio.Queue() # Queue for outgoing queries

    def ask(self, destination: str, query_text: str) -> None:
        """
        Package a request for information from another region and add it to the outgoing request queue.

        Args:
            destination (str), query (str)

        Returns:
            None if the request is successfully added to the queue,
            Exception if an error occurs during addition

        :param destination: The 'name' parameter of a NeuralRegion instance representing the target region
        :param query_text: A natural language query string
        """

        # Prepare the request
        message = {
            "source": self.name,
            "destination": destination,
            "content": query_text,
        }

        # Add the request to the queue for outgoing queries
        self.queries.put_nowait(message)
        return

    async def reply(self, request: dict) -> Exception | None:
        """
        Process a request from another region.

        Args:
            request (dict)

        Returns:
            None if request is successfully handled
            AssertionError if request is incorrectly addressed

        :param request: A dict in the form of {"source": str, "destination": str, "content": str}
        """
        # Extract information from the request
        source = request.get("source", "unknown")
        destination = request.get("destination", "unknown")
        query = request.get("content", "")

        # Verify addressing
        try:
            assert destination == self.name, \
                self.name + " got request from " + source + " intended for " + destination
        except AssertionError as e:
            return e

        # Process the query based on the responding region's specific function
        response = {
            "source": self.name,
            "destination": source,
            "content": await self._process(query)
        }

        # Add the reply to the reply queue of the responding region
        self.replies.put_nowait(response)
        await asyncio.sleep(0)
        return None

    async def _process(self, query: str) -> str:
        """
        Internal method to process a query based on the region's function. LLM is called here to process
        region-specific prompt. This should be overridden by specific region implementations.

        Args:
            query (str)

        Returns:
            str: Processed information

        :param query: A string containing the query to be processed.
        """
        # Default implementation - should be overridden
        await asyncio.sleep(0)
        return ''