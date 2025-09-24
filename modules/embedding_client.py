import asyncio
import logging
from typing import Optional, List

import aiohttp

from exceptions import HTTPError, SchemaMismatchError


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
        logging.debug(f"Sending embedding request for text length {len(text)} to '{url}'")
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

                logging.info(f"Received embedding for text of length {len(text)}")
                return result["data"][0]["embedding"]

        except SchemaMismatchError:
            raise
        except aiohttp.ClientError as e:
            raise HTTPError(0, f"Connection error: {str(e)}")
        except asyncio.TimeoutError as e:
            raise HTTPError(0, f"Timeout error: {str(e)}")
        except Exception as e:
            raise HTTPError(0, f"Network error: {str(e)}")
