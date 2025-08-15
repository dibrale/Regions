import asyncio
import json
from modules.llamacpp_api import LLMLink

class Region:
    """
    Base class for regions that can communicate with each other.
    Each region has a specific function and can process requests from other regions.
    """

    def __init__(self, name: str, task: str, llm: LLMLink, connections: dict[str, str] | None):
        """
        Initialize a region.

        Args:
            name (str), task (str)

        :param name: A string with the name of the region
        :param task: A string describing region function
        """

        self.name = name
        self.task = task
        self.llm = llm
        if connections is None:
            self.connections = {}
        else:
            self.connections = connections
        self.inbox = asyncio.Queue()  # Queue for incoming requests and replies
        self.outbox = asyncio.Queue()  # Queue for outgoing requests and replies
        self._context = {}
        self._queries = {}

    def _post(self, destination: str, content: str, role: str) -> None:

        message = {
            "source": self.name,
            "destination": destination,
            "content": content,
            "role": role
        }

        # Add the message to the queue for outgoing queries
        self.outbox.put_nowait(message)

    def _ask(self, destination: str, query_text: str) -> None:
        self._post(destination, query_text, 'request')
        return

    def _reply(self, destination: str, reply_text: str) -> None:
        self._post(destination, reply_text, 'reply')
        return

    def _run_inbox(self):
        while not self.inbox.empty():
            message = self.inbox.get_nowait()
            if message['type'] == 'reply':
                self._context[message['source']] = message['content']
            elif message['type'] == 'request':
                self._queries[message['source']] = message['content']
            else:
                raise AssertionError(f"{self.name}: Unknown message type")
        return

    def _make_prompt(self, question: str, bom: str = '<|im_start|>', eom: str = '<|im_end|>', think: str = None) -> str:

        schema = {'focus': self.task, 'knowledge': [*self._context.values()]}
        prefix = f"{bom}system\nReply to the user, given your focus and knowledge per the given schema:"
        prompt = f"{prefix}\n{schema}{eom}\n{bom}user\n{question}{eom}\n{bom}assistant\n"
        if think: prompt += f"{think}\n"

        return prompt

    async def make_replies(self) -> bool:
        faultless = True

        for question in self._queries:
            prompt = self._make_prompt(question['content'])
            reply = None

            try:
                reply = await self.llm.text(prompt)
            except Exception as e:
                print(f"\n{self.name}: Processing failed. {e}")
                faultless = False

            if reply:
                self._reply(question['source'], reply)

        return faultless

    async def make_questions(self) -> bool:

        faultless = True
        questions = {}

        user_prompt = (
            "Below is a list of sources and their respective focus. Keeping your own focus in mind, ask each of them \
one question to update your knowledge.\n\n" + str(self.connections) +
            '\n\nReply with your questions in valid JSON format according to the template:\n' +
             '{[{"source": source1, "question": question1}, {"source": source2, "question": question2}, ... ]}\n\n'
        )

        prompt = self._make_prompt(user_prompt)

        try:
            reply = await self.llm.text(prompt)
            questions = json.loads(reply)
        except Exception as e:
            print(f"\n{self.name}: Processing failed. {e}")
            faultless = False
            return faultless

        if questions:
            for question in questions:
                try:
                    if question['source'] not in self.connections:
                        raise AssertionError(f"{self.name}: {question['source']} is not a valid recipient")
                    else:
                        self._ask(question['source'], question['question'])
                except Exception as e:
                    print(f"\n{self.name}: Error processing LLM reply. {e}")
                    faultless = False
        else:
            print("\n{self.name}: Asking no questions.")

        return faultless
