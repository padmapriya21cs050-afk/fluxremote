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
      title="Flux AI"
      subtitle="Ask anything"
      welcomeMessage="Hello! I can help with device connectivity, troubleshooting, coding, debugging, writing, math, systems, and general knowledge."
      placeholder="Ask anything..."
      quickPrompts={[
        { label: "Explain Screen", prompt: "Explain what is happening on the screen and what I should focus on next." },
        { label: "Diagnose", prompt: "Diagnose the issue I’m seeing in this session and suggest practical next steps." },
        { label: "Generate Code", prompt: "Generate a clean, production-ready code example for the task I’m working on." },
        { label: "Translate", prompt: "Translate this request or code snippet into the target language and explain it clearly." },
        { label: "Summarize", prompt: "Summarize the current situation, key details, and the best next action." },
      ]}
      compact={compact}
      className=""
    />
  );
}
