from modules.config import params, send_queue
import asyncio
from modules.logutils import print_v

# Make the semaphore
semaphore = {
    'pause': False,
    'webui': True,
    'squire': True
}

connection = {
    'live': False
}


# Fake signal manager for testing. Just prints the signal and does nothing
async def fake_signal_manager(receive_queue: asyncio.Queue, send_queue: asyncio.Queue | None):
    while True:
        item = await receive_queue.get()
        print(f"Got signal type {type(item)} from queue\nContents: {str(item)}")
        await asyncio.sleep(0)


# The actual signal manager. Updates the internal semaphore
async def signal_manager(receive_queue: asyncio.Queue, send_queue: asyncio.Queue):
    while True:
        out = {}
        item = await receive_queue.get()
        print_v(f"Got request from queue: {str(item)}")
        for key in item.keys():
            # print_v(f"Checking key '{key}'")
            if key == 'echo':
                out.update({key: item[key]})
            elif key == 'ping':
                out.update({'pong': 0})
            elif key == 'query':
                if item[key] == 'id':
                    out.update({'script_name': params['script_name']})
                    connection['live'] = True
                elif item[key] == 'semaphore':
                    out.update(semaphore)
                elif item[key] in semaphore.keys():
                    out.update({item[key]: semaphore[item[key]]})
            elif key == 'close':
                connection['live'] = False
            elif key in semaphore.keys():
                semaphore.update(item)
                out.update({key: semaphore[key]})
            else:
                print_v(f"No key match for '{key}'")
            await asyncio.sleep(0)
        if out:
            send_queue.put_nowait(out)
            print_v(f"Queued reply to send: {str(out)}")
        await asyncio.sleep(0)


# Get a semaphore signal
async def get_signal(key):
    try:
        return semaphore[key]
    except KeyError:
        return None


# Set a semaphore signal, sending an update to the client
async def set_signal(item: dict, send_queue: asyncio.Queue):
    semaphore.update(item)
    send_queue.put_nowait(semaphore)


# Wait at the semaphore
async def signal(key, go_value=True, go_on_none=False, check_frequency=0.25, checks_per_reminder=8):
    print_wait = True
    check_number = 0
    while True:
        sig = await get_signal(key)
        if sig == go_value:
            break
        elif isinstance(sig, type(None)) and go_on_none:
            break
        await asyncio.sleep(check_frequency)
        check_number += 1
        if check_number == checks_per_reminder:
            if connection['live']:
                send_queue.put_nowait({'waiting': key})
            check_number = 0
        print_v(f"Waiting at semaphore for {key}:{go_value}", print_wait)
        print_wait = False
        await asyncio.sleep(0)
    if connection['live']:
        send_queue.put_nowait({'going': key})
    print_v(f"Semaphore cleared with {key}:{sig}", params['verbose'])
