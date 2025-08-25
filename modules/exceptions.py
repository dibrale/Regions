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

# ServiceUnavailableError is deprecated and may be removed
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
