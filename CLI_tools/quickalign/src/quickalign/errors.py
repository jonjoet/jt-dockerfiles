"""Errors shared by the CLI, core and optional browser interface."""
class QuickalignError(Exception):
    """Expected actionable job failure."""

class ValidationError(QuickalignError):
    """Invalid input or unsafe persisted state."""

class CommandError(QuickalignError):
    def __init__(self, message, *, command=None, returncode=None, logs=None):
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.logs = logs
