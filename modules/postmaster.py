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
        default_resend_delay (float): Delay used for retry operations (default: delay-0.01)
        messages (asyncio.Queue): Internal queue for collected messages
        undeliverable (str): Policy for undeliverable messages ('drop', 'retry', 'reroute', 'return', 'error')
        rts_source (str): Custom return-to-sender source address (used when undeliverable='return')
        rts_prepend (bool|None): Whether to prepend undeliverable notice to message content (used when undeliverable='return')
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
        cc: str = None,
        print_address: str = 'terminal',
    ) -> None:
        """Initializes the Postmaster with routing configuration.

        Args:
            registry: Region registry containing all managed regions
            delay: Collection interval in seconds (default: 0.5)
            undeliverable: Policy for handling undeliverable messages:
                - 'drop': Discard messages (default)
                - 'retry': Requeue messages after delay
                - 'reroute': Redirect to reroute_destination
                - 'return': Return to sender with optional modifications
                - 'error': Raise RuntimeError
            rts_source: Custom source address for return-to-sender messages
            rts_prepend: Whether to prepend undeliverable notice to message content.
                         If None (default), no prepend occurs.
            reroute_destination: Target region name for rerouted messages
            cc: Name of a "CC" region (for debugging/logging purposes)
            print_address: Destination that will cause the message to be written to sys.stdout via print()

        Raises:
            RuntimeError: If undeliverable='reroute' but reroute_destination is empty

        Notes:
            - Return-to-sender parameters (rts_source, rts_prepend) are only active when
              undeliverable='return'. Otherwise, they are ignored with a warning.
            - Reroute destination must be specified when undeliverable='reroute'.
            - Configured undeliverable policy is logged at initialization.
            - default_resend_delay is automatically set to delay-0.01 to reduce retry priority
        """
        self.registry = registry
        self.cc = cc
        self.print_address = print_address
        self.delay = delay
        self.default_resend_delay = delay-0.01  # Should optimistically be long enough for other messages to arrive first
                                                # This reduces priority of resends compared to new arrivals
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
        loop = asyncio.get_event_loop()
        self.collect = loop.create_task(self.collector())
        self.emit = loop.create_task(self.emitter())

    async def stop(self) -> bool:
        """
        Stops both the collector and emitter tasks (if running) and waits for the message
        queue to empty before returning. Returns True if all tasks were stopped successfully
        or were not running, and False if any task cancellation encountered an exception
        or the message queue failed to drain within the timeout period.

        Steps:
          1. Checks if tasks are running (collector/emit)
          2. Stops emitter task (if running) and logs result
          3. Waits for message queue to drain (with timeout = 2 * delay)
          4. Stops collector task (if running) and logs result
          5. Returns True only if all tasks were stopped without error

        Returns:
            bool: True if shutdown completed successfully (tasks stopped or not running,
                  and queue drained), False if any task cancellation failed or queue didn't
                  drain within timeout.

        Note:
            - If tasks weren't running, returns True immediately
            - Queue drain failure results in an error log but doesn't prevent shutdown

        Side Effects:
            - May shut down only one of collector/emitter, or both.
        """
        # Check if tasks are already running and stop them

        if not self.collect and not self.emit:
            logging.info("Postmaster tasks were not running, nothing to stop")
            await asyncio.sleep(0)
            return True

        success = True

        if self.emit:
            logging.info("Stopping emitter task")
            try:
                self.emit.cancel()
                logging.info("Emitter task stopped successfully")
            except Exception as e:
                logging.error(f"Emitter task raised an exception on cancellation: {e}")
                success = False
        else:
            logging.info("Emitter task was not running")

        # Allow the emitter to stop and collect any last messages
        total_delay = 0
        sleep_tick = 0.1
        max_delay = self.delay * 2 # twice the collector polling interval
        logging.info(f"Waiting for message queue to drain")
        while True:
            await asyncio.sleep(sleep_tick)
            total_delay += sleep_tick

            if self.messages.empty():
                logging.info("Messages queue empty")
                break

            if total_delay >= max_delay:
                logging.error(f"Queue did not empty after {max_delay} seconds")
                success = False
                break

        if self.collect:
            logging.info("Stopping collector task")
            try:
                self.collect.cancel()
                logging.info("Collector task stopped successfully")
            except Exception as e:
                logging.error(f"Collector task raised an exception on cancellation: {e}")
                success = False
        else:
            logging.info("Collector task was not running")

        return success

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
        logging.info("Starting postmaster collector")
        try:
            logging.debug(f"Polling regions: {', '.join([region.name for region in self.registry])}")
        except Exception as e:
            logging.error(f"Error occurred while polling: {e}")
        while True:  # Runs forever
            await asyncio.sleep(0)
            await asyncio.sleep(self.delay)
            for entry in self.registry:  # Process each region
                # logging.debug(f"Processing outbox from '{entry.name}'")
                if hasattr(entry.region, 'outbox'):
                    while True:  # Drain region outbox completely
                        msg = None
                        try:
                            msg = entry.region.outbox.get_nowait()  # Non-blocking pop
                            logging.debug(f"Message received from '{entry.name}': {msg}")
                        except asyncio.QueueEmpty:  # raised when pop attempted on empty queue
                            # logging.debug(f"No messages left in '{entry.name}'")
                            break  # breaks out of INNER loop
                        except Exception as e:
                            logging.error(f"Unexpected error occurred while processing region '{entry.name}': {e}")
                        self.messages.put_nowait(msg)
                        # await asyncio.sleep(0)  # Yield to other tasks

    async def resend(self, msg: dict, resend_delay: float = None):
        """Requeues a message after a configurable delay for retry delivery.

        Args:
            msg (dict): The undeliverable message to be resent
            resend_delay (float, optional): Custom delay before resending.
                If not provided, uses default_resend_delay (delay-0.01 seconds)

        Notes:
            - Delay is implemented with non-blocking sleeps to avoid starving other tasks
            - After delay, message is re-queued for delivery attempt
            - Used when undeliverable='retry' policy is active
            - default_resend_delay creates lower priority for resends compared to new messages
        """
        if resend_delay:
            delay = resend_delay
        else:
            delay = self.default_resend_delay

        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < delay:
            await asyncio.sleep(0.01)

        await self.messages.put(msg)

    async def emitter(self):
        """Background task that processes messages in batches after fixed intervals.

        Operation:
            1. Waits at least `delay` seconds between processing batches
            2. Processes ALL messages currently in the internal queue:
                a. Attempts delivery to target region's inbox
                b. Handles undeliverable messages per configured policy:
                    - 'drop': Discards message immediately
                    - 'retry': Schedules retry after `default_resend_delay` (delay-0.01)
                    - 'reroute': Redirects to `reroute_destination` (if available)
                    - 'return': Modifies message for return to sender with optional:
                        * Source address override (rts_source)
                        * Content prepend (rts_prepend)
                    - 'error': Raises RuntimeError

        Side Effects:

            - Message role is set to 'reply' in the course of return-to-sender behavior to avoid feedback loops
            - The 'retry' behavior runs a new asyncio task for each resend attempt. While these tasks terminate after the message is resent, a buildup of undelivered messages can easily result if new messages along the same route also remain undeliverable.

        Notes:
            - Processes messages in batches rather than individual items
            - Retry delay is intentionally shorter than collection interval to:
                * Reduce priority of resends compared to new messages
                * Prevent retry bottlenecks
            - Unlimited retries possible (monitor for message buildup)
            - Logs undeliverable messages as warnings
            - Runs continuously until task cancellation
        """
        logging.info("Starting postmaster emitter")
        while True:

            # Wait at least the delay time
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < self.delay or self.messages.empty():
                await asyncio.sleep(0.01)

            while not self.messages.empty():
                await asyncio.sleep(0) # Yield here in case of cancellation
                logging.debug(f"Postmaster emitter processing {self.messages.qsize()} messages")
                message = self.messages.get_nowait()
                sent = False
                for entry in self.registry:
                    logging.debug(f"Looking for messages to '{entry.name}'")
                    if message['destination'] == entry.name:
                        logging.debug(f"Found message for '{entry.name}' from '{message['source']}'")
                        try:
                            entry.region.inbox.put_nowait(message)
                        except Exception as e:
                            logging.error(f"Failed to send message to '{entry.name}': {e}")
                        if self.cc:
                            self.registry[self.cc].inbox.put_nowait(message)
                        sent = True
                        logging.info(f"Message sent from '{message['source']}' to '{message['destination']}'")
                        break   # Exit region loop after delivery

                if message['destination'] == self.print_address:
                    print(f"{message['source']}: {message['content']}")
                    continue

                if not sent:

                    logging.warning(
                        f"Message from '{message['source']}' to '{message['destination']}' could not be delivered")

                    match self.undeliverable:
                        case 'drop':
                            continue        # Skip to next message

                        case 'retry':       # Note: Unlimited retries can cause bottlenecks. Consider implementing maximum.

                            asyncio.create_task(self.resend(message))
                            continue

                        case 'reroute':

                            # If the rerouting destination is unavailable despite reroute behavior, drop the message
                            if message['destination'] == self.reroute_destination:
                                logging.warning(f"Reroute destination '{message['destination']}' unavailable. Dropping message.")
                                continue

                            else:
                                message['destination'] = self.reroute_destination
                                logging.info(f"Rerouting from '{message['source']}' to '{message['destination']}'")
                                self.messages.put_nowait(message)
                                continue

                        case 'return':
                            if message['source'] == self.rts_source:
                                logging.warning(f"Could not return message to sender '{message['destination']}'. Message dropped.")
                                continue
                            else:
                                original = message
                                message['role'] = 'reply'       # Role is now reply, not request, to avoid feedback effects
                                if self.rts_prepend:
                                    message['content'] = \
                                        f"Could not deliver message to '{message['destination']}'. Content: {original['content']}"
                                message['destination'] = original['source']
                                if self.rts_source:
                                    message['source'] = self.rts_source

                                self.messages.put_nowait(message)
                                continue

                        case 'error':
                            raise RuntimeError(f"Could not deliver message to '{message['destination']}'")