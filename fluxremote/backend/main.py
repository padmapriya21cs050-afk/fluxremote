# fluxremote/backend/main.py
import logging
import time
import os
import sys
import json
import uuid
import secrets
import ast
import asyncio
import traceback
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Any, Dict, Set, Optional, List
from pydantic import BaseModel
from dotenv import load_dotenv, find_dotenv
from google import genai

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fluxremote.backend.models import DeviceRegister, SessionCreate, SessionResponse
from fluxremote.backend import database as db
from fluxremote.backend import auth
from fluxremote.backend.tunnel_auth import extract_ws_auth_token, is_ws_request_authorized

# Set up logging first so environment loading can be reported.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fluxremote.backend")
WS_TUNNEL_TOKEN = os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")


def _load_dotenv_paths() -> List[str]:
    loaded_files: List[str] = []
    env_paths = [
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.path.dirname(__file__), ".env.local"),
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", ".env.local"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"),
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


LOADED_ENV_FILES = _load_dotenv_paths()


def get_gemini_api_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY")


logger.info("GEMINI_API_KEY found: %s", "YES" if get_gemini_api_key() else "NO")
logger.info("Dotenv files loaded for Gemini config: %s", ", ".join(LOADED_ENV_FILES) if LOADED_ENV_FILES else "None")

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
    logger.info("Closing websocket due to invalid or missing tunnel token (code=1008)")
    try:
        await websocket.close(code=1008)
    except Exception:
        traceback.print_exc()
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

    @staticmethod
    def chat(message: str, history: Optional[List[Dict[str, str]]] = None, context: Optional[Dict[str, Any]] = None) -> str:
        api_key = get_gemini_api_key()
        if not api_key:
            logger.error("Gemini chat request blocked: missing GEMINI_API_KEY.")
            return "Gemini is not configured right now, but I can still help. Please try again shortly or ask a simpler question."

        client = GeminiClient(api_key)

        try:
            history_lines = []
            if history:
                for item in history[-10:]:
                    role = item.get("role", "user")
                    content = item.get("content", "")
                    if content:
                        history_lines.append(f"{role}: {content}")

            context_lines = []
            if context:
                for key, value in context.items():
                    if isinstance(value, (dict, list)):
                        context_lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                    else:
                        context_lines.append(f"{key}: {value}")

            prompt = f"""
            You are FluxRemote AI Copilot, a helpful assistant for a remote desktop product.
            Answer any user question clearly and helpfully, including programming, Windows/Linux troubleshooting, networking, AI, mathematics, writing, and general knowledge.
            If the user asks about FluxRemote, explain how to troubleshoot the connection or use the product. Keep answers concise, practical, and friendly.

            Recent conversation:
            {chr(10).join(history_lines) if history_lines else 'None'}

            Session context:
            {chr(10).join(context_lines) if context_lines else 'None'}

            User message:
            {message}
            """
            answer = client.generate(prompt)
            reply = _extract_gemini_text(answer)
            if reply:
                return reply

            logger.error("Gemini chat returned empty or unexpected response: %s", answer)
            return "I’m here to help. Gemini returned an empty response, so please try again with a slightly different question."
        except Exception as exc:
            logger.error("Gemini chat request failure: %s", exc)
            return "I’m sorry, the AI service is currently unavailable. Please try again in a moment."


GEMINI_CLIENT_INITIALIZED = False
if get_gemini_api_key():
    try:
        GeminiClient(get_gemini_api_key())
        GEMINI_CLIENT_INITIALIZED = True
    except Exception as exc:
        logger.error("Gemini SDK client initialization failed at startup: %s", exc)

logger.info("Gemini client initialized successfully: %s", "YES" if GEMINI_CLIENT_INITIALIZED else "NO")

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

class AIChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = None
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AIChatResponse(BaseModel):
    reply: str
    fallback: bool = False


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
    logger.info("REGISTER DEVICE endpoint: entering | device_id=%s | device_name=%s", device.device_id, device.device_name)
    # Hashes the password used for connecting to the host
    hash_pwd = auth.hash_password(device.access_password)
    print("=" * 80)
    print("REGISTER DEVICE")
    print(f"  device_id={repr(device.device_id)}")
    print(f"  received_password={repr(device.access_password)}")
    print(f"  generated_hash={repr(hash_pwd)}")
    print("=" * 80)
    logger.info("REGISTER DEVICE | device_id=%s | password_len=%d | hash_len=%d", 
                device.device_id, len(device.access_password) if device.access_password else 0, len(hash_pwd))
    
    success = db.register_device(device.device_id, device.device_name, hash_pwd)
    logger.info("REGISTER DEVICE endpoint: registration_result=%s | device_id=%s", success, device.device_id)
    if not success:
        logger.error("REGISTER DEVICE endpoint: database insert/update failed | device_id=%s", device.device_id)
        raise HTTPException(
            status_code=500,
            detail="Failed to register or update device configuration."
        )
    
    # Verify the hash was stored correctly
    stored_device = db.get_device(device.device_id)
    if stored_device:
        stored_hash = stored_device.get("access_password_hash")
        verify_result = auth.verify_password(device.access_password, stored_hash)
        print("-" * 80)
        print("REGISTER DEVICE: Post-insert verification")
        print(f"  stored_hash_after_insert={repr(stored_hash)}")
        print(f"  verify_password(received_password, stored_hash)={verify_result}")
        print(f"  received_password={repr(device.access_password)}")
        print("-" * 80)
        logger.info("REGISTER DEVICE: Post-insert verification | verify_result=%s | hash_match=%s", 
                    verify_result, stored_hash == hash_pwd)
    else:
        print("-" * 80)
        print("REGISTER DEVICE: WARNING - Device not found in DB after insert!")
        print(f"  device_id={repr(device.device_id)}")
        print("-" * 80)
        logger.error("REGISTER DEVICE: Device not found after registration | device_id=%s", device.device_id)
    
    logger.info("REGISTER DEVICE endpoint: success | device_id=%s", device.device_id)
    return {
        "message": "Device registered successfully.",
        "device_id": device.device_id,
        "tunnel_mode": is_tunnel_url(device.device_name if device.device_name else ""),
    }

@app.get("/api/devices/online")
def list_online_devices():
    logger.info("LIST ONLINE DEVICES endpoint: entering")
    devices = db.get_online_devices()
    logger.info("LIST ONLINE DEVICES endpoint: returned_count=%d", len(devices))
    return devices

@app.post("/api/ai/chat", response_model=AIChatResponse)
def ai_chat(request: AIChatRequest):
    """Chat endpoint for the FluxRemote AI Copilot."""
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="A non-empty message is required.")

    reply = GeminiAssistant.chat(
        request.message.strip(),
        history=request.history,
        context=request.context,
    )
    fallback = "Gemini is not configured right now" in reply or "currently unavailable" in reply or "empty response" in reply
    return AIChatResponse(reply=reply, fallback=fallback)


