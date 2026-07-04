# fluxremote/backend/models.py
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class DeviceRegister(BaseModel):
    device_id: str = Field(..., description="Unique alphanumeric hardware/software device identifier")
    device_name: str = Field(..., description="User-friendly name of the desktop machine")
    access_password: str = Field(..., description="Security connection password for remote access validation")

class DeviceStatusResponse(BaseModel):
    device_id: str
    device_name: str
    is_online: bool
    last_seen: datetime

class SessionCreate(BaseModel):
    device_id: str
    access_password: str

class SessionResponse(BaseModel):
    session_id: str
    device_id: str
    viewer_id: str
    host_id: str
    status: str
    created_at: datetime
    session_token: Optional[str] = None
    pairing_code: Optional[str] = None
