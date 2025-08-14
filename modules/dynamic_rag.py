"""
Dynamic RAG Storage, Indexing and Retrieval System

A comprehensive RAG system with:
- Async operations using asyncio and aiohttp
- llama.cpp embedding server integration via OpenAI-compatible API
- SQLite database with rate limiting
- Dynamic incremental indexing
- Comprehensive error handling
"""

import asyncio
import aiohttp
import sqlite3
import json
import time
import hashlib
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime
import logging

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
        """Acquire rate limit permission"""
        async with self._lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            
            if time_since_last < self.min_interval:
                raise ServiceUnavailableError("Rate limit exceeded - concurrent requests not allowed")
            
            self.last_request_time = current_time

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
        """Get embedding for text using OpenAI-compatible API"""
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
        """Store a document chunk with rate limiting"""
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
        """Retrieve all chunks from database"""
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
        """Delete a chunk by hash"""
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
    """Calculate cosine similarity between two vectors"""
    if len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = sum(a * a for a in vec1) ** 0.5
    magnitude2 = sum(b * b for b in vec2) ** 0.5
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)

class DynamicRAGSystem:
    """Main RAG system with dynamic indexing and retrieval"""
    
    def __init__(self, 
                 db_path: str = "rag_storage.db",
                 embedding_server_url: str = "http://localhost:8080",
                 embedding_model: str = "text-embedding-ada-002"):
        self.db_manager = DatabaseManager(db_path)
        self.embedding_server_url = embedding_server_url
        self.embedding_model = embedding_model
    
    async def store_document(self, 
                           content: str, 
                           actors: List[str],
                           document_id: Optional[str] = None,
                           chunk_size: int = 512,
                           overlap: int = 50) -> List[str]:
        """Store a document with chunking and embedding generation"""
        
        # Generate chunks
        chunks = self._chunk_text(content, chunk_size, overlap)
        chunk_hashes = []
        
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
        
        return chunk_hashes
    
    async def retrieve_similar(self, 
                             query: str, 
                             similarity_threshold: float = 0.7,
                             max_results: int = 5) -> List[RetrievalResult]:
        """Retrieve similar chunks based on query"""
        
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
                    # print(f"Similarity: {similarity:.2f}")
                    results.append(RetrievalResult(chunk=chunk, similarity_score=similarity))
        
        # Sort by similarity and limit results
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        results = results[:max_results]
        
        if not results:
            raise NoMatchingEntryError(similarity_threshold)
        
        return results
    
    async def update_chunk(self, chunk_hash: str, new_content: str, actors: List[str]) -> bool:
        """Update an existing chunk with new content"""
        
        # Delete old chunk
        deleted = await self.db_manager.delete_chunk(chunk_hash)
        if not deleted:
            return False

        # Rate limiting delay
        await asyncio.sleep(0.5)

        # Generate new embedding
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
        return True
    
    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Split text into overlapping chunks"""
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
        """Get system statistics"""
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
        rag_system = DynamicRAGSystem()
        
        try:
            # Store a document
            chunk_hashes = await rag_system.store_document(
                content="This is a sample document about machine learning and artificial intelligence.",
                actors=["user1", "system"],
                document_id="doc_001"
            )
            print(f"Stored document with {len(chunk_hashes)} chunks")
            
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
            stats = await rag_system.get_stats()
            print("System stats:", stats)
            
        except RAGException as e:
            print(f"RAG Error {e.code}: {e.description}")
        except Exception as e:
            print(f"Unexpected error: {e}")
    
    # Run example
    # asyncio.run(main())

