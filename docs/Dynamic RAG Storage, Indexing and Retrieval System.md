# Dynamic RAG Storage, Indexing and Retrieval System

A comprehensive RAG (Retrieval-Augmented Generation) system implemented in Python with async operations, llama.cpp embedding server integration, SQLite database with rate limiting, and comprehensive error handling.

## Features

### Core Capabilities
- **Async Operations**: All I/O-bound operations (embedding calls, database interactions) are properly async-compatible using `asyncio` and `aiohttp`
- **Embedding Integration**: llama.cpp server integration via OpenAI-compatible API for high-performance CPU inference
- **Database**: SQLite database with strict rate limiting (one query per 500ms) and concurrent request denial
- **Dynamic Indexing**: Incremental dynamic index maintenance with chunk metadata (timestamp, actors)
- **Error Handling**: Comprehensive error handling with specific error codes and descriptions
- **Unit Tests**: Complete test suite covering store/retrieve functionality, precision/recall, and hallucination rate

### Technical Specifications
- **Rate Limiting**: 500ms minimum interval between database queries
- **No Retry Mechanism**: Failed requests are not automatically retried
- **Concurrent Request Handling**: Concurrent requests are denied with 'service unavailable' error
- **Metadata Fields**: Each chunk includes timestamp (int) and actors (list[str])
- **Error Format**: All errors return tuples with (int, str) format

## Installation

### Prerequisites
```bash
pip install aiohttp sqlite3
```

### Files
- `dynamic_rag.py` - Main implementation
- `test_*.py` - Unit test files

## Usage

### Basic Usage

```python
import asyncio
from modules.dynamic_rag import DynamicRAGSystem

async def main():
    # Initialize the RAG system
    rag_system = DynamicRAGSystem(
        db_path="my_rag.db",
        embedding_server_url="http://localhost:8080",  # llama.cpp server
        embedding_model="text-embedding-ada-002"
    )
    
    # Store a document
    chunk_hashes = await rag_system.store_document(
        content="Machine learning is a powerful technique for data analysis.",
        actors=["data_scientist", "researcher"],
        document_id="ml_doc_001",
        chunk_size=512,
        overlap=50
    )
    print(f"Stored {len(chunk_hashes)} chunks")
    
    # Retrieve similar content
    results = await rag_system.retrieve_similar(
        query="machine learning techniques",
        similarity_threshold=0.7,
        max_results=5
    )
    
    for result in results:
        print(f"Similarity: {result.similarity_score:.3f}")
        print(f"Content: {result.chunk.content[:100]}...")
        print(f"Actors: {result.chunk.metadata.actors}")
        print()

asyncio.run(main())
```

### Error Handling

```python
from modules.dynamic_rag import (
    NoMatchingEntryError,
    DatabaseNotAccessibleError,
    ServiceUnavailableError,
    SchemaMismatchError,
    HTTPError,
    ErrorCodes, DynamicRAGSystem
)

rag_system = DynamicRAGSystem()

async def main():
    try:
        results = await rag_system.retrieve_similar("query", 0.9, 5)
    except NoMatchingEntryError as e:
        print(f"No results found: {e.description} (Code: {e.code})")
    except ServiceUnavailableError as e:
        print(f"Rate limited: {e.description} (Code: {e.code})")
    except HTTPError as e:
        print(f"Connection error: {e.description} (Code: {e.code})")
```

### Additional Usage

```python
# Update existing chunk
updated = await rag_system.update_chunk(
    chunk_hash="existing_hash",
    new_content="Updated content with new information.",
    actors=["updated_user", "system"]
)

# Get system statistics
stats = await rag_system.get_stats()
print(f"Total chunks: {stats['total_chunks']}")
print(f"Unique documents: {stats['unique_documents']}")
print(f"All actors: {stats['actors']}")
```

## Architecture

### Core Components

1. **DynamicRAGSystem**: Main system class orchestrating all operations
2. **EmbeddingClient**: Async HTTP client for llama.cpp server communication
3. **DatabaseManager**: SQLite database operations with rate limiting
4. **RateLimiter**: Enforces 500ms minimum interval between operations
5. **Error Classes**: Comprehensive error handling with specific codes

