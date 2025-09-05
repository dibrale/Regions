import asyncio
import hashlib
import json
import logging
import pathlib
import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

from exceptions import DatabaseNotAccessibleError

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

            logging.debug(f"{self.db_name}: Storing document chunk with hash: {chunk.chunk_hash}")
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
            logging.debug(f"{self.db_name}: Retrieved all stored document chunks")
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
