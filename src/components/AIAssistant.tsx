import React from "react";
import RemoteCopilot from "./RemoteCopilot";

interface AIAssistantProps {
  apiBaseUrl: string;
  connectionStatus: string;
  latency: number;
  fps: number;
  websocketState: string;
  hostResolution: string;
  viewerResolution: string;
  isConnected?: boolean;
  compact?: boolean;
}

export default function AIAssistant({
  apiBaseUrl,
  connectionStatus,
  latency,
  fps,
  websocketState,
  hostResolution,
  viewerResolution,
  isConnected = true,
  compact = false,
}: AIAssistantProps) {
  return (
    <RemoteCopilot
      apiBaseUrl={apiBaseUrl}
      isConnected={isConnected}
      sessionId={`fluxremote-support-${connectionStatus}`}
      connectionStatus={connectionStatus}
      latency={latency}
      fps={fps}
      websocketState={websocketState}
      hostResolution={hostResolution}
      viewerResolution={viewerResolution}
      mode="support"
      title="FluxRemote Help Assistant"
      subtitle="Get help with setup, connectivity, permissions, input, and troubleshooting."
      welcomeMessage="Hello! I’m FluxRemote Help Assistant. I can help with device connectivity, host issues, viewer problems, keyboard and mouse input, screen sharing, performance, authentication, file transfer, installation, and Windows permissions."
      placeholder="Describe the FluxRemote problem you’re seeing…"
      quickPrompts={[
        { label: "Device Connectivity", prompt: "Help me troubleshoot device connection problems in FluxRemote." },
        { label: "Host Problems", prompt: "What should I check if the FluxRemote host is offline or unreachable?" },
        { label: "Keyboard & Mouse", prompt: "Help me fix keyboard and mouse input issues in FluxRemote." },
        { label: "Screen Sharing", prompt: "Help me fix screen sharing or display issues in FluxRemote." },
        { label: "Network", prompt: "Help me diagnose network or latency issues affecting FluxRemote." },
        { label: "Authentication", prompt: "Help me resolve authentication or permission problems in FluxRemote." },
      ]}
      compact={compact}
      className="h-full rounded-none border-0 shadow-none"
    />
  );
}
