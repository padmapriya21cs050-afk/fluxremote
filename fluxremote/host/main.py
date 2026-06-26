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
from typing import Dict, Any, Optional

# Required external packages
try:
    import mss
    import pyautogui
    from PIL import Image
    import io
    import websocket
    import requests
except ImportError:
    print("Warning: Missing required packages. Run: pip install mss pyautogui pillow websocket-client requests")
    # We will still generate the complete file for compilation/packaging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Host: %(message)s")
logger = logging.getLogger("fluxremote.host")

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = False  # Prevent crash if mouse goes to (0,0)
pyautogui.PAUSE = 0.01       # Reduce delay between commands for low latency

class FluxHost:
    def __init__(self, server_url: str, device_id: str, access_password: str, device_name: str = None):
        self.server_url = server_url.rstrip('/')
        self.device_id = device_id
        self.access_password = access_password
        self.device_name = device_name or socket.gethostname()
        
        # Connection statuses
        self.running = False
        self.connected = False
        self.ws: Optional[websocket.WebSocketApp] = None
        
        # Stream parameters
        self.fps = 15
        self.quality = 60 # 0-100 JPEG quality
        
        # Threads
        self.capture_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        
        # Performance metrics
        self.frame_count = 0
        self.last_fps_check = time.time()
        self.current_fps = 0

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
            response = requests.post(f"{http_url}/api/devices/register", json=payload, timeout=5)
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
        ws_endpoint = f"{self.server_url}/ws/host/{self.device_id}"
        
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
        logger.info("Host Agent stopped.")

    def on_open(self, ws):
        logger.info("WebSocket connection established. Starting worker threads...")
        self.connected = True
        
        # Launch capture & transmit loop
        self.capture_thread = threading.Thread(target=self._capture_and_stream_loop, daemon=True)
        self.capture_thread.start()
        
        # Launch background heartbeat ping
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket closed. Code: {close_status_code}, Message: {close_msg}")
        self.connected = False

    def on_error(self, ws, error):
        logger.error(f"WebSocket transport error: {error}")

    def on_message(self, ws, message):
        """Handles incoming keyboard/mouse/control updates from viewer."""
        try:
            data = json.loads(message)
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
                # Relative or absolute coords
                x = int(payload.get("x", 0))
                y = int(payload.get("y", 0))
                pyautogui.moveTo(x, y)
                
            elif msg_type == "mouse_click":
                button = payload.get("button", "left")
                pyautogui.click(button=button)
                
            elif msg_type == "mouse_double_click":
                pyautogui.doubleClick()
                
            elif msg_type == "mouse_right_click":
                pyautogui.rightClick()
                
            elif msg_type == "mouse_scroll":
                amount = int(payload.get("amount", 0))
                # On Windows scroll is positive for up, negative for down
                pyautogui.scroll(amount)
                
            elif msg_type == "key_press":
                key = payload.get("key")
                if key:
                    pyautogui.press(key)
                    
            elif msg_type == "key_shortcut":
                keys = payload.get("keys", [])
                if keys:
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

    def _heartbeat_loop(self):
        """Sends periodic 'heartbeat' pings to the relay server to avoid timeout disconnects."""
        while self.connected and self.running:
            try:
                if self.ws:
                    self.ws.send("heartbeat")
            except Exception:
                break
            time.sleep(15)

    def _capture_and_stream_loop(self):
        """Ultra-fast loop capturing primary screen using mss, compressing, and sending."""
        logger.info("Desktop Screen Stream Active.")
        
        with mss.mss() as sct:
            # Capture primary monitor (index 1)
            monitor = sct.monitors[1]
            
            while self.connected and self.running:
                start_time = time.time()
                
                try:
                    # 1. Grab screen buffer
                    sct_img = sct.grab(monitor)
                    
                    # 2. Convert raw BGRA pixels to high-efficiency Pillow RGB image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    # 3. Compress directly to memory as JPEG byte stream
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=self.quality)
                    jpeg_bytes = img_byte_arr.getvalue()
                    
                    # 4. Transmit binary bytes directly over WebSocket
                    if self.ws and self.connected:
                        self.ws.send(jpeg_bytes, opcode=websocket.ABNF.OPCODE_BINARY)
                        
                    # Calculate stats
                    self.frame_count += 1
                    now = time.time()
                    if now - self.last_fps_check >= 1.0:
                        self.current_fps = self.frame_count
                        self.frame_count = 0
                        self.last_fps_check = now
                        
                    # Throttling based on FPS target
                    elapsed = time.time() - start_time
                    delay = (1.0 / self.fps) - elapsed
                    if delay > 0:
                        time.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"Error in capture or transmission loop: {e}")
                    time.sleep(1)


# Command-Line Starter
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FluxRemote Host Agent Daemon")
    parser.add_argument("--server", default="ws://localhost:8000", help="Relay server websocket address")
    parser.add_argument("--id", default="DESKTOP-PC10", help="Unique Remote Device ID")
    parser.add_argument("--password", default="1234567", help="Target access password")
    args = parser.parse_args()
    
    print("------------------------------------------")
    print("       FLUXREMOTE WINDOWS HOST AGENT     ")
    print(f"       Device ID: {args.id}")
    print(f"       Server: {args.server}")
    print("------------------------------------------")
    
    host = FluxHost(server_url=args.server, device_id=args.id, access_password=args.password)
    try:
        host.start()
    except KeyboardInterrupt:
        host.stop()
        sys.exit(0)
