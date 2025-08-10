import os
from pathlib import Path
from shutil import copyfile

from modules.logutils import *
from modules.ooba_api_old import print_response_stream
# from modules.saveutils import *
# from modules.tokenutils import *
from modules.stringutils import *
# from modules.appraiseutils import *
# from modules.scriptutils import *
# from modules.api import start_server, send_data, receive_request
# from modules.sigutils import signal_manager, signal

from modules.config import params

# Aggregates text content from the queue
async def aggregate_text(statement, text, body, chara_text, thoughts, answers, convo) -> str:
    await send_update()
    print_v("Aggregator waiting for text", params['verbose'])

    # Make timestamp
    time_stamp = f"\nCurrent Date: {next(long_date())}\nCurrent Local Time: {next(time())}"

    aggregated_text = '\nAnswer: '

    # Asynchronously get text from Squire
    aggregated_text += text
    print_v(f'Aggregator found new output', params['verbose'])

    # Format character text using the template
    chara_text = chara_text.format(
        persona=attributes['char_persona'].strip(),
        scenario=attributes['world_scenario'].strip(),
    )

    # Tasks to process answers, thoughts and conversation into strings
    answer_loader = make_answers_string(answers, 400)
    thought_loader = make_thoughts_string(thoughts)
    statement_loader = last_statement_thought(convo, statement)
    convo_loader = make_convo_string(convo)

    # Gather answers, thoughts and conversation text before moving on
    answer_text, thought_text, statement_text, convo_text = await asyncio.gather(
        answer_loader, thought_loader, statement_loader, convo_loader)

    print_v('Preparing final prompt', params['verbose'])
    final_prompt = llama_squeeze(
        chara_text + convo_text + time_stamp
        + thought_text + statement_text
        + answer_text
        + aggregated_text
        + body + '\n')  # Llama gives null output when prompt does not end with newline

    print_v('Generated prompt', params['verbose'])
    print_v(f'Approximate length: {llama_token_length(final_prompt)} tokens', params['verbose'])
    return final_prompt


# Function to handle rx/tx to the user-facing LLM
async def exchange(
        aggregated_queue: asyncio.Queue,
        webui_queue: asyncio.Queue,
        script_queue: asyncio.Queue,
        retry_delay=params['retry_delay']
):
    aggregated_text = await aggregated_queue.get()
    response_done = False
    await send_update('start', 'webui')
    while not response_done:
        try:
            response_done = await print_response_stream(assure_string(aggregated_text), webui_queue, loop)
        except ConnectionError as e:
            print_v(e)
            print_v(f'Waiting for {retry_delay} seconds, then trying again')
            await asyncio.sleep(retry_delay)
    response = await webui_queue.get()
    await send_update('stop', 'webui')

    # Functions that write to the same file are staggered
    if response:
        gathered_question = await asyncio.gather(
            parse_question(response),
            parse_save_thought(response, loop))
        parsed_question = assure_string(gathered_question[0])
        await parse_save_goal(response, loop),
        await asyncio.gather(parse_save_speech(response), script_queue.put(parsed_question))


async def send_to_squire(in_queue: asyncio.Queue):
    await signal('squire')
    text = await in_queue.get()
    if text == '' or not text:
        print_v('Continuing without asking a question - writing loopback reply')
        await loop.run_in_executor(None, copyfile, path['continue_template'], path['squire_out'])

    else:
        print_v('Got question text. Preparing to write question.txt', params['verbose'])
        await write_text_file(text, path['squire_question'])

        # Pass the CUDA_VISIBLE_DEVICES parameter when running Squire
        if params['CUDA_VISIBLE_DEVICES']:
            prefix = f"CUDA_VISIBLE_DEVICES={params['CUDA_VISIBLE_DEVICES']}"
        else:
            prefix = ''

        args = (
            '-o', path['squire_out'],
            '-l', path['squire_model'],
            '-m', path['squire_template'],
            '-q', path['squire_question'],
            '-w', path['squire_keyword_template'],
            '-v'
        )

        # Handle a blank input, i.e. during first iteration
        if text.strip() == '':
            await write_text_file(
                'You have yet to ask a question.',
                path['squire_out']
            )
        else:
            await send_update('start')
            code = await run_script(path['squire'], *args, prefix=prefix)
            await send_update('stop')

            # Handle Squire failing by writing an output file communicating that
            if code != 0:
                await write_text_file(
                    'Could not return an answer. Try rephrasing your question and asking again.',
                    path['squire_out']
                )
    await asyncio.sleep(0)


