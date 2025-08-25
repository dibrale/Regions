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

import asyncio
import uuid

import aiohttp
import sqlite3
import json
import time
import hashlib
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

from _pytest.logging import caplog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Error codes
class ErrorCodes:
    NO_MATCHING_ENTRY = 1001
    DATABASE_NOT_ACCESSIBLE = 1002
    SERVICE_UNAVAILABLE = 1003
    SCHEMA_MISMATCH = 1004
    HTTP_ERROR = 1005

# Custom exceptions
class RAGException(Exception):
    """Base exception for RAG system"""
    def __init__(self, code: int, description: str):
        self.code = code
        self.description = description
        super().__init__(f"Error {code}: {description}")

class NoMatchingEntryError(RAGException):
    def __init__(self, threshold: float):
        super().__init__(ErrorCodes.NO_MATCHING_ENTRY, 
                        f"No matching entry found for similarity threshold {threshold}")

class DatabaseNotAccessibleError(RAGException):
    def __init__(self, details: str = ""):
        super().__init__(ErrorCodes.DATABASE_NOT_ACCESSIBLE, 
                        f"Database not accessible: {details}")

class ServiceUnavailableError(RAGException):
    def __init__(self, details: str = "Rate limit exceeded"):
        super().__init__(ErrorCodes.SERVICE_UNAVAILABLE, 
                        f"Service unavailable: {details}")

class SchemaMismatchError(RAGException):
    def __init__(self, details: str):
        super().__init__(ErrorCodes.SCHEMA_MISMATCH, 
                        f"Schema mismatch: {details}")

class HTTPError(RAGException):
    def __init__(self, status_code: int, details: str = ""):
        super().__init__(ErrorCodes.HTTP_ERROR, 
                        f"HTTP error {status_code}: {details}")

@dataclass
class ChunkMetadata:
    """Metadata for document chunks"""
    timestamp: int
    actors: List[str]
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None

@dataclass
class DocumentChunk:
    """Document chunk with content and metadata"""
    content: str
    metadata: ChunkMetadata
    embedding: Optional[List[float]] = None
    chunk_hash: Optional[str] = None

@dataclass
class RetrievalResult:
    """Result from similarity search"""
    chunk: DocumentChunk
    similarity_score: float

class RateLimiter:
    """Rate limiter for database operations (500ms between queries)"""
    
    def __init__(self, min_interval: float = 0.5):
        self.min_interval = min_interval
        self.last_request_time = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time

            # Wait if needed instead of raising error
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)

            self.last_request_time = time.time()

class EmbeddingClient:
    """Async client for llama.cpp embedding server with OpenAI-compatible API"""
    
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
        """Get embedding for text using OpenAI-compatible API

        Args:
            text (str): Input text to generate embedding for

        Returns:
            List[float]: Generated embedding vector

        Raises:
            HTTPError: If server returns non-200 status
            SchemaMismatchError: If response format is invalid
            RuntimeError: If client not used as context manager
        """
        if not self.session:
            raise RuntimeError("EmbeddingClient must be used as async context manager")

        url = f"{self.base_url}/v1/embeddings"
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

                # Extract embedding from OpenAI-compatible response
                if "data" not in result or not result["data"]:
                    raise SchemaMismatchError("Invalid embedding response format")

                return result["data"][0]["embedding"]

        except SchemaMismatchError:
            # Re-raise schema mismatch errors as-is
            raise
        except aiohttp.ClientError as e:
            raise HTTPError(0, f"Connection error: {str(e)}")
        except asyncio.TimeoutError as e:
            raise HTTPError(0, f"Timeout error: {str(e)}")
        except Exception as e:
            raise HTTPError(0, f"Network error: {str(e)}")

