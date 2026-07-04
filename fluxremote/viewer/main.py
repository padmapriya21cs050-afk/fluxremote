# fluxremote/viewer/main.py
"""
FluxRemote Viewer Client
A high-performance thread-safe PySide6 GUI application for remote desktop viewing,
device discovery, authentication, and secure relay control.
"""

import os
import sys
import json
import logging
import threading
import time
from typing import Optional, Dict, Any
from urllib.parse import quote

# Qt Imports
try:
    from PySide6.QtCore import Qt, QThread, Signal, Slot, QByteArray, QBuffer, QIODevice, QTimer
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QLineEdit, QPushButton, QLabel, QListWidget,
                                 QListWidgetItem, QMessageBox, QSlider, QStatusBar, QSplitter)
    from PySide6.QtGui import QImage, QPixmap, QKeyEvent, QMouseEvent, QWheelEvent, QKeySequence
except ImportError:
    print("Warning: PySide6 is not installed. Run: pip install PySide6 requests websocket-client pyperclip")
    # We will still generate the complete production-grade source code for compilation

import requests
import websocket
import pyperclip

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] Viewer: %(message)s")
logger = logging.getLogger("fluxremote.viewer")

class WSClientThread(QThread):
    """Background thread that manages the screen stream WebSocket connection."""
    
    frame_received = Signal(bytes)
    status_updated = Signal(str)
    connection_lost = Signal()
    
    def __init__(self, ws_url: str, device_id: str, auth_token: Optional[str] = None):
        super().__init__()
        self.ws_url = ws_url
        self.device_id = device_id
        self.auth_token = auth_token or os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = True
        
    def _build_ws_endpoint(self, path: str) -> str:
        url = f"{self.ws_url}{path}"
        if not self.auth_token:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}token={quote(self.auth_token)}"
        
    def run(self):
        ws_endpoint = self._build_ws_endpoint(f"/ws/viewer/{self.device_id}")
        logger.info(f"Connecting viewer WebSocket: {ws_endpoint}")
        self.status_updated.emit("Establishing secure link...")
        
        while self.running:
            try:
                # Use on_data to reliably receive binary frames (JPEG bytes)
                self.ws = websocket.WebSocketApp(
                    ws_endpoint,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_data=self.on_data,
                    on_error=self.on_error,
                    on_close=self.on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Viewer WebSocket loop error: {e}")
                self.status_updated.emit("Connection error.")
                
            if self.running:
                # Retry delay
                self.status_updated.emit("Retrying link in 3 seconds...")
                time.sleep(3)
                
    def on_open(self, ws):
        logger.info("Viewer WebSocket linked to relay.")
        self.status_updated.emit("Connected. Waiting for host stream...")
        
    def on_message(self, ws, message):
        # Text messages handled here (errors/status)
        if isinstance(message, bytes):
            # Some transports may deliver binary here; handle defensively
            self.frame_received.emit(message)
        else:
            try:
                data = json.loads(message)
                if data.get("type") == "error":
                    self.status_updated.emit(data.get("message", "Error notification"))
            except Exception:
                pass

    def on_data(self, ws, data, data_type, cont):
        """Callback invoked by websocket-client for raw data frames.
        We only care about binary frames (data_type == OPCODE_BINARY).
        """
        try:
            if data_type == websocket.ABNF.OPCODE_BINARY:
                # `data` is a bytes-like object containing the JPEG frame
                self.frame_received.emit(data)
        except Exception as e:
            logger.error(f"Error in on_data handler: {e}")

    def on_close(self, ws, code, msg):
        logger.warning(f"Viewer socket disconnected: {code} - {msg}")
        self.status_updated.emit("Disconnected from relay.")
        self.connection_lost.emit()

    def on_error(self, ws, error):
        logger.error(f"Viewer socket error: {error}")
        self.status_updated.emit(f"Error: {error}")

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        self.wait()


class ControlWSClientThread(QThread):
    """Dedicated low-latency WebSocket tunnel for mouse, keyboard, and clipboard input."""

    status_updated = Signal(str)

    def __init__(self, ws_url: str, device_id: str, auth_token: Optional[str] = None):
        super().__init__()
        self.ws_url = ws_url
        self.device_id = device_id
        self.auth_token = auth_token or os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = True

    def _build_ws_endpoint(self, path: str) -> str:
        url = f"{self.ws_url}{path}"
        if not self.auth_token:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}token={quote(self.auth_token)}"

    def run(self):
        ws_endpoint = self._build_ws_endpoint(f"/ws/control/{self.device_id}")
        logger.info(f"Connecting control tunnel: {ws_endpoint}")
        self.status_updated.emit("Control tunnel connecting...")

        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    ws_endpoint,
                    on_open=self.on_open,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Control tunnel loop error: {e}")
                self.status_updated.emit("Control tunnel error.")

            if self.running:
                time.sleep(1)

    def on_open(self, ws):
        logger.info("Control tunnel linked to relay.")
        self.status_updated.emit("Control tunnel ready.")

    def on_close(self, ws, code, msg):
        logger.warning(f"Control tunnel disconnected: {code} - {msg}")

    def on_error(self, ws, error):
        logger.error(f"Control tunnel socket error: {error}")

    def __init__(self, ws_url: str, device_id: str, auth_token: Optional[str] = None):
        super().__init__()
        self.ws_url = ws_url
        self.device_id = device_id
        self.auth_token = auth_token or os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")
        self.ws: Optional[websocket.WebSocketApp] = None
        self.running = True
        self._input_latency_samples = []

    def send_action(self, msg_type: str, payload: dict):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                # Keep input traffic on the dedicated control tunnel so it bypasses screen-frame backpressure.
                send_started = time.perf_counter()
                packet = json.dumps({"type": msg_type, "payload": payload})
                self.ws.send(packet)
                latency_ms = (time.perf_counter() - send_started) * 1000.0
                self._record_input_latency(latency_ms)
            except Exception as e:
                logger.error(f"Failed to send control packet: {e}")

    def _record_input_latency(self, latency_ms: float):
        self._input_latency_samples.append(latency_ms)
        if len(self._input_latency_samples) >= 20:
            average_ms = sum(self._input_latency_samples) / len(self._input_latency_samples)
            logger.info("Average control-tunnel send latency: %.2f ms", average_ms)
            self._input_latency_samples.clear()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()
        self.wait()