# Situation appraisal block
async def appraise(answered: bool, answer_attempts: int, answers_synth: str, thoughts: dict, llm) -> bool:
    print_v('Entering appraise function', params['verbose'])
    # Initialize a new goals list
    new_goals_list = {'goals': []}

    # Summarize our thoughts and load any goals we have
    goals_task = load_json_data(path['goals'])
    thoughts_task = chunk_process(thoughts['thoughts'], llm)
    failed_goals_task = load_json_data(path['goals_failed'])
    met_goals_task = load_json_data(path['goals_met'])

    await send_update('start', 'thoughts_sum')
    goals, thoughts_sum, failed_goals_list, met_goals_list = await asyncio.gather(
        goals_task, thoughts_task, failed_goals_task, met_goals_task)
    await send_update('stop', 'thoughts_sum')

    # Launch goal appraisal when question was answered
    if answered and not check_nil(goals) and not check_nil(thoughts_sum):
        goals_with_status = await check_goals(goals['goals'], thoughts_sum, answers_synth, llm)

        met_goals_list['goals'].append(goals_with_status['met'])
        new_goals_list['goals'] = goals_with_status['unmet']

        # Generate new goal if you don't have one
        if not new_goals_list['goals']:
            goal = await new_goal(
                met_goals_list['goals'],
                new_goals_list['goals'],
                f"{attributes['char_persona']}\n{attributes['world_scenario']}",
                llm
            )
            new_goals_list['goals'].append(goal)

            # Prepare goal prefix for chat history, then load chat history and write to it
            # await write_crumb(goal, prefix=f"{attributes['char_name']} has a goal: ")

        write_goals_task = write_json_data(new_goals_list, path['goals'])
        write_persistent_task = append_json_data(new_goals_list['goals'], 'goals', path['goals_persistent'])
        write_met_goals_task = write_json_data(met_goals_list, path['goals_met'])
        await asyncio.gather(write_goals_task, write_persistent_task, write_met_goals_task)
        return False

    # If our attempts to answer a question are repeatedly frustrated, we restate our goals in a new way
    # We otherwise wipe the work files clean and reset the script
    elif answer_attempts >= params['answer_attempts_max']:
        print_v(f"Attempted to answer {answer_attempts} times - recording failure")
        if not check_nil(goals):
            await send_update('start', 'goals_sum')
            goals_sum = await process(goals['goals'], llm)
            await send_update('stop', 'goals_sum')

            print_v(f"Restated goal for crumb: {goals_sum}", params['verbose'])
            failed_goals_list['goals'].append(goals['goals'])

            await send_update('goal_failed')
            failed_goals_task = write_json_data(failed_goals_list, path['goals_failed'])
            crumb_task = write_crumb(
                goals_sum,
                prefix=f"I wasn't successful in doing something I wanted to do. The goal I had in mind - ")
            reset_task = reset(loop)
            await asyncio.gather(reset_task, crumb_task, failed_goals_task)

            goal = await new_goal(
                met_goals_list['goals'],
                new_goals_list['goals'],
                f"{attributes['char_persona']}\n{attributes['world_scenario']}",
                llm
            )

            goal_task = append_json_data(goal, 'goals', path['goals'])
            crumb_task = write_crumb(goal, prefix=f"I thought of something I would like to do. ")
            persistent_task = append_json_data(goal, 'goals', path['goals_persistent'])
            await asyncio.gather(goal_task, crumb_task, persistent_task)

            return True

    return False


