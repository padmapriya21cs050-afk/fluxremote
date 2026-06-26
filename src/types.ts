// Device types
export interface Device {
  id: string;
  name: string;
  status: "online" | "offline" | "in-session";
  lastSeen?: string;
  ipAddress?: string;
}

// Connection types
export interface ConnectionSession {
  sessionId: string;
  deviceId: string;
  deviceName: string;
  connectedAt: string;
  connectionStatus: "connecting" | "connected" | "disconnecting" | "disconnected";
}

// Remote viewer frame data
export interface RemoteFrame {
  type: "frame" | "cursor" | "clipboard";
  data: any;
}

