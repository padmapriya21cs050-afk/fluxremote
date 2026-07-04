# fluxremote/backend/main.py
import logging
import time
import os
import json
import uuid
import secrets
import asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Set, Optional, List
from dotenv import load_dotenv, find_dotenv
from google import genai

from models import DeviceRegister, SessionCreate, SessionResponse
import database as db
import auth
from tunnel_auth import extract_ws_auth_token, is_ws_request_authorized

# Set up logging first so environment loading can be reported.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fluxremote.backend")
WS_TUNNEL_TOKEN = os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")


def _load_dotenv_paths() -> List[str]:
    loaded_files: List[str] = []
    env_paths = [
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
    ]

    for path in env_paths:
        if os.path.isfile(path) and load_dotenv(path, override=False):
            loaded_files.append(path)

    root_dotenv = find_dotenv(usecwd=True)
    if root_dotenv and root_dotenv not in loaded_files and load_dotenv(root_dotenv, override=False):
        loaded_files.append(root_dotenv)

    if loaded_files:
        logger.info("Loaded .env files: %s", ", ".join(loaded_files))
    else:
        logger.info("No .env files loaded by python-dotenv; using existing environment variables.")

    return loaded_files


_load_dotenv_paths()


def get_gemini_api_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY")


logger.info("Gemini API key detected: %s", "YES" if get_gemini_api_key() else "NO")

app = FastAPI(
    title="FluxRemote Signalling and Relay Server",
    description="Secure, high-speed remote desktop control relay server.",
    version="1.0.0"
)

TUNNEL_PATTERNS = ["trycloudflare.com", "ngrok.io", "tailscale.net"]


async def _ensure_ws_authorized(websocket: WebSocket) -> bool:
    if not WS_TUNNEL_TOKEN:
        return True

    headers = dict(websocket.headers.items()) if websocket.headers else {}
    if is_ws_request_authorized(dict(websocket.query_params), WS_TUNNEL_TOKEN, headers):
        return True

    await websocket.accept()
    await websocket.send_text(json.dumps({"type": "error", "message": "Invalid or missing tunnel token."}))
    await websocket.close(code=1008)
    return False


def is_tunnel_url(origin: str) -> bool:
    origin = origin or ""
    return any(pattern in origin for pattern in TUNNEL_PATTERNS)


class GeminiClient:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> Any:
        return self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )


