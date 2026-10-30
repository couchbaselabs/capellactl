"""Process exit codes (docs/release-1.0.0/00-architecture.md section 5.3).

These are the only exit codes capellactl uses. Code must refer to the names, never to numbers.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    CHANGES = 2  # plan/drift --detailed-exitcode found changes; also click usage errors
    CONFIG_INVALID = 3
    BLOCKED = 4
    TIMEOUT = 5
    INTERRUPTED = 130


class CliExit(Exception):
    """Raised anywhere to end the command with a message and an exit code.

    `message` says what happened, `action` what the reader can do about it (CAP-063): every CliExit with a message
    gives an action."""

    def __init__(self, code: ExitCode, message: str = "", topic: str | None = None, action: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.topic = topic
        self.action = action
