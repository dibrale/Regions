import json
from typing import Any

from modules.logutils import print_v

import re


# Check for None and return an empty string in its place. Otherwise, pass the input to output as string.
def assure_string(txt) -> str:
    if not txt:
        return ''
    return str(txt)


# Handle strings and string lists equally, assuring a string as output
def list_or_str_to_str(txt: str | list[str], join_string='\n', if_blank='') -> str:
    if type(txt) is str:
        out = txt.strip()
    elif type(txt) is list[str]:
        out = join_string.join(txt).strip()
    elif not txt:
        return if_blank
    else:
        out = str(txt)
    return out


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


# Extract question from an arbitrary string
async def parse_question(input_string: str):
    result = re.search(r"Question\s*\d*\s*:\s*\d*\s*(?P<QUESTION>(.*?)[.?])", input_string)

    try:
        question = result.group('QUESTION')
        print_v(f'Question: {question}')
        return question
    except AttributeError:
        return None


# Test for a string or string list that is not worth processing
def check_nil(query: str | list | dict) -> bool:
    check_list = []

    if type(query) is str:
        check_list = [query]
    elif type(query) is list:
        check_list = query
    elif type(query) is dict:
        intermediate_list = query.values()
        for item in intermediate_list:
            check_list.append(item)

    if not check_list:
        return True

    for item in check_list:
        if not (str(item) == 'Nothing.' or str(item) == '' or not item):
            return False

    return True

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

def extract_json_segment(s: str) -> str | None:
    in_string = False
    n = len(s)
    for i in range(n):
        if in_string:
            if s[i] == '"' and (i == 0 or s[i - 1] != '\\'):
                in_string = False
            continue

        last_valid = i
        for j in range(i, n + 1):
            try:
                json.loads(s[i:j])
                last_valid = j
            except json.JSONDecodeError:
                break
            except Exception as e:
                print(e)
                break
        if last_valid > i:
            return s[i:last_valid]
    return None