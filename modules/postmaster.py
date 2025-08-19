import asyncio
import logging
from region_registry import RegionRegistry

class Postmaster:
    """Manages message routing between regions with configurable undeliverable handling.

    Coordinates message flow between regions by:
    1. Collecting outgoing messages from region outboxes
    2. Delivering messages to target region inboxes
    3. Handling undeliverable messages according to configured policy

    Attributes:
        registry (RegionRegistry): Registry containing all managed regions
        delay (float): Collection interval in seconds (default: 0.5)
        messages (asyncio.Queue): Internal queue for collected messages
        undeliverable (str): Policy for undeliverable messages ('drop', 'retry', 'reroute', 'return', 'error')
        rts_source (str): Custom return-to-sender source address (used when undeliverable='return')
        rts_prepend (bool): Whether to prepend undeliverable notice to message content (used when undeliverable='return')
        reroute_destination (str): Target region for rerouted messages (used when undeliverable='reroute')
        collect (asyncio.Task): Background task for message collection
        emit (asyncio.Task): Background task for message emission
    """

    def __init__(
        self,
        registry: RegionRegistry,
        delay: float = 0.5,
        undeliverable: str = 'drop',
        rts_source: str = '',
        rts_prepend: bool = None,
        reroute_destination: str = '',
    ) -> None:
        """Initializes the Postmaster with routing configuration.

        Args:
            registry: Region registry containing all managed regions
            delay: Collection interval in seconds (default: 0.5)
            undeliverable: Policy for handling undeliverable messages:
                - 'drop': Discard messages (default)
                - 'retry': Requeue messages indefinitely
                - 'reroute': Redirect to reroute_destination
                - 'return': Return to sender with optional modifications
                - 'error': Raise RuntimeError
            rts_source: Custom source address for return-to-sender messages
            rts_prepend: Whether to prepend undeliverable notice to message content
            reroute_destination: Target region name for rerouted messages

        Raises:
            RuntimeError: If undeliverable='reroute' but reroute_destination is empty

        Notes:
            - Return-to-sender parameters (rts_source, rts_prepend) are only active when
              undeliverable='return'. Otherwise they're ignored with a warning.
            - Reroute destination must be specified when undeliverable='reroute'.
            - Configured undeliverable policy is logged at initialization.
        """
        self.registry = registry
        self.delay = delay
        self.messages = asyncio.Queue()
        self.undeliverable = undeliverable
        logging.info(f"Undeliverable message behavior is '{self.undeliverable}'")

        # Check for return to sender arguments
        if self.undeliverable == 'return':
            self.rts_source = rts_source
            self.rts_prepend = rts_prepend
        elif rts_source or rts_prepend:
            logging.warning("Return to sender arguments set, but not used")

        # Check for reroute arguments
        if self.undeliverable == 'reroute':
            if not reroute_destination:
                raise RuntimeError('Reroute destination not specified')
            else:
                self.reroute_destination = reroute_destination
                logging.info(f"Routing undeliverable messages to '{reroute_destination}'")

        # Task holder variables
        self.collect = None
        self.emit = None

    async def start(self):
        """Launches background message processing tasks.

        Starts two concurrent background tasks:
        - collector(): Periodically gathers messages from region outboxes
        - emitter(): Processes messages for delivery or undeliverable handling

        Notes:
            Must be called to activate message routing. Does not block execution.
        """
        self.collect = asyncio.create_task(self.collector())
        self.emit = asyncio.create_task(self.emitter())

    async def collector(self):
        """Background task that collects messages from region outboxes.

        Operation:
            1. Waits `delay` seconds between collection cycles
            2. Iterates through all regions in registry
            3. Drains each region's outbox completely
            4. Adds collected messages to internal queue

        Notes:
            - Runs continuously until task cancellation
            - Uses non-blocking queue operations to avoid blocking
            - Yields control after each message to allow other tasks to run
        """
        while True:  # Runs forever
            await asyncio.sleep(self.delay)  # Wait before checking regions
            for region in self.registry:  # Process each region
                while True:  # Drain region outbox completely
                    try:
                        msg = region.outbox.get_nowait()  # Non-blocking pop
                    except asyncio.QueueEmpty:  # raised when pop attempted on empty queue
                        break  # breaks out of INNER loop
                    self.messages.put_nowait(msg)
                    await asyncio.sleep(0)  # Yield to other tasks

    async def emitter(self):
        """Background task that processes messages for delivery.

        Operation:
            1. Waits for messages from internal queue
            2. Attempts delivery to target region's inbox
            3. Handles undeliverable messages per configured policy:
                - 'drop': Discards message
                - 'retry': Requeues message after delay
                - 'reroute': Changes destination to reroute_destination
                - 'return': Modifies message for return to sender
                - 'error': Raises exception

        Notes:
            - Runs continuously until task cancellation
            - Logs warnings for undeliverable messages
            - Retry policy has no maximum attempts (potential bottleneck risk)
        """
        while True:
            message = await self.messages.get()  # Blocks until message arrives

            sent = False
            for region in self.registry:
                if message['destination'] == region.name:
                    region.inbox.put_nowait(message)
                    break   # Exit region loop after delivery

            if not sent:
                logging.warning(
                    f"Message from '{message['source']}' to '{message['destination']}' could not be delivered")

                match self.undeliverable:
                    case 'drop':
                        continue        # Skip to next message

                    case 'retry':       # Note: Unlimited retries can cause bottlenecks. Consider implementing maximum.
                        await asyncio.sleep(self.delay)
                                        # Should optimistically be long enough for other messages to arrive first
                                        # This reduces retry priority
                        self.messages.put_nowait(message)

                    case 'reroute':
                        message['destination'] = self.reroute_destination
                        self.messages.put_nowait(message)

                    case 'return':
                        original = message
                        message['destination'] = original['source']
                        if self.rts_source:
                            message['source'] = self.rts_source
                        if self.rts_prepend:
                            message['content'] = \
                                f"Could not deliver message to '{original['destination']}'. Content: {original['content']}"
                        self.messages.put_nowait(message)

                    case 'error':
                        raise RuntimeError(f"Could not deliver message to '{message['destination']}'")