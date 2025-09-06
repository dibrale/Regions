import asyncio
import pathlib
import re
import uuid

import json
import time
from typing import List, Dict, Any, Optional, Union
import logging

from database_manager import DatabaseManager, RetrievalResult, ChunkMetadata, DocumentChunk
from embedding_client import EmbeddingClient
from exceptions import *
from utils import _chunk_text, cosine_similarity

"""
Dynamic RAG (Retrieval-Augmented Generation) Storage, Indexing, and Retrieval System.

This module implements a comprehensive framework for building a RAG system with:
- Asynchronous operations using asyncio and aiohttp for efficient I/O handling
- Integration with llama.cpp embedding server via OpenAI-compatible API
- SQLite database backend with built-in rate limiting
- Dynamic incremental indexing capabilities
- Actor-based filtering and similarity search
- Comprehensive error handling with standardized error codes

The system supports document chunking, embedding generation, storage, and retrieval
with configurable parameters for chunk size, overlap, and similarity thresholds.
"""

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DynamicRAGSystem:
    """Core system for document storage, indexing, and retrieval operations.

    Manages full lifecycle of document chunks including:
    - Text chunking with configurable size/overlap
    - Embedding generation via external server
    - Database storage with rate limiting
    - Cosine similarity and actor-based retrieval
    - System statistics collection

    Attributes:
        db_manager (database_manager.DatabaseManager): Database interaction handler
        embedding_server_url (str): URL of embedding server
        embedding_model (str): Embedding model name
        name (str): Unique system identifier
        _default_chunk_size (int): Default chunk size in characters
        _default_overlap (int): Default chunk overlap in characters
        _default_max_results (int): Default maximum retrieval results
    """

    def __init__(self,
                 db_path: str = "rag_storage.db",
                 embedding_server_url: str = "http://localhost:8080",
                 embedding_model: str = "text-embedding-ada-002",
                 name: Optional[str] = None,
                 chunk_size: int = 512,
                 overlap: int = 50,
                 max_results: int = 5,
                 ) -> None:
        """Initialize the Dynamic RAG system.

        Args:
            db_path (str): Path to SQLite database (default: 'rag_storage.db')
            embedding_server_url (str): Embedding server URL (default: localhost:8080)
            embedding_model (str): Model name for embeddings (default: text-embedding-ada-002)
            name (Optional[str]): System identifier (generates UUID if None)
            chunk_size (int): Default chunk size in characters (>0)
            overlap (int): Default chunk overlap in characters (>=0)
            max_results (int): Default maximum retrieval results (>=1)

        Raises:
            ValueError: If chunk_size <= 0, overlap < 0, or max_results < 1
        """
        self.db_manager = DatabaseManager(db_path)
        self.db_name = pathlib.PurePath(db_path).name
        self.embedding_server_url = embedding_server_url
        self.embedding_model = embedding_model
        if name is None:
            self.name = str(uuid.uuid4())
        else:
            self.name = name
        self._default_chunk_size = chunk_size
        self._default_overlap = overlap
        self._default_max_results = max_results

    def save(self, path: str) -> None:
        """Save current configuration to a JSON file."""
        pure_path = pathlib.PurePath(path)
        if self.name:
            logging.info(f"Saving '{self.name}' configuration to {pure_path}")
        else:
            logging.info(f"Saving configuration to {pure_path}")
        try:
            with open(str(pure_path), 'w') as f:
                json.dump({
                    "db_path": self.db_manager.db_path,
                    "embedding_server_url": self.embedding_server_url,
                    "embedding_model": self.embedding_model,
                    "name": self.name,
                    "chunk_size": self._default_chunk_size,
                    "overlap": self._default_overlap,
                    "max_results": self._default_max_results
                }, f, indent=4)
            logging.info(f"{self.db_name}: RAG configuration saved to {pure_path}")
        except IOError as e:
            logging.error(f"{self.db_name}: Failed to save RAG configuration: {str(e)}")

    @classmethod
    def load(cls, path: str) -> 'DynamicRAGSystem | None':
        """Load a Dynamic RAG system from a JSON file."""
        pure_path = pathlib.PurePath(path)
        logging.info(f"{cls.__name__}: Loading RAG configuration from {pure_path.name}")
        try:
            with open(str(pure_path)) as f:
                config = json.load(f)
                if config.get('name') is not None:
                    logging.info(f"{cls.__name__}: Loaded '{config['name']}' RAG configuration")
                else:
                    logging.info(f"{cls.__name__}: Loaded RAG configuration")
                return cls(
                    db_path=config['db_path'],
                    embedding_server_url=config['embedding_server_url'],
                    embedding_model=config['embedding_model'],
                    name=config.get('name', None),
                    chunk_size=config['chunk_size'],
                    overlap=config['overlap'],
                    max_results=config['max_results']
                )
        except IOError as e:
            logging.error(f"{cls.__name__}: Failed to load RAG configuration: {str(e)}")

    async def store_document(self,
                             content: str,
                             actors: List[str],
                             document_id: Optional[str] = None,
                             chunk_size: Optional[int] = None,
                             overlap: Optional[int] = None) -> List[str]:
        """Store a document by splitting into chunks and generating embeddings.

        Automatically generates chunk_hash from content. Enforces 0.5s delay between
        consecutive chunk storage operations to comply with database rate limiting.

        Args:
            content (str): Full document text
            actors (List[str]): Actor identifiers associated with the document
            document_id (Optional[str]): Unique document identifier
            chunk_size (Optional[int]): Chunk size override (uses default if None)
            overlap (Optional[int]): Chunk overlap override (uses default if None)

        Returns:
            List[str]: SHA-256 hashes of stored chunks (generated from content)

        Raises:
            HTTPError: If embedding server communication fails
            DatabaseNotAccessibleError: If database storage fails
        """
        chunk_hashes = []

        # Use defaults if overrides not provided
        chunk_size = chunk_size or self._default_chunk_size
        overlap = overlap or self._default_overlap

        # Generate chunks
        chunks = _chunk_text(content, chunk_size, overlap)

        async with EmbeddingClient(self.embedding_server_url, self.embedding_model) as embedding_client:
            for i, chunk_content in enumerate(chunks):
                # Generate embedding
                embedding = await embedding_client.get_embedding(chunk_content)

                # Create metadata
                metadata = ChunkMetadata(
                    timestamp=int(time.time()),
                    actors=actors,
                    chunk_id=f"{document_id or 'doc'}_{i}" if document_id else None,
                    document_id=document_id
                )

                # Create chunk
                chunk = DocumentChunk(
                    content=chunk_content,
                    metadata=metadata,
                    embedding=embedding
                )

                # Store chunk (chunk_hash auto-generated if missing)
                await self.db_manager.store_chunk(chunk)
                chunk_hashes.append(chunk.chunk_hash)

                # Add delay between chunks to comply with rate limiting
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)

        logging.info(f"{self.db_name}: Document stored with {len(chunk_hashes)} chunks")
        return chunk_hashes

    async def store(self, data: str | list[str] | dict | list[dict]) -> bool:
        """
        Store data from files in the RAG database. Accepts multiple input types:
            * Single string representing a file path
            * List of strings, each representing a file path
            * Dictionary with path strings for keys and actor strings or lists for values
            * A list of dictionaries, each with a single 'path' key and actor string or list for values

        :param data: Files to store
        :return: True in case of valid input with no warnings, False otherwise

        Side Effects:
            * Raises a ValueError in case of invalid input format
            * Logs a warning message if any file cannot be processed
            * Logs a warning for each document that failed to store
        """
        doc_paths: list[str] = []
        actors: list = []
        stored_chunks = []
        success: list[bool] = []

        if isinstance(data, dict):
            length = len(data)
            doc_paths = [str(path) for path in data.keys()]
            actors = [str(actor_list) for actor_list in data.values()]
        elif isinstance(data, list):
            length = len(data)
            for doc in data:
                if isinstance(doc, dict):
                    doc_paths.append(''.join([str(path) for path in doc.keys()]))
                    actors.append(''.join([str(path) for path in doc.values()]))
                if isinstance(doc, str):
                    doc_paths.append(doc)
                    actors.append([''])
        elif isinstance(data, str):
            length = 1
            doc_paths = [data]
            actors = [['']]
        else:
            try:
                raise ValueError(f"Unsupported data type: {type(data)}")
            except Exception as e:
                logging.error(f"{self.db_name}: {e}")
            finally:
                return False

        logging.info(f"{self.db_name}: Storing {length} documents...")
        for index in range(0, len(doc_paths)):
            pure_path = pathlib.PurePath(doc_paths[index])
            try:
                with open(doc_paths[index]) as f:
                    lines = f.readlines()
                    content = ''.join(lines)
            except FileNotFoundError:
                logging.warning(f"{self.db_name}: Document '{pure_path.name}' not found. Skipping.")
                success.append(False)
                continue
            except IOError as e:
                logging.warning(f"{self.db_name}: Failed to read document '{pure_path.name}': {str(e)}")
                success.append(False)
                continue

            if isinstance(actors[index], list):
                actor_list = actors[index]
            elif isinstance(actors[index], str):
                actor_list = re.split(r".\s",actors[index])
            else:
                actor_list = [str(actors[index])]

            try:
                chunk_hashes = await self.store_document(
                    content=content,
                    actors=actor_list
                )
                stored_chunks.extend(chunk_hashes)
                success.append(True)
            except Exception as e:
                logging.error(f"{self.db_name}: Failed to store document '{pure_path.name}': {str(e)}")
                success.append(False)
                continue
        logging.info(f"{self.name}: Total chunks stored: {len(stored_chunks)}")

        failures = length - sum(success)
        logging.info(f"{self.name}: Documents stored: {sum(success)}/{length}")
        if failures:
            logging.warning(f"{self.db_name}: {failures} document(s) failed to store.")
            return False
        return True

    async def retrieve_similar(self,
                               query: str,
                               similarity_threshold: float = 0.7,
                               max_results: Optional[int] = None) -> List[RetrievalResult]:
        """Retrieve chunks similar to query using cosine similarity.

        Cosine similarity (range: -1 to 1) measures vector orientation, with 1
        indicating identical direction. Filters results below threshold.

        Args:
            query (str): Search query text
            similarity_threshold (float): Minimum similarity score (0.0-1.0)
            max_results (Optional[int]): Maximum results to return

        Returns:
            List[RetrievalResult]: Sorted list of matching chunks (highest similarity first)

        Raises:
            NoMatchingEntryError: If no chunks meet threshold
            HTTPError: If embedding generation fails
        """
        max_results = max_results or self._default_max_results

        # Generate query embedding
        async with EmbeddingClient(self.embedding_server_url, self.embedding_model) as embedding_client:
            query_embedding = await embedding_client.get_embedding(query)

        # Get all chunks from database
        all_chunks = await self.db_manager.get_all_chunks()

        # Calculate similarities
        results = []
        for chunk in all_chunks:
            if chunk.embedding:
                similarity = cosine_similarity(query_embedding, chunk.embedding)
                if similarity >= similarity_threshold:
                    results.append(RetrievalResult(chunk=chunk, similarity_score=similarity))

        # Sort by similarity and limit results
        results = await self.sort_results(results, similarity_threshold,'cosine similarity', max_results)
        if not results:
            raise NoMatchingEntryError(similarity_threshold)
        return results

    async def sort_results(self, results: List[RetrievalResult], similarity: float, method_name: str | None, max_results: int = 5) -> List[RetrievalResult]:
        """Sort retrieved results."""
        # Sort by similarity and limit results
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        results = results[:max_results]

        if not results:
            error_msg = f"{self.db_name}: No chunks found. Similarity threshold: {similarity:.2f}"
            if method_name:
                error_msg += f" ({method_name})"
            logging.error(error_msg)
            return []

        log_msg = f"{self.db_name}: Retrieved {len(results)} chunks. Similarity threshold: {similarity:.2f}"
        if method_name:
            log_msg += f" ({method_name})"
        logging.info(log_msg)
        return results


    async def retrieve_by_actor(self,
                                actors: List[str],
                                similarity_threshold: float = 0.5,
                                max_results: int = 5) -> List[RetrievalResult]:
        """Retrieve chunks based on actor membership similarity.

        Uses metric: similarity = matched_actors / (len(actors) + |len(actors) - len(chunk_actors)|),
        which penalizes discrepancies in actor list lengths and content.

        Args:
            actors (List[str]): Target actor list
            similarity_threshold (float): Minimum similarity score
            max_results (int): Maximum results to return

        Returns:
            List[RetrievalResult]: Sorted list of matching chunks (highest similarity first)

        Raises:
            NoMatchingEntryError: If no chunks meet threshold
        """
        # Get all chunks from database
        all_chunks = await self.db_manager.get_all_chunks()

        # Calculate similarities
        results = []
        for chunk in all_chunks:
            actors_matched = len(set(actors).intersection(chunk.metadata.actors))
            similarity = actors_matched / (len(actors) + abs(len(actors) - len(chunk.metadata.actors)))

            if similarity >= similarity_threshold:
                results.append(RetrievalResult(chunk=chunk, similarity_score=similarity))

        # Sort by actor and limit results
        results = await self.sort_results(results, similarity_threshold, 'actor similarity', max_results)
        if not results:
            raise NoMatchingEntryError(similarity_threshold)
        return results

    async def delete_chunk(self, chunk: Union[DocumentChunk, str]) -> bool:
        """Delete a chunk by hash.

        Accepts either DocumentChunk object or SHA-256 hash string.

        Args:
            chunk (Union[DocumentChunk, str]): Chunk object or hash to delete

        Returns:
            bool: True if deletion succeeded, False if chunk not found

        Raises:
            TypeError: If unsupported chunk type provided
        """
        if isinstance(chunk, DocumentChunk):
            chunk_hash = chunk.chunk_hash
        elif isinstance(chunk, str):
            chunk_hash = chunk
        else:
            raise TypeError("chunk must be DocumentChunk or str")

        logging.debug(f"{self.db_name}: Deleting chunk with hash {chunk_hash}")
        deleted = await self.db_manager.delete_chunk(chunk_hash)
        if not deleted:
            logging.warning(f"{self.db_name}: Chunk {chunk_hash} could not be deleted")
            return False
        else:
            logging.info(f"{self.db_name}: Deleted chunk {chunk_hash}")
            return True

    async def update_chunk(self, chunk_hash: str, new_content: str, actors: List[str]) -> bool:
        """Update chunk content through delete-then-store operation.

        Includes 0.5s rate limiting delay between operations to comply with database constraints.

        Args:
            chunk_hash (str): SHA-256 hash of chunk to update
            new_content (str): New text content
            actors (List[str]): New actor identifiers

        Returns:
            bool: True if update succeeded

        Raises:
            DatabaseNotAccessibleError: If storage fails
            HTTPError: If embedding generation fails
        """
        # Delete old chunk
        deleted = await self.delete_chunk(chunk_hash)
        if not deleted:
            return False

        # Generate new embedding
        logging.debug(f"Generating new embedding for updated chunk")
        async with EmbeddingClient(self.embedding_server_url, self.embedding_model) as embedding_client:
            embedding = await embedding_client.get_embedding(new_content)

        # Create updated chunk
        metadata = ChunkMetadata(
            timestamp=int(time.time()),
            actors=actors
        )

        chunk = DocumentChunk(
            content=new_content,
            metadata=metadata,
            embedding=embedding,
            chunk_hash=chunk_hash
        )

        # Store updated chunk
        await self.db_manager.store_chunk(chunk)
        logging.info(f"{self.db_name}: Updated chunk with hash {chunk_hash}")
        return True

    async def get_stats(self) -> Dict[str, Any]:
        """Get system statistics.

        Returns:
            Dict[str, Any]: Statistics including:
                - 'total_chunks': Total stored chunks
                - 'unique_documents': Count of unique document IDs
                - 'unique_actors': Count of unique actors
                - 'actors': List of all unique actor identifiers
        """
        chunks = await self.db_manager.get_all_chunks()

        total_chunks = len(chunks)
        unique_documents = len(set(chunk.metadata.document_id for chunk in chunks if chunk.metadata.document_id))
        unique_actors = set()
        for chunk in chunks:
            unique_actors.update(chunk.metadata.actors)

        return {
            "total_chunks": total_chunks,
            "unique_documents": unique_documents,
            "unique_actors": len(unique_actors),
            "actors": list(unique_actors)
        }