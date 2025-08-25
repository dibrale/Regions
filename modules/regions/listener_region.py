import asyncio
import logging
import multiprocessing as mp
from typing import Callable

from regions.base_region import BaseRegion
from orchestrator import Orchestrator


class ListenerRegion(BaseRegion):
    """
    Specialized region that continuously receives and forwards traffic for logging, debugging, or output purposes.
    Unlike standard regions, it:
      - Only processes incoming messages (never initiates requests or replies)
      - Automatically forwards all received messages to an external output process
      - Operates as a passive observer (typically configured as a carbon copy receiver via Postmaster)

    This region is designed for traffic monitoring and does not participate in normal message routing. Once started,
    it runs a background task that periodically drains its inbox and forwards messages via a multiprocessing queue
    to the specified output handler.

    Notes:
        - Configure as a carbon copy receiver by setting the Postmaster's 'cc' parameter to this region's name.
        - Message metadata (including 'source' and 'destination') remains unchanged when copied to this region.
        - Intentionally lacks standard region capabilities (connections, outbox, and messaging methods) to prevent
          accidental use in normal traffic routing.
        - The `out_process` function MUST handle a sentinel value (None) to gracefully terminate. It should run in a
          loop that breaks when receiving None.

    Usage:
        Ensure that the ListenerRegion is registered and configured to run 'start' in layer 0. Multiple
        ListenerRegions can be started in the same chain for organizational purposes, especially if longer
        initialization methods are being called concurrently. Run 'stop' for ListenerRegions in the final layer of the
        execution configuration to cleanly terminate the forwarding process. The 'verify' method checks that these
        practices are followed for a ListenerRegion instance in a given orchestrator.

    Example:
        Example out_process implementation:

        >>> def handle_output(q: mp.Queue):
        >>>    while True:
        >>>        msg = q.get()
        >>>        if msg is None: break   # Sentinel check

        Processing of message follows.

    Critical Considerations:
        - Do not send organic traffic (intended recipient) to a ListenerRegion if it is designated as the CC region
          for the postmaster. Doing causes message duplication. Use dedicated regions for receiving organic traffic.
        - Calling base-class methods (e.g., _post, _ask) will raise NameError due to deliberate deletion of
          required attributes during initialization.
        - Output processing occurs in a separate process via mp.Queue, enabling non-blocking forwarding.
        - out_process MUST handle sentinel (None) for graceful shutdown
        - Do not call start() multiple times without stop() in between
        - Always call stop() to prevent resource leaks
    """

    def __init__(self, name: str, out_process: Callable, delay: float = 0.5):
        super().__init__(name, "Receive and forward all incoming messages.")
        del self.connections, self.outbox

        self.delay = delay
        self.forward_task = None
        self.out_q = mp.Queue()
        self.out_process = out_process
        self.p = None

    def _post(self, destination: str, content: str, role: str) -> None:
        raise NotImplementedError("ListenerRegion does not support outgoing messages.")

    def _ask(self, destination: str, message: str) -> None:
        raise NotImplementedError("ListenerRegion does not support sending requests.")

    def _reply(self, source: str, content: str) -> None:
        raise NotImplementedError("ListenerRegion does not support sending replies.")

    def _run_inbox(self):
        raise NotImplementedError("ListenerRegion does not need to sort messages.")

    async def start(self) -> None:
        """
        Launches the background forwarding task.
        Starts continuous inbox processing that periodically forwards received messages.
        """
        if self.p is not None:
            raise RuntimeError("Region already started")
        self.p = mp.Process(target=self.out_process, args=(self.out_q,))
        self.p.start()  # Start mp process
        self.forward_task = asyncio.create_task(self.forward())

    async def forward(self) -> None:
        """
        Background task that continuously:
          1. Waits for 'delay' seconds between inbox checks
          2. Drains ALL pending messages from inbox
          3. Forwards each message to output process via mp.Queue
          4. Yields control to other asyncio tasks

        Runs indefinitely until the region is stopped.
        """
        try:
            while True:
                await asyncio.sleep(self.delay)
                while True:
                    try:
                        msg = self.inbox.get_nowait()
                        await asyncio.to_thread(self.out_q.put, msg)
                        await asyncio.sleep(0)
                    except asyncio.QueueEmpty:
                        break
        except asyncio.CancelledError:
            # Drain inbox during cancellation
            while not self.inbox.empty():
                msg = await self.inbox.get()
                self.out_q.put(msg)
            raise  # Propagate cancellation

    async def stop(self) -> None:

        # 1. Drain inbox one last time
        while not self.inbox.empty():
            msg = await self.inbox.get()
            self.out_q.put(msg)  # Blocking put (safe during shutdown)

        """Cleanly stops forwarding and terminates output process."""
        # 2. Cancel forwarding task
        if self.forward_task:
            self.forward_task.cancel()
            try:
                await self.forward_task
            except asyncio.CancelledError:
                pass
            self.forward_task = None

        # 3. Signal output process to stop
        if self.p and self.p.is_alive():
            self.out_q.put(None)  # Sentinel value

        # 4. Clean up process
        if self.p:
            self.p.join(timeout=2.0)
            if self.p.is_alive():
                self.p.terminate()  # Force cleanup if unresponsive
            self.p.close()
            self.p = None

        # 5. Close queue
        self.out_q.close()

    def verify(self, orchestrator: Orchestrator) -> bool:
        """
        Verify correct configuration of ListenerRegion in the orchestrator via the region profile.

        Ensures the ListenerRegion is properly configured for its intended role as a traffic monitor:
          1. Appears only in layer 0 (initialization) and the terminal layer (shutdown)
          2. Executes 'start()' in layer 0
          3. Executes 'stop()' in the terminal layer

        Args:
            orchestrator (Orchestrator): The orchestrator instance to validate

        Returns:
            bool: True if configuration is correct, False otherwise

        Note:
            - Logs detailed error messages for each misconfiguration
            - Returns False if any validation check fails

        Side Effects:
            - Does not check whether the instance is present in the orchestrator's layer configuration. While this is
              done to allow the region to remain silent if desired, relying on this method without external checks
              such as the 'verify' method may lead to undesired silent behavior.
        """
        profile = orchestrator.region_profile(self.name)
        faultless = True

        # Get the region profile
        if not profile:
            logging.error(f"{self.name}: No region profile found in orchestrator.")
            return False

        layers = list(profile.keys())
        last_layer = len(orchestrator.execution_config)-1
        expected_layers = [0, len(orchestrator.execution_config)-1]

        # Ensure that only the initial and final layers are configured for this region
        try:
            assert layers == expected_layers
        except AssertionError:
            unexpected_layers = list(set(layers) - set(expected_layers))
            if not 0 in layers:
                logging.error(f"{self.name}: Missing from layer 0 execution configuration")
                faultless = False
            if not last_layer in layers:
                logging.error(f"{self.name}: Missing from terminal layer execution configuration")
                faultless = False
            if unexpected_layers:
                logging.error(
                    f"{self.name}: Unexpectedly found in execution configuration at layers: " +
                    f"{', '.join(str(x) for x in unexpected_layers)}"
                )

        # Ensure that 'start' is called in layer 0
        try:
            assert profile[0] == 'start'
        except AssertionError:
            logging.error(
                f"{self.name} Expected start method in layer 0 of execution configuration. Found {', '.join(profile[0])} instead."
            )
            faultless = False

        # Ensure that 'stop' is called on the final layer
        try:
            assert profile[last_layer] == 'stop'
        except AssertionError:
            logging.error(
                f"{self.name} Expected stop method in terminal layer of execution configuration. Found {', '.join(profile[last_layer])} instead."
            )
            faultless = False

        return faultless
