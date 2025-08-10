import sys
import inspect
from datetime import datetime



# Some timestamp generators
def make_now():
    now = datetime.now()
    yield now


def long_date():
    now = datetime.now()
    yield f"""{now.strftime('%A')}, {now.strftime('%B')} {now.strftime('%d')}, {now.strftime('%Y')}"""


def time():
    now = datetime.now()
    yield f"""{now.strftime('%H')}:{now.strftime('%M')}:{now.strftime('%S')}"""


def log_date_time():
    yield f"{next(long_date())}, {next(time())}: "


def log_timestamp():
    now = datetime.now()
    yield datetime.timestamp(now)


# Log printing function with options
def print_v(item, verbose_flag=True, out_handle: str = 'script_name', timestamp=True):
    prefix = f"[{out_handle}] "
    if timestamp:
        prefix += next(log_date_time())
    if verbose_flag:
        print(prefix + str(item), file=sys.stderr)


def get_fcn_name():
    frame = inspect.stack()
    return frame[2].function
