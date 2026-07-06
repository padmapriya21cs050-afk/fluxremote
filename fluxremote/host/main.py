# fluxremote/host/main.py
"""
FluxRemote Host Agent
Runs locally on the target Windows machine to capture desktop screens
and process keyboard/mouse injection instructions from the Viewer.
"""

import os
import sys
import time
import json
import socket
import logging
import threading
import ctypes
from urllib.parse import quote
from typing import Dict, Any, Optional

# Required external packages
try:
    import mss
    import pyautogui
    from PIL import Image
    import io
    import websocket
    import requests
    import psutil
    from pynput.mouse import Controller as PynputMouseController, Button as PynputButton
except ImportError:
    print("Warning: Missing required packages. Run: pip install mss pyautogui pillow websocket-client requests pynput psutil")
    pyautogui = None
    psutil = None
    PynputMouseController = None
    PynputButton = None
    # We will still generate the complete file for compilation/packaging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Host: %(message)s")
logger = logging.getLogger("fluxremote.host")

# PyAutoGUI Safety settings
if pyautogui is not None:
    pyautogui.FAILSAFE = False  # Prevent crash if mouse goes to (0,0)
    pyautogui.PAUSE = 0.0       # Eliminate pause delay between commands
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0

class FluxHost:
    def __init__(self, server_url: str, device_id: str, access_password: str, device_name: str = None, tunnel_token: Optional[str] = None):
        self.server_url = server_url.rstrip('/')
        self.device_id = device_id
        self.access_password = access_password
        self.device_name = device_name or socket.gethostname()
        self.tunnel_token = tunnel_token or os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")
        
        # Connection statuses
        self.running = False
        self.connected = False
        self.ws: Optional[websocket.WebSocketApp] = None
        self.control_ws: Optional[websocket.WebSocketApp] = None
        
        # Stream parameters
        self.fps = 15
        self.target_fps = 15
        self.quality = 60  # Start in the adaptive 40-80 range
        self.min_quality = 40
        self.max_quality = 80
        self.bandwidth_bps = 0
        self.last_frame_time = time.time()
        self.last_send_duration = 0.0
        self.reject_frame = False
        self.current_resolution = (0, 0)

        self.pynput_enabled = PynputMouseController is not None
        self.mouse_controller = PynputMouseController() if self.pynput_enabled else None
        
        # Threads
        self.capture_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.control_thread: Optional[threading.Thread] = None
        self.stats_thread: Optional[threading.Thread] = None
        
        # Performance metrics
        self.frame_count = 0
        self.last_fps_check = time.time()
        self.current_fps = 0
        self.last_stats_sent = 0.0
        self.input_latency_samples = []

    def _build_ws_url(self, path: str) -> str:
        url = f"{self.server_url}{path}"
        if not self.tunnel_token:
            return url

        separator = "&" if "?" in url else "?"
        return f"{url}{separator}token={quote(self.tunnel_token)}"

    def register_device(self) -> bool:
        """Registers device metadata on the server before launching socket connection."""
        register_url = f"{self.server_url}/api/devices/register"
        payload = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "access_password": self.access_password
        }
        try:
            # Swap ws:// with http:// or wss:// with https://
            http_url = self.server_url.replace("ws://", "http://").replace("wss://", "https://")
            headers = {}
            if self.tunnel_token:
                headers["Authorization"] = f"Bearer {self.tunnel_token}"
            response = requests.post(f"{http_url}/api/devices/register", json=payload, headers=headers, timeout=5)
            if response.status_code == 200:
                logger.info("Successfully registered/updated device on signalling server.")
                return True
            else:
                logger.error(f"Failed to register device: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error registering device on server: {e}")
            return False

    def start(self):
        """Starts the host agent and handles auto-reconnections."""
        if not self.register_device():
            logger.warning("Continuing starting procedures, but server registration failed. Port may be offline.")
            
        self.running = True
        
        # Build WS URL
        ws_endpoint = self._build_ws_url(f"/ws/host/{self.device_id}")
        
        while self.running:
            logger.info(f"Connecting to signaling server: {ws_endpoint}")
            try:
                self.ws = websocket.WebSocketApp(
                    ws_endpoint,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"WebSocket execution error: {e}")
                
            if self.running:
                logger.info("Disconnected. Retrying connection in 5 seconds...")
                time.sleep(5)

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        if self.control_ws:
            self.control_ws.close()
        logger.info("Host Agent stopped.")

    def on_open(self, ws):
        logger.info("Screen WebSocket connection established. Starting worker threads...")
        self.connected = True
        self._start_control_connection()
        
        # Launch capture & transmit loop
        self.capture_thread = threading.Thread(target=self._capture_and_stream_loop, daemon=True)
        self.capture_thread.start()
        
        # Launch background heartbeat ping
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

        # Send periodic host stats and resolution metadata
        self.stats_thread = threading.Thread(target=self._stats_report_loop, daemon=True)
        self.stats_thread.start()

    def _start_control_connection(self):
        if not self.running:
            return

        if self.control_thread and self.control_thread.is_alive():
            return

        self.control_thread = threading.Thread(target=self._run_control_ws, daemon=True)
        self.control_thread.start()

    def _run_control_ws(self):
        control_endpoint = self._build_ws_url(f"/ws/control-host/{self.device_id}")
        logger.info(f"Connecting control tunnel: {control_endpoint}")

        while self.running:
            try:
                self.control_ws = websocket.WebSocketApp(
                    control_endpoint,
                    on_open=self.on_control_open,
                    on_message=self.on_control_message,
                    on_error=self.on_control_error,
                    on_close=self.on_control_close,
                )
                self.control_ws.run_forever()
            except Exception as e:
                logger.error(f"Control tunnel execution error: {e}")

            if self.running:
                logger.info("Control tunnel disconnected. Retrying in 2 seconds...")
                time.sleep(2)

    def on_control_open(self, ws):
        logger.info("Control tunnel connected.")

    def on_control_message(self, ws, message):
        self._handle_control_message(message)

    def on_control_error(self, ws, error):
        logger.error(f"Control tunnel transport error: {error}")

    def on_control_close(self, ws, close_status_code, close_msg):
        logger.warning(f"Control tunnel closed. Code: {close_status_code}, Message: {close_msg}")

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket closed. Code: {close_status_code}, Message: {close_msg}")
        self.connected = False

    def on_error(self, ws, error):
        logger.error(f"WebSocket transport error: {error}")

    def _move_mouse(self, x: int, y: int):
        x = int(x)
        y = int(y)

        if self.pynput_enabled and self.mouse_controller:
            try:
                self.mouse_controller.position = (x, y)
                return
            except Exception as exc:
                logger.debug(f"Pynput mouse move failed: {exc}")

        if pyautogui is not None:
            try:
                pyautogui.moveTo(x, y, duration=0)
                return
            except Exception as exc:
                logger.debug(f"PyAutoGUI mouse move failed: {exc}")

        if sys.platform.startswith("win"):
            try:
                ctypes.windll.user32.SetCursorPos(x, y)
                return
            except Exception as exc:
                logger.debug(f"Windows native cursor fallback failed: {exc}")

        logger.warning("Mouse movement fallback exhausted; cursor may be slow or unavailable.")

    def _click_mouse(self, button: str = "left"):
        if self.pynput_enabled and self.mouse_controller:
            try:
                btn = PynputButton.left if button == "left" else PynputButton.right if button == "right" else PynputButton.middle
                self.mouse_controller.click(btn)
                return
            except Exception:
                pass
        pyautogui.click(button=button)

    def _double_click_mouse(self):
        if self.pynput_enabled and self.mouse_controller:
            try:
                self.mouse_controller.click(PynputButton.left, 2)
                return
            except Exception:
                pass
        pyautogui.doubleClick()

    def _record_input_latency(self, latency_ms: float, msg_type: str):
        self.input_latency_samples.append((msg_type, latency_ms))
        if len(self.input_latency_samples) >= 20:
            average_ms = sum(item[1] for item in self.input_latency_samples) / len(self.input_latency_samples)
            logger.info("Average input execution latency: %.2f ms over %d %s events", average_ms, len(self.input_latency_samples), msg_type)
            self.input_latency_samples.clear()

    def _handle_control_message(self, message):
        """Handles incoming keyboard/mouse/control updates from viewer via the dedicated control tunnel."""
        started = time.perf_counter()
        msg_type = None
        try:
            logger.debug("Control message received: %r", message)
            if message is None:
                return

            if isinstance(message, (bytes, bytearray)):
                message = message.decode("utf-8", errors="replace")

            if isinstance(message, str):
                if not message.strip():
                    return
                if message.strip().lower() in {"ping", "pong"}:
                    return

            try:
                data = json.loads(message)
            except Exception:
                logger.warning("Ignoring non-JSON control message: %r", message)
                return

            msg_type = data.get("type")
            payload = data.get("payload", {})
            
            if msg_type == "fps_update":
                self.fps = max(1, min(60, int(payload.get("fps", 15))))
                logger.info(f"Stream target FPS updated to {self.fps}")
                
            elif msg_type == "quality_update":
                self.quality = max(10, min(100, int(payload.get("quality", 60))))
                logger.info(f"Stream quality updated to {self.quality}%")
                
            elif msg_type == "viewer_status":
                status = payload.get("status")
                logger.info(f"Viewer status changed: {status}")
                
            elif msg_type == "mouse_move":
                x = int(payload.get("x", 0))
                y = int(payload.get("y", 0))
                self._move_mouse(x, y)
                
            elif msg_type == "mouse_click":
                x = payload.get("x")
                y = payload.get("y")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    self._move_mouse(int(x), int(y))
                button = payload.get("button", "left")
                self._click_mouse(button)
                
            elif msg_type == "mouse_double_click":
                x = payload.get("x")
                y = payload.get("y")
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    self._move_mouse(int(x), int(y))
                self._double_click_mouse()
                
            elif msg_type == "mouse_right_click":
                if pyautogui is not None:
                    pyautogui.rightClick()
                
            elif msg_type == "mouse_scroll":
                amount = int(payload.get("amount", 0))
                # On Windows scroll is positive for up, negative for down
                if pyautogui is not None:
                    pyautogui.scroll(amount)
                
            elif msg_type == "key_press":
                key = payload.get("key")
                if key and pyautogui is not None:
                    pyautogui.press(key)
                    
            elif msg_type == "key_shortcut":
                keys = payload.get("keys", [])
                if keys and pyautogui is not None:
                    pyautogui.hotkey(*keys)
                    
            elif msg_type == "clipboard_sync":
                text = payload.get("text", "")
                if text:
                    try:
                        import pyperclip
                        pyperclip.copy(text)
                        logger.info("Clipboard synchronized with Viewer payload.")
                    except ImportError:
                        pass
                        
        except Exception as e:
            logger.error(f"Failed to execute incoming Viewer control event: {e}")
        finally:
            # Measure the host-side cost of processing input so we can debug responsiveness without changing the protocol.
            if msg_type in {"mouse_move", "mouse_click", "mouse_double_click", "mouse_right_click", "mouse_scroll", "key_press", "key_shortcut"}:
                self._record_input_latency((time.perf_counter() - started) * 1000.0, msg_type)

    def on_message(self, ws, message):
        self._handle_control_message(message)

    def _heartbeat_loop(self):
        """Sends periodic 'heartbeat' pings to the relay server to avoid timeout disconnects."""
        while self.connected and self.running:
            try:
                if self.ws:
                    self.ws.send("ping")
            except Exception:
                break
            time.sleep(10)

    def _stats_report_loop(self):
        """Sends periodic host machine performance and resolution statistics."""
        while self.connected and self.running:
            try:
                width, height = self.current_resolution
                stats_payload = {
                    "type": "host_stats",
                    "payload": {
                        "resolution": {"width": width, "height": height},
                        "fps": self.current_fps,
                        "bandwidth_bps": int(self.bandwidth_bps),
                        "cpu_percent": psutil.cpu_percent(interval=None) if psutil else None,
                        "memory_percent": psutil.virtual_memory().percent if psutil else None,
                        "timestamp": time.time()
                    }
                }
                if self.ws and self.connected:
                    self.ws.send(json.dumps(stats_payload))
            except Exception as exc:
                logger.debug(f"Host stats loop failure: {exc}")
            time.sleep(3)

    def _capture_and_stream_loop(self):
        """Ultra-fast loop capturing the full virtual desktop screen, compressing, and sending."""
        logger.info("Desktop Screen Stream Active.")
        
        with mss.mss() as sct:
            full_monitor = sct.monitors[0]
            self.current_resolution = (full_monitor["width"], full_monitor["height"])
            
            while self.connected and self.running:
                start_time = time.time()
                try:
                    sct_img = sct.grab(full_monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    width, height = sct_img.size
                    self.current_resolution = (width, height)

                    if width > 2560 or height > 1600:
                        scale = min(2560 / width, 1600 / height)
                        if scale < 1.0:
                            new_size = (int(width * scale), int(height * scale))
                            img = img.resize(new_size, Image.LANCZOS)
                            width, height = new_size

                    img_byte_arr = io.BytesIO()
                    adaptive_quality = max(self.min_quality, min(self.max_quality, int(self.quality)))
                    img.save(img_byte_arr, format='JPEG', quality=adaptive_quality)
                    jpeg_bytes = img_byte_arr.getvalue()

                    if self.ws and self.connected:
                        send_start = time.time()
                        self.ws.send(jpeg_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
                        send_elapsed = time.time() - send_start
                        self.last_send_duration = send_elapsed
                        self.bandwidth_bps = len(jpeg_bytes) * 8 / max(send_elapsed, 0.001)

                    self.frame_count += 1
                    now = time.time()
                    if now - self.last_fps_check >= 1.0:
                        self.current_fps = self.frame_count
                        self.frame_count = 0
                        self.last_fps_check = now

                    if self.last_send_duration > 0.2 or len(jpeg_bytes) > 400000:
                        self.fps = max(10, self.fps - 1)
                        self.quality = max(self.min_quality, self.quality - 3)
                    elif self.last_send_duration < 0.08 and self.fps < self.target_fps:
                        self.fps = min(self.target_fps, self.fps + 1)
                        self.quality = min(self.max_quality, self.quality + 1)

                    target_delay = 1.0 / self.fps
                    elapsed = time.time() - start_time
                    if elapsed < target_delay:
                        time.sleep(target_delay - elapsed)
                    elif elapsed > target_delay * 1.5:
                        logger.debug("Skipping frame due to slow network or encoding delays.")
                        time.sleep(0.01)
                except Exception as e:
                    logger.error(f"Error in capture or transmission loop: {e}")
                    time.sleep(1)


# Command-Line Starter
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FluxRemote Host Agent Daemon")
    parser.add_argument("--server", default="wss://fluxremote-mbyy.onrender.com", help="Relay server websocket address")
    parser.add_argument("--id", default="DESKTOP-PC10", help="Unique Remote Device ID")
    parser.add_argument("--password", default="1234567", help="Target access password")
    parser.add_argument("--auth-token", default=os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN"), help="Optional auth token for tunnelled websocket connections")
    parser.add_argument("--hide-console", action="store_true", help="Hide the Windows console window when launching the host")
    args = parser.parse_args()
    
    if args.hide_console and sys.platform.startswith("win"):
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    print("------------------------------------------")
    print("       FLUXREMOTE WINDOWS HOST AGENT     ")
    print(f"       Device ID: {args.id}")
    print(f"       Server: {args.server}")
    print("------------------------------------------")
    
    host = FluxHost(server_url=args.server, device_id=args.id, access_password=args.password, tunnel_token=args.auth_token)
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()
        sys.exit(0)
