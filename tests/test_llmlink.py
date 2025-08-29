import asyncio
import json
import logging
import unittest

from modules.llmlink import LLMLink

class TestLLMLink(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup happens in the event loop
        logging.info("Loading parameters from 'test_params.json'")
        test_params = json.load(open('test_params.json', 'r'))

        self.obj = LLMLink(url=f"{test_params['llm_host']}:{test_params['llm_port']}")
        logging.info("Initialized LLMLink object for testing")
        await asyncio.sleep(0)

    async def test_chat(self):
        test_string = 'Hello!'
        print("> " + test_string)
        result = await self.obj.chat(test_string)
        print(f"=== MODEL OUTPUT ===\n{result}\n=== END MODEL OUTPUT ===\n")
        assert isinstance(result, str)

    async def test_text(self):
        test_string = 'Twinkle, Twinkle little '
        max_tokens = 32
        print("> " + test_string)
        result = await self.obj.text(test_string,max_tokens)
        print(f"=== MODEL OUTPUT ===\n{result}\n=== END MODEL OUTPUT ===\n")
        assert isinstance(result, str)

    async def test_model(self):
        result = await self.obj.model()
        print("\n"+result+"\n")
        assert result

    async def test_health(self):
        result = await self.obj.health()
        assert result[1] == 'ok'


if __name__ == "__main__":
    unittest.main()