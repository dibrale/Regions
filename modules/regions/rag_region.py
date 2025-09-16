import json
import logging

from regions.base_region import BaseRegion
from modules.dynamic_rag import DynamicRAGSystem, RetrievalResult


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
                 reply_with_actors: bool = False,
                 threshold: float = 0.5,
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
            threshold (float, optional): Minimum similarity score. Defaults to 0.5.

        Note:
            - The region maintains separate queues for incoming/outgoing messages
            - Connections dictionary should contain {region_name: task_description} pairs
            - _incoming_requests stores incoming requests for reply generation
            - _incoming_replies stores incoming replies for knowledge database updates
        """
        super().__init__(name, task, connections)
        self.rag = rag
        self.reply_with_actors = reply_with_actors
        self.threshold = float(threshold)

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

        if self._incoming_requests.empty():
            logging.info(f"{self.name}: No incoming requests to process.")
            return True
        while not self._incoming_requests.empty():
            request = self._incoming_requests.get_nowait()
            source, question = request.popitem()

            matches = None
            reply = ''
            try:
                matches = await self.rag.retrieve_similar(question, self.threshold)
            except Exception as e:
                logging.warning(f"{self.name}: Processing failed. {e.args}")
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
                    self.connections.update({source: 'Previously replied to'})
            else:
                logging.info(f"{self.name}: No matches found.")

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

        if self._incoming_replies.empty():
            logging.info(f"{self.name}: No incoming replies to process.")
            return True

        while not self._incoming_replies.empty():
            request = self._incoming_replies.get_nowait()
            source, update = request.popitem()
            updated = False
            hashes_to_delete = []

            try:
                results = await self.rag.retrieve_similar(update)
            except Exception as e:
                logging.warning(f"{self.name}: Processing failed. {e.args}")
                faultless = False

            if results:
                max_score = max(result.similarity_score for result in results)

                for result in results:
                    if result.similarity_score == max_score and not updated:
                        updated = await self.rag.update_chunk(
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
                logging.info(f"\n{self.name}: Processing failed - no results found.")
                faultless = False
            if updated:
                logging.info(f"\n{self.name}: Database update from {source} succeeded.")
            if hashes_to_delete:
                logging.info(f"\n{self.name}: Consolidated {len(hashes_to_delete)+1} chunks.")

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
