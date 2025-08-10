import json
import asyncio

# import yaml

# Load parameter file
try:
    with open('params.json', encoding='utf-8') as f:
        [params, llm_params, webui_params] = json.load(f)
        print("Imported parameters from params.json")
except Exception as e:
    print(e)
    try:
        with open('../params.json', encoding='utf-8') as f:
            [params, llm_params, webui_params] = json.load(f)
            print("Imported parameters from ../params.json")
    except Exception as e:
        print(e)

print(params)
"""
# Load the character sheet once
suffix = params['char_card_path'][-4:].lstrip('.')

# Internal scheme is based on JSON-format characters
if suffix == 'json' or suffix == 'jsn':
    try:
        with open(params['char_card_path'], 'r', encoding='utf-8') as f:
            attributes = json.load(f)
    except Exception as e:
        print(e)

# Load a YAML character and populate the keys expected from a JSON character
elif suffix == 'yaml' or suffix == 'yml':
    try:
        with open(params['char_card_path'], 'r', encoding='utf-8') as f:
            attributes = yaml.safe_load(f)
    except Exception as e:
        print(e)

    if 'name' in attributes:
        attributes['char_name'] = attributes['name']
    else:
        raise KeyError(f"The character file at {params['char_card_path']} lacks a character name")

    if 'greeting' in attributes:
        attributes['char_greeting'] = attributes['greeting']
    else:
        attributes['char_greeting'] = ''

    if 'context' in attributes:
        attributes['char_persona'] = attributes['context'].lstrip(f"{attributes['char_name']}'s Persona: ")
    else:
        attributes['char_persona'] = ''


# Ensure that a username is present
if 'user_name' in params:
    attributes['your_name'] = params['user_name']
elif 'your_name' not in attributes:
    attributes['your_name'] = 'User'

# Handle missing world_scenario
if 'world_scenario' not in attributes:
    attributes['world_scenario'] = ''


# Create file paths
path = {
    'judge_template': f"{params['template_dir']}/judge_template.txt",
    'aye_template': f"{params['template_dir']}/aye_template.txt",
    'nay_template': f"{params['template_dir']}/nay_template.txt",
    'body_template': f"{params['template_dir']}/body_template.txt",
    'char_template': f"{params['template_dir']}/character_template.txt",
    'continue_template': f"{params['template_dir']}/continue_template.txt",
    'goal_eval_template': f"{params['template_dir']}/goal_eval_template.txt",
    'goal_thought_eval_template': f"{params['template_dir']}/goal_thought_eval_template.txt",
    'set_goal_template': f"{params['template_dir']}/set_goal_template.txt",
    'statement_template': f"{params['template_dir']}/statement_template.txt",
    'summarize_template': f"{params['template_dir']}/summarize_template.txt",
    'synthesize_template': f"{params['template_dir']}/synthesize_template.txt",
    'char_card': params['char_card_path'],
    'thoughts': f"{params['work_dir']}/thoughts.json",
    'goals': f"{params['work_dir']}/goals.json",
    'goals_met': f"{params['results_dir']}/goals_met.json",
    'goals_failed': f"{params['results_dir']}/goals_failed.json",
    'answers': f"{params['work_dir']}/answers.json",
    'thoughts_persistent': f"{params['results_dir']}/thoughts.json",
    'goals_persistent': f"{params['results_dir']}/goals.json",
    'answers_persistent': f"{params['results_dir']}/answers.json",
    'char_log': params['char_log_path'],
    'squire': f"{params['squire_path']}/squire.py",
    'squire_template': f"{params['squire_path']}/template.txt",
    'squire_keyword_template': f"{params['squire_path']}/keyword_template.txt",
    'squire_question': f"{params['squire_path']}/question.txt",
    'squire_model': params['model_path']
}
"""

file_queue, text_queue, squire_queue, response_queue, aggregate_queue, send_queue, receive_queue \
    = (asyncio.Queue(), asyncio.Queue(), asyncio.Queue(), asyncio.Queue(),
       asyncio.Queue(), asyncio.Queue(), asyncio.Queue(),)
