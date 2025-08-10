import json
import requests

from modules.llamacpp_api_test import assistant_message
from modules.stringutils import assure_string, parse_host_port

class LLMLink:
    """A client for interacting with an LLprint("Hello, World!")M running on an OpenAI-compatible API endpoint.

       This class handles configuration of API endpoints, parameters, and headers,
       and provides a streamlined interface for sending prompts and receiving responses.
       By default, it connects to 'http://192.168.1.232:5000/'.

       Attributes:
           host (str): API endpoint host and port
           params (dict): LLM inference parameters
           headers (dict): HTTP headers for API requests
    """
    def __init__(self, host: str = '192.168.1.232:5000', params: dict = None, headers: dict = None):
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

                Note:
                    - If no URL is provided, defaults to local LLM server (for development)
                    - All parameters use safe defaults to ensure immediate usability
                    - SSL verification is disabled by default (use only for trusted local networks)
        """
        self.url = host
        self.params = params
        self.headers = headers

        self.host, self.port = parse_host_port(host)

        if not self.port:
            self.base_url = f'https://{self.host}'
        else:
            self.base_url = f'https://{self.host}:{self.port}'

        self.chat_url = f'{self.base_url}/v1/chat/completions'
        self.text_url = f'{self.base_url}/v1/completions'

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
                        - If str or list: Converted to {"role": "user", "content": <prompt>}
                        - If dict: Used directly as message (expected to have "role" and "content")

                Returns:
                    str: Generated text response from the LLM

                Raises:
                    requests.exceptions.RequestException: On network/API errors
                    KeyError: If response structure doesn't match expected format

                Example:
                    \r llm = LLMLink()
                    \r llm.eval("What is an AI?")                               # String input
                    \r llm.eval({"role": "user", "content": "What is an AI?"})  # Dictionary input
                    \r llm.eval([{"role": "user", "content": "What is an AI?"},\
                       {"role": "assistant", "content": "A miserable pile of weights"},\
                       {"role": "user", "content": "No, really?"}])             # List input
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
            message = {"role": "user", "content": assure_string(prompt)}

        # Build request payload by merging parameters
        data = {"messages": message, **self.params}
        print(data)

        # Send request (disable SSL verification for local development)
        response = requests.post(
            self.chat_url,
            headers=self.headers,
            json=data,
            verify=False  # WARNING: Set to 'True' for remote calls
        )
        response.raise_for_status()  # Raise exception for HTTP errors

        return response.json()['choices'][0]['message']['content']

    def text(self, prompt: str) -> str:

        print("Sending to" + self.text_url)

        response = requests.post(
            self.text_url,
            headers=self.headers,
            json=[prompt],
            verify=False  # WARNING: Set to 'True' for remote calls
        )
        response.raise_for_status()  # Raise exception for HTTP errors
        return response.json()['choices'][0].text
    '''
history = []
llm = LLMLink()

while True:
    user_message = input("> ")
    assistant_message = llm.text(user_message)
    print(assistant_message)

    history.append({"role": "user", "content": user_message})
    assistant_message = llm.chat(history)
    history.append({"role": "assistant", "content": assistant_message})
    print(assistant_message)
    '''