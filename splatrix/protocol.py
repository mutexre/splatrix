"""Client-server protocol for Splatrix processing.

Defines the JSON message format exchanged over WebSocket between the
UI client and the processing server.  Shared by both sides.

Protocol version history:
  1 — initial version
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Operation(Enum):
    """Coarse-grained operations the server can execute."""
    DATA = "data"
    TRAINING = "training"
    EXPORT = "export"


class Stage(Enum):
    """Fine-grained progress sub-stages reported within an operation."""
    FRAMES = "frames"
    FEATURE_EXTRACT = "feature_extract"
    FEATURE_MATCH = "feature_match"
    RECONSTRUCTION = "reconstruction"
    TRAINING = "training"
    EXPORT = "export"


class StageState(Enum):
    """Client-side validity state for a project stage."""
    NO_DATA = "no_data"
    VALID = "valid"
    OUTDATED = "outdated"


class RequestStatus(Enum):
    """Server-side status of a processing request."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CRASHED = "crashed"


# ---------------------------------------------------------------------------
# Dependency graph — which Operation depends on which
# ---------------------------------------------------------------------------

OPERATION_DEPENDENCIES: dict[Operation, list[Operation]] = {
    Operation.DATA: [],
    Operation.TRAINING: [Operation.DATA],
    Operation.EXPORT: [Operation.TRAINING],
}


# ---------------------------------------------------------------------------
# Stage ↔ Operation mapping
# ---------------------------------------------------------------------------

OPERATION_STAGES: dict[Operation, list[Stage]] = {
    Operation.DATA: [
        Stage.FRAMES,
        Stage.FEATURE_EXTRACT,
        Stage.FEATURE_MATCH,
        Stage.RECONSTRUCTION,
    ],
    Operation.TRAINING: [Stage.TRAINING],
    Operation.EXPORT: [Stage.EXPORT],
}


# ---------------------------------------------------------------------------
# Client → Server messages
# ---------------------------------------------------------------------------

@dataclass
class HelloMsg:
    protocol_version: int
    client_id: str
    type: str = "hello"


@dataclass
class RunStageMsg:
    client_id: str
    project_id: str
    stage: str              # Stage.value
    input_dir: str
    output_dir: str
    operation: str = ""     # deprecated, use stage
    depends_on: dict[str, int] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    type: str = "run_stage"


@dataclass
class CancelMsg:
    request_id: str
    type: str = "cancel"


@dataclass
class GetStatusMsg:
    client_id: str
    project_id: str
    type: str = "get_status"


@dataclass
class GetLogMsg:
    request_id: str
    type: str = "get_log"


@dataclass
class AcknowledgeMsg:
    request_id: str
    type: str = "acknowledge"


@dataclass
class RejectMsg:
    request_id: str
    type: str = "reject"


# ---------------------------------------------------------------------------
# Server → Client events
# ---------------------------------------------------------------------------

@dataclass
class HelloEvent:
    protocol_version: int
    server_id: str
    type: str = "hello"


@dataclass
class ErrorEvent:
    code: str
    message: str
    type: str = "error"


@dataclass
class AcceptedEvent:
    request_id: str
    type: str = "accepted"


@dataclass
class ProgressEvent:
    request_id: str
    stage: str              # Stage.value
    progress: float         # 0.0 – 1.0
    type: str = "progress"


@dataclass
class CompletedEvent:
    request_id: str
    output_dir: str
    type: str = "completed"


@dataclass
class FailedEvent:
    request_id: str
    error: str
    type: str = "failed"


@dataclass
class CancelledEvent:
    request_id: str
    type: str = "cancelled"


@dataclass
class AcknowledgedEvent:
    request_id: str
    type: str = "acknowledged"


@dataclass
class RejectedEvent:
    request_id: str
    type: str = "rejected"


@dataclass
class StatusEvent:
    active_requests: list[dict[str, Any]]
    type: str = "status"


@dataclass
class LogEvent:
    request_id: str
    content: str
    type: str = "log"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def to_json(msg) -> str:
    """Serialize a message dataclass to a JSON string."""
    return json.dumps(asdict(msg), separators=(",", ":"))


def from_json(raw: str | bytes) -> dict[str, Any]:
    """Deserialize a JSON string to a plain dict.

    Raises ``ValueError`` on malformed JSON.
    """
    return json.loads(raw)


# Map message type strings to their dataclass for client→server messages
CLIENT_MSG_TYPES: dict[str, type] = {
    "hello": HelloMsg,
    "run_stage": RunStageMsg,
    "cancel": CancelMsg,
    "get_status": GetStatusMsg,
    "get_log": GetLogMsg,
    "acknowledge": AcknowledgeMsg,
    "reject": RejectMsg,
}

# Map event type strings to their dataclass for server→client events
SERVER_EVENT_TYPES: dict[str, type] = {
    "hello": HelloEvent,
    "error": ErrorEvent,
    "accepted": AcceptedEvent,
    "progress": ProgressEvent,
    "completed": CompletedEvent,
    "failed": FailedEvent,
    "cancelled": CancelledEvent,
    "acknowledged": AcknowledgedEvent,
    "rejected": RejectedEvent,
    "status": StatusEvent,
    "log": LogEvent,
}


def parse_client_msg(data: dict[str, Any]) -> Optional[object]:
    """Instantiate the appropriate client message dataclass from a dict.

    Returns ``None`` if the type is unknown.
    """
    msg_type = data.get("type")
    cls = CLIENT_MSG_TYPES.get(msg_type)
    if cls is None:
        return None
    fields = {k: v for k, v in data.items() if k in {f.name for f in cls.__dataclass_fields__.values()}}
    return cls(**fields)


def parse_server_event(data: dict[str, Any]) -> Optional[object]:
    """Instantiate the appropriate server event dataclass from a dict.

    Returns ``None`` if the type is unknown.
    """
    msg_type = data.get("type")
    cls = SERVER_EVENT_TYPES.get(msg_type)
    if cls is None:
        return None
    fields = {k: v for k, v in data.items() if k in {f.name for f in cls.__dataclass_fields__.values()}}
    return cls(**fields)
