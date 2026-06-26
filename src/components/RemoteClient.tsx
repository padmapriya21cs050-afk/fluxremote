import React, { useState, useEffect, useRef } from "react";
import {
  Monitor,
  Settings,
  LogOut,
  Lock,
  Wifi,
  WifiOff,
  Send,
  Copy,
  Check,
  Loader,
  AlertCircle,
  ChevronRight,
} from "lucide-react";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface Device {
  id: string;
  name: string;
  status: "online" | "offline" | "in-session";
}

interface ConnectionStatus {
  connected: boolean;
  device?: string;
  latency?: number;
}

export default function RemoteClient() {
  const [activeTab, setActiveTab] = useState<"devices" | "remote" | "settings">(
    "devices"
  );

  // Devices state
  const [devices, setDevices] = useState<Device[]>([]);
  const [loadingDevices, setLoadingDevices] = useState(false);

  // Connection state
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({
    connected: false,
  });
  const [connectionError, setConnectionError] = useState("");

  // Remote viewer state
  const videoRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Cursor position for viewer
  const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });

  // Settings state
  const [apiUrl, setApiUrl] = useState(API_BASE_URL);
  const [settingsSaved, setSettingsSaved] = useState(false);

  const getWebSocketUrl = (apiBase: string, deviceId: string): string => {
    try {
      const url = new URL(apiBase);
      const protocol = url.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${url.host}/ws/viewer/${encodeURIComponent(deviceId)}`;
    } catch {
      const normalized = apiBase.replace(/\/+$/, "").replace(/^https?:\/\//, "");
      const protocol = apiBase.startsWith("https:") ? "wss:" : "ws:";
      return `${protocol}//${normalized}/ws/viewer/${encodeURIComponent(deviceId)}`;
    }
  };

  const getHostWebSocketUrl = (apiBase: string, deviceId: string): string => {
    try {
      const url = new URL(apiBase);
      const protocol = url.protocol === "https:" ? "wss:" : "ws:";
      return `${protocol}//${url.host}/ws/host/${encodeURIComponent(deviceId)}`;
    } catch {
      const normalized = apiBase.replace(/\/+$/, "").replace(/^https?:\/\//, "");
      const protocol = apiBase.startsWith("https:") ? "wss:" : "ws:";
      return `${protocol}//${normalized}/ws/host/${encodeURIComponent(deviceId)}`;
    }
  };

  // Clipboard states
  const [localClipboard, setLocalClipboard] = useState("");
  const [showCopyFeedback, setShowCopyFeedback] = useState(false);
  const hostWsRef = useRef<WebSocket | null>(null);
  const [hostRegistered, setHostRegistered] = useState(false);

  // Fetch available devices
  const fetchDevices = async () => {
    setLoadingDevices(true);
    try {
      const response = await fetch(`${apiUrl}/api/devices/online`);

      if (!response.ok) throw new Error("Failed to fetch devices");

      const payload = await response.json();
      const deviceList = Array.isArray(payload) ? payload : payload.devices || [];
      setDevices(
        deviceList.map((device: any) => ({
          id: device.device_id || device.id,
          name: device.device_name || device.name,
          status: device.is_online ? "online" : "offline",
        }))
      );
    } catch (err) {
      console.error("Error fetching devices:", err);
    } finally {
      setLoadingDevices(false);
    }
  };

  // Connect to device
  const handleConnect = async (device: Device) => {
    setSelectedDevice(device);
    setIsConnecting(true);
    setConnectionError("");

    try {
      const accessPassword = window.prompt(
        "Enter the access password for this device:"
      );
      if (!accessPassword) {
        throw new Error("Connection canceled: access password is required.");
      }

      const response = await fetch(`${apiUrl}/api/sessions/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          device_id: device.id,
          access_password: accessPassword,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || "Connection failed");
      }

      const data = await response.json();
      const wsUrl = getWebSocketUrl(apiUrl, device.id);

      wsRef.current = new WebSocket(wsUrl);

      wsRef.current.onopen = () => {
        setIsConnecting(false);
        setConnectionStatus({ connected: true, device: device.name });
        setActiveTab("remote");
      };

      wsRef.current.onmessage = (event) => {
        // Handle incoming stream frames or data
        if (videoRef.current && event.data instanceof Blob) {
          const ctx = videoRef.current.getContext("2d");
          if (ctx) {
            const img = new Image();
            img.onload = () => {
              ctx.drawImage(img, 0, 0);
            };
            img.src = URL.createObjectURL(event.data);
          }
        }
      };

      wsRef.current.onerror = () => {
        setConnectionError("WebSocket connection error");
      };

      wsRef.current.onclose = () => {
        setConnectionStatus({ connected: false });
        setSelectedDevice(null);
      };
    } catch (err) {
      setConnectionError(
        err instanceof Error ? err.message : "Connection failed"
      );
      setIsConnecting(false);
    }
  };

  // Disconnect from device
  const handleDisconnect = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionStatus({ connected: false });
    setSelectedDevice(null);
    setActiveTab("devices");
  };

  // Send remote input via WebSocket
  const handleRemoteInput = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    wsRef.current.send(
      JSON.stringify({
        type: "input",
        action: "click",
        x: Math.round((x / rect.width) * 1920),
        y: Math.round((y / rect.height) * 1080),
      })
    );
  };

  // Handle mouse move tracking
  const handleMouseMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setCursorPos({
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    });
  };

  // Save settings
  const handleSaveSettings = () => {
    localStorage.setItem("apiUrl", apiUrl);
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 3000);
  };

  // Copy to clipboard
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setShowCopyFeedback(true);
    setTimeout(() => setShowCopyFeedback(false), 2000);
  };

  // Handle logout
  const handleLogout = () => {
    setDevices([]);
    handleDisconnect();
  };

  // Load initial settings
  useEffect(() => {
    const savedApiUrl = localStorage.getItem("apiUrl");
    if (savedApiUrl) {
      setApiUrl(savedApiUrl);
    }
  }, []);

  const hostRegistrationStarted = useRef(false);

  useEffect(() => {
    if (hostRegistrationStarted.current) {
      return;
    }
    hostRegistrationStarted.current = true;

    // Auto-register a host device (for development) and refresh device list
    const registerHost = async () => {
      try {
        // Persist device id
        let deviceId = localStorage.getItem("hostDeviceId");
        if (!deviceId) {
          deviceId = (crypto && (crypto as any).randomUUID ? (crypto as any).randomUUID() : `dev-${Date.now()}-${Math.random().toString(36).slice(2,8)}`);
          localStorage.setItem("hostDeviceId", deviceId);
        }

        let deviceName = localStorage.getItem("hostDeviceName");
        if (!deviceName) {
          deviceName = (navigator as any).userAgentData?.platform || navigator.platform || "My Computer";
          localStorage.setItem("hostDeviceName", deviceName);
        }

        const payload = {
          device_id: deviceId,
          device_name: deviceName,
          access_password: "123456",
        };

        // Register device with backend
        const registerResp = await fetch(`${apiUrl}/api/devices/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!registerResp.ok) {
          console.warn("Host registration failed", await registerResp.text().catch(()=>null));
        } else {
          setHostRegistered(true);
          // Open host WebSocket to mark device online
          try {
            const wsUrl = getHostWebSocketUrl(apiUrl, deviceId);
            hostWsRef.current = new WebSocket(wsUrl);
            hostWsRef.current.onopen = () => {
              console.info("Host websocket connected:", wsUrl);
            };
            hostWsRef.current.onclose = () => {
              console.info("Host websocket closed");
            };
            hostWsRef.current.onerror = (e) => console.error("Host websocket error", e);
          } catch (e) {
            console.error("Failed to open host websocket", e);
          }
        }

        // Refresh devices list after registration
        await fetchDevices();
      } catch (e) {
        console.error("Auto host registration failed:", e);
      }
    };

    registerHost();
  }, [apiUrl]);

  // MAIN APPLICATION INTERFACE
  return (
    <div className="flex h-screen w-screen bg-[#0B132B] text-slate-100 overflow-hidden">
      {/* Sidebar */}
      <div className="w-56 bg-[#1E293B] border-r border-slate-800 flex flex-col shrink-0">
        {/* Header */}
        <div className="p-4 flex items-center gap-3 border-b border-slate-800">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Monitor className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white">FluxRemote</h1>
            <p className="text-[10px] text-slate-400">Client</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          <button
            onClick={() => setActiveTab("devices")}
            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-semibold transition ${
              activeTab === "devices"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
            }`}
          >
            <Monitor className="w-4 h-4" />
            Devices
          </button>

          <button
            onClick={() => setActiveTab("remote")}
            disabled={!connectionStatus.connected}
            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-semibold transition ${
              !connectionStatus.connected ? "opacity-40 cursor-not-allowed" : ""
            } ${
              activeTab === "remote"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
            }`}
          >
            <Wifi className="w-4 h-4" />
            Remote
          </button>

          <button
            onClick={() => setActiveTab("settings")}
            className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs font-semibold transition ${
              activeTab === "settings"
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
            }`}
          >
            <Settings className="w-4 h-4" />
            Settings
          </button>
        </nav>

        {/* Status & Logout */}
        <div className="p-4 border-t border-slate-800 space-y-3">
          <div className="text-[10px]">
            <div className="flex items-center gap-2 text-slate-400 mb-1">
              <span className={`w-2 h-2 rounded-full ${
                connectionStatus.connected ? "bg-emerald-500" : "bg-slate-500"
              }`} />
              <span>
                {connectionStatus.connected
                  ? `Connected: ${connectionStatus.device}`
                  : "Not connected"}
              </span>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Status Bar */}
        <div className="h-12 border-b border-slate-800 bg-[#0F172A] flex items-center px-6 shrink-0">
          <div className="flex items-center gap-2 text-xs font-mono">
            <div
              className={`w-2 h-2 rounded-full ${
                connectionStatus.connected ? "bg-emerald-500 animate-pulse" : "bg-slate-600"
              }`}
            />
            {connectionStatus.connected ? (
              <>
                <span className="text-slate-400">
                  Connected to:{" "}
                  <b className="text-white">{connectionStatus.device}</b>
                </span>
                {connectionStatus.latency && (
                  <span className="text-slate-400">
                    Latency: <b className="text-blue-400">{connectionStatus.latency} ms</b>
                  </span>
                )}
              </>
            ) : (
              <span className="text-slate-400">Ready for connection</span>
            )}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* DEVICES TAB */}
          {activeTab === "devices" && (
            <div className="space-y-6 max-w-5xl">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Devices</h2>
                <p className="text-sm text-slate-400">
                  Select a device to start a remote session
                </p>
              </div>

              {loadingDevices ? (
                <div className="flex items-center justify-center py-12">
                  <Loader className="w-6 h-6 text-blue-500 animate-spin" />
                </div>
              ) : devices.length === 0 ? (
                <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-8 text-center">
                  <Monitor className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                  <p className="text-slate-400">No devices available</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {devices.map((device) => (
                    <div
                      key={device.id}
                      className="bg-[#1E293B] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div>
                          <h3 className="font-semibold text-white">{device.name}</h3>
                          <p className="text-xs text-slate-400 font-mono">{device.id}</p>
                        </div>
                        <div
                          className={`w-2 h-2 rounded-full ${
                            device.status === "online"
                              ? "bg-emerald-500"
                              : device.status === "in-session"
                              ? "bg-blue-500"
                              : "bg-slate-500"
                          }`}
                        />
                      </div>

                      <button
                        onClick={() => handleConnect(device)}
                        disabled={device.status === "offline" || isConnecting}
                        className="w-full py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs font-bold rounded-lg transition flex items-center justify-center gap-2"
                      >
                        {isConnecting ? (
                          <>
                            <Loader className="w-3 h-3 animate-spin" />
                            Connecting...
                          </>
                        ) : (
                          <>
                            <Wifi className="w-3 h-3" />
                            Connect
                          </>
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Refresh button */}
              <div className="flex gap-2">
                <button
                  onClick={fetchDevices}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition"
                >
                  Refresh Devices
                </button>
              </div>
            </div>
          )}

          {/* REMOTE TAB */}
          {activeTab === "remote" && (
            <div className="space-y-4 max-w-5xl">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">
                    {selectedDevice?.name}
                  </h2>
                  <p className="text-sm text-slate-400">Remote desktop viewer</p>
                </div>
                <button
                  onClick={handleDisconnect}
                  className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-lg transition"
                >
                  Disconnect
                </button>
              </div>

              {/* Canvas/Video Viewer */}
              <div className="bg-slate-950 border-2 border-slate-800 rounded-lg overflow-hidden shadow-xl">
                <canvas
                  ref={videoRef}
                  onClick={handleRemoteInput}
                  onMouseMove={handleMouseMove}
                  width={1920}
                  height={1080}
                  className="w-full cursor-crosshair bg-black"
                />
              </div>

              {connectionError && (
                <div className="bg-rose-500/10 border border-rose-500/30 text-rose-400 px-4 py-3 rounded-lg text-sm flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  {connectionError}
                </div>
              )}
            </div>
          )}

          {/* SETTINGS TAB */}
          {activeTab === "settings" && (
            <div className="space-y-6 max-w-2xl">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Settings</h2>
                <p className="text-sm text-slate-400">
                  Configure FluxRemote client settings
                </p>
              </div>

              {/* API Configuration */}
              <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-white mb-3">
                    API Configuration
                  </h3>
                  <label className="text-xs font-semibold text-slate-300 block mb-2">
                    Backend API URL
                  </label>
                  <input
                    type="text"
                    value={apiUrl}
                    onChange={(e) => setApiUrl(e.target.value)}
                    placeholder="http://localhost:8000"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white placeholder:text-slate-600 focus:outline-none focus:border-blue-500 transition text-sm"
                  />
                  <p className="text-xs text-slate-500 mt-2">
                    Current: <span className="font-mono">{API_BASE_URL}</span>
                  </p>
                </div>

                <button
                  onClick={handleSaveSettings}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition"
                >
                  {settingsSaved ? "✓ Saved" : "Save Settings"}
                </button>
              </div>

              {/* Device Information */}
              {selectedDevice && (
                <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6 space-y-4">
                  <h3 className="text-sm font-semibold text-white">
                    Active Connection
                  </h3>
                  <div className="space-y-2 text-sm">
                    <p>
                      <span className="text-slate-400">Device:</span>
                      <span className="text-white ml-2">{selectedDevice.name}</span>
                    </p>
                    <p>
                      <span className="text-slate-400">ID:</span>
                      <span className="text-slate-300 ml-2 font-mono text-xs">
                        {selectedDevice.id}
                      </span>
                    </p>
                  </div>
                </div>
              )}

              {/* About */}
              <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6">
                <h3 className="text-sm font-semibold text-white mb-2">About</h3>
                <p className="text-xs text-slate-400">
                  FluxRemote v1.0.0
                  <br />
                  Secure remote access client
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