@app.post("/api/copilot/chat", response_model=AIChatResponse)
def copilot_chat(request: AIChatRequest):
    """Session-scoped copilot endpoint for the remote session AI card."""
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="A non-empty message is required.")

    reply = GeminiAssistant.chat(
        request.message.strip(),
        history=request.history,
        context=request.context,
    )
    fallback = "Gemini is not configured right now" in reply or "currently unavailable" in reply or "empty response" in reply
    return AIChatResponse(reply=reply, fallback=fallback)


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
    device_id = session_req.device_id
    supplied_password = session_req.access_password
    
    print("=" * 80)
    print("CREATE_SESSION: Entry point")
    print(f"  received_device_id={repr(device_id)}")
    print(f"  supplied_password={repr(supplied_password)}")
    print("=" * 80)
    logger.info("CREATE_SESSION: Entry point | device_id=%s | password_len=%d", device_id, len(supplied_password) if supplied_password else 0)

    device = db.get_device(device_id)
    
    print("-" * 80)
    print("CREATE_SESSION: After db.get_device()")
    print(f"  device_found={device is not None}")
    if device:
        print(f"  stored_password_hash={repr(device['access_password_hash'])}")
        print(f"  device_is_online={device['is_online']}")
    else:
        print(f"  stored_password_hash=N/A (device not found)")
        print(f"  device_is_online=N/A")
    print("-" * 80)
    logger.info("CREATE_SESSION: db.get_device() result | found=%s", device is not None)

    if not device:
        print("!" * 80)
        print("EARLY RETURN: HTTP 404")
        print(f"  reason=device_not_found")
        print(f"  device_id={repr(device_id)}")
        print("!" * 80)
        logger.info("EARLY RETURN: HTTP 404 | device_not_found | device_id=%s", device_id)
        raise HTTPException(status_code=404, detail="Target device not registered.")

    if not device["is_online"]:
        print("!" * 80)
        print("EARLY RETURN: HTTP 400")
        print(f"  reason=device_offline")
        print(f"  device_id={repr(device_id)}")
        print(f"  device_is_online={device['is_online']}")
        print("!" * 80)
        logger.info("EARLY RETURN: HTTP 400 | device_offline | device_id=%s | is_online=%s", device_id, device["is_online"])
        raise HTTPException(status_code=400, detail="Target host desktop is currently offline.")

    password_matches = auth.verify_password(supplied_password, device["access_password_hash"])
    
    print("-" * 80)
    print("CREATE_SESSION: Password verification result")
    print(f"  verify_password() returned={password_matches}")
    print(f"  received_password={repr(supplied_password)}")
    print(f"  stored_hash={repr(device['access_password_hash'])}")
    print("-" * 80)
    logger.info("CREATE_SESSION: Password verification | result=%s | supplied_len=%d | hash_len=%d", 
                password_matches, len(supplied_password) if supplied_password else 0, 
                len(device["access_password_hash"]) if device.get("access_password_hash") else 0)

    if not password_matches:
        print("!" * 80)
        print("EARLY RETURN: HTTP 403")
        print(f"  reason=password_verification_failed")
        print(f"  device_id={repr(device_id)}")
        print(f"  verify_password()={password_matches}")
        print(f"  received_password={repr(supplied_password)}")
        print(f"  stored_hash={repr(device['access_password_hash'])}")
        print("!" * 80)
        logger.info("EARLY RETURN: HTTP 403 | password_verification_failed | device_id=%s | verify_result=%s", device_id, password_matches)
        raise HTTPException(status_code=403, detail="Invalid access password.")

    print("=" * 80)
    print("CREATE_SESSION: All checks passed, creating session")
    print(f"  device_id={repr(device_id)}")
    print(f"  password_matches=True")
    print("=" * 80)
    logger.info("CREATE_SESSION: All checks passed | device_id=%s", device_id)

    logger.info("Session creation accepted for device_id=%s", device_id)

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
        logger.info("REGISTER_HOST: entering | device_id=%s", device_id)
        await websocket.accept()
        self.hosts[device_id] = websocket
        db.update_device_status(device_id, is_online=True)
        logger.info("REGISTER_HOST: success | device_id=%s | host_count=%d", device_id, len(self.hosts))
        print("Host connected", device_id)

    def unregister_host(self, device_id: str):
        logger.info("UNREGISTER_HOST: entering | device_id=%s", device_id)
        if device_id in self.hosts:
            del self.hosts[device_id]
        db.update_device_status(device_id, is_online=False)
        logger.info("UNREGISTER_HOST: success | device_id=%s | host_count=%d", device_id, len(self.hosts))

    async def register_viewer(self, device_id: str, websocket: WebSocket) -> bool:
        await websocket.accept()
        if device_id not in self.hosts:
            await websocket.send_text(json.dumps({"type": "error", "message": "Host is offline."}))
            logger.info("Closing viewer websocket for device %s because host is offline (code=1000)", device_id)
            try:
                await websocket.close(code=1000)
            except Exception:
                traceback.print_exc()
            return False

        if device_id not in self.viewers:
            self.viewers[device_id] = set()
        self.viewers[device_id].add(websocket)
        self.viewer_targets[websocket] = device_id
        viewer_keys = sorted(self.viewers.keys())
        print(f"REGISTER_VIEWER device={device_id}")
        print(f"Total viewers after registration: {len(self.viewers[device_id])}")
        print(f"Viewer websocket id: {id(websocket)}")
        print(f"Viewer dictionary keys: {viewer_keys}")
        logger.info("Viewer connected: %s", device_id)
        print(f"Viewer connected: {device_id}")
        logger.info("Viewer dictionary keys after connection: %s", viewer_keys)
        logger.info("Viewer connected to desktop %s. Total viewers: %d", device_id, len(self.viewers[device_id]))

        # Notify host that a viewer joined
        try:
            await self.hosts[device_id].send_text(json.dumps({"type": "viewer_status", "status": "connected"}))
        except Exception as e:
            logger.error(f"Failed to send viewer notification to host: {e}")
            traceback.print_exc()

        return True

    async def unregister_viewer(self, websocket: WebSocket):
        device_id = self.viewer_targets.get(websocket, "unknown")
        print(f"UNREGISTER_VIEWER device={device_id}")
        try:
            if websocket in self.viewer_targets:
                if device_id in self.viewers:
                    self.viewers[device_id].discard(websocket)
                    if not self.viewers[device_id]:
                        del self.viewers[device_id]
                        print(f"Viewer dictionary key removed: {device_id}")
                        logger.info("Viewer dictionary key removed: %s", device_id)
                        # Inform host that all viewers disconnected
                        if device_id in self.hosts:
                            try:
                                await self.hosts[device_id].send_text(json.dumps({"type": "viewer_status", "status": "disconnected"}))
                            except Exception:
                                pass
                del self.viewer_targets[websocket]
                logger.info("Viewer disconnected: %s", device_id)
                print(f"Viewer disconnected: {device_id}")
            print("Remaining viewers:", self.viewers.get(device_id, set()) if device_id != "unknown" else set())
        except Exception as exc:
            print(f"UNREGISTER_VIEWER exception for device={device_id}: {exc}")
            traceback.print_exc()
            raise

    async def register_host_control(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.host_controls[device_id] = websocket
        logger.info(f"Host control tunnel connected for desktop {device_id}.")
        print("Control host connected", device_id)

    def unregister_host_control(self, device_id: str):
        if device_id in self.host_controls:
            del self.host_controls[device_id]
        print("Control host disconnected", device_id)

    async def register_viewer_control(self, device_id: str, websocket: WebSocket) -> bool:
        await websocket.accept()
        if device_id not in self.host_controls:
            await websocket.send_text(json.dumps({"type": "error", "message": "Host control tunnel is offline."}))
            logger.info("Closing control viewer websocket for device %s because host control tunnel is offline (code=1000)", device_id)
            try:
                await websocket.close(code=1000)
            except Exception:
                traceback.print_exc()
            return False

        if device_id not in self.control_viewers:
            self.control_viewers[device_id] = set()
        self.control_viewers[device_id].add(websocket)
        self.control_viewer_targets[websocket] = device_id
        print("Control viewer connected", device_id)
        return True

    async def unregister_viewer_control(self, websocket: WebSocket):
        if websocket in self.control_viewer_targets:
            device_id = self.control_viewer_targets[websocket]
            if device_id in self.control_viewers:
                self.control_viewers[device_id].discard(websocket)
                if not self.control_viewers[device_id]:
                    del self.control_viewers[device_id]
            del self.control_viewer_targets[websocket]
            print("Control viewer disconnected", device_id)

    async def relay_from_host(self, device_id: str, message: Any):
        """Relays screen video frames (binary or text) to all connected viewers."""
        if device_id in self.viewers:
            targets = list(self.viewers[device_id])
            size = len(message) if isinstance(message, (bytes, bytearray)) else len(str(message))
            viewer_count = len(targets)

            print("----------------------------------------------------")
            print("HOST FRAME RECEIVED")
            print(f"device={device_id}")
            print(f"frame_size={size}")
            print(f"viewer_count={viewer_count}")
            print("----------------------------------------------------")

            if isinstance(message, (bytes, bytearray)):
                print(f"JPEG SIZE = {len(message)} bytes")
            else:
                print(f"JPEG SIZE = {len(str(message))} bytes")

            if viewer_count == 0:
                print("No viewers registered for this device.")

            # Record statistics
            self.bytes_transferred[device_id] = self.bytes_transferred.get(device_id, 0) + size

            # Send to all active viewers
            coros = []
            for ws in targets:
                print(f"viewer websocket id: {id(ws)}")
                print(f"viewer websocket client_state: {getattr(ws, 'client_state', None)}")
                print(f"viewer websocket application_state: {getattr(ws, 'application_state', None)}")
                is_connected = str(getattr(ws, 'client_state', None)) == 'CONNECTED'
                if not is_connected:
                    print("Skipping disconnected viewer.")
                try:
                    if isinstance(message, bytes):
                        logger.info("Host binary frame received for device %s size=%d bytes", device_id, len(message))
                        coros.append(ws.send_bytes(message))
                        logger.info("Forwarding host binary frame to viewer for device %s size=%d bytes", device_id, len(message))
                    else:
                        coros.append(ws.send_text(message))
                except Exception:
                    traceback.print_exc()
            if coros:
                results = await asyncio.gather(*coros, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        print("SEND ERROR:")
                        traceback.print_exception(type(result), result, result.__traceback__)
                    else:
                        print("FRAME DELIVERED SUCCESSFULLY")
        else:
            if isinstance(message, (bytes, bytearray)):
                logger.info("No viewer connected for device %s; dropping host binary frame size=%d bytes", device_id, len(message))
            else:
                logger.info("No viewer connected for device %s; dropping host text payload", device_id)

    async def relay_from_viewer(self, websocket: WebSocket, message: Any):
        """Relays interactive controls from a specific viewer to their target host."""
        if websocket in self.viewer_targets:
            device_id = self.viewer_targets[websocket]
            if device_id in self.hosts:
                # Forward the raw message string exactly as received. Do not parse/modify.
                raw = message
                if isinstance(message, (bytes, bytearray)):
                    try:
                        raw = message.decode("utf-8")
                    except Exception as exc:
                        logger.debug(f"Relay ignored non-decodable viewer control bytes: {exc}")
                        return

                if raw is None:
                    logger.debug("Relay ignored None viewer control payload")
                    return

                raw_str = str(raw)
                # Ignore simple heartbeats
                if raw_str.strip() in ("", "heartbeat", "ping", "pong"):
                    logger.debug("Relay ignored viewer control payload: %r", raw_str)
                    return

                print("FROM VIEWER:", repr(raw_str))
                try:
                    await self.hosts[device_id].send_text(raw_str)
                    print("FORWARD TO HOST:", repr(raw_str))
                    logger.debug("Relay forwarded viewer control to host %s: %r", device_id, raw_str)

                    # Acknowledge if message contains a message_id (best-effort, but do not modify forwarded payload)
                    try:
                        parsed = json.loads(raw_str)
                        if isinstance(parsed, dict) and parsed.get("type"):
                            await websocket.send_text(json.dumps({
                                "type": "control_ack",
                                "payload": {"message_id": parsed.get("message_id"), "status": "received"}
                            }))
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Error relaying event to host {device_id}: {e}")
                    traceback.print_exc()

    async def relay_control_from_viewer(self, websocket: WebSocket, message: Any):
        """Relays low-latency viewer input over a dedicated control tunnel to the host."""
        if websocket in self.control_viewer_targets:
            device_id = self.control_viewer_targets[websocket]
            # Expecting an already-extracted raw text message. Forward it verbatim.
            raw = message
            if isinstance(message, (bytes, bytearray)):
                try:
                    raw = message.decode("utf-8")
                except Exception as exc:
                    logger.debug(f"Relay ignored non-decodable viewer control bytes: {exc}")
                    return

            if raw is None:
                logger.debug("Relay ignored None control payload")
                return

            raw_str = str(raw)
            if raw_str.strip() in ("", "heartbeat", "ping", "pong"):
                logger.debug("Relay ignored control payload: %r", raw_str)
                return

            print("FROM VIEWER:", repr(raw_str))
            logger.debug("Relay received low-latency viewer control for %s: %r", device_id, raw_str)
            try:
                if device_id in self.host_controls:
                    await self.host_controls[device_id].send_text(raw_str)
                elif device_id in self.hosts:
                    await self.hosts[device_id].send_text(raw_str)
                print("FORWARD TO HOST:", repr(raw_str))
                logger.debug("Relay forwarded low-latency control to host %s: %r", device_id, raw_str)

                try:
                    parsed = json.loads(raw_str)
                    if isinstance(parsed, dict) and parsed.get("type"):
                        await websocket.send_text(json.dumps({
                            "type": "control_ack",
                            "payload": {"message_id": parsed.get("message_id"), "status": "sent"}
                        }))
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error relaying control event to host {device_id}: {e}")
                traceback.print_exc()

def _normalize_ws_payload(payload: Any) -> Optional[str]:
    if payload is None:
        return None

    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            payload = payload["text"]
        elif isinstance(payload.get("bytes"), (bytes, bytearray)):
            try:
                return payload["bytes"].decode("utf-8")
            except Exception as exc:
                logger.debug(f"Control payload dict bytes decode failed: {exc}")
                return None
        else:
            return None

    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except Exception as exc:
            logger.debug(f"Control payload bytes decode failed: {exc}")
            return None

    text = str(payload).strip()

    if text.startswith(("b'", 'b"')):
        try:
            raw_bytes = ast.literal_eval(text)
            if isinstance(raw_bytes, (bytes, bytearray)):
                text = raw_bytes.decode("utf-8", errors="replace").strip()
        except Exception as exc:
            logger.debug(f"Control payload literal_eval failed: {exc}")

    while (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        inner = text[1:-1].strip()
        if inner.startswith('{') or inner.startswith('['):
            text = inner
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                text = parsed.strip()
                continue
            if isinstance(parsed, (dict, list)):
                text = json.dumps(parsed)
                break
        except Exception:
            break

    if text.startswith("{") and "'" in text and '"' not in text:
        text = text.replace("'", '"')

    return text


connection_manager = ConnectionManager()


@app.websocket("/ws/host/{device_id}")
async def ws_host_endpoint(websocket: WebSocket, device_id: str):
    logger.info("WS_HOST: entering | device_id=%s", device_id)
    if not await _ensure_ws_authorized(websocket):
        logger.warning("WS_HOST: authorization failed | device_id=%s", device_id)
        return

    await connection_manager.register_host(device_id, websocket)
    connection_manager.session_start_times[device_id] = time.time()
    connection_manager.bytes_transferred[device_id] = 0
    
    try:
        while True:
            try:
                data = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                logger.warning(f"Host {device_id} disconnected unexpectedly (receive).")
                break
            except Exception:
                traceback.print_exc()
                break

            if "bytes" in data:
                logger.info("WS_HOST: binary frame received | device_id=%s | size=%d", device_id, len(data.get("bytes", b"")))
                await connection_manager.relay_from_host(device_id, data["bytes"])
            elif "text" in data:
                text_data = data["text"]
                logger.info("WS_HOST: text frame received | device_id=%s | text=%s", device_id, text_data)
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
    logger.info("Viewer websocket request received for device %s", device_id)
    print(f"Viewer websocket request received for device {device_id}")

    if not await _ensure_ws_authorized(websocket):
        return

    session_token = extract_ws_auth_token(dict(websocket.query_params), dict(websocket.headers.items()) if websocket.headers else None)
    logger.info("Viewer websocket auth token present for device %s: %s", device_id, bool(session_token))
    if session_token:
        session = db.get_session_by_token(session_token)
        if not session or session["device_id"] != device_id:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "Invalid or expired session token."}))
            logger.info("Closing viewer websocket for device %s because session token is invalid or expired (code=1000)", device_id)
            try:
                await websocket.close(code=1000)
            except Exception:
                traceback.print_exc()
            return

    success = await connection_manager.register_viewer(device_id, websocket)
    if not success:
        logger.info("Viewer websocket registration failed for device %s", device_id)
        return

    try:
        while True:
            try:
                data = await websocket.receive()
            except WebSocketDisconnect:
                logger.info("Viewer websocket disconnected for device %s", device_id)
                break
            except RuntimeError as exc:
                logger.exception("Viewer websocket receive runtime error for device %s", device_id)
                print(f"Viewer websocket receive runtime error for device {device_id}: {exc}")
                traceback.print_exc()
                break
            except Exception as exc:
                logger.exception("Viewer websocket unexpected exception for device %s", device_id)
                print(f"Viewer websocket unexpected exception for device {device_id}: {exc}")
                traceback.print_exc()
                break

            if "text" in data:
                raw_message = data["text"]
            elif "bytes" in data:
                raw_message = data["bytes"]
            else:
                continue

            normalized = _normalize_ws_payload(raw_message)
            logger.debug("Viewer control raw receive: %r -> %r", raw_message, normalized)
            if normalized in (None, "", "heartbeat", "ping", "pong"):
                logger.debug("Viewer control ignored payload: %r", raw_message)
                continue
            await connection_manager.relay_from_viewer(websocket, normalized)
    except WebSocketDisconnect:
        logger.info("Viewer websocket disconnected for device %s", device_id)
    except Exception as exc:
        logger.exception("Viewer websocket exception while processing device %s", device_id)
        print(f"Viewer websocket exception while processing device {device_id}: {exc}")
        traceback.print_exc()
    finally:
        await connection_manager.unregister_viewer(websocket)


