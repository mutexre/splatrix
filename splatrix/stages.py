"""Pipeline stage and state enums.

Stage and StageState are canonical in protocol.py; re-exported here for
backward compatibility with existing imports.
"""

from .protocol import Stage, StageState  # noqa: F401

from enum import Enum


class PipelineState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
