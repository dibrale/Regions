"""
Rather than replying, this region feeds all output forward to all connections.
"""
import logging

from llmlink import LLMLink
from regions.region import Region
from utils import make_prompt


class FeedForwardRegion(Region):
    def __init__(self, name: str, task: str, llm: LLMLink, connections: dict[str, str] | None):
        super().__init__(name, task, llm, connections)

    async def make_replies(self) -> bool:
        """
        Generate replies to all pending requests in _incoming_requests, sending them to connected
        regions rather than the requesting region.

        Returns:
            bool: True if all replies were successfully generated, False otherwise

        Note:
            - Processes each pending request from _incoming_requests
            - Generates replies using LLM with region-specific context
            - Sends replies via _reply() method to all connected regions
            - Returns False if any LLM processing fails
            - Clears _incoming_requests after processing
        """
        try:
            faultless, success = self._make_replies_init()
        except ValueError:
            logging.info(f"{self.name}: No incoming requests to process.")
            return True

        initial_length = self._incoming_requests.qsize()
        while not self._incoming_requests.empty():
            request = self._incoming_requests.get_nowait()
            source, question = request.popitem()

            prompt = make_prompt(
                question,
                '\n'.join([self.focus_str, self._replies_block(), self._requests_block()])
            )

            reply = await self._get_from_llm(prompt)

            if reply:
                for recipient in [*self.connections.keys()]:
                    self._reply(recipient, reply)
                success.append(True)
            else:
                faultless = False
                success.append(False)

        logging.info(f"{self.name}: Prepared replies to {sum(success)}/{initial_length}"
                     f" queries for forwarding to {len(self.connections)} regions.")
        if sum(success) != initial_length:
            logging.warning(f"{initial_length - sum(success)} replies failed to generate.")
        return faultless