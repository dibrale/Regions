import asyncio
import json
import logging
import re

from regions.base_region import BaseRegion
from modules.llmlink import LLMLink


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

    def _make_prompt(self, question: str, bom: str = '<|im_start|>', eom: str = '<|im_end|>', think: str = None) -> str:
        """
        Construct a structured prompt for the LLM.

        Args:
            question (str): User query or request to process
            bom (str, optional): Beginning of message delimiter. Defaults to '('.
            eom (str, optional): End of message delimiter. Defaults to '<|im_end|>'.
            think (str, optional): Optional thinking trace to include in prompt. Defaults to None.

        Returns:
            str: Formatted prompt string ready for LLM processing

        Note:
            - Builds schema containing region's task focus and accumulated knowledge
            - Uses delimiters to structure system/user/assistant sections
            - Includes thinking trace if provided
        """
        raw_incoming_replies = [*self._incoming_replies.values()]
        schema = {'focus': self.task, 'knowledge': [reply for reply in raw_incoming_replies if reply]}
        prefix = f"{bom}system\nReply to the user, given your focus and knowledge per the given schema:"
        prompt = f"{prefix}\n{schema}{eom}\n{bom}user\n{question}{eom}\n{bom}assistant\n"
        if think: prompt += f"{think}\n"
        return prompt

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
        faultless = True
        self._run_inbox()

        for source, question in self._incoming_requests.items():
            prompt = self._make_prompt(question)
            reply = None
            try:
                raw_reply = await self.llm.text(prompt)
                logging.debug(f"{self.name}: Got reply from LLM: {raw_reply}")

                # Parse out model thinking
                # If there is no thinking block, pass the raw reply
                try:
                    reply = re.findall(r"<think>.*</think>\n(.*)", raw_reply, flags=re.DOTALL)[0].strip()
                except IndexError:
                    reply = raw_reply.strip()

                logging.debug(f"{self.name}: Extracted reply: {reply}", False)

            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False
            if reply:
                self._reply(source, reply)

        self._incoming_requests.clear()  # Clear processed queries
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
                "Below is a list of sources and their respective focus. Keeping your own focus in mind, ask each of them " +
                "one question to update your knowledge.\n\n" + str(self.connections) +
                '\n\nReply with your questions in valid JSON format according to the template:\n' +
                '[{"source": source1, "question": question1}, {"source": source2, "question": question2}, ... ]\n\n'
        )
        prompt = self._make_prompt(user_prompt)
        try:
            reply = await self.llm.text(prompt)
            logging.debug(f"{self.name}: Got reply from LLM: {reply}", False)
            questions = json.loads(re.findall(r"\[\s*?\n*?\s*?{.*?}\s*?\n*?\s*?]", reply, flags=re.DOTALL)[-1])
            logging.debug(f"{self.name}: Extracted questions: {questions}", False)
        except Exception as e:
            print(f"\n{self.name}: Processing failed. {e}")
            faultless = False
            return faultless
        for question in questions:
            try:
                if question['source'] not in self.connections:
                    raise AssertionError(f"{self.name}: {question['source']} is not a valid recipient")
                self._ask(question['source'], question['question'])
            except Exception as e:
                print(f"\n{self.name}: Error processing LLM reply. {e}")
                faultless = False
        return faultless