def _extract_gemini_text(answer: Any) -> str:
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    text_value = getattr(answer, "text", None)
    if isinstance(text_value, str) and text_value.strip():
        return text_value.strip()

    if isinstance(answer, dict):
        candidates = answer.get("candidates")
        if isinstance(candidates, list) and candidates:
            first = candidates[0]
            if isinstance(first, dict):
                content = first.get("content") or {}
                if isinstance(content, dict):
                    parts = content.get("parts") or []
                    if isinstance(parts, list):
                        for part in parts:
                            if isinstance(part, dict):
                                text = part.get("text")
                                if isinstance(text, str) and text.strip():
                                    return text.strip()
                if isinstance(first.get("text"), str) and first.get("text").strip():
                    return first.get("text").strip()

        output = answer.get("output")
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

        for field in ("text", "message", "response"):
            value = answer.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if hasattr(answer, "candidates"):
        for candidate in answer.candidates or []:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                text = getattr(part, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()

    return ""


class GeminiAssistant:
    @staticmethod
    def explain(prompt: str) -> str:
        api_key = get_gemini_api_key()
        if not api_key:
            logger.error("Gemini assistant request blocked: missing GEMINI_API_KEY.")
            return "Gemini API is not configured. Set GEMINI_API_KEY to enable AI assistance."

        client = GeminiClient(api_key)

        try:
            answer = client.generate(prompt)
            explanation = _extract_gemini_text(answer)
            if explanation:
                return explanation

            logger.error("Gemini assistant returned empty or unexpected response: %s", answer)
            return "Gemini returned an empty or unexpected response."
        except Exception as exc:
            logger.error("Gemini assistant request failure: %s", exc)
            return "Unable to reach Gemini for assistant analysis: Gemini API request failed."

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
    return {
        "message": "Device registered successfully.",
        "device_id": device.device_id,
        "tunnel_mode": is_tunnel_url(device.device_name if device.device_name else ""),
    }

@app.get("/api/devices/online")
def list_online_devices():
    return db.get_online_devices()

@app.post("/api/ai/explain")
def ai_explain_issue(request: Dict[str, Any]):
    """AI Assistant endpoint: explains connection issues and suggests fixes."""
    issue_type = request.get("type", "")
    context = request.get("context", "")
    logs = request.get("logs", "")
    
    prompt = f"""
    The user is experiencing a FluxRemote connection issue.
    
    Issue Type: {issue_type}
    Context: {context}
    Recent Logs: {logs}
    
    Please provide:
    1. A plain English explanation of what happened
    2. 2-3 recommended fixes
    3. If it's a network issue, suggest bandwidth/quality adjustments
    
    Be concise and actionable.
    """
    
    explanation = GeminiAssistant.explain(prompt.strip())
    # Support both client conventions: answer and explanation
    return {"answer": explanation, "explanation": explanation}

@app.post("/api/sessions/create", response_model=SessionResponse)
def create_session(session_req: SessionCreate):
    device = db.get_device(session_req.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Target device not registered.")

    if not device["is_online"]:
        raise HTTPException(status_code=400, detail="Target host desktop is currently offline.")

    if not auth.verify_password(session_req.access_password, device["access_password_hash"]):
        raise HTTPException(status_code=403, detail="Invalid access password.")

    session_id = str(uuid.uuid4())
    viewer_id = str(uuid.uuid4())
    host_id = device["device_id"]
    session_token = secrets.token_urlsafe(32)
    pairing_code = secrets.token_hex(3).upper()

    created = db.create_session(session_id, device["device_id"], viewer_id, host_id, session_token=session_token, pairing_code=pairing_code)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create session.")

    return {
        "session_id": session_id,
        "device_id": device["device_id"],
        "viewer_id": viewer_id,
        "host_id": host_id,
        "status": "authorized",
        "created_at": db.datetime.now(),
        "session_token": session_token,
        "pairing_code": pairing_code
    }


# --- REAL-TIME WEBSOCKET RELAY & SIGNALING ENGINE ---

class ConnectionManager:
    def __init__(self):
        # Maps device_id -> Host WebSocket for screen stream
        self.hosts: Dict[str, WebSocket] = {}
        # Maps device_id -> Set of Viewer WebSockets (multiple client support)
        self.viewers: Dict[str, Set[WebSocket]] = {}
        # Maps viewer WebSocket -> device_id it's watching
        self.viewer_targets: Dict[WebSocket, str] = {}
        # Maps device_id -> Host WebSocket for low-latency control tunnel
        self.host_controls: Dict[str, WebSocket] = {}
        # Maps device_id -> Set of Viewer WebSockets for control tunnel
        self.control_viewers: Dict[str, Set[WebSocket]] = {}
        # Maps viewer control WebSocket -> device_id it's targeting
        self.control_viewer_targets: Dict[WebSocket, str] = {}
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

    async def register_host_control(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.host_controls[device_id] = websocket
        logger.info(f"Host control tunnel connected for desktop {device_id}.")

    def unregister_host_control(self, device_id: str):
        if device_id in self.host_controls:
            del self.host_controls[device_id]

    async def register_viewer_control(self, device_id: str, websocket: WebSocket) -> bool:
        await websocket.accept()
        if device_id not in self.host_controls and device_id not in self.hosts:
            await websocket.send_text(json.dumps({"type": "error", "message": "Host control tunnel is offline."}))
            await websocket.close()
            return False

        if device_id not in self.control_viewers:
            self.control_viewers[device_id] = set()
        self.control_viewers[device_id].add(websocket)
        self.control_viewer_targets[websocket] = device_id
        return True

    async def unregister_viewer_control(self, websocket: WebSocket):
        if websocket in self.control_viewer_targets:
            device_id = self.control_viewer_targets[websocket]
            if device_id in self.control_viewers:
                self.control_viewers[device_id].discard(websocket)
                if not self.control_viewers[device_id]:
                    del self.control_viewers[device_id]
            del self.control_viewer_targets[websocket]

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
                    # Acknowledge reception back to the viewer for retry fallback
                    try:
                        parsed = json.loads(message)
                        if isinstance(parsed, dict) and parsed.get("type"):
                            await websocket.send_text(json.dumps({
                                "type": "control_ack",
                                "payload": {"message_id": parsed.get("message_id"), "status": "received"}
                            }))
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Error relaying event to host {device_id}: {e}")

    async def relay_control_from_viewer(self, websocket: WebSocket, message: str):
        """Relays low-latency viewer input over a dedicated control tunnel to the host."""
        if websocket in self.control_viewer_targets:
            device_id = self.control_viewer_targets[websocket]
            try:
                if device_id in self.host_controls:
                    await self.host_controls[device_id].send_text(message)
                elif device_id in self.hosts:
                    await self.hosts[device_id].send_text(message)

                # Always acknowledge control packets back to viewer
                try:
                    parsed = json.loads(message)
                    if isinstance(parsed, dict) and parsed.get("type"):
                        await websocket.send_text(json.dumps({
                            "type": "control_ack",
                            "payload": {"message_id": parsed.get("message_id"), "status": "sent"}
                        }))
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error relaying control event to host {device_id}: {e}")

connection_manager = ConnectionManager()


@app.websocket("/ws/host/{device_id}")
async def ws_host_endpoint(websocket: WebSocket, device_id: str):
    if not await _ensure_ws_authorized(websocket):
        return

    await connection_manager.register_host(device_id, websocket)
    connection_manager.session_start_times[device_id] = time.time()
    connection_manager.bytes_transferred[device_id] = 0
    
    try:
        while True:
            data = await websocket.receive()
            if "bytes" in data:
                await connection_manager.relay_from_host(device_id, data["bytes"])
            elif "text" in data:
                text_data = data["text"]
                if text_data in ("heartbeat", "ping"):
                    db.update_device_status(device_id, is_online=True)
                    if text_data == "ping":
                        await websocket.send_text("pong")
                else:
                    await connection_manager.relay_from_host(device_id, text_data)
    except WebSocketDisconnect:
        logger.warning(f"Host {device_id} disconnected unexpectedly.")
    finally:
        connection_manager.unregister_host(device_id)
        ## Session history can be closed when an active session exists
        duration = int(time.time() - connection_manager.session_start_times.get(device_id, time.time()))
        bytes_tx = connection_manager.bytes_transferred.get(device_id, 0)
        try:
            db.close_session(session_id=f"host_{device_id}", duration=duration, bytes_tx=bytes_tx)
        except Exception:
            pass


@app.websocket("/ws/viewer/{device_id}")
async def ws_viewer_endpoint(websocket: WebSocket, device_id: str):
    if not await _ensure_ws_authorized(websocket):
        return

    session_token = extract_ws_auth_token(dict(websocket.query_params), dict(websocket.headers.items()) if websocket.headers else None)
    if session_token:
        session = db.get_session_by_token(session_token)
        if not session or session["device_id"] != device_id:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "Invalid or expired session token."}))
            await websocket.close()
            return

    success = await connection_manager.register_viewer(device_id, websocket)
    if not success:
        return

    try:
        while True:
            message = await websocket.receive_text()
            if message == "heartbeat":
                continue
            await connection_manager.relay_from_viewer(websocket, message)
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.unregister_viewer(websocket)


@app.websocket("/ws/control/{device_id}")
async def ws_control_viewer_endpoint(websocket: WebSocket, device_id: str):
    if not await _ensure_ws_authorized(websocket):
        return

    success = await connection_manager.register_viewer_control(device_id, websocket)
    if not success:
        return

    try:
        while True:
            message = await websocket.receive_text()
            if message == "heartbeat":
                continue
            await connection_manager.relay_control_from_viewer(websocket, message)
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.unregister_viewer_control(websocket)


@app.websocket("/ws/control-host/{device_id}")
async def ws_control_host_endpoint(websocket: WebSocket, device_id: str):
    if not await _ensure_ws_authorized(websocket):
        return

    await connection_manager.register_host_control(device_id, websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.unregister_host_control(device_id)
