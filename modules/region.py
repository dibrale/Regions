import asyncio
import json
from typing import override

from modules.llamacpp_api import LLMLink
from modules.dynamic_rag import DynamicRAGSystem, RetrievalResult
from scratch.neural_region_scratch import NeuralRegion


class Region:
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
        _context (dict): Stores knowledge received from other regions (keyed by source region name)
        _queries (dict): Stores pending requests received from other regions (keyed by source region name)
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
        self.name = name
        self.task = task
        self.llm = llm
        if connections is None:
            self.connections = {}
        else:
            self.connections = connections
        self.inbox = asyncio.Queue()  # Queue for incoming requests and replies
        self.outbox = asyncio.Queue()  # Queue for outgoing requests and replies
        self._context = {}
        self._queries = {}

    def _post(self, destination: str, content: str, role: str) -> None:
        """
        Internal method to send a formatted message to another region.

        Args:
            destination (str): Target region name
            content (str): Message payload
            role (str): Message type ('request' or 'reply')

        Note:
            - Constructs a standardized message dictionary with source/destination metadata
            - Places message directly into outbox queue (non-blocking)
            - Should only be called by _ask() or _reply() methods
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
        Send a request query to another region.

        Args:
            destination (str): Target region name
            query_text (str): Question to ask the destination region

        Note:
            - Uses _post() with role='request'
            - Non-blocking operation (immediately returns)
        """
        self._post(destination, query_text, 'request')

    def _reply(self, destination: str, reply_text: str) -> None:
        """
        Send a reply to a region that previously requested information.

        Args:
            destination (str): Target region name
            reply_text (str): Response content to send

        Note:
            - Uses _post() with role='reply'
            - Non-blocking operation (immediately returns)
        """
        self._post(destination, reply_text, 'reply')

    def _run_inbox(self):
        """
        Process all pending messages in the inbox queue.

        Note:
            - Processes messages until inbox is empty
            - Categorizes messages by 'role' (request/reply)
            - Stores replies in _context (keyed by source region)
            - Stores requests in _queries (keyed by source region)
            - Raises AssertionError for unknown message types
            - Should be called before processing messages
        """
        while not self.inbox.empty():
            message = self.inbox.get_nowait()
            if message['role'] == 'reply':
                self._context[message['source']] = message['content']
            elif message['role'] == 'request':
                self._queries[message['source']] = message['content']
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")

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
        schema = {'focus': self.task, 'knowledge': [*self._context.values()]}
        prefix = f"{bom}system\nReply to the user, given your focus and knowledge per the given schema:"
        prompt = f"{prefix}\n{schema}{eom}\n{bom}user\n{question}{eom}\n{bom}assistant\n"
        if think: prompt += f"{think}\n"
        return prompt

    async def make_replies(self) -> bool:
        """
        Generate replies to all pending requests in _queries.

        Returns:
            bool: True if all replies were successfully generated, False otherwise

        Note:
            - Processes each pending request from _queries
            - Generates replies using LLM with region-specific context
            - Sends replies via _reply() method
            - Returns False if any LLM processing fails
            - Clears _queries after processing
        """
        faultless = True
        self._run_inbox()

        for source, question in self._queries.items():
            prompt = self._make_prompt(question)
            reply = None
            try:
                reply = await self.llm.text(prompt)
            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False
            if reply:
                self._reply(source, reply)

        self._queries.clear()  # Clear processed queries
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
            questions = json.loads(reply)
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

