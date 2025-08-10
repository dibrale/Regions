import json

import requests

from modules.stringutils import assure_string, parse_host_port

class LLMLink:
    """A client for interacting with an LLM running on an OpenAI-compatible API. Has additional methods
       supporting llama.cpp-specific endpoints.

       This class handles configuration of API endpoints, parameters, and headers,
       and provides a streamlined interface for sending prompts and receiving responses.
       By default, it connects to 'http://192.168.1.232:5000/'.

       Attributes:
           url (str): Original host string (host:port) provided during initialization
           host (str): Host part of the API endpoint (e.g., '192.168.1.232')
           port (str | None): Port part of the API endpoint (e.g., '5000'), or None if not specified
           params (dict): LLM inference parameters
           headers (dict): HTTP headers for API requests
           ssl (bool): Whether SSL verification is enabled (for https)
    """
    def __init__(self, host: str = '192.168.1.232:5000', params: dict = None, headers: dict = None, ssl: bool = False):
        """Initialize the LLMLink client with optional configuration.

        Args:
            host (str, optional): API endpoint host:port. Defaults to local development server.
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
            - If no host is provided, defaults to local LLM server (for development)
            - All parameters use safe defaults to ensure immediate usability
            - SSL verification is disabled by default (use only for trusted local networks)
        """
        self.url = host
        self.params = params
        self.headers = headers
        self.ssl = ssl

        self.host, self.port = parse_host_port(host)

        if self.ssl:
            self.protocol = 'https'
        else:
            self.protocol = 'http'

        if not self.port:
            self.base_url = f'{self.protocol}://{self.host}'
        else:
            self.base_url = f'{self.protocol}://{self.host}:{self.port}'

        self.chat_url = f'{self.base_url}/v1/chat/completions'
        self.text_url = f'{self.base_url}/v1/completions'
        self.models_url = f'{self.base_url}/v1/models'
        self.tokenize_url = f'{self.base_url}/tokenize'
        self.health_url = f'{self.base_url}/health'

        if not params:
            self.params = {
                "temperature": 1,
                "top_p": 0,
                "top_k": 100,
                "top_n_sigma": 1
            }

        if not headers:
            self.headers = {"Content-Type": "application/json"}

    def chat(self, prompt) -> str:
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
            requests.exceptions.RequestException: On network/API errors
            ValueError: If prompt dictionary is missing required keys
            KeyError: If response structure doesn't match expected format

        Example:
            >>> llm = LLMLink()
            >>> llm.chat("What is an AI?")  # String input
            'Artificial Intelligence (AI) refers to...'
            >>> llm.chat({"role": "user", "content": "What is an AI?"})  # Dictionary input
            'Artificial Intelligence (AI) refers to...'
            >>> llm.chat([{"role": "user", "content": "What is an AI?"},
            ...           {"role": "assistant", "content": "A miserable pile of weights"},
            ...           {"role": "user", "content": "No, really?"}])  # List input
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

        # Send request (disable SSL verification for local development)
        response = requests.post(
            self.chat_url,
            headers=self.headers,
            json=data,
            verify=self.ssl
        )
        response.raise_for_status()  # Raise exception for HTTP errors

        return response.json()['choices'][0]['message']['content']

    def text(self, prompt: str, max_tokens: int = 2048) -> str:
        """Generate text completion for a given prompt.

        Sends a prompt to the text completion endpoint (OpenAI-compatible) and returns
        the generated text. Uses configured LLM parameters and specified max_tokens.

        Args:
            prompt (str): The prompt string to send to the LLM
            max_tokens (int, optional): Maximum number of tokens to generate. Defaults to 2048.

        Returns:
            str: Generated text response from the LLM (first choice)

        Raises:
            requests.exceptions.RequestException: On network/API errors
            KeyError: If response structure doesn't match expected format

        Example:
            >>> llm = LLMLink()
            >>> llm.text("Once upon a time", max_tokens=100)
            'in a galaxy far, far away...'
        """
        data = {"prompt": prompt, "max_tokens": max_tokens, **self.params}

        response = requests.post(
            self.text_url,
            headers=self.headers,
            json=data,
            verify=self.ssl
        )
        response.raise_for_status()
        return response.json()['choices'][0]['text']

    def health(self) -> tuple[int, str]:
        """Check the health status of the LLM server.

        Returns a tuple containing the HTTP status code and a descriptive string
        based on common status codes.

        Returns:
            tuple[int, str]: (status_code, description) where description is:
                - 'ok' for 200 (healthy)
                - 'loading' for 503 (model loading)
                - 'error' for other status codes

        Raises:
            requests.exceptions.RequestException: On network/API errors

        Example:
            >>> llm = LLMLink()
            >>> llm.health()
            (200, 'ok')
        """
        response = requests.get(
            self.health_url,
            headers=self.headers,
            verify=self.ssl
        )
        if response.status_code == 200:
            desc = 'ok'
        elif response.status_code == 503:
            desc = 'loading'
        else:
            desc = 'error'
        return response.status_code, desc

    def model(self) -> str:
        """Retrieve the name of the currently loaded LLM model.

        Queries the models endpoint and returns the name of the first model
        in the response list.

        Returns:
            str: Name of the LLM model

        Raises:
            requests.exceptions.RequestException: On network/API errors
            KeyError: If response structure lacks 'models' key or is empty

        Example:
            >>> llm = LLMLink()
            >>> llm.model()
            'ggml-model-q4_k'
        """
        response = requests.get(
            self.models_url,
            headers=self.headers,
            verify=self.ssl
        )
        return json.loads(response.text[:])['models'][0]['name']

    def n_tokens(self, content: str) -> int:
        """Count the number of tokens in a given content string.

        Uses the llama.cpp-specific tokenize endpoint to determine token count.

        Args:
            content (str): The string content to tokenize

        Returns:
            int: Number of tokens in the content

        Raises:
            requests.exceptions.RequestException: On network/API errors
            KeyError: If response structure lacks 'tokens' key

        Example:
            >>> llm = LLMLink()
            >>> llm.n_tokens("Hello, world!")
            3
        """
        response = requests.post(
            self.tokenize_url,
            headers=self.headers,
            json={"content": content},
            verify=self.ssl
        )
        return len(json.loads(response.text[:])['tokens'])