@app.websocket("/ws/control/{device_id}")
async def ws_control_viewer_endpoint(websocket: WebSocket, device_id: str):
    if not await _ensure_ws_authorized(websocket):
        return

    session_token = extract_ws_auth_token(dict(websocket.query_params), dict(websocket.headers.items()) if websocket.headers else None)
    if session_token:
        session = db.get_session_by_token(session_token)
        if not session or session["device_id"] != device_id:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "Invalid or expired session token."}))
            logger.info("Closing control viewer websocket for device %s because session token is invalid or expired (code=1000)", device_id)
            try:
                await websocket.close(code=1000)
            except Exception:
                traceback.print_exc()
            return

    success = await connection_manager.register_viewer_control(device_id, websocket)
    if not success:
        return

    try:
        while True:
            try:
                data = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                break

            if "text" in data:
                raw_message = data["text"]
            elif "bytes" in data:
                try:
                    raw_message = data["bytes"].decode("utf-8")
                except Exception:
                    logger.debug("Control channel received non-decodable bytes; ignoring")
                    continue
            else:
                continue

            print("FROM VIEWER:", repr(raw_message))
            if isinstance(raw_message, str) and raw_message.strip() in (None, "", "heartbeat", "ping", "pong"):
                logger.debug("Control channel ignored payload: %r", raw_message)
                continue
            logger.debug("Control channel received payload: %r", raw_message)
            # Forward the raw text verbatim
            await connection_manager.relay_control_from_viewer(websocket, raw_message)
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
            try:
                data = await websocket.receive()
            except (WebSocketDisconnect, RuntimeError):
                break

            if "text" in data:
                raw_message = data["text"]
            elif "bytes" in data:
                try:
                    raw_message = data["bytes"].decode("utf-8")
                except Exception:
                    logger.debug("Control host sent non-decodable bytes; ignoring")
                    continue
            else:
                continue

            print("FROM HOST:", repr(raw_message))
            if isinstance(raw_message, str) and raw_message.strip() in (None, "", "heartbeat", "ping", "pong"):
                logger.debug("Control host ignored payload: %r", raw_message)
                continue

            # Forward host-sent control messages to all connected control viewers for this device
            viewers = list(connection_manager.control_viewers.get(device_id, []))
            coros = []
            for ws in viewers:
                try:
                    coros.append(ws.send_text(raw_message))
                    print("FORWARD TO VIEWER:", repr(raw_message))
                except Exception:
                    pass
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.unregister_host_control(device_id)
