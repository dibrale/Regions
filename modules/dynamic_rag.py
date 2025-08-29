import asyncio
import pathlib
import uuid

import aiohttp
import sqlite3
import json
import time
import hashlib
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
import logging

from exceptions import *
from utils import _chunk_text

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


@dataclass
class ChunkMetadata:
    """Metadata associated with document chunks.

    Attributes:
        timestamp (int): Unix timestamp when the chunk was created
        actors (List[str]): List of actor identifiers associated with the chunk
        chunk_id (Optional[str]): Unique identifier for the chunk within a document
        document_id (Optional[str]): Unique identifier for the source document
    """
    timestamp: int
    actors: List[str]
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None


@dataclass
class DocumentChunk:
    """Document chunk containing text content and associated metadata.

    Attributes:
        content (str): The text content of the chunk
        metadata (ChunkMetadata): Metadata describing the chunk
        embedding (Optional[List[float]]): Vector embedding of the content
        chunk_hash (Optional[str]): SHA-256 hash of the content (used as unique identifier)
    """
    content: str
    metadata: ChunkMetadata
    embedding: Optional[List[float]] = None
    chunk_hash: Optional[str] = None


@dataclass
class RetrievalResult:
    """Result from similarity search operations.

    Attributes:
        chunk (DocumentChunk): The retrieved document chunk
        similarity_score (float): Score indicating similarity to the query (range: -1 to 1)
    """
    chunk: DocumentChunk
    similarity_score: float


class RateLimiter:
    """Rate limiter enforcing minimum interval between database operations.

    Ensures at least `min_interval` seconds elapse between consecutive operations
    by sleeping when necessary (does not raise errors). Uses asyncio lock to prevent
    concurrent access violations.

    Attributes:
        min_interval (float): Minimum time interval between operations in seconds
        last_request_time (float): Timestamp of last operation
    """

    def __init__(self, min_interval: float = 0.1):
        self.min_interval = min_interval
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire access to the database with enforced minimum interval.

        If less than `min_interval` seconds have passed since the last operation,
        sleeps for the remaining time. Safe for concurrent use.
        """
        async with self._lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            # Sleep if needed to enforce minimum interval
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)

            self.last_request_time = time.time()


class EmbeddingClient:
    """Async client for OpenAI-compatible embedding servers (e.g., llama.cpp).

    Must be used as an async context manager to handle session lifecycle.

    Attributes:
        base_url (str): Base URL of the embedding server
        model (str): Embedding model name to use
        session (Optional[aiohttp.ClientSession]): HTTP session (managed automatically)
    """

    def __init__(self, base_url: str = "http://localhost:8080", model: str = "text-embedding-ada-002"):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for input text.

        Requires use as async context manager. Handles server errors and
        response validation.

        Args:
            text (str): Input text to embed

        Returns:
            List[float]: Generated embedding vector

        Raises:
            RuntimeError: If not used as context manager
            HTTPError: For non-200 responses or network issues
            SchemaMismatchError: If response format is invalid
        """
        if not self.session:
            raise RuntimeError("EmbeddingClient must be used as async context manager")

        url = f"{self.base_url}/v1/embeddings"
        logging.info(f"Sending embedding request for text length {len(text)} to '{url}'")
        payload = {
            "model": self.model,
            "input": text
        }

        try:
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise HTTPError(response.status, error_text)

                result = await response.json()

                # Validate response structure
                if "data" not in result or not result["data"]:
                    raise SchemaMismatchError("Invalid embedding response format")

                logging.info(f"Successfully received embedding for text of length {len(text)}")
                return result["data"][0]["embedding"]

        except SchemaMismatchError:
            raise
        except aiohttp.ClientError as e:
            raise HTTPError(0, f"Connection error: {str(e)}")
        except asyncio.TimeoutError as e:
            raise HTTPError(0, f"Timeout error: {str(e)}")
        except Exception as e:
            raise HTTPError(0, f"Network error: {str(e)}")


