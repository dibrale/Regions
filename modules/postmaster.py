import asyncio
import logging
from region_registry import RegionRegistry

class Postmaster:
    def __init__(self,
                 registry: RegionRegistry,
                 delay: float = 0.5,
                 undeliverable: str = 'drop',
                 rts_source: str = '',
                 rts_prepend: bool = True,
                 reroute_destination: str = '',
                 ) -> None:
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
        self.collect = asyncio.create_task(self.collector())
        self.emit = asyncio.create_task(self.emitter())

    async def collector(self):
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
        while True:
            message = await self.messages.get()  # Blocks until message arrives

            sent = False
            for region in self.registry:
                if message['destination'] == region.name:
                    region.inbox.put_nowait(message)
                    break   # Exit region loop after delivery

            if not sent:
                logging.warning(
                    f"Message from '{message['source']}' to '{message['destination']} could not be delivered")

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
                        raise RuntimeError("Could not deliver message to self.messages.put_nowait(message)")