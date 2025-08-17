import asyncio
import json
import re

# from typing import override

from modules.llamacpp_api import LLMLink
from modules.dynamic_rag import DynamicRAGSystem, RetrievalResult
from modules.logutils import print_v
from modules.stringutils import extract_json_segment


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
        self._incoming_requests = {}  # Stores requests (keyed by source)
        self._incoming_replies = {}  # Stores replies (keyed by source)

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
                self._incoming_requests[message['source']] = message['content']
            elif message['role'] == 'reply':
                self._incoming_replies[message['source']] = message['content']
            else:
                raise AssertionError(f"{self.name}: Unknown message role: {message['role']}")

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
        schema = {'focus': self.task, 'knowledge': [*self._incoming_replies.values()]}
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
                print_v(f"{self.name}: Got reply from LLM: {raw_reply}", False)

                # Parse out model thinking
                # If there is no thinking block, pass the raw reply
                try:
                    reply = re.findall(r"<think>.*</think>\n(.*)", raw_reply, flags=re.DOTALL)[0].strip()
                except IndexError:
                    reply = raw_reply.strip()

                print_v(f"{self.name}: Extracted reply: {reply}", False)

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
            print_v(f"{self.name}: Got reply from LLM: {reply}", False)
            questions = json.loads(re.findall(r"\[\s*?\n*?\s*?{.*?}\s*?\n*?\s*?]", reply, flags=re.DOTALL)[-1])
            print_v(f"{self.name}: Extracted questions: {questions}", False)
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

class RAGRegion(BaseRegion):
    """
    A functional unit within a distributed system that communicates with other regions using Retrieval-Augmented Generation (RAG).

    Instead of relying on LLM-powered interactions, this region uses a dynamic RAG system to retrieve and update
    knowledge fragments. It processes incoming requests by retrieving relevant information from its knowledge base and
    replies with structured data fragments. Additionally, it handles incoming updates from other regions to consolidate
    and refine its knowledge database through similarity-based consolidation.

    Attributes:
        name (str): Unique identifier for the region
        task (str): Functional description of the region's purpose (e.g., "provide historical facts")
        rag (DynamicRAGSystem): Interface to the RAG system for retrieval and knowledge updates
        connections (dict[str, str]): Mapping of downstream region names to their task descriptions
        reply_with_actors (bool): Whether to include actor metadata in replies (default: False)
        inbox (asyncio.Queue): Queue for incoming messages (requests and replies)
        outbox (asyncio.Queue): Queue for outgoing messages (requests and replies)
        _incoming_requests (dict): Stores pending requests received from other regions (keyed by source region name)
        _incoming_replies (dict): Stores pending replies received from other regions (keyed for knowledge updates)
    """

    def __init__(self,
                 name: str,
                 task: str,
                 rag: DynamicRAGSystem,
                 connections: dict[str,str] | None,
                 reply_with_actors: bool = False
                 ):

        """
        Initialize a RAG-powered region with communication capabilities and knowledge management.

        Args:
            name (str): Unique identifier for the region
            task (str): Functional description of the region's purpose
            rag (DynamicRAGSystem): Interface to the RAG system for retrieval and updates
            connections (dict[str, str] | None): Mapping of region names to their task descriptions.
                If None, initializes with empty connections dictionary.
            reply_with_actors (bool, optional): Whether to include actor metadata in replies. Defaults to False.

        Note:
            - The region maintains separate queues for incoming/outgoing messages
            - Connections dictionary should contain {region_name: task_description} pairs
            - _incoming_requests stores incoming requests for reply generation
            - _incoming_replies stores incoming replies for knowledge database updates
        """
        super().__init__(name, task, connections)
        self.rag = rag
        self.reply_with_actors = reply_with_actors

    async def make_replies(self) -> bool:
        """
        Generate structured replies to all pending requests using RAG retrieval.

        Returns:
            bool: True if all replies were successfully generated, False otherwise

        Note:
            - Processes each pending request from _incoming_requests
            - Retrieves relevant knowledge fragments using RAG system
            - Constructs replies as JSON-formatted memory fragments
            - Includes actor metadata if reply_with_actors=True
            - Sends replies via _reply() method
            - Returns False if retrieval fails
            - Clears _incoming_requests after processing
        """
        faultless = True
        self._run_inbox()

        for source, question in self._incoming_requests.items():
            matches = None
            reply = ''
            try:
                await asyncio.sleep(0.5)
                matches = await self.rag.retrieve_similar(question, 0.5)
            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False
            if matches:
                for match in matches:
                    # CORRECTED: Dictionary key access with proper JSON formatting
                    reply += '{"memory_fragment": "' + match.chunk.content + '"'
                    if self.reply_with_actors:
                        actors = match.chunk.metadata.actors
                        reply += ', "actors": ' + json.dumps(actors)
                    reply += '},\n'
                if reply:
                    self._reply(source, reply)
            else:
                print(f"{self.name}: No matches found.")

        self._incoming_requests.clear()  # Clear processed queries
        return faultless

    async def make_updates(self, consolidate_threshold: float = 0.1):
        """
        Process incoming knowledge updates and consolidate similar fragments in the RAG database.

        Args:
            consolidate_threshold (float, optional): Maximum similarity difference for consolidation.
                Defaults to 0.1 (10% difference).

        Returns:
            bool: True if all updates were successfully processed, False otherwise

        Note:
            - Processes each incoming reply from _incoming_replies
            - Finds highest-similarity fragment to update
            - Consolidates fragments within similarity threshold
            - Deletes consolidated fragments to reduce redundancy
            - Logs update and consolidation results
            - Returns False if retrieval or update fails
            - Clears _incoming_replies after processing
        """
        faultless = True
        self._run_inbox()
        results: list[RetrievalResult] = []

        for source, update in self._incoming_replies.items():
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

        self._incoming_replies.clear()
        return faultless

    async def request_summaries(self) -> None:
        """
        Request knowledge summaries from all connected regions.

        Raises:
            ValueError: If no valid connections exist

        Note:
            - Sends a standardized "Summarize the knowledge you have" request
            - Targets all regions in connections dictionary
            - Uses _ask() method for non-blocking communication
            - Should be called periodically to refresh knowledge
        """
        if not self.connections:
            raise ValueError(f"{self.name}: No valid connections for summarization.")
        for connection in self.connections:
            self._ask(connection, "Summarize the knowledge you have.")