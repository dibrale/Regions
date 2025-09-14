import logging
from dataclasses import dataclass
from functools import partial
from typing import Callable, Any

from postmaster import Postmaster


def inject(postmaster: Postmaster, source: str, role: str, destination: str, content: str) -> None:
    """Inject a message into the distributed system using the postmaster.

    Args:
        postmaster (Postmaster): The postmaster instance to use for sending messages.
        source (str): The source identifier for the message (e.g., "region-a").
        role(str): The role of the message ('request' or 'reply').
        destination (str): The destination identifier for the message (e.g., "region-b").
        content (str): The message content to be sent.

    This function places the message dictionary into the postmaster's message queue.
    """
    msg = dict(source=source, destination=destination, role=role, content=content)
    postmaster.messages.put_nowait(msg)
    logging.info(f"Injected {role} from '{source}' to '{destination}'")

@dataclass
class Injector:
    """Context manager for injecting messages with a fixed role and source identifier using a fixed postmaster instance.

    The Injector class provides a convenient way to send multiple messages with the same source
    using a context manager. It pre-configures the source address and default role so that only destination and
    content need to be specified when sending messages.

    The `send` method uses the default role (set at initialization), while `request` and `reply` methods override
    the role to 'request' and 'reply' respectively.

    Example:
        >>> from postmaster import Postmaster
        >>> postmaster = Postmaster()
        >>> with Injector(postmaster, "user") as injector:
        ...     injector.send("region-b", "Hello from user")  # Uses default role='reply'
        ...     injector.request("region-c", "Request message")  # Explicitly sets role='request'
        ...     injector.reply("region-d", "Reply message")  # Explicitly sets role='reply'

    Attributes:
        postmaster (Postmaster): The postmaster instance used for message delivery.
        source (str): The fixed source identifier for all messages sent through this injector.
        role (str): The default role used by the `send` method (default: 'reply').

    Note:
        - It may be convenient to set the name of the injector (e.g., "user", "admin") as the injector's name. For example: with Injector(postmaster, "user") as user: ...
        - Injector objects can be nested. For example: with Injector(postmaster, "user") as user: with user = Injector(postmaster, "admin"): ...

    Side Effects:
        - Injectors can be used to prime the system with persistent replies that will be stored in the internal _incoming_replies dictionary of a receiving 'Region' instance.
        - Instances of the 'Region' class only retain one content string per source at any given time, with any new reply replacing the previous one.
        - Injecting an empty reply using the same source identifier effectively deletes an original reply retained by a 'Region' instance, though an empty string keyed to the source will remain in its _incoming_replies dictionary.
    """
    postmaster: Postmaster
    source: str
    role: str = 'reply'

    def __enter__(self):
        self.send = partial(inject, self.postmaster, self.source, self.role)
        self.request = partial(inject, self.postmaster, self.source, 'request')
        self.reply = partial(inject, self.postmaster, self.source, 'reply')
        return self

    def __exit__(self, *exc):
        pass        # nothing special to clean up

class Addressograph:
    """
    Decorator that injects a pre-configured Injector instance into a function.

    Note:
        - The decorated function must accept a parameter named exactly like `injector_name`.
        - Multiple injectors can be added with different `injector_name` values.

    Example:
        Using a single decorator:

        >>> @Addressograph(postmaster, "user", role="request", injector_name="user")
        >>> def my_func(user):
        >>>     user.send("region-b", "Hello")

        Using multiple decorators:

        >>> @Addressograph(postmaster, "user", role="request", injector_name="user")
        >>> @Addressograph(postmaster, "admin", role="reply", injector_name="admin")
        >>> def process_messages(user, admin):
        >>>     user.send("region-b", "User request")
        >>>     admin.send("region-c", "Admin reply")
    """

    def __init__(self, postmaster: Postmaster, source: str, role: str = 'reply', injector_name: str = 'injector'):
        self.postmaster = postmaster
        self.source = source
        self.role = role
        self.injector_name = injector_name  # Name of the function parameter

    def __call__(self, func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            # Create the injector
            injector = Injector(self.postmaster, self.source, self.role)

            # Add injector to kwargs under the specified name
            kwargs[self.injector_name] = injector

            # Call the function with the injector
            with injector:
                return func(*args, **kwargs)

        return wrapper