# Main function that runs the script
async def main():
    # Initialize state trackers
    answer_attempts = 0
    first_run = await reset(loop)
    answered = False
    question = ''

    # Load files that only need to be loaded once
    statement, body, chara_text = await asyncio.gather(
        read_text_file(path['statement_template']),
        read_text_file(path['body_template']),
        read_text_file(path['char_template']),
    )

    # Create LLM for use by appraisal functions
    llm = await llama(loop)

    # Monitor the directory for new text files
    asyncio.run_coroutine_threadsafe(monitor_directory(params['squire_out_dir'], file_queue, text_queue, loop), loop)

    # Start server
    server_task = await asyncio.to_thread(start_server, send_data, receive_request,
                                                  host=params['host'], port=params['port'])
    asyncio.run_coroutine_threadsafe(server_task, loop)

    # Start signal manager
    # asyncio.run_coroutine_threadsafe(signal_manager(receive_queue, send_queue), loop)
    manager_task = await asyncio.to_thread(signal_manager, receive_queue, send_queue)
    asyncio.run_coroutine_threadsafe(manager_task, loop)

    while True:
        # Load all data needed to generate a prompt. Should be rate-limited by text_queue.get()
        await signal('pause')
        text, thoughts, answers, convo = await asyncio.gather(
            text_queue.get(),
            load_json_data(path['thoughts']),
            load_json_data(path['answers']),
            load_json_data(path['char_log'])
        )

        await signal('pause')
        if answered or first_run:
            answer_attempts = 0

            # Task to send text to the LLM, then Squire
            exchange_task = loop.create_task(exchange(aggregate_queue, response_queue, squire_queue))

            # Generate the prompt
            await signal('pause')
            aggregate_task = loop.create_task(
                aggregate_text(statement, text, body, chara_text, thoughts, answers, convo))

            prompt = await aggregate_task

            # Await tasks for getting the prompt, processing it, then sending the reply to Squire
            aggregate_put_task = aggregate_queue.put(prompt)
            await aggregate_put_task

            await signal('pause')
            await exchange_task

        else:
            # Ask again rather than ascending the information
            squire_put_task = squire_queue.put(question)
            answer_attempts += 1
            await squire_put_task

        # Task to launch Squire in response to a question by the LLM
        await signal('pause')
        squire_task = loop.create_task(send_to_squire(squire_queue))
        await squire_task

        if first_run:
            first_run = False

        # Turn the answers into a coherent output, if there are enough to work with
        await signal('pause')
        if len(answers['answers']) > 0:
            # We summarize the answers in hope of faster overall execution, but an answer list can also be supplied
            await send_update('start', 'answers_synth')
            answers_synth = await chunk_process(answers['answers'], llm)
            await send_update('stop', 'answers_synth')

            # Check if question has been answered
            await signal('pause')
            [question, answered] = await check_answered(answers_synth, llm)

            # Launch appraisal loop
            await signal('pause')
            appraise_task = loop.create_task(appraise(answered, answer_attempts, answers_synth, thoughts, llm))
            first_run = await appraise_task
            if first_run:
                await text_queue.put('Think about your new goal.')


if __name__ == "__main__":
    # Set environment variables
    os.environ["CUDA_VISIBLE_DEVICES"] = str(params['CUDA_VISIBLE_DEVICES'])

    # Check file paths before entering loop
    paths_found = 0
    for key in path.keys():
        if key:
            f = Path(path[key])
            if f.is_file():
                print_v(f"Found {path[key]}", params['verbose'])
                paths_found += 1
            elif f.is_dir():
                print_v(f"{path[key]} is a directory. Expected a file.")
            elif not f.exists():
                print_v(f"{path[key]} not found.")
    print_v(f"Found {paths_found}/{len(path)} input files")
    if paths_found != len(path):
        raise FileNotFoundError("Some required input files could not be found. See output for details. Check your "
                                "parameters and ensure the files are in place.")

    path.update({'squire_out': f"{params['squire_out_dir']}/out.txt"})

    # Enter the main event loop
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(main())
    loop.run_forever()