class DatabaseManager:
    """SQLite database manager with integrated rate limiting.

    Handles storage, retrieval, and deletion of document chunks while enforcing
    minimum query intervals via RateLimiter.

    Attributes:
        db_path (str): Path to SQLite database file
        rate_limiter (RateLimiter): Rate limiting instance
    """

    def __init__(self, db_path: str = "rag_storage.db"):
        self.db_path = db_path
        self.db_name = pathlib.PurePath(db_path).name
        self.rate_limiter = RateLimiter()
        self._init_database()

    def _init_database(self):
        """Initialize database schema with required tables and indexes.

        Creates 'chunks' table with columns for content, embedding, metadata,
        and indexes for hash and timestamp.

        Raises:
            DatabaseNotAccessibleError: If initialization fails
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create chunks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_hash TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    timestamp INTEGER NOT NULL,
                    actors TEXT NOT NULL,
                    chunk_id TEXT,
                    document_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for efficient queries
            cursor.execute("""
                           CREATE INDEX IF NOT EXISTS idx_chunk_hash ON chunks(chunk_hash)
                           """)
            cursor.execute("""
                           CREATE INDEX IF NOT EXISTS idx_timestamp ON chunks(timestamp)
                           """)

            conn.commit()
            conn.close()

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"Failed to initialize database: {str(e)}")

        logging.info(f"Database initialized successfully at '{self.db_path}'")

    async def store_chunk(self, chunk: DocumentChunk) -> bool:
        """Store a document chunk in the database.

        Handles serialization of embedding and actors. Automatically generates
        chunk_hash if missing. Enforces rate limiting via RateLimiter.

        Args:
            chunk (DocumentChunk): Chunk to store

        Returns:
            bool: True if storage succeeded

        Raises:
            DatabaseNotAccessibleError: If database operation fails
        """
        await self.rate_limiter.acquire()

        try:
            # Generate chunk hash if not provided
            if not chunk.chunk_hash:
                chunk.chunk_hash = hashlib.sha256(chunk.content.encode()).hexdigest()

            logging.info(f"{self.db_name}: Storing document chunk with hash: {chunk.chunk_hash}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Serialize embedding and actors
            embedding_blob = json.dumps(chunk.embedding).encode()
            actors_json = json.dumps(chunk.metadata.actors)

            cursor.execute("""
                INSERT OR REPLACE INTO chunks 
                (chunk_hash, content, embedding, timestamp, actors, chunk_id, document_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                chunk.chunk_hash,
                chunk.content,
                embedding_blob,
                chunk.metadata.timestamp,
                actors_json,
                chunk.metadata.chunk_id,
                chunk.metadata.document_id
            ))

            conn.commit()
            conn.close()
            return True

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"{self.db_name}: Failed to store chunk: {str(e)}")

    async def get_all_chunks(self) -> List[DocumentChunk]:
        """Retrieve all stored document chunks.

        Handles deserialization of embedding and actors. Enforces rate limiting.

        Returns:
            List[DocumentChunk]: All stored chunks

        Raises:
            DatabaseNotAccessibleError: If retrieval fails
        """
        await self.rate_limiter.acquire()

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                           SELECT chunk_hash, content, embedding, timestamp, actors, chunk_id, document_id
                           FROM chunks
                           """)

            chunks = []
            for row in cursor.fetchall():
                chunk_hash, content, embedding_blob, timestamp, actors_json, chunk_id, document_id = row

                # Deserialize data
                embedding = json.loads(embedding_blob.decode())
                actors = json.loads(actors_json)

                metadata = ChunkMetadata(
                    timestamp=timestamp,
                    actors=actors,
                    chunk_id=chunk_id,
                    document_id=document_id
                )

                chunk = DocumentChunk(
                    content=content,
                    metadata=metadata,
                    embedding=embedding,
                    chunk_hash=chunk_hash
                )
                chunks.append(chunk)

            conn.close()
            logging.info(f"{self.db_name}: Retrieved all stored document chunks")
            return chunks

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"{self.db_name}: Failed to retrieve chunks. {str(e)}")

    async def delete_chunk(self, chunk_hash: str) -> bool:
        """Delete a chunk by its SHA-256 hash.

        Enforces rate limiting before deletion.

        Args:
            chunk_hash (str): SHA-256 hash of the chunk to delete

        Returns:
            bool: True if chunk was deleted (false if not found)

        Raises:
            DatabaseNotAccessibleError: If deletion fails
        """
        await self.rate_limiter.acquire()

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM chunks WHERE chunk_hash = ?", (chunk_hash,))
            deleted = cursor.rowcount > 0

            conn.commit()
            conn.close()
            logging.info(f"{self.db_name}: Deleted document chunk with hash: {chunk_hash}")
            return deleted

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"{self.db_name}: Failed to delete chunk. {str(e)}")


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Measures vector orientation (range: -1 to 1), with 1 indicating identical direction.
    Returns 0.0 for zero-magnitude vectors or mismatched dimensions.

    Args:
        vec1 (List[float]): First vector
        vec2 (List[float]): Second vector

    Returns:
        float: Similarity score between -1 and 1
    """
    if len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = sum(a * a for a in vec1) ** 0.5
    magnitude2 = sum(b * b for b in vec2) ** 0.5

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


class DynamicRAGSystem:
    """Core system for document storage, indexing, and retrieval operations.

    Manages full lifecycle of document chunks including:
    - Text chunking with configurable size/overlap
    - Embedding generation via external server
    - Database storage with rate limiting
    - Cosine similarity and actor-based retrieval
    - System statistics collection

    Attributes:
        db_manager (DatabaseManager): Database interaction handler
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

        logging.info(f"{self.db_name}: Deleting chunk with hash {chunk_hash}")
        deleted = await self.db_manager.delete_chunk(chunk_hash)
        if not deleted:
            logger.warning(f"{self.db_name}: Chunk {chunk_hash} could not be deleted")
            return False
        else:
            logger.info(f"{self.db_name}: Deleted chunk {chunk_hash}")
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
        logging.info(f"Generating new embedding for updated chunk")
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


if __name__ == "__main__":
    # Example usage
    async def main():
        rag_system = DynamicRAGSystem(embedding_server_url="http://localhost:10000",
                                      embedding_model="nomic-embed-text:latest")

        try:
            # Store a document
            chunk_hashes = await rag_system.store_document(
                content="This is a sample document about machine learning and artificial intelligence.",
                actors=["user1", "system"],
                document_id="doc_001"
            )
            print(f"Stored document with {len(chunk_hashes)} chunks")
            await asyncio.sleep(0.5)

            # Retrieve similar content
            results = await rag_system.retrieve_similar(
                query="machine learning",
                similarity_threshold=0.5,
                max_results=3
            )

            print(f"Found {len(results)} similar chunks:")
            for result in results:
                print(f"  Similarity: {result.similarity_score:.3f}")
                print(f"  Content: {result.chunk.content[:100]}...")
                print(f"  Actors: {result.chunk.metadata.actors}")
                print()

            # Get system stats
            await asyncio.sleep(0.5)
            stats = await rag_system.get_stats()
            print("System stats:", stats)

        except RAGException as e:
            print(f"RAG Error {e.code}: {e.description}")
        except Exception as e:
            print(f"Unexpected error: {e}")

        # print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")


    # Run example
    asyncio.run(main())