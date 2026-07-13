import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  Monitor,
  Settings,
  LogOut,
  Wifi,
  Loader,
  AlertCircle,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Activity,
  X,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import RemoteCopilot from "./RemoteCopilot";
import SessionDashboard from "./SessionDashboard";
import TunnelSettings from "./TunnelSettings";
import { getApiBase, normalizeServerUrl } from "../utils/api";


const buildWebSocketUrl = (serverUrl: string, path: string, token?: string) => {
  const normalized = normalizeServerUrl(serverUrl);
  try {
    const parsed = new URL(normalized);
    let protocol = parsed.protocol;
    if (protocol === "https:") protocol = "wss:";
    if (protocol === "http:") protocol = "ws:";
    if (protocol !== "ws:" && protocol !== "wss:") protocol = "wss:";
    const url = `${protocol}//${parsed.host}${path}`;
    if (!token) {
      return url;
    }

    const params = new URLSearchParams();
    params.set("token", token);
    params.set("auth_token", token);
    return `${url}${url.includes("?") ? "&" : "?"}${params.toString()}`;
  } catch {
    const cleaned = normalized.replace(/\/+$/, "");
    const prefix = cleaned.startsWith("http") ? cleaned : `https://${cleaned}`;
    const parsed = new URL(prefix);
    const protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${parsed.host}${path}`;
    if (!token) {
      return url;
    }

    const params = new URLSearchParams();
    params.set("token", token);
    params.set("auth_token", token);
    return `${url}${url.includes("?") ? "&" : "?"}${params.toString()}`;
  }
};

const generateId = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
};

interface Device {
  id: string;
  name: string;
  status: "online" | "offline" | "in-session";
}

interface ConnectionStatus {
  connected: boolean;
  device?: string;
}

interface DashboardMetrics {
  ping: number;
  fps: number;
  bandwidth: number;
  hostCpu: number;
  hostMemory: number;
  sessionDuration: number;
}

interface PendingInput {
  packet: Record<string, any>;
  attempts: number;
  lastSent: number;
}

export default function RemoteClient() {
  const [activeTab, setActiveTab] = useState<"devices" | "remote" | "settings">("devices");

  // Devices state
  const [devices, setDevices] = useState<Device[]>([]);
  const [loadingDevices, setLoadingDevices] = useState(false);

  // Connection state
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>({ connected: false });
  const [connectionError, setConnectionError] = useState("");
  const [websocketState, setWebsocketState] = useState("disconnected");
  const [hostStatus, setHostStatus] = useState("offline");
  const [viewerStatus, setViewerStatus] = useState("disconnected");

  // Remote viewer state
  const videoRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const controlWsRef = useRef<WebSocket | null>(null);
  const [zoom, setZoom] = useState(1);
  const [fitMode, setFitMode] = useState(true);
  const canvasContainerRef = useRef<HTMLDivElement>(null);
  const [remoteResolution, setRemoteResolution] = useState({ width: 1920, height: 1080 });

  // Settings state
  const [tunnelEnabled, setTunnelEnabled] = useState(false);
  const [tunnelUrl, setTunnelUrl] = useState("");
  const [tunnelToken, setTunnelToken] = useState("");
  const [tunnelProvider, setTunnelProvider] = useState<"Cloudflare" | "Ngrok" | "Tailscale">("Cloudflare");
  const [settingsSaved, setSettingsSaved] = useState(false);

  // Dashboard state
  const [dashboardMetrics, setDashboardMetrics] = useState<DashboardMetrics>({
    ping: 0,
    fps: 0,
    bandwidth: 0,
    hostCpu: 0,
    hostMemory: 0,
    sessionDuration: 0,
  });
  const sessionStartTimeRef = useRef<number>(0);
  const lastFpsTimeRef = useRef(Date.now());
  const frameCountRef = useRef(0);
  const lastPingSentRef = useRef<number>(0);
  const remoteResolutionRef = useRef({ width: 1920, height: 1080 });

  // AI panel state
  const [aiPanelCollapsed, setAiPanelCollapsed] = useState(false);
  const [aiPanelWidth, setAiPanelWidth] = useState(360);
  const [resizingAiPanel, setResizingAiPanel] = useState(false);
  const aiResizeStartRef = useRef<{ x: number; width: number } | null>(null);

  // Input reliability state
  const pendingInputsRef = useRef<Map<string, PendingInput>>(new Map());
  const inputQueueRef = useRef<Record<string, any>[]>([]);
  const inputRetryIntervalRef = useRef<number | null>(null);
  const heartbeatIntervalRef = useRef<number | null>(null);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (!resizingAiPanel || !aiResizeStartRef.current) return;
      const delta = aiResizeStartRef.current.x - event.clientX;
      const nextWidth = Math.min(520, Math.max(320, aiResizeStartRef.current.width + delta));
      setAiPanelWidth(nextWidth);
    };

    const handleMouseUp = () => {
      setResizingAiPanel(false);
      aiResizeStartRef.current = null;
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [resizingAiPanel]);

  const activeServerUrl = useMemo(() => {
    if (tunnelEnabled && tunnelUrl.trim()) {
      return normalizeServerUrl(tunnelUrl);
    }
    return getApiBase();
  }, [tunnelEnabled, tunnelUrl]);

  const activeAuthHeaders = useMemo(() => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (tunnelEnabled && tunnelToken.trim()) {
      headers["Authorization"] = `Bearer ${tunnelToken.trim()}`;
    }
    return headers;
  }, [tunnelEnabled, tunnelToken]);

  const getWebSocketUrl = (deviceId: string, sessionToken?: string) => {
    const authToken = tunnelEnabled && tunnelToken.trim() ? tunnelToken.trim() : sessionToken;
    return buildWebSocketUrl(activeServerUrl, `/ws/viewer/${encodeURIComponent(deviceId)}`, authToken);
  };
  const getControlWebSocketUrl = (deviceId: string, sessionToken?: string) => {
    const authToken = tunnelEnabled && tunnelToken.trim() ? tunnelToken.trim() : sessionToken;
    return buildWebSocketUrl(activeServerUrl, `/ws/control/${encodeURIComponent(deviceId)}`, authToken);
  };
  const getHostWebSocketUrl = (deviceId: string) => buildWebSocketUrl(activeServerUrl, `/ws/host/${encodeURIComponent(deviceId)}`, tunnelEnabled ? tunnelToken.trim() : undefined);

  const persistSettings = () => {
    localStorage.setItem("tunnelEnabled", JSON.stringify(tunnelEnabled));
    localStorage.setItem("tunnelUrl", tunnelUrl);
    localStorage.setItem("tunnelToken", tunnelToken);
    localStorage.setItem("tunnelProvider", tunnelProvider);
    setSettingsSaved(true);
    setTimeout(() => setSettingsSaved(false), 3000);
  };

  const loadSettings = () => {
    const enabled = localStorage.getItem("tunnelEnabled");
    const url = localStorage.getItem("tunnelUrl");
    const token = localStorage.getItem("tunnelToken");
    const provider = localStorage.getItem("tunnelProvider");

    setTunnelEnabled(enabled === "true");
    if (url) setTunnelUrl(url);
    if (token) setTunnelToken(token);
    if (provider === "Ngrok" || provider === "Tailscale" || provider === "Cloudflare") {
      setTunnelProvider(provider);
    }
  };

  const fetchDevices = async () => {
    setLoadingDevices(true);
    try {
      const response = await fetch(`${getApiBase(tunnelEnabled && tunnelUrl.trim() ? tunnelUrl : undefined)}/api/devices/online`, { headers: activeAuthHeaders });
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

  const requestAiExplanation = async (issueType: string, context: string) => {
    setIsConnecting(false);
    setConnectionError("");
    setWebsocketState("fetching_ai");
    try {
      const response = await fetch(`${getApiBase(tunnelEnabled && tunnelUrl.trim() ? tunnelUrl : undefined)}/api/ai/explain`, {
        method: "POST",
        headers: activeAuthHeaders,
        body: JSON.stringify({
          type: issueType,
          context,
          metrics: {
            connection_status: connectionStatus.connected ? "connected" : "disconnected",
            latency_ms: dashboardMetrics.ping,
            fps: dashboardMetrics.fps,
            websocket_state: websocketState,
            host_resolution: `${remoteResolution.width}x${remoteResolution.height}`,
            viewer_resolution: `${canvasContainerRef.current?.clientWidth || 0}x${canvasContainerRef.current?.clientHeight || 0}`,
          },
        }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(`AI service error: ${body}`);
      }

      const data = await response.json();
      return data.answer || data.explanation || "No explanation returned.";
    } catch (err) {
      console.error("AI explanation error:", err);
      return "Failed to fetch AI explanation. Check your server and Gemini API key.";
    } finally {
      setWebsocketState(connectionStatus.connected ? "connected" : "disconnected");
    }
  };

  const updateSessionDuration = () => {
    const now = Date.now();
    setDashboardMetrics((prev) => ({
      ...prev,
      sessionDuration: Math.floor((now - sessionStartTimeRef.current) / 1000),
    }));
  };

  const startHeartbeatAndRetries = () => {
    if (heartbeatIntervalRef.current) {
      window.clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }

    heartbeatIntervalRef.current = window.setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("heartbeat");
      }
      if (controlWsRef.current?.readyState === WebSocket.OPEN) {
        controlWsRef.current.send(JSON.stringify({ type: "heartbeat", payload: {} }));
        sendControlPacket("ping_check", {});
      }

      const now = Date.now();
      pendingInputsRef.current.forEach((pending, messageId) => {
        if (now - pending.lastSent > 1200 && pending.attempts < 5) {
          try {
            controlWsRef.current?.send(JSON.stringify(pending.packet));
            pendingInputsRef.current.set(messageId, {
              ...pending,
              attempts: pending.attempts + 1,
              lastSent: now,
            });
          } catch (err) {
            console.warn("Retrying control packet failed:", err);
          }
        }
      });
    }, 1000);
  };

  const stopHeartbeatAndRetries = () => {
    if (heartbeatIntervalRef.current) {
      window.clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
  };

  const queueControlInput = (packet: Record<string, any>) => {
    inputQueueRef.current.push(packet);
    if (inputQueueRef.current.length > 200) {
      inputQueueRef.current.shift();
    }
  };

  const flushQueuedInputs = () => {
    while (inputQueueRef.current.length > 0 && controlWsRef.current?.readyState === WebSocket.OPEN) {
      const packet = inputQueueRef.current.shift();
      if (packet) {
        try {
          controlWsRef.current.send(JSON.stringify(packet));
          pendingInputsRef.current.set(packet.message_id, {
            packet,
            attempts: 1,
            lastSent: Date.now(),
          });
        } catch (err) {
          queueControlInput(packet);
          break;
        }
      }
    }
  };

  const sendControlPacket = (type: string, payload: Record<string, any>) => {
    const message_id = generateId();
    const packet = {
      type,
      payload,
      message_id,
      timestamp: Date.now(),
    };

    if (controlWsRef.current?.readyState === WebSocket.OPEN) {
      try {
        const payload = JSON.stringify(packet);
        controlWsRef.current.send(payload);
        pendingInputsRef.current.set(message_id, {
          packet,
          attempts: 1,
          lastSent: Date.now(),
        });
      } catch (err) {
        queueControlInput(packet);
      }
    } else {
      queueControlInput(packet);
    }
  };

  const acknowledgeControlPacket = (messageId: string) => {
    pendingInputsRef.current.delete(messageId);
  };

  const connectControlSocket = (deviceId: string, sessionToken?: string) => {
    if (!deviceId) return;
    if (controlWsRef.current && controlWsRef.current.readyState === WebSocket.OPEN) return;
    const url = getControlWebSocketUrl(deviceId, sessionToken);
    console.log("Opening Control WS:", {
      url,
      authMode: tunnelEnabled && tunnelToken.trim() ? "tunnel-token" : sessionToken ? "session-token" : "none",
    });
    const controlSocket = new WebSocket(url);
    controlSocket.onopen = () => {
      setWebsocketState("control_ready");
      setViewerStatus("connected");
      flushQueuedInputs();
    };

    controlSocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "control_ack" && data.payload?.message_id) {
          acknowledgeControlPacket(data.payload.message_id);
          if (data.payload.status === "sent") {
            const now = Date.now();
            setDashboardMetrics((prev) => ({ ...prev, ping: Math.round(now - (lastPingSentRef.current || now)) }));
          }
        }
      } catch (err) {
        console.warn("Unknown control message:", err);
      }
    };

    controlSocket.onerror = () => {
      setWebsocketState("control_error");
      setViewerStatus("reconnecting");
      console.error("Control WS error");
    };

    controlSocket.onclose = (event) => {
      console.error("Control WS closed:", event.code, event.reason || "No reason provided");
      setViewerStatus("disconnected");
      setTimeout(() => connectControlSocket(deviceId), 2000);
    };

    controlWsRef.current = controlSocket;
  };

  const resetZoom = () => {
    setZoom(1);
    setFitMode(false);
  };

  const handleZoomIn = () => {
    setFitMode(false);
    setZoom((prev) => Math.min(prev + 0.25, 3));
  };

  const handleZoomOut = () => {
    setFitMode(false);
    setZoom((prev) => Math.max(prev - 0.25, 0.5));
  };

  const handleFitScreen = () => {
    if (!videoRef.current || !canvasContainerRef.current) return;

    const containerWidth = canvasContainerRef.current.clientWidth;
    const containerHeight = canvasContainerRef.current.clientHeight;
    const { width, height } = videoRef.current;
    const fitZoom = Math.min(containerWidth / width, containerHeight / height, 1);

    setZoom(fitZoom || 1);
    setFitMode(true);
  };

  const handleToggleFullscreen = async () => {
    if (!canvasContainerRef.current) return;

    if (!document.fullscreenElement) {
      try {
        await canvasContainerRef.current.requestFullscreen();
      } catch (err) {
        console.error("Fullscreen request failed:", err);
      }
    } else {
      await document.exitFullscreen();
    }
  };

  const closeRemoteSession = () => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (controlWsRef.current) {
      controlWsRef.current.close();
      controlWsRef.current = null;
    }
    stopHeartbeatAndRetries();
    setConnectionStatus({ connected: false });
    setIsConnecting(false);
    setConnectionError("");
    setSelectedDevice(null);
    setWebsocketState("disconnected");
    setHostStatus("offline");
    setViewerStatus("disconnected");
    setZoom(1);
    setFitMode(true);
  };

  const handleConnect = async (device: Device) => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (controlWsRef.current) {
      controlWsRef.current.close();
      controlWsRef.current = null;
    }
    stopHeartbeatAndRetries();

    setSelectedDevice(device);
    setIsConnecting(true);
    setConnectionError("");
    sessionStartTimeRef.current = Date.now();

    try {
      const accessPassword = window.prompt("Enter the access password for this device:");
      if (!accessPassword) {
        throw new Error("Connection canceled: access password is required.");
      }

      const response = await fetch(`${getApiBase(tunnelEnabled && tunnelUrl.trim() ? tunnelUrl : undefined)}/api/sessions/create`, {
        method: "POST",
        headers: activeAuthHeaders,
        body: JSON.stringify({ device_id: device.id, access_password: accessPassword }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || "Connection failed");
      }

      const sessionData = await response.json().catch(() => ({}));
      const sessionToken = typeof sessionData?.session_token === "string" ? sessionData.session_token : undefined;
      console.log("Session Response:", { sessionToken, deviceId: device.id, sessionData });

      setActiveTab("remote");
      setConnectionStatus({ connected: false, device: device.name });
      setWebsocketState("connecting");

      const wsUrl = getWebSocketUrl(device.id, sessionToken);
      console.log("Opening Screen WS:", {
        url: wsUrl,
        authMode: tunnelEnabled && tunnelToken.trim() ? "tunnel-token" : sessionToken ? "session-token" : "none",
      });
      let socket: WebSocket;
      try {
        socket = new WebSocket(wsUrl);
      } catch (err) {
        throw new Error(`WebSocket failed: ${err instanceof Error ? err.message : String(err)}`);
      }
      socket.binaryType = "arraybuffer";
      wsRef.current = socket;

      socket.onopen = () => {
        setIsConnecting(false);
        setConnectionStatus({ connected: true, device: device.name });
        setActiveTab("remote");
        setWebsocketState("connected");
        setHostStatus("online");
        setViewerStatus("connected");
        sessionStartTimeRef.current = Date.now();
        startHeartbeatAndRetries();
        connectControlSocket(device.id, sessionToken);
      };

      socket.onmessage = async (event) => {
        if (!videoRef.current) return;
        const ctx = videoRef.current.getContext("2d");
        if (!ctx) return;

        if (event.data instanceof ArrayBuffer || event.data instanceof Blob || ArrayBuffer.isView(event.data)) {
          try {
            const blobSource =
              event.data instanceof Blob
                ? event.data
                : event.data instanceof ArrayBuffer
                  ? event.data
                  : new Uint8Array(event.data.buffer, event.data.byteOffset, event.data.byteLength);
            const blob = new Blob([blobSource], { type: "image/jpeg" });
            const bitmap = await createImageBitmap(blob);
            remoteResolutionRef.current = { width: bitmap.width, height: bitmap.height };
            setRemoteResolution({ width: bitmap.width, height: bitmap.height });
            videoRef.current.width = bitmap.width;
            videoRef.current.height = bitmap.height;
            ctx.clearRect(0, 0, bitmap.width, bitmap.height);
            ctx.drawImage(bitmap, 0, 0);
            bitmap.close();

            frameCountRef.current += 1;
            const now = Date.now();
            if (now - lastFpsTimeRef.current >= 1000) {
              setDashboardMetrics((prev) => ({
                ...prev,
                fps: frameCountRef.current,
                sessionDuration: Math.floor((now - sessionStartTimeRef.current) / 1000),
              }));
              frameCountRef.current = 0;
              lastFpsTimeRef.current = now;
            }
          } catch (err) {
            console.error("Failed to decode image frame:", err);
          }
        } else {
          try {
            const payload = JSON.parse(event.data);
            if (payload?.type === "host_stats") {
              const values = payload.payload || {};
              setDashboardMetrics((prev) => ({
                ...prev,
                fps: values.fps ?? prev.fps,
                bandwidth: values.bandwidth_bps ? Math.round(values.bandwidth_bps / 1024) : prev.bandwidth,
                hostCpu: values.cpu_percent ?? prev.hostCpu,
                hostMemory: values.memory_percent ?? prev.hostMemory,
              }));
              setHostStatus("online");
            } else if (payload?.type === "control_ack") {
              if (payload.payload?.message_id) {
                acknowledgeControlPacket(payload.payload.message_id);
              }
            } else if (payload?.type === "error") {
              setConnectionError(payload.message || "Remote stream error");
            }
          } catch (err) {
            console.warn("Received non-JSON viewer payload", err);
          }
        }
      };

      socket.onerror = () => {
        setConnectionError("WebSocket connection error");
        setWebsocketState("error");
        setIsConnecting(false);
        console.error("Screen WS error");
        closeRemoteSession();
      };

      socket.onclose = (event) => {
        console.error("Screen WS closed:", event.code, event.reason || "No reason provided");
        if (!connectionStatus.connected) {
          setConnectionError("WebSocket closed before the remote session could start.");
        }
        closeRemoteSession();
      };
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "Connection failed";
      console.error("Connection error:", errorMsg, err);
      setConnectionError(errorMsg);
      setIsConnecting(false);
    }
  };

  const handleDisconnect = () => {
    closeRemoteSession();
    setActiveTab("devices");
  };

  const sendRemoteInput = (msg: Record<string, unknown>) => {
    if (!selectedDevice) return;
    sendControlPacket(msg.type as string, msg.payload as Record<string, any>);
  };

  const handleMouseDown = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!selectedDevice) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / zoom;
    const y = (event.clientY - rect.top) / zoom;
    const mappedX = Math.round((x / remoteResolution.width) * remoteResolution.width);
    const mappedY = Math.round((y / remoteResolution.height) * remoteResolution.height);

    let button = "left";
    if (event.button === 2) button = "right";
    if (event.button === 1) button = "middle";

    sendControlPacket("mouse_click", {
      button,
      x: Math.max(0, Math.min(remoteResolution.width, mappedX)),
      y: Math.max(0, Math.min(remoteResolution.height, mappedY)),
    });
  };

  const moveThrottleRef = useRef<number>(0);
  const handleMouseMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!selectedDevice) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left) / zoom;
    const y = (event.clientY - rect.top) / zoom;

    const now = performance.now();
    if (now - moveThrottleRef.current < 40) return;
    moveThrottleRef.current = now;

    const mappedX = Math.round((x / remoteResolution.width) * remoteResolution.width);
    const mappedY = Math.round((y / remoteResolution.height) * remoteResolution.height);
    sendControlPacket("mouse_move", {
      x: Math.max(0, Math.min(remoteResolution.width, mappedX)),
      y: Math.max(0, Math.min(remoteResolution.height, mappedY)),
    });
  };

  const handleCanvasContextMenu = (event: React.MouseEvent<HTMLCanvasElement>) => {
    event.preventDefault();
  };

  const handleWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    if (event.ctrlKey) {
      event.preventDefault();
      if (event.deltaY < 0) {
        handleZoomIn();
      } else {
        handleZoomOut();
      }
    } else if (!selectedDevice) {
      return;
    } else {
      event.preventDefault();
      sendControlPacket("mouse_scroll", {
        amount: event.deltaY > 0 ? -120 : 120,
      });
    }
  };

  const handleKeyDown = (event: KeyboardEvent) => {
    if (!selectedDevice || !connectionStatus.connected) return;
    const key = event.key;
    if (key.length === 1 || key === "Enter" || key === "Escape" || key === "Backspace" || key === "Tab") {
      event.preventDefault();
      sendControlPacket("key_press", { key });
    }
  };

  useEffect(() => {
    loadSettings();
    fetchDevices();
  }, []);

  useEffect(() => {
    if (fitMode) {
      handleFitScreen();
    }
  }, [remoteResolution, fitMode]);

  useEffect(() => {
    if (!canvasContainerRef.current) return;
    const observer = new ResizeObserver(() => {
      if (fitMode) handleFitScreen();
    });
    observer.observe(canvasContainerRef.current);
    return () => observer.disconnect();
  }, [fitMode, remoteResolution]);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedDevice, connectionStatus.connected]);

  useEffect(() => {
    if (!wsRef.current && selectedDevice && connectionStatus.connected) {
      connectControlSocket(selectedDevice.id);
    }
  }, [selectedDevice, connectionStatus.connected]);

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (controlWsRef.current) controlWsRef.current.close();
      stopHeartbeatAndRetries();
    };
  }, []);

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
  };

  const handleLogout = () => {
    setDevices([]);
    closeRemoteSession();
  };

  const sessionMetrics = {
    connection: connectionStatus.connected ? "Connected" : "Disconnected",
    ping: dashboardMetrics.ping,
    fps: dashboardMetrics.fps,
    bandwidth: dashboardMetrics.bandwidth,
    cpu: dashboardMetrics.hostCpu,
    memory: dashboardMetrics.hostMemory,
    resolution: `${remoteResolution.width}x${remoteResolution.height}`,
    hostStatus,
    viewerStatus,
  };

  const handleReconnect = () => {
    if (selectedDevice) {
      handleDisconnect();
      handleConnect(selectedDevice);
    }
  };

  return (
    <div className="flex h-screen w-screen bg-[#0B132B] text-slate-100 overflow-hidden">
      <div className="w-56 bg-[#1E293B] border-r border-slate-800 flex flex-col shrink-0">
        <div className="p-4 flex items-center gap-3 border-b border-slate-800">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
            <Monitor className="w-4 h-4 text-white" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-white">FluxRemote</h1>
            <p className="text-[10px] text-slate-400">Client</p>
          </div>
        </div>

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

        <div className="p-4 border-t border-slate-800 space-y-3">
          <div className="text-[10px]">
            <div className="flex items-center gap-2 text-slate-400 mb-1">
              <span
                className={`w-2 h-2 rounded-full ${
                  connectionStatus.connected ? "bg-emerald-500 animate-pulse" : "bg-slate-500"
                }`}
              />
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

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-12 border-b border-slate-800 bg-[#0F172A] flex items-center px-6 shrink-0 justify-between">
          <div className="flex items-center gap-4 text-xs font-mono">
            <div className={`w-2 h-2 rounded-full ${connectionStatus.connected ? "bg-emerald-500 animate-pulse" : "bg-slate-600"}`} />
            {connectionStatus.connected ? (
              <>
                <span className="text-slate-400">
                  Connected to: <b className="text-white">{connectionStatus.device}</b>
                </span>
                {dashboardMetrics.ping > 0 && (
                  <span className="text-slate-400">
                    Ping: <b className="text-blue-400">{dashboardMetrics.ping}ms</b>
                  </span>
                )}
              </>
            ) : (
              <span className="text-slate-400">Ready for connection</span>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 flex gap-6">
          {activeTab === "devices" && (
            <div className="space-y-6 max-w-5xl w-full">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Devices</h2>
                <p className="text-sm text-slate-400">Select a device to start a remote session</p>
              </div>

              {loadingDevices ? (
                <div className="flex items-center justify-center py-12">
                  <Loader className="w-6 h-6 text-blue-500 animate-spin" />
                </div>
              ) : (
                <>
                  {connectionError && !connectionStatus.connected && (
                    <div className="bg-rose-500/10 border border-rose-500/30 text-rose-400 px-4 py-3 rounded-lg text-sm mb-4">
                      {connectionError}
                    </div>
                  )}
                  {devices.length === 0 ? (
                    <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-8 text-center">
                      <Monitor className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                      <p className="text-slate-400">No devices available</p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {devices.map((device) => (
                        <div key={device.id} className="bg-[#1E293B] border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition">
                          <div className="flex items-start justify-between mb-3">
                            <div>
                              <h3 className="font-semibold text-white">{device.name}</h3>
                              <p className="text-xs text-slate-400 font-mono">{device.id}</p>
                            </div>
                            <div className={`w-2 h-2 rounded-full ${device.status === "online" ? "bg-emerald-500" : device.status === "in-session" ? "bg-blue-500" : "bg-slate-500"}`} />
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

                  <div className="flex gap-2">
                    <button
                      onClick={fetchDevices}
                      className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition"
                    >
                      Refresh Devices
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {activeTab === "remote" && (
            <div className="space-y-4 flex-1 flex flex-col">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{selectedDevice?.name}</h2>
                  <p className="text-sm text-slate-400">Remote desktop viewer</p>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button
                    onClick={handleFitScreen}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg transition flex items-center gap-1"
                    title="Fit to screen"
                  >
                    <Maximize2 className="w-3 h-3" /> Fit
                  </button>
                  <button
                    onClick={handleZoomIn}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg transition flex items-center gap-1"
                    title="Zoom in"
                  >
                    <ZoomIn className="w-3 h-3" />
                  </button>
                  <button
                    onClick={handleZoomOut}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg transition flex items-center gap-1"
                    title="Zoom out"
                  >
                    <ZoomOut className="w-3 h-3" />
                  </button>
                  <button
                    onClick={resetZoom}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg transition"
                    title="100% scale"
                  >
                    100%
                  </button>
                  <button
                    onClick={handleToggleFullscreen}
                    className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg transition flex items-center gap-1"
                    title="Fullscreen"
                  >
                    <Maximize2 className="w-3 h-3" />
                  </button>
                  <button
                    onClick={handleDisconnect}
                    className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-lg transition"
                  >
                    Disconnect
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs text-slate-400">
                <span>Zoom: {Math.round(zoom * 100)}%</span>
                <span>|</span>
                <span>Resolution: {remoteResolution.width}x{remoteResolution.height}</span>
                <span>|</span>
                <span>Session: {dashboardMetrics.sessionDuration}s</span>
              </div>

              <div className="flex min-h-0 flex-1 gap-4">
                <div className="flex min-h-0 flex-[0_0_75%] flex-col gap-4">
                  <div
                    ref={canvasContainerRef}
                    className="flex flex-1 items-center justify-center overflow-auto rounded-lg border-2 border-slate-800 bg-slate-950 shadow-xl"
                  >
                    <canvas
                      ref={videoRef}
                      onMouseDown={handleMouseDown}
                      onMouseMove={handleMouseMove}
                      onContextMenu={handleCanvasContextMenu}
                      onWheel={handleWheel}
                      width={remoteResolution.width}
                      height={remoteResolution.height}
                      className="block cursor-crosshair bg-black"
                      style={{
                        width: `${remoteResolution.width * zoom}px`,
                        height: `${remoteResolution.height * zoom}px`,
                        maxWidth: "100%",
                        maxHeight: "100%",
                      }}
                    />
                  </div>

                  <div className="overflow-y-auto">
                    <SessionDashboard
                      connection={sessionMetrics.connection}
                      websocketState={websocketState}
                      hostStatus={sessionMetrics.hostStatus}
                      viewerStatus={sessionMetrics.viewerStatus}
                      ping={sessionMetrics.ping}
                      fps={sessionMetrics.fps}
                      bandwidth={sessionMetrics.bandwidth}
                      cpu={sessionMetrics.cpu}
                      memory={sessionMetrics.memory}
                      resolution={sessionMetrics.resolution}
                      onReconnect={handleReconnect}
                    />
                  </div>
                </div>

                {connectionStatus.connected && (
                  <div className="flex min-h-0 flex-[0_0_25%] min-w-[320px] max-w-[420px] flex-col">
                    <RemoteCopilot
                      apiBaseUrl={getApiBase(tunnelEnabled && tunnelUrl.trim() ? tunnelUrl : undefined)}
                      isConnected={connectionStatus.connected}
                      sessionId={selectedDevice?.id ?? "remote-session"}
                      connectionStatus={connectionStatus.connected ? "connected" : "disconnected"}
                      latency={dashboardMetrics.ping}
                      fps={dashboardMetrics.fps}
                      websocketState={websocketState}
                      hostResolution={`${remoteResolution.width}x${remoteResolution.height}`}
                      viewerResolution={`${canvasContainerRef.current?.clientWidth || 0}x${canvasContainerRef.current?.clientHeight || 0}`}
                    />
                  </div>
                )}
              </div>

              {connectionError && (
                <div className="bg-rose-500/10 border border-rose-500/30 text-rose-400 px-4 py-3 rounded-lg text-sm flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  <div className="flex-1">{connectionError}</div>
                  <button
                    onClick={handleReconnect}
                    className="ml-2 px-3 py-1 bg-rose-600 hover:bg-rose-700 rounded text-xs font-bold transition"
                  >
                    Retry
                  </button>
                </div>
              )}
            </div>
          )}

          {activeTab === "settings" && (
            <div className="space-y-6 max-w-2xl w-full">
              <div>
                <h2 className="text-xl font-bold text-white mb-1">Settings</h2>
                <p className="text-sm text-slate-400">Configure FluxRemote client settings</p>
              </div>

              <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6 space-y-4">
                <div>
                  <h3 className="text-sm font-semibold text-white mb-3">Backend Connectivity</h3>
                  <label className="text-xs font-semibold text-slate-300 block mb-2">
                    Tunnel mode
                  </label>
                  <div className="flex items-center gap-3 mb-3">
                    <button
                      onClick={() => setTunnelEnabled(true)}
                      className={`px-3 py-2 rounded-lg text-xs font-semibold ${tunnelEnabled ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                    >
                      Enabled
                    </button>
                    <button
                      onClick={() => setTunnelEnabled(false)}
                      className={`px-3 py-2 rounded-lg text-xs font-semibold ${!tunnelEnabled ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                    >
                      Disabled
                    </button>
                  </div>

                  <label className="text-xs font-semibold text-slate-300 block mb-2">
                    Provider
                  </label>
                  <select
                    value={tunnelProvider}
                    onChange={(event) => setTunnelProvider(event.target.value as any)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
                  >
                    <option>Cloudflare</option>
                    <option>Ngrok</option>
                    <option>Tailscale</option>
                  </select>
                </div>

                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-semibold text-slate-300 block mb-2">
                      Tunnel URL
                    </label>
                    <input
                      value={tunnelUrl}
                      onChange={(event) => setTunnelUrl(event.target.value)}
                      placeholder="https://example.trycloudflare.com"
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-slate-300 block mb-2">
                      Token (optional)
                    </label>
                    <input
                      value={tunnelToken}
                      onChange={(event) => setTunnelToken(event.target.value)}
                      placeholder="Tunnel bearer token"
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                <button
                  onClick={persistSettings}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-lg transition"
                >
                  {settingsSaved ? "✓ Saved" : "Save Tunnel Settings"}
                </button>
              </div>

              <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6 space-y-4">
                <h3 className="text-sm font-semibold text-white">Current connectivity</h3>
                <div className="text-xs text-slate-400 space-y-2">
                  <div>
                    <span className="font-semibold text-slate-200">Server:</span> {activeServerUrl}
                  </div>
                  <div>
                    <span className="font-semibold text-slate-200">Tunnel mode:</span> {tunnelEnabled ? "Enabled" : "Disabled"}
                  </div>
                  <div>
                    <span className="font-semibold text-slate-200">Provider:</span> {tunnelProvider}
                  </div>
                </div>
              </div>

              <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6">
                <h3 className="text-sm font-semibold text-white mb-2">About</h3>
                <p className="text-xs text-slate-400">
                  FluxRemote v1.0.0
                  <br />
                  Secure remote access client
                  <br />
                  Supports tunnel URL routing, input buffering, and AI troubleshooting.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
