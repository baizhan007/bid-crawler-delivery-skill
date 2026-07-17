"""Process-local guard that makes replay adapters strictly offline."""

from __future__ import annotations

import asyncio
import http.client
import os
import socket
import subprocess
import urllib.request
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator
from unittest.mock import patch

from .errors import NetworkAccessBlocked


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise NetworkAccessBlocked("Network and subprocess access are disabled during fixture replay")


@contextmanager
def offline_network_guard() -> Iterator[None]:
    """Block common network paths for both adapter import and execution.

    The low-level socket patches cover networking libraries that are not known
    to the factory. Subprocess creation is blocked as well so replay code cannot
    escape the guard by invoking curl, PowerShell, or another interpreter.
    """

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, "connect", _blocked))
        stack.enter_context(patch.object(socket.socket, "connect_ex", _blocked))
        stack.enter_context(patch.object(socket, "create_connection", _blocked))
        stack.enter_context(patch.object(socket, "getaddrinfo", _blocked))
        stack.enter_context(patch.object(http.client.HTTPConnection, "connect", _blocked))
        stack.enter_context(patch.object(http.client.HTTPSConnection, "connect", _blocked))
        stack.enter_context(patch.object(urllib.request, "urlopen", _blocked))
        stack.enter_context(patch.object(asyncio.BaseEventLoop, "create_connection", _blocked))
        stack.enter_context(patch.object(asyncio.BaseEventLoop, "create_datagram_endpoint", _blocked))
        stack.enter_context(patch.object(subprocess, "Popen", _blocked))
        stack.enter_context(patch.object(subprocess, "run", _blocked))
        stack.enter_context(patch.object(subprocess, "call", _blocked))
        stack.enter_context(patch.object(subprocess, "check_call", _blocked))
        stack.enter_context(patch.object(subprocess, "check_output", _blocked))
        stack.enter_context(patch.object(os, "system", _blocked))
        stack.enter_context(patch.object(os, "popen", _blocked))
        try:
            import requests.sessions
        except ImportError:
            pass
        else:
            stack.enter_context(patch.object(requests.sessions.Session, "request", _blocked))
        yield
