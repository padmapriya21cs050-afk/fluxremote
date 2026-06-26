# fluxremote/backend/main.py
import logging
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Set, Optional, List
import json
import uuid
import asyncio

from models import DeviceRegister, SessionCreate, SessionResponse
import database as db
import auth

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fluxremote.backend")

app = FastAPI(
    title="FluxRemote Signalling and Relay Server",
    description="Secure, high-speed remote desktop control relay server.",
    version="1.0.0"
)

# Enable CORS for frontend and API usage
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startup DB initialization
@app.on_event("startup")
def startup_event():
    db.init_db()
    logger.info("FluxRemote Backend started and database schema validated.")

# --- HTTP ENDPOINTS ---

@app.get("/")
def read_root():
    return {
        "app": "FluxRemote Signal Server",
        "status": "operational",
        "active_connections": len(connection_manager.hosts) + len(connection_manager.viewers)
    }

@app.post("/api/devices/register")
def register_device(device: DeviceRegister):
    # Hashes the password used for connecting to the host
    hash_pwd = auth.hash_password(device.access_password)
    success = db.register_device(device.device_id, device.device_name, hash_pwd)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to register or update device configuration."
        )
    return {"message": "Device registered successfully.", "device_id": device.device_id}

@app.get("/api/devices/online")
def list_online_devices():
    return db.get_online_devices()

@app.post("/api/sessions/create", response_model=SessionResponse)
def create_session(session_req: SessionCreate):
    device = db.get_device(session_req.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Target device not registered.")
    
    # DEMO MODE: Password verification temporarily disabled.
    # Automatically authorize the session whenever the device exists and is online.
    if not device["is_online"]:
        raise HTTPException(status_code=400, detail="Target host desktop is currently offline.")
        
    session_id = str(uuid.uuid4())
    viewer_id = str(uuid.uuid4())
    host_id = device["device_id"]
    
    created = db.create_session(session_id, device["device_id"], viewer_id, host_id)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create session.")
    
    return {
        "session_id": session_id,
        "device_id": device["device_id"],
        "viewer_id": viewer_id,
        "host_id": host_id,
        "status": "authorized",
        "created_at": db.datetime.now()
    }


# --- REAL-TIME WEBSOCKET RELAY & SIGNALING ENGINE ---

class ConnectionManager:
    def __init__(self):
        # Maps device_id -> Host WebSocket
        self.hosts: Dict[str, WebSocket] = {}
        # Maps device_id -> Set of Viewer WebSockets (multiple client support)
        self.viewers: Dict[str, Set[WebSocket]] = {}
        # Maps viewer WebSocket -> device_id it's watching
        self.viewer_targets: Dict[WebSocket, str] = {}
        # Simple stats tracking per session for history records
        self.bytes_transferred: Dict[str, int] = {}
        self.session_start_times: Dict[str, float] = {}

    async def register_host(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.hosts[device_id] = websocket
        db.update_device_status(device_id, is_online=True)
        logger.info(f"Host desktop {device_id} is now ONLINE.")

    def unregister_host(self, device_id: str):
        if device_id in self.hosts:
            del self.hosts[device_id]
        db.update_device_status(device_id, is_online=False)
        logger.info(f"Host desktop {device_id} is now OFFLINE.")

    async def register_viewer(self, device_id: str, websocket: WebSocket) -> bool:
        await websocket.accept()
        if device_id not in self.hosts:
            await websocket.send_text(json.dumps({"type": "error", "message": "Host is offline."}))
            await websocket.close()
            return False
            
        if device_id not in self.viewers:
            self.viewers[device_id] = set()
        self.viewers[device_id].add(websocket)
        self.viewer_targets[websocket] = device_id
        logger.info(f"Viewer connected to desktop {device_id}. Total viewers: {len(self.viewers[device_id])}")
        
        # Notify host that a viewer joined
        try:
            await self.hosts[device_id].send_text(json.dumps({"type": "viewer_status", "status": "connected"}))
        except Exception as e:
            logger.error(f"Failed to send viewer notification to host: {e}")
            
        return True

    async def unregister_viewer(self, websocket: WebSocket):
        if websocket in self.viewer_targets:
            device_id = self.viewer_targets[websocket]
            if device_id in self.viewers:
                self.viewers[device_id].discard(websocket)
                if not self.viewers[device_id]:
                    del self.viewers[device_id]
                    # Inform host that all viewers disconnected
                    if device_id in self.hosts:
                        try:
                            await self.hosts[device_id].send_text(json.dumps({"type": "viewer_status", "status": "disconnected"}))
                        except Exception:
                            pass
            del self.viewer_targets[websocket]
            logger.info(f"Viewer disconnected from desktop {device_id}.")

    async def relay_from_host(self, device_id: str, message: Any):
        """Relays screen video frames (binary or text) to all connected viewers."""
        if device_id in self.viewers:
            targets = list(self.viewers[device_id])
            size = len(message) if isinstance(message, (bytes, bytearray)) else len(str(message))
            
            # Record statistics
            self.bytes_transferred[device_id] = self.bytes_transferred.get(device_id, 0) + size
            
            # Send to all active viewers
            coros = []
            for ws in targets:
                try:
                    if isinstance(message, bytes):
                        coros.append(ws.send_bytes(message))
                    else:
                        coros.append(ws.send_text(message))
                except Exception:
                    pass
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)

    async def relay_from_viewer(self, websocket: WebSocket, message: str):
        """Relays interactive controls from a specific viewer to their target host."""
        if websocket in self.viewer_targets:
            device_id = self.viewer_targets[websocket]
            if device_id in self.hosts:
                try:
                    # Forward the JSON action parameters direct to host input queue
                    await self.hosts[device_id].send_text(message)
                except Exception as e:
                    logger.error(f"Error relaying event to host {device_id}: {e}")

connection_manager = ConnectionManager()


@app.websocket("/ws/host/{device_id}")
async def ws_host_endpoint(websocket: WebSocket, device_id: str):
    await connection_manager.register_host(device_id, websocket)
    connection_manager.session_start_times[device_id] = time.time()
    connection_manager.bytes_transferred[device_id] = 0
    
    try:
        while True:
            # Hosts send binary screens (JPEG) or JSON heartbeats/fps-control
            data = await websocket.receive()
            if "bytes" in data:
                # Direct binary JPEG frame broadcast
                await connection_manager.relay_from_host(device_id, data["bytes"])
            elif "text" in data:
                # Text heartbeats/status messages
                text_data = data["text"]
                if text_data == "heartbeat":
                    db.update_device_status(device_id, is_online=True)
                else:
                    await connection_manager.relay_from_host(device_id, text_data)
                    
    except WebSocketDisconnect:
        logger.warning(f"Host {device_id} disconnected unexpectedly.")
    finally:
        connection_manager.unregister_host(device_id)
        # Log session connection history
        duration = int(time.time() - connection_manager.session_start_times.get(device_id, time.time()))
        bytes_tx = connection_manager.bytes_transferred.get(device_id, 0)
        db.close_session(session_id=f"host_{device_id}", duration=duration, bytes_tx=bytes_tx)


@app.websocket("/ws/viewer/{device_id}")
async def ws_viewer_endpoint(websocket: WebSocket, device_id: str):
    success = await connection_manager.register_viewer(device_id, websocket)
    if not success:
        return

    try:
        while True:
            # Viewers send JSON keystroke inputs, mouse co-ords, clicks, and scroll rates
            message = await websocket.receive_text()
            if message == "heartbeat":
                continue
            await connection_manager.relay_from_viewer(websocket, message)
            
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.unregister_viewer(websocket)
