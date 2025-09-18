import asyncio
import logging
from asyncio import Queue
from typing import Any, List
import re


# Check for None and return an empty string in its place. Otherwise, pass the input to output as string.
def assure_string(txt) -> str:
    if not txt:
        return ''
    return str(txt)

# Parse a string for boolean output, returning None for inconsistent replies
def bool_from_str(text_in: str, true_str='true', false_str='false', case_sensitive=False) -> bool | None:

    # Apply case sensitivity
    if not case_sensitive:
        text = text_in.lower()
        true = true_str.lower()
        false = false_str.lower()
    else:
        text = text_in
        true = true_str
        false = false_str

    # Check for statements
    is_true = text.count(true)
    is_false = text.count(false)
    if is_true > 0 >= is_false:
        return True
    elif is_false > 0 >= is_true:
        return False
    else:
        return None

#Get host and port from string
def parse_host_port(s: str) -> tuple[str | Any, int] | tuple[str | Any, None] | None:
    pattern_with_port = r'([a-zA-Z0-9.-]+):(\d+)'
    match = re.search(pattern_with_port, s)
    if match:
        host = match.group(1)
        port = int(match.group(2))
        return host, port

    pattern_without_port = r'([a-zA-Z0-9.-]+)'
    match = re.search(pattern_without_port, s)
    if match:
        host = match.group(1)
        return host, None

    return None

# Initialize a list
def set_list(list_input: list) -> list:
    if not list_input: return []
    return list_input

# Trim empty list items from the end of a list. Returns number of items removed.
def trim_list(list_input: list) -> int:
    num_popped = 0
    for i in range(len(list_input))[::-1]:
        if not list_input[i]:
            list_input.pop(i)
            num_popped += 1
        else:
            break
    return num_popped

# Check execution configuration entry. Returns input if valid.
def check_execution_entry(entry: tuple):
    assert type(entry) is tuple, f"Expected tuple, got {type(entry)}"
    assert len(entry) == 2, f"Expected tuple of length 2, got {len(entry)}"
    assert isinstance(entry[0], str), f"Expected string for region name, got {type(entry[0])}"
    assert isinstance(entry[1], str), f"Expected string for method name, got {type(entry[1])}"
    assert bool(entry[0]), "Expected non-empty region name"
    assert bool(entry[1]), "Expected non-empty method name"
    return entry

def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split text into overlapping chunks.

    Example: With chunk_size=100 and overlap=20, each subsequent chunk starts
    80 characters after previous.

    Args:
        text (str): Input text to chunk
        chunk_size (int): Size of each chunk in characters (>0)
        overlap (int): Overlap between chunks in characters (>=0)

    Returns:
        List[str]: Generated text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks

async def until_empty(queue: Queue, interval: float = 0.1, timeout: float = 3) -> bool:
    """Wait until the queue is empty without blocking other work.

    Args:
        queue (Queue): The queue to wait for.
        interval (float, optional): The time to wait between checks in seconds. Defaults to 0.1.
        timeout (float, optional): The maximum time to wait in seconds. Defaults to 3.
    """
    if queue.empty():
        logging.debug("Queue is already empty")
        return True
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout:
        if queue.empty():
            logging.debug(f"Queue is now empty")
            return True
        else:
            await asyncio.sleep(interval)
    logging.warning(f"Queue  not empty after timeout")
    return False

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Measures vector orientation (range: -1 to 1), with 1 indicating identical direction.
    Returns 0.0 for zero-magnitude vectors or mismatched dimensions.

    Args:
        vec1 (List[float]): First vector
        vec2 (List[float]): Second vector

    Returns:
        float: Similarity score between -1 and 1
    """
    if len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = sum(a * a for a in vec1) ** 0.5
    magnitude2 = sum(b * b for b in vec2) ** 0.5

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)

def use_logging_standard() -> None:
    """Configure logging preferences in a standard way throughout the Regions package."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True
    )
