import React from "react";
import RemoteCopilot from "./RemoteCopilot";

interface RemoteSessionCopilotProps {
  apiBaseUrl: string;
  isConnected: boolean;
  sessionId: string;
  connectionStatus: string;
  latency: number;
  fps: number;
  websocketState: string;
  hostResolution: string;
  viewerResolution: string;
}

export default function RemoteSessionCopilot(props: RemoteSessionCopilotProps) {
  return (
    <RemoteCopilot
      {...props}
      mode="general"
      title="🤖 AI Copilot"
      subtitle="Ask anything from programming and debugging to writing, math, and general knowledge."
      welcomeMessage="Hello! I can help with programming, debugging, writing, math, system questions, and general knowledge."
      placeholder="Ask anything…"
    />
  );
}
