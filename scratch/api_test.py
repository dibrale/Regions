import websockets.client
import asyncio
import json

params = {
    'strings': ['foo', 'asdfg', 'fgkuj', 'zxcvads', 'bar'],
    'score': []
}


async def api_test(message: str):
    uri = "ws://localhost:1230"
    async with websockets.client.connect(uri) as websocket:
        reply_decoded = {}
        out = {'echo': message}
        try:
            print(f"Sending: {str(out)}")
            await asyncio.wait_for(websocket.send(json.dumps(out)), 1)
            # async with websocket as socket:
            async for message in websocket:
                reply_decoded.update(json.loads(message))
            # reply = await asyncio.wait_for(websocket.recv(), 1)
            # reply_decoded = json.loads(reply)
            print(f"Got:     {reply_decoded}")
        except Exception as e:
            print(e)
        finally:
            if reply_decoded == out:
                params['score'].append(True)
            else:
                params['score'].append(False)

if __name__ == "__main__":
    for i in range(len(params['strings'])):
        asyncio.run(api_test(params['strings'][i]))
    # asyncio.run(api_test(params['strings'][0]))

    final_score = 0
    for point in params['score']:
        if point:
            final_score += 1

    max_score = len(params['strings'])

    print(f"{final_score}/{max_score} echo tests passed")


