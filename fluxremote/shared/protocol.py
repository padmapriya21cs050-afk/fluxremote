# fluxremote/shared/protocol.py
"""
FluxRemote Shared Protocol Definitions
Defines message structures, action types, and serialization formats.
"""

import json
from typing import Dict, Any

class MessageType:
    # Connection messages
    AUTH_REQ = "auth_req"
    AUTH_RESP = "auth_resp"
    HEARTBEAT = "heartbeat"
    
    # Desktop control messages
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_DOUBLE_CLICK = "mouse_double_click"
    MOUSE_RIGHT_CLICK = "mouse_right_click"
    MOUSE_SCROLL = "mouse_scroll"
    
    KEY_PRESS = "key_press"
    KEY_RELEASE = "key_release"
    KEY_SHORTCUT = "key_shortcut"
    
    CLIPBOARD_SYNC = "clipboard_sync"
    
    # Control/config updates
    FPS_UPDATE = "fps_update"
    QUALITY_UPDATE = "quality_update"
    STATUS_MSG = "status_msg"


def create_json_message(msg_type: str, payload: Dict[str, Any]) -> str:
    """Creates a standardized JSON text packet."""
    return json.dumps({
        "type": msg_type,
        "payload": payload
    })


def parse_message(raw_msg: str) -> Dict[str, Any]:
    """Parses incoming JSON text packets."""
    try:
        return json.loads(raw_msg)
    except json.JSONDecodeError:
        return {"type": "error", "payload": {"message": "Invalid JSON format"}}
