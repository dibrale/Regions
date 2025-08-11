import asyncio
import unittest
from modules.llamacpp_api import LLMLink

class TestLLMLink(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup happens in the event loop
        self.obj = LLMLink()
        print("Initialized LLMLink object for testing")
        await asyncio.sleep(0)

    async def test_chat(self):
        print("-----------------------")
        print("Chat method test")
        print("-----------------------")
        test_string = 'Hello!'
        print("> "+test_string)
        result = await self.obj.chat(test_string)
        print("\n"+result+"\n")

    async def test_text(self):
        print("-----------------------")
        print("Text method test")
        print("-----------------------")
        test_string = 'Twinkle, Twinkle little '
        max_tokens = 100
        print("> " + test_string)
        result = await self.obj.text(test_string,max_tokens)
        print("\n"+result+"\n")

    async def test_model(self):
        print("-----------------------")
        print("Model method test")
        print("-----------------------")
        result = await self.obj.model()
        print("\n"+result+"\n")

    async def test_health(self):
        print("-----------------------")
        print("Health method test")
        print("-----------------------")
        result = await self.obj.health()
        print("\n" + result[1] + "\n")

if __name__ == "__main__":
    unittest.main()