import json

import aiohttp
import logging
import pathlib

from modules.utils import assure_string, parse_host_port


class LLMLink:
    """A client for interacting with an LLM running on an OpenAI-compatible API. Has additional methods
       supporting llama.cpp-specific endpoints.

       This class handles configuration of API endpoints, parameters, and headers,
       and provides a streamlined interface for sending prompts and receiving responses.
       By default, it connects to 'http://192.168.1.232:5000/'.

       Attributes:
           url (str): Original host string (host:port) provided during initialization
           _host (str): Host part of the API endpoint (e.g., '192.168.1.232')
           _port (str | None): Port part of the API endpoint (e.g., '5000'), or None if not specified
           params (dict): LLM inference parameters
           headers (dict): HTTP headers for API requests
           ssl (bool): Whether SSL verification is enabled (for https)
    """

    def __init__(self,
                 url: str = '192.168.1.232:5000',
                 params: dict = None,
                 headers: dict = None,
                 name: str = None,
                 ssl: bool = False):
        """Initialize the LLMLink client with optional configuration.

        Args:
            url (str, optional): API endpoint _host:_port. Defaults to local development server.
            params (dict, optional): LLM inference parameters. Defaults to:
                {
                    "temperature": 1,
                    "top_p": 0,
                    "top_k": 100,
                    "top_n_sigma": 1
                }
            headers (dict, optional): HTTP headers. Defaults to {"Content-Type": "application/json"}.
            ssl (bool, optional): Whether to enable SSL verification. Defaults to False.

        Note:
            - If no _host is provided, defaults to local LLM server (for development)
            - All parameters use safe defaults to ensure immediate usability
            - SSL verification is disabled by default (use only for trusted local networks)
        """
        self.url = url
        self.params = params
        self.headers = headers
        self.name = name
        self.ssl = ssl
        self._configure()

    def __setattr__(self, name, value):
        if not name.startswith('_'):
            self._configure()

    def _configure(self):

        self._host, self._port = parse_host_port(self.url)

        if self.ssl:
            self._protocol = 'https'
        else:
            self._protocol = 'http'

        if not self._port:
            self._base_url = f'{self._protocol}://{self._host}'
        else:
            self._base_url = f'{self._protocol}://{self._host}:{self._port}'

        self._chat_url = f'{self._base_url}/v1/chat/completions'
        self._text_url = f'{self._base_url}/v1/completions'
        self._models_url = f'{self._base_url}/v1/models'
        self._tokenize_url = f'{self._base_url}/tokenize'
        self._health_url = f'{self._base_url}/health'

        if not self.params:
            self.params = {
                "temperature": 1,
                "top_p": 0,
                "top_k": 100,
                "top_n_sigma": 1
            }

        if not self.headers:
            self.headers = {"Content-Type": "application/json"}

    def save(self, path: str) -> None:
        """Save LLMLink to a JSON file."""
        pure_path = pathlib.PurePath(path)
        if self.name:
            logging.info(f"Saving '{self.name}' LLMLink configuration to {pure_path}")
        else:
            logging.info(f"Saving LLMLink configuration to {pure_path}")
        try:
            with open(str(pure_path), 'w') as f:
                json.dump({
                    "url": self.url,
                    "params": self.params,
                    "headers": self.headers,
                    "name": self.name,
                    "ssl": self.ssl,
                }, f, indent=4)
            logging.info(f"{self.name}: LLMLink configuration saved to {pure_path}")
        except IOError as e:
            logging.error(f"{self.name}: Failed to save LLMLink configuration: {str(e)}")

    @classmethod
    def load(cls, path: str) -> 'LLMLink | None':
        """Load a LLMLink from a JSON file."""
        pure_path = pathlib.PurePath(path)
        logging.info(f"{cls.__name__}: Loading LLMLink configuration from {pure_path.name}")
        try:
            with open(str(pure_path)) as f:
                config = json.load(f)
                if config.get('name') is not None:
                    logging.info(f"{cls.__name__}: Loaded '{config['name']}' LLMLink configuration")
                else:
                    logging.info(f"{cls.__name__}: Loaded LLMLink configuration")
                return cls(
                    url=config['url'],
                    params=config['params'],
                    headers=config['headers'],
                    name=config.get('name', None),
                    ssl=config['ssl'],
                )
        except IOError as e:
            logging.error(f"{cls.__name__}: Failed to load LLMLink configuration: {str(e)}")

    async def chat(self, prompt) -> str:
        """Send a prompt to the LLM and return the response text.

        This method handles prompt formatting, API request, and response parsing.
        Supports both string prompts and structured message dictionaries.

        Args:
            prompt (str | dict | list): Input prompt to send to LLM.
                - If str: Converted to {"role": "user", "content": <prompt>}
                - If list: Used directly as message history
                - If dict: Used directly as message (must contain "role" and "content")

        Returns:
            str: Generated text response from the LLM (first choice)

        Raises:
            aiohttp.ClientResponseError: On network/API errors
            ValueError: If prompt dictionary is missing required keys
            KeyError: If response structure doesn't match expected format

        Example:
            >>> llm = LLMLink()
            >>> await llm.chat("What is an AI?")  # String input
            'Artificial Intelligence (AI) refers to...'
            >>> await llm.chat({"role": "user", "content": "What is an AI?"})  # Dictionary input
            'Artificial Intelligence (AI) refers to...'
            >>> await llm.chat([{"role": "user", "content": "What is an AI?"},
            ...                {"role": "assistant", "content": "A miserable pile of weights"},
            ...                {"role": "user", "content": "No, really?"}])  # List input
            'Actually, AI is...'
        """
        # Handle string vs dictionary prompts
        if isinstance(prompt, dict):
            # Validate dictionary structure
            if 'role' not in prompt or 'content' not in prompt:
                raise ValueError(
                    "Prompt dictionary must contain both 'role' and 'content' keys. "
                    f"Missing key: {', '.join({'role', 'content'} - set(prompt.keys()))}"
                )
            message = prompt
        elif isinstance(prompt, list):
            message = prompt
        else:
            message = [{"role": "user", "content": assure_string(prompt)}]

        # Build request payload by merging parameters
        data = {"messages": message, **self.params}

        # Send request using aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self._chat_url,
                    headers=self.headers,
                    json=data,
                    ssl=self.ssl
            ) as response:
                response.raise_for_status()
                return (await response.json())['choices'][0]['message']['content']

    async def text(self, prompt: str, max_tokens: int = 4096) -> str:
        """Generate text completion for a given prompt.

        Sends a prompt to the text completion endpoint (OpenAI-compatible) and returns
        the generated text. Uses configured LLM parameters and specified max_tokens.

        Args:
            prompt (str): The prompt string to send to the LLM
            max_tokens (int, optional): Maximum number of tokens to generate. Defaults to 4096.

        Returns:
            str: Generated text response from the LLM (first choice)

        Raises:
            aiohttp.ClientResponseError: On network/API errors
            KeyError: If response structure doesn't match expected format

        Example:
            >>> llm = LLMLink()
            >>> await llm.text("Once upon a time", max_tokens=100)
            'in a galaxy far, far away...'
        """
        data = {"prompt": prompt, "max_tokens": max_tokens, **self.params}

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self._text_url,
                    headers=self.headers,
                    json=data,
                    ssl=self.ssl
            ) as response:
                response.raise_for_status()
                return (await response.json())['choices'][0]['text']

    async def health(self) -> tuple[int, str]:
        """Check the health status of the LLM server.

        Returns a tuple containing the HTTP status code and a descriptive string
        based on common status codes.

        Returns:
            tuple[int, str]: (status_code, description) where description is:
                - 'ok' for 200 (healthy)
                - 'loading' for 503 (model loading)
                - 'error' for other status codes

        Raises:
            aiohttp.ClientResponseError: On network/API errors

        Example:
            >>> llm = LLMLink()
            >>> await llm.health()
            (200, 'ok')
        """
        async with aiohttp.ClientSession() as session:
            async with await session.get(
                    self._health_url,
                    headers=self.headers,
                    ssl=self.ssl
            ) as response:
                if response.status == 200:
                    desc = 'ok'
                elif response.status == 503:
                    desc = 'loading'
                else:
                    desc = 'error'

                return response.status, desc

    async def model(self) -> str:
        """Retrieve the name of the currently loaded LLM model.

        Queries the models endpoint and returns the name of the first model
        in the response list.

        Returns:
            str: Name of the LLM model

        Raises:
            aiohttp.ClientResponseError: On network/API errors
            KeyError: If response structure lacks 'models' key or is empty

        Example:
            >>> llm = LLMLink()
            >>> await llm.model()
            'ggml-model-q4_k'
        """
        async with aiohttp.ClientSession() as session:
            async with await session.get(
                    self._models_url,
                    headers=self.headers,
                    ssl=self.ssl
            ) as response:
                response.raise_for_status()
                data = await response.json()
                return data['models'][0]['name']

    async def n_tokens(self, content: str) -> int:
        """Count the number of tokens in a given content string.

        Uses the llama.cpp-specific tokenize endpoint to determine token count.

        Args:
            content (str): The string content to tokenize

        Returns:
            int: Number of tokens in the content

        Raises:
            aiohttp.ClientResponseError: On network/API errors
            KeyError: If response structure lacks 'tokens' key

        Example:
            >>> llm = LLMLink()
            >>> await llm.n_tokens("Hello, world!")
            3
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    self._tokenize_url,
                    headers=self.headers,
                    json={"content": content},
                    ssl=self.ssl
            ) as response:
                response.raise_for_status()
                data = await response.json()
                return len(data['tokens'])