class DatabaseManager:
    """SQLite database manager with rate limiting"""

    def __init__(self, db_path: str = "rag_storage.db"):
        self.db_path = db_path
        self.rate_limiter = RateLimiter()
        self._init_database()

    def _init_database(self):
        """Initialize database schema"""
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

            # Create index for similarity search optimization
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

    async def store_chunk(self, chunk: DocumentChunk) -> bool:
        """Store a document chunk with rate limiting

        Args:
            chunk (DocumentChunk): Chunk object to store

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
            raise DatabaseNotAccessibleError(f"Failed to store chunk: {str(e)}")

    async def get_all_chunks(self) -> List[DocumentChunk]:
        """Retrieve all chunks from database

        Returns:
            List[DocumentChunk]: All stored chunks

        Raises:
            DatabaseNotAccessibleError: If database operation fails
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
            return chunks

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"Failed to retrieve chunks: {str(e)}")

    async def delete_chunk(self, chunk_hash: str) -> bool:
        """Delete a chunk by hash

        Args:
            chunk_hash (str): SHA-256 hash of chunk to delete

        Returns:
            bool: True if deletion succeeded

        Raises:
            DatabaseNotAccessibleError: If database operation fails
        """
        await self.rate_limiter.acquire()

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM chunks WHERE chunk_hash = ?", (chunk_hash,))
            deleted = cursor.rowcount > 0

            conn.commit()
            conn.close()
            return deleted

        except sqlite3.Error as e:
            raise DatabaseNotAccessibleError(f"Failed to delete chunk: {str(e)}")

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors

    Cosine similarity measures vector orientation (range: -1 to 1), with 1 indicating
    identical direction. Commonly used for embedding comparisons in RAG systems.

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
    """Core class managing document storage and retrieval operations.

    Handles the full lifecycle of document chunks including:
    - Text chunking with configurable size/overlap
    - Embedding generation via external server
    - Database storage with rate limiting
    - Cosine similarity and actor-based retrieval
    - System statistics collection

    Attributes:
        db_manager (DatabaseManager): Manages database interactions
        embedding_server_url (str): URL of embedding server (default: localhost:8080)
        embedding_model (str): Embedding model name (default: text-embedding-ada-002)
        name (str): Unique system identifier (UUID if not provided)
        _default_chunk_size (int): Default chunk size in characters (>0, default: 512)
        _default_overlap (int): Default chunk overlap in characters (>=0, default: 50)
        _default_max_results (int): Default max retrieval results (>=1, default: 5)
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
        """Initializes the Dynamic RAG system with configurable parameters.

        Args:
            db_path (str): Path to SQLite database file (default: 'rag_storage.db')
            embedding_server_url (str): URL of embedding server (default: 'http://localhost:8080')
            embedding_model (str): Embedding model name (default: 'text-embedding-ada-002')
            name (Optional[str]): Unique system identifier (default: generates UUID)
            chunk_size (int): Size of text chunks in characters (>0, default: 512)
            overlap (int): Overlap between chunks in characters (>=0, default: 50)
            max_results (int): Maximum retrieval results (>=1, default: 5)

        Raises:
            ValueError: If chunk_size <= 0, overlap < 0, or max_results < 1
        """
        self.db_manager = DatabaseManager(db_path)
        self.embedding_server_url = embedding_server_url
        self.embedding_model = embedding_model
        if name is None:
            self.name = str(uuid.uuid4())
        else:
            self.name = name
        self._default_chunk_size = chunk_size
        self._default_overlap = overlap
        self._default_max_results = max_results

    async def store_document(self,
                             content: str,
                             actors: List[str],
                             document_id: Optional[str] = None,
                             chunk_size: Optional[int] = None,
                             overlap: Optional[int] = None) -> List[str]:
        """Stores a document by splitting into chunks and generating embeddings.

        Args:
            content (str): Full document text content
            actors (List[str]): Actor identifiers associated with the document
            document_id (Optional[str]): Unique document identifier (default: None)
            chunk_size (Optional[int]): Chunk size in characters (default: 512)
            overlap (Optional[int]): Chunk overlap in characters (default: 50)

        Returns:
            List[str]: SHA-256 hashes of stored chunks, usable for later retrieval/deletion

        Raises:
            HTTPError: If embedding server communication fails
            DatabaseNotAccessibleError: If database storage fails
            ServiceUnavailableError: If rate limiting is exceeded
        """
        chunk_hashes = []

        # Populate size and overlap
        chunk_size = chunk_size or self._default_chunk_size
        overlap = overlap or self._default_overlap

        # Generate chunks
        chunks = self._chunk_text(content, chunk_size, overlap)

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

                # Store chunk with rate limiting handled by database manager
                await self.db_manager.store_chunk(chunk)
                chunk_hashes.append(chunk.chunk_hash)

                # Add delay between chunks to respect rate limiting
                if i < len(chunks) - 1:  # Don't wait after the last chunk
                    await asyncio.sleep(0.5)

        logging.info(f"Document stored with {len(chunk_hashes)} chunks")
        return chunk_hashes

    async def retrieve_similar(self,
                             query: str,
                             similarity_threshold: float = 0.7,
                             max_results: Optional[int] = None) -> List[RetrievalResult]:
        """Retrieves chunks similar to query using cosine similarity.

        Cosine similarity (range: -1 to 1) measures vector orientation in embedding space,
        with 1 indicating identical direction. Default threshold=0.7 filters weak matches.

        Args:
            query (str): Search query text
            similarity_threshold (float): Minimum similarity score (0.0-1.0, default: 0.7)
            max_results (Optional[int]): Maximum results to return (default: 5)

        Returns:
            List[RetrievalResult]: Sorted list of matching chunks ordered by similarity score

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
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        results = results[:max_results]

        if not results:
            logging.error(f"No chunks found with similarity threshold {similarity_threshold}")
            raise NoMatchingEntryError(similarity_threshold)

        return results

    async def retrieve_by_actor(self,
                                actors: List[str],
                                similarity_threshold: float = 0.5,
                                max_results: int = 5) -> List[RetrievalResult]:
        """Retrieves chunks based on actor membership similarity.

        Uses metric: similarity = matched_actors / (len(actors) + |len(actors) - len(chunk_actors)|),
        which penalizes discrepancies in actor list lengths.

        Args:
            actors (List[str]): Target actor list
            similarity_threshold (float): Minimum similarity score (default: 0.5)
            max_results (int): Maximum results to return (default: 5)

        Returns:
            List[RetrievalResult]: Sorted list of matching chunks with similarity scores

        Raises:
            NoMatchingEntryError: If no chunks meet threshold
        """
        # Get all chunks from database
        all_chunks = await self.db_manager.get_all_chunks()

        # Calculate similarities
        results = []
        for chunk in all_chunks:
            actors_matched = len(set(actors).intersection(chunk.metadata.actors))
            similarity = actors_matched/(len(actors) + abs(len(actors) - len(chunk.metadata.actors)))

            if similarity >= similarity_threshold:
                results.append(RetrievalResult(chunk=chunk, similarity_score=similarity))

        # Sort by similarity and limit results
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        results = results[:max_results]

        if not results:
            logging.error(f"No chunks found with actor search - similarity threshold {similarity_threshold}")
            raise NoMatchingEntryError(similarity_threshold)

        return results

    async def delete_chunk(self, chunk: Union[DocumentChunk, str] | str) -> bool:
        """Deletes a chunk by hash.

        Accepts either DocumentChunk object or SHA-256 hash string.

        Args:
            chunk (Union[DocumentChunk, str]): Chunk object or hash to delete

        Returns:
            bool: True if deletion succeeded, False if chunk not found

        Raises:
            TypeError: If unsupported chunk type provided
        """
        if chunk is str:
            chunk_hash = chunk
        else:
            chunk_hash = chunk.chunk_hash if isinstance(chunk, DocumentChunk) else chunk

        logging.info(f"Deleting chunk with hash {chunk_hash}")
        deleted = await self.db_manager.delete_chunk(chunk_hash)
        if not deleted:
            logger.warning(f"Chunk {chunk_hash} could not be deleted")
            return False
        else:
            logger.info(f"Deleted chunk {chunk_hash}")
            return True

    async def update_chunk(self, chunk_hash: str, new_content: str, actors: List[str]) -> bool:
        """Updates chunk content through delete-then-store operation.

        Includes 0.5s rate limiting delay between operations to comply with database constraints.

        Args:
            chunk_hash (str): SHA-256 hash of chunk to update
            new_content (str): New text content
            actors (List[str]): New actor identifiers

        Returns:
            bool: True if update succeeded, False otherwise

        Raises:
            DatabaseNotAccessibleError: If storage fails
            HTTPError: If embedding generation fails
        """
        # Delete old chunk
        deleted = await self.delete_chunk(chunk_hash)
        if not deleted:
            return False

        # Rate limiting delay
        await asyncio.sleep(0.5)

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
        logging.info(f"Updated chunk with hash {chunk_hash}")
        return True

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Split text into overlapping chunks.

        Example: With chunk_size=100 and overlap=20, each subsequent chunk starts 80 characters after previous.

        Args:
            text (str): Input text to chunk
            chunk_size (int): Size of each chunk in characters (>0)
            overlap (int): Overlap between chunks in characters (>=0)

        Returns:
            List[str]: Generated text chunks
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)

            if end >= len(text):
                break

            start = end - overlap

        return chunks

    async def get_stats(self) -> Dict[str, Any]:
        """Gets system statistics.

        Returns:
            Dict[str, Any]: Contains:
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

# Utility functions for error handling
def handle_rag_error(func):
    """Decorator to handle RAG exceptions and return error tuples"""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except RAGException as e:
            return e.code, e.description
        except Exception as e:
            return ErrorCodes.SERVICE_UNAVAILABLE, f"Unexpected error: {str(e)}"
    return wrapper

if __name__ == "__main__":
    # Example usage
    async def main():
        rag_system = DynamicRAGSystem(embedding_server_url="http://localhost:10000", embedding_model="nomic-embed-text:latest")

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