import json
import logging
import re

from regions.base_region import BaseRegion
from modules.llmlink import LLMLink
from modules.utils import make_prompt


class Region(BaseRegion):
    """
    A functional unit within a distributed system that communicates with other regions using LLM-powered interactions.

    Each region has a specific task focus and maintains knowledge about other regions through asynchronous message
    exchanges. Regions process incoming requests, generate replies using an LLM, and proactively query other regions
    to update their knowledge base. Communication occurs through inbox/outbox queues that handle request/reply cycles.

    Attributes:
        name (str): Unique identifier for the region
        task (str): Functional description of the region's purpose (e.g., "provide weather information")
        llm (LLMLink): Interface to the LLM service for text generation
        connections (dict[str, str]): Mapping of downstream region names to their task descriptions
        inbox (asyncio.Queue): Queue for incoming messages (requests and replies)
        outbox (asyncio.Queue): Queue for outgoing messages (requests and replies)
        _incoming_replies (dict): Stores knowledge received from other regions (keyed by source region name)
        _incoming_requests (dict): Stores pending requests received from other regions (keyed by source region name)
    """

    def __init__(self, name: str, task: str, llm: LLMLink, connections: dict[str, str] | None):
        """
        Initialize a region with communication capabilities and LLM integration.

        Args:
            name (str): Unique identifier for the region
            task (str): Functional description of the region's purpose
            llm (LLMLink): Interface to the LLM service for text generation
            connections (dict[str, str] | None): Mapping of region names to their task descriptions.
                If None, initializes with empty connections dictionary.

        Note:
            - The region maintains separate queues for incoming/outgoing messages
            - Connections dictionary should contain {region_name: task_description} pairs
            - _context and _queries dictionaries are initialized empty for knowledge management
        """
        super().__init__(name, task, connections)
        self.llm = llm
        self.focus_str = f"Your focus: {self.task}"

    def _replies_block(self) -> str:
        """
        Writes incoming replies block by peeking at the incoming replies queue.
        :return: (str): A prefixed JSON dump of incoming replies
        """
        if not self._incoming_replies.empty():
            raw_incoming_replies = [*self._incoming_replies.__dict__['_queue']]
        else:
            return ''
        schema_str = json.dumps(raw_incoming_replies, indent=2)
        block = f"Below is a summary of your knowledge from different sources:\n{schema_str}\n"
        return block

    def _requests_block(self) -> str:
        """
        Writes incoming requests block by peeking at the incoming requests queue.
        :return: (str): A prefixed JSON dump of incoming requests
        """
        if not self._incoming_requests.empty():
            raw_incoming_requests = [*self._incoming_requests.__dict__['_queue']]
        else:
            return ''
        schema_str = json.dumps(raw_incoming_requests, indent=2)
        prefix = ("Below is a list of current incoming requests, "
                  "which may contain useful information:")
        block = f"{prefix}\n{schema_str}\n"
        return block

    async def _parse_thinking(self, raw_reply: str) -> str:
        """
            Extracts the thinking block from raw LLM replies using delimiter patterns.

            Parses raw LLM responses to isolate the assistant's final reply by:
            - Searching for content between '<think> ... </think>' delimiters (thinking block)
            - Returning the cleaned reply if thinking block exists
            - Falling back to raw reply (stripped) if no thinking block found

            Args:
                raw_reply (str): Raw response string from LLM, potentially containing
                    thinking traces enclosed in '<think> ... </think>' delimiters

            Returns:
                str: Cleaned reply string with thinking block removed (if present),
                    or stripped raw reply if no thinking block detected

            Note:
                - Logs debug messages about extraction status
                - Returns stripped content to remove extraneous whitespace
        """
        # Parse out model thinking
        # If there is no thinking block, pass the raw reply
        try:
            reply = re.findall(r"<think>.*</think>\n(.*)", raw_reply, flags=re.DOTALL)[0].strip()
            logging.debug("Thinking block found in raw reply.")
        except IndexError:
            reply = raw_reply.strip()

        logging.debug(f"{self.name}: Extracted reply: {str(reply)}")
        return reply

    async def _get_from_llm(self, prompt: str) -> str:
        """
        Sends prompt to LLM and processes raw response through thinking extraction.

        Handles end-to-end LLM interaction by:
        1. Generating raw reply via self.llm.text()
        2. Parsing thinking blocks using _parse_thinking()
        3. Managing exceptions and logging failures

        Args:
            prompt (str): Formatted prompt string ready for LLM processing

        Returns:
            str: Processed reply string from LLM (thinking block extracted),
                or empty string if errors occur during processing

        Note:
            - Logs raw LLM responses at debug level
            - Catches exceptions during LLM processing and logs warnings
            - Returns empty string on failure but preserves raw output in logs
            - Always returns a string (never raises exceptions)
        """
        raw_reply = ""
        reply = ""
        try:
            raw_reply = await self.llm.text(prompt)
            logging.debug(f"{self.name}: Got reply from LLM: {raw_reply}")
            reply = await self._parse_thinking(raw_reply)

        except Exception as e:
            logging.warning(f"{self.name}: Processing failed. {e.args}")
            logging.debug("Attempting to dump raw output...")
            logging.debug(raw_reply)

        return reply

    def _make_replies_init(self) -> tuple:
        """
        Internal function to set initial variables for make_replies(). Raises
        ValueError if incoming request queue is empty.
        :return:
        tuple: initial settings for 'faultless' (True) and 'success' (empty list) variables
        """
        logging.debug(f"{self.name}: Initiating reply generation...")
        self._run_inbox()
        if self._incoming_requests.empty():
            raise ValueError
        return True, []


    async def make_replies(self) -> bool:
        """
        Generate replies to all pending requests in _incoming_requests.

        Returns:
            bool: True if all replies were successfully generated, False otherwise

        Note:
            - Processes each pending request from _incoming_requests
            - Generates replies using LLM with region-specific context
            - Sends replies via _reply() method
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
                self._reply(source, reply)
                success.append(True)
            else:
                faultless = False
                success.append(False)

        logging.info(f"{self.name}: Replied to {sum(success)}/{initial_length} queries.")
        if sum(success) != initial_length:
            logging.warning(f"{initial_length - sum(success)} replies failed to generate.")
        return faultless

    async def make_questions(self) -> bool:
        """
        Generate questions for connected regions to update knowledge.

        Returns:
            bool: True if questions were successfully generated and sent, False otherwise

        Note:
            - Constructs a prompt asking LLM to generate questions for connected regions
            - Processes LLM response to extract valid questions
            - Sends questions via _ask() method
            - Validates destination regions against connections dictionary
            - Returns False if JSON parsing fails or invalid destinations are specified
        """
        faultless = True
        self._run_inbox()

        user_prompt = (
                "Below is a dictionary of sources and their respective focus. Keeping your own "
                "focus in mind, ask each of them one or more questions to update your knowledge."
                "\n\n" + json.dumps(self.connections, indent=2) +
                '\n\nReply with your questions in valid JSON format according to the template:\n'
                '[{"source": source1, "question": question1}, {"source": source2, '
                '"question": question2}, ... ]'
        )

        prompt = make_prompt(
            user_prompt,
            '\n'.join([self.focus_str, self._replies_block(), self._requests_block()])
        )
        reply = await self._get_from_llm(prompt)

        if not reply:
            logging.warning(f"{self.name}: No questions generated.")
            return False

        try:
            questions = json.loads(re.findall(r"\[\s*?\n*?\s*?\{.*?}\s*?\n*?\s*?]", reply, flags=re.DOTALL)[-1])
            logging.debug(f"{self.name}: Extracted questions: {questions}")
        except Exception as e:
            logging.warning(f"{self.name}: Processing failed. {e.args}")
            logging.debug("Attempting to dump output...")
            logging.debug(reply)
            logging.warning(f"{self.name}: No questions generated.")
            faultless = False
            return faultless
        if questions:
            for question in questions:
                try:
                    if question['source'] not in self.connections:
                        raise AssertionError(f"{self.name}: {question['source']} is not a valid recipient")
                    self._ask(question['source'], question['question'])
                except Exception as e:
                    logging.error(f"{self.name}: Error processing LLM reply. {e}")
                    faultless = False
        else:
            logging.warning(f"{self.name}: No questions generated.")
            return True
        return faultless

    async def summarize_replies(self) -> bool:
        """
        Consolidates incoming replies into a single coherent knowledge summary.

        Generates concise summaries of accumulated replies by:
        - Aggregating all reply content into a single LLM prompt
        - Requesting summarization via _get_from_llm()
        - Replacing queue contents with summarized knowledge

        Returns:
            bool: True if summarization succeeded for all replies,
                  False if any LLM processing failed

        Note:
            - Processes _incoming_replies queue containing (source, content) tuples
            - Constructs prompt with instruction: 'Summarize... into single paragraph'
            - Replaces original queue items with summarized results
            - Logs success/failure metrics (e.g., 'Summarized X replies to Y items')
            - Returns True immediately if queue is empty
            - Maintains knowledge coherence by preserving summarized information
        """
        faultless = True
        self._run_inbox()
        original_length = self._incoming_replies.qsize()
        if self._incoming_replies.empty():
            logging.info(f"{self.name}: No replies to summarize.")
            return True
        self._consolidate_replies()
        replies = {}
        prompt = 'Summarize the following into a single coherent paragraph without losing information:\n\n'
        if not self._incoming_replies.empty():
            while not self._incoming_replies.empty():
                item = self._incoming_replies.get_nowait()
                source = next(iter(item.keys()))
                content = item[source]
                prompt += content
                try:
                    reply = await self._get_from_llm(make_prompt(prompt))
                except Exception as e:
                    logging.warning(f"{self.name}: Processing failed. {e.args}")
                    reply = ""
                if not reply:
                    logging.warning(f"{self.name}: Summarizing failed for replies from '{source}'. Restoring original content.")
                    faultless = False
                replies.update({source: reply})
            for source in replies:
                self._incoming_replies.put_nowait({source: replies[source]})
            logging.info(
                f"{self.name}: Summarized {original_length} replies to a total of {self._incoming_replies.qsize()} items.")
            return faultless
        raise AssertionError(
            "Incoming reply queue empty after consolidation, but it should not be. Please bring this to the attention of the developer and proceed with caution.")