class RAGRegion:

    def __init__(self,
                 name: str,
                 task: str,
                 rag: DynamicRAGSystem,
                 connections: dict[str,str] | None,
                 reply_with_actors: bool = False
                 ):
        self.name = name
        self.task = task
        self.rag = rag
        self.reply_with_actors = reply_with_actors
        if connections is None:
            self.connections = {}
        else:
            self.connections = connections
        self.inbox = asyncio.Queue()  # Queue for incoming requests and replies
        self.outbox = asyncio.Queue()  # Queue for outgoing requests and replies
        self._queries = {}
        self._requests = {}

    def _post(self, destination: str, content: str, role: str) -> None:
        """
        Internal method to send a formatted message to another region.

        Args:
            destination (str): Target region name
            content (str): Message payload
            role (str): Message type ('request' or 'reply')

        Note:
            - Constructs a standardized message dictionary with source/destination metadata
            - Places message directly into outbox queue (non-blocking)
            - Should only be called by _ask() or _reply() methods
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
        Send a request query to another region.

        Args:
            destination (str): Target region name
            query_text (str): Question to ask the destination region

        Note:
            - Uses _post() with role='request'
            - Non-blocking operation (immediately returns)
        """
        self._post(destination, query_text, 'request')

    def _reply(self, destination: str, reply_text: str) -> None:
        """
        Send a reply to a region that previously requested information.

        Args:
            destination (str): Target region name
            reply_text (str): Response content to send

        Note:
            - Uses _post() with role='reply'
            - Non-blocking operation (immediately returns)
        """
        self._post(destination, reply_text, 'reply')

    def _run_inbox(self):
        """
        Process all pending messages in the inbox queue.

        Note:
            - Processes messages until inbox is empty
            - Accepts only messages with the 'request' role
            - Raises AttributeError for messages with 'reply' role
            - Raises AssertionError for unknown message types
            - Should be called before processing messages
        """
        while not self.inbox.empty():
            message = self.inbox.get_nowait()
            if message['role'] == 'reply':
                self._requests[message['source']] = message['content']
            elif message['role'] == 'request':
                self._queries[message['source']] = message['content']
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")

    async def make_replies(self) -> bool:
        """
        Generate replies to all pending requests in _queries.

        Returns:
            bool: True if all replies were successfully generated, False otherwise

        Note:
            - Processes each pending request from _queries
            - Generates replies using RAG search
            - Sends replies via _reply() method
            - Returns False if any processing fails
            - Clears _queries after processing
        """
        faultless = True
        self._run_inbox()

        for source, question in self._queries.items():
            matches = None
            reply = ''
            try:
                matches = await self.rag.retrieve_similar(question)
            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False
            for match in matches:
                reply+='{"memory_fragment": '+f"{match.chunk.content}"
                if self.reply_with_actors:
                    reply += ', "actors": '+f"{match.chunk.metadata.actors}\n"
                reply+="},\n"
            if reply:
                self._reply(source, reply)

        self._queries.clear()  # Clear processed queries
        return faultless

    async def make_updates(self, consolidate_threshold: float = 0.1):
        faultless = True
        self._run_inbox()
        results: list[RetrievalResult] = []

        for source, update in self._requests.items():
            updated = False
            hashes_to_delete = []

            try:
                results = await self.rag.retrieve_similar(update)
            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False

            if results:
                max_score = max(result.similarity_score for result in results)


                for result in results:
                    if result.similarity_score == max_score and not updated:
                        updated = self.rag.update_chunk(
                            result.chunk.chunk_hash,
                            update,
                            result.chunk.metadata.actors
                        )
                    if result.similarity_score > max_score-consolidate_threshold:
                        hashes_to_delete.append(result.chunk.chunk_hash)
                if hashes_to_delete:
                    for chunk_hash in hashes_to_delete:
                        success = await self.rag.delete_chunk(chunk_hash)
                        faultless = faultless and success
            else:
                print(f"\n{self.name}: Processing failed - no results found.")
                faultless = False
            if updated:
                print(f"\n{self.name}: Database update from {source} succeeded.")
            if hashes_to_delete:
                print(f"\n{self.name}: Consolidated {len(hashes_to_delete)+1} chunks.")


        self._requests.clear()
        return faultless

    async def request_summaries(self) -> None:
        if not self.connections:
            raise ValueError(f"{self.name}: No valid connections for summarization.")
        for connection in self.connections:
            self._ask(connection[0], "Summarize the knowledge you have.")