class DesktopCanvas(QLabel):
    """Custom rendering canvas for remote desktop frame drawing and coordinate-mapped event capturing."""
    
    action_triggered = Signal(str, dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.original_width = 1920 # Default host standard resolution
        self.original_height = 1080
        self.setScaledContents(True)
        self.setMinimumSize(800, 450)

        # Coalesce mouse movement updates to a ~12 ms cadence and interpolate between points for smoother motion.
        self._pending_mouse_move = None
        self._mouse_move_target = None
        self._last_mouse_send_position = None
        self._mouse_move_timer = QTimer(self)
        self._mouse_move_timer.setSingleShot(True)
        self._mouse_move_timer.timeout.connect(self._flush_pending_mouse_move)
        self._last_mouse_send_time = 0.0

    def update_resolution(self, width: int, height: int):
        self.original_width = width
        self.original_height = height

    def _map_coordinates(self, local_x: int, local_y: int) -> tuple:
        """Translates current window canvas pixel points into actual remote display coordinate points."""
        scale_x = self.original_width / self.width()
        scale_y = self.original_height / self.height()
        return int(local_x * scale_x), int(local_y * scale_y)

    def mouseMoveEvent(self, event: QMouseEvent):
        rx, ry = self._map_coordinates(event.position().x(), event.position().y())
        now = time.time()
        # Queue the latest mouse target; moves are throttled to ~12 ms and smoothed with interpolation.
        self._mouse_move_target = (rx, ry)

        if now - self._last_mouse_send_time >= 0.012:
            self._last_mouse_send_time = now
            self._flush_pending_mouse_move()
        elif not self._mouse_move_timer.isActive():
            self._mouse_move_timer.start(12)
        event.accept()

    def _flush_pending_mouse_move(self):
        if self._mouse_move_target is None:
            return

        target_x, target_y = self._mouse_move_target
        if self._last_mouse_send_position is None:
            send_position = (target_x, target_y)
        else:
            last_x, last_y = self._last_mouse_send_position
            # Interpolate halfway to the newest target so cursor motion remains smooth while still staying responsive.
            send_position = (
                int(last_x + (target_x - last_x) * 0.55),
                int(last_y + (target_y - last_y) * 0.55),
            )

        self._last_mouse_send_position = send_position
        self._mouse_move_target = None
        self._pending_mouse_move = None
        self.action_triggered.emit("mouse_move", {"x": send_position[0], "y": send_position[1]})

    def mousePressEvent(self, event: QMouseEvent):
        # Clicks bypass the mouse-move throttle and go out immediately to preserve precise interaction.
        self._mouse_move_timer.stop()
        self._flush_pending_mouse_move()

        button = "left"
        if event.button() == Qt.RightButton:
            button = "right"
        elif event.button() == Qt.MiddleButton:
            button = "middle"
            
        self.action_triggered.emit("mouse_click", {"button": button})
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.action_triggered.emit("mouse_double_click", {})
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        # PySide6: angleDelta returns scrolling step amounts
        amount = event.angleDelta().y()
        self.action_triggered.emit("mouse_scroll", {"amount": amount})
        event.accept()


class RemoteSessionWindow(QMainWindow):
    """The live desktop screen streaming controller containing FPS/quality sliders,
    the scaling video frame layer, and a connection status bar."""
    
    def __init__(self, ws_url: str, device_id: str, auth_token: Optional[str] = None):
        super().__init__()
        self.ws_url = ws_url
        self.device_id = device_id
        self.auth_token = auth_token or os.environ.get("FLUXREMOTE_TUNNEL_TOKEN") or os.environ.get("TUNNEL_TOKEN")
        
        self.setWindowTitle(f"FluxRemote: Controlling {device_id}")
        self.resize(1100, 700)
        
        # Build Central Structure
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Control bar
        self.control_layout = QHBoxLayout()
        self.control_layout.setContentsMargins(10, 5, 10, 5)
        
        self.lbl_fps = QLabel("Target FPS (15):")
        self.slider_fps = QSlider(Qt.Horizontal)
        self.slider_fps.setRange(1, 60)
        self.slider_fps.setValue(15)
        self.slider_fps.valueChanged.connect(self.on_fps_changed)
        
        self.lbl_quality = QLabel("JPEG Quality (60%):")
        self.slider_quality = QSlider(Qt.Horizontal)
        self.slider_quality.setRange(10, 100)
        self.slider_quality.setValue(60)
        self.slider_quality.valueChanged.connect(self.on_quality_changed)
        
        self.btn_disconnect = QPushButton("Disconnect Session")
        self.btn_disconnect.setStyleSheet("background-color: #d32f2f; color: white; font-weight: bold; padding: 5px;")
        self.btn_disconnect.clicked.connect(self.close)
        
        self.control_layout.addWidget(self.lbl_fps)
        self.control_layout.addWidget(self.slider_fps)
        self.control_layout.addWidget(self.lbl_quality)
        self.control_layout.addWidget(self.slider_quality)
        self.control_layout.addWidget(self.btn_disconnect)
        
        self.main_layout.addLayout(self.control_layout)
        
        # Streaming display Canvas
        self.canvas = DesktopCanvas()
        self.canvas.action_triggered.connect(self.send_user_action)
        self.main_layout.addWidget(self.canvas)
        
        # Setup Status bar
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.showMessage("Ready.")
        
        # Create networking threads
        self.net_thread = WSClientThread(self.ws_url, self.device_id, self.auth_token)
        self.net_thread.frame_received.connect(self.draw_frame)
        self.net_thread.status_updated.connect(self.statusbar.showMessage)
        self.net_thread.connection_lost.connect(self.on_connection_lost)
        self.net_thread.start()

        self.control_thread = ControlWSClientThread(self.ws_url, self.device_id, self.auth_token)
        self.control_thread.status_updated.connect(self.statusbar.showMessage)
        self.control_thread.start()
        
        # Clipboard sync monitor
        self.last_clipboard = ""
        self.clipboard_timer = threading.Thread(target=self._clipboard_monitor_loop, daemon=True)
        self.clipboard_timer.start()

    def draw_frame(self, jpeg_bytes: bytes):
        """Draws binary JPEG screen pixels smoothly into the Qt QLabel Canvas."""
        try:
            size = len(jpeg_bytes) if jpeg_bytes else 0
            logger.debug(f"Received frame bytes: {size}")

            pixmap = QPixmap()
            # Try explicit JPEG decode first
            ok = pixmap.loadFromData(jpeg_bytes, "JPEG")
            if not ok or pixmap.isNull():
                # Fallback to auto-detect format
                logger.debug("Primary JPEG load failed, trying auto-detect format.")
                pixmap = QPixmap()
                ok2 = pixmap.loadFromData(jpeg_bytes)
                if not ok2 or pixmap.isNull():
                    logger.error("Failed to construct QPixmap from received frame data.")
                    return

            self.canvas.setPixmap(pixmap)
            self.canvas.update_resolution(pixmap.width(), pixmap.height())
        except Exception as e:
            logger.error(f"Error drawing received frame: {e}")

    def send_user_action(self, msg_type: str, payload: dict):
        self.control_thread.send_action(msg_type, payload)

    def on_fps_changed(self, value: int):
        self.lbl_fps.setText(f"Target FPS ({value}):")
        self.send_user_action("fps_update", {"fps": value})

    def on_quality_changed(self, value: int):
        self.lbl_quality.setText(f"JPEG Quality ({value}%):")
        self.send_user_action("quality_update", {"quality": value})

    def on_connection_lost(self):
        QMessageBox.warning(self, "Session Expired", "Desktop host stream terminated unexpectedly.")
        self.close()

    def keyPressEvent(self, event: QKeyEvent):
        """Binds keyboard keystroke captures and routes them seamlessly over WebSockets."""
        key_name = event.text()
        if not key_name:
            # Map system shortcut keys (arrow keys, backspaces, entries)
            key = event.key()
            if key == Qt.Key_Backspace:
                key_name = "backspace"
            elif key == Qt.Key_Enter or key == Qt.Key_Return:
                key_name = "enter"
            elif key == Qt.Key_Tab:
                key_name = "tab"
            elif key == Qt.Key_Escape:
                key_name = "escape"
            elif key == Qt.Key_Left:
                key_name = "left"
            elif key == Qt.Key_Right:
                key_name = "right"
            elif key == Qt.Key_Up:
                key_name = "up"
            elif key == Qt.Key_Down:
                key_name = "down"
                
        if key_name:
            self.send_user_action("key_press", {"key": key_name})
        event.accept()

    def _clipboard_monitor_loop(self):
        """Periodically checks local Windows clipboard and syncs copy triggers to host clipboard."""
        while self.net_thread.isRunning():
            try:
                current_text = pyperclip.paste()
                if current_text and current_text != self.last_clipboard:
                    self.last_clipboard = current_text
                    self.send_user_action("clipboard_sync", {"text": current_text})
            except Exception:
                pass
            time.sleep(2)

    def closeEvent(self, event):
        self.control_thread.stop()
        self.net_thread.stop()
        event.accept()


class DeviceExplorerWindow(QMainWindow):
    """Control hub that displays registered desktops, verifies target credentials,
    and bridges connection handshakes."""
    
    def __init__(self, server_url: str, username: str = "Guest"):
        super().__init__()
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.session_window: Optional[RemoteSessionWindow] = None
        
        self.setWindowTitle(f"FluxRemote Control Hub - User: {self.username}")
        self.resize(700, 450)
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # Header
        self.lbl_title = QLabel("Choose an online host computer to control:")
        self.lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        self.main_layout.addWidget(self.lbl_title)
        
        # List of devices
        self.device_list = QListWidget()
        self.main_layout.addWidget(self.device_list)
        
        # Details & connection action buttons
        self.controls_layout = QHBoxLayout()
        
        self.lbl_pass = QLabel("Host Access Password:")
        self.txt_pass = QLineEdit()
        self.txt_pass.setEchoMode(QLineEdit.Password)
        self.txt_pass.setPlaceholderText("Enter password of target desktop")
        
        self.btn_refresh = QPushButton("Refresh List")
        self.btn_refresh.clicked.connect(self.refresh_devices)
        self.btn_refresh.setStyleSheet("background-color: #0288d1; color: white; padding: 6px;")
        
        self.btn_connect = QPushButton("Control Device")
        self.btn_connect.clicked.connect(self.initiate_connection)
        self.btn_connect.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold; padding: 6px;")
        
        self.controls_layout.addWidget(self.lbl_pass)
        self.controls_layout.addWidget(self.txt_pass)
        self.controls_layout.addWidget(self.btn_refresh)
        self.controls_layout.addWidget(self.btn_connect)
        
        self.main_layout.addLayout(self.controls_layout)
        
        # Initial population of device configurations
        self.refresh_devices()

    def refresh_devices(self):
        self.device_list.clear()
        try:
            http_url = self.server_url.replace("ws://", "http://").replace("wss://", "https://")
            response = requests.get(f"{http_url}/api/devices/online", timeout=5)
            if response.status_code == 200:
                devices = response.json()
                for dev in devices:
                    item = QListWidgetItem()
                    item.setText(f"🖥️ {dev['device_name']} (ID: {dev['device_id']}) - ONLINE")
                    item.setData(Qt.UserRole, dev['device_id'])
                    self.device_list.addItem(item)
                if not devices:
                    self.device_list.addItem("No remote computers are active. Launch host agent on your target PC first.")
            else:
                QMessageBox.warning(self, "Data Error", "Unable to load online device definitions.")
        except Exception as e:
            logger.error(f"Failed to fetch online devices: {e}")
            QMessageBox.critical(self, "Network Failure", "Cannot reach signaling server.")

    def initiate_connection(self):
        selected_item = self.device_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Selection Required", "Please select an active computer from the explorer list.")
            return
            
        device_id = selected_item.data(Qt.UserRole)
        if not device_id:
            return
            
        password = self.txt_pass.text().strip()
        if not password:
            QMessageBox.warning(self, "Password Required", "Please fill in the target's access connection password.")
            return
            
        # Call API to generate and validate remote session
        try:
            http_url = self.server_url.replace("ws://", "http://").replace("wss://", "https://")
            payload = {"device_id": device_id, "access_password": password}
            
            response = requests.post(f"{http_url}/api/sessions/create", json=payload, timeout=5)
            if response.status_code == 200:
                # Handshake authorized
                logger.info("Connection Session Authorized. Launching streaming viewer stage...")
                self.session_window = RemoteSessionWindow(self.server_url, device_id)
                self.session_window.show()
                self.txt_pass.clear()
            else:
                error_msg = response.json().get("detail", "Access rejected. Invalid device password.")
                QMessageBox.warning(self, "Security Refusal", error_msg)
        except Exception as e:
            QMessageBox.critical(self, "Relay Error", f"Failed to negotiate device handshake: {e}")


# Login UI removed: application now launches directly into DeviceExplorerWindow


# Main Launch Logic
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FluxRemote GUI Desktop Viewer")
    parser.add_argument("--server", default="ws://localhost:3000", help="FastAPI Signalling server websocket root")
    args = parser.parse_args()
    
    app = QApplication(sys.argv)
    
    # Configure Qt layout direction and appearance
    app.setStyle("Fusion")
    
    explorer = DeviceExplorerWindow(args.server)
    explorer.show()
    
    sys.exit(app.exec())