### Data Models

```python
@dataclass
class ChunkMetadata:
    timestamp: int
    actors: List[str]
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None

@dataclass
class DocumentChunk:
    content: str
    metadata: ChunkMetadata
    embedding: Optional[List[float]] = None
    chunk_hash: Optional[str] = None

@dataclass
class RetrievalResult:
    chunk: DocumentChunk
    similarity_score: float
```

## Error Codes

| Code | Error Type | Description |
|------|------------|-------------|
| 1001 | NO_MATCHING_ENTRY | No matching entry for given similarity threshold |
| 1002 | DATABASE_NOT_ACCESSIBLE | Database not accessible |
| 1003 | SERVICE_UNAVAILABLE | Service unavailable (rate limit exceeded) |
| 1004 | SCHEMA_MISMATCH | Schema mismatch in request |
| 1005 | HTTP_ERROR | HTTP error with status code |

## Testing

### Run All Tests
```bash
# Individual test suites
python test_database.py
python test_embedding_client.py
python test_rag_system.py
python test_error.py

# Comprehensive test suite
python comprehensive_unit_tests.py

# System validation
python system_validation.py
```

### Test Coverage
- **Basic Functionality**: Store and retrieve operations
- **Precision/Recall**: Retrieval accuracy metrics
- **Latency**: Performance requirements validation
- **Hallucination Rate**: Irrelevant result detection
- **Error Handling**: All error scenarios
- **Rate Limiting**: Concurrent request denial

## Performance Characteristics

### Rate Limiting
- **Database Operations**: 500ms minimum interval
- **Concurrent Requests**: Automatically denied
- **No Retry Logic**: Failed requests must be manually retried

### Latency Targets
- **Retrieval**: < 2 seconds average
- **Storage**: < 5 seconds average
- **Embedding Generation**: Depends on llama.cpp server performance

### Scalability
- **SQLite Database**: Suitable for moderate workloads
- **Embedding Cache**: In-memory during operation
- **Chunk Size**: Configurable (default 512 characters)

## llama.cpp Server Setup

### Installation
```bash
# Clone and build llama.cpp
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
make

# Download a quantized embedding model (example)
wget https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/model.gguf
```

### Server Startup
```bash
# Start embedding server on port 8080
./server -m model.gguf --port 8080 --embedding
```

### API Compatibility
The system expects OpenAI-compatible API endpoints:
- `POST /v1/embeddings` - Generate embeddings
- Request format: `{"input": "text", "model": "model_name"}`
- Response format: `{"data": [{"embedding": [float, ...]}]}`

## Production Deployment

### Database Considerations
- **Backup Strategy**: Regular SQLite database backups
- **Disk Space**: Monitor database growth
- **Concurrent Access**: Single-process access recommended

### Monitoring
- **Error Rates**: Monitor exception frequencies
- **Response Times**: Track latency metrics  
- **Rate Limiting**: Monitor service unavailable errors

### Security
- **Database Access**: Secure file permissions
- **Network**: Secure llama.cpp server communication
- **Input Validation**: Sanitize user inputs

## Limitations

1. **Single Database Connection**: No connection pooling
2. **In-Memory Embeddings**: No persistent embedding cache
3. **Rate Limiting**: May impact high-throughput scenarios
4. **SQLite Limitations**: Not suitable for high-concurrency workloads
5. **No Authentication**: Embedding server access not authenticated

## Contributing

### Development Setup
```bash
# Install development dependencies
pip install aiohttp pytest pytest-asyncio

# Run tests
python -m pytest test_*.py
```

### Code Style
- Follow PEP 8 guidelines
- Use type hints for all functions
- Document all public methods
- Include error handling for all operations

## License

This implementation is provided as-is for educational and development purposes.

## Changelog

### Version 1.0.0
- Initial implementation with all required features
- Comprehensive test suite
- Full documentation
- System validation framework

