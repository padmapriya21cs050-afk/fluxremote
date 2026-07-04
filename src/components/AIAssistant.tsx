import React, { useState } from "react";

interface AIAssistantProps {
  apiBaseUrl: string;
  connectionStatus: string;
  latency: number;
  fps: number;
  websocketState: string;
  hostResolution: string;
  viewerResolution: string;
}

const COMMON_ISSUES = [
  {
    label: "Connection slow",
    type: "slow_connection",
    prompt: "Why is my connection slow?",
  },
  {
    label: "Host offline",
    type: "host_offline",
    prompt: "Why is the host offline?",
  },
  {
    label: "Black screen",
    type: "black_screen",
    prompt: "Viewer connected but black screen.",
  },
  {
    label: "Mouse delay",
    type: "mouse_delay",
    prompt: "Why is mouse delayed?",
  },
  {
    label: "Keyboard delay",
    type: "keyboard_delay",
    prompt: "Keyboard not working or delayed.",
  },
  {
    label: "WebSocket errors",
    type: "websocket_error",
    prompt: "Explain websocket errors and how to fix them.",
  },
  {
    label: "Render issues",
    type: "render_issues",
    prompt: "Explain Render deployment issues.",
  },
  {
    label: "Vercel issues",
    type: "vercel_issues",
    prompt: "Explain Vercel deployment issues.",
  },
];

export default function AIAssistant({
  apiBaseUrl,
  connectionStatus,
  latency,
  fps,
  websocketState,
  hostResolution,
  viewerResolution,
}: AIAssistantProps) {
  const [selectedIssue, setSelectedIssue] = useState(COMMON_ISSUES[0]);
  const [customQuestion, setCustomQuestion] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const buildPayload = (issueType: string, question: string) => ({
    type: issueType,
    context: question,
    metrics: {
      connection_status: connectionStatus,
      latency_ms: latency,
      fps,
      websocket_state: websocketState,
      host_resolution: hostResolution,
      viewer_resolution: viewerResolution,
    },
  });

  const requestExplanation = async (issueType: string, prompt: string) => {
    setLoading(true);
    setError("");
    setResponse("");

    try {
      const result = await fetch(`${apiBaseUrl}/api/ai/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload(issueType, prompt)),
      });

      if (!result.ok) {
        const body = await result.text();
        throw new Error(`AI service error: ${body}`);
      }

      const json = await result.json();
      setResponse(json.answer || json.explanation || "No explanation returned.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to contact AI service.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 w-full max-w-4xl">
      <div className="bg-[#1E293B] border border-slate-800 rounded-lg p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-white">AI Assistant</h2>
            <p className="text-sm text-slate-400">
              Practical troubleshooting guidance for remote sessions.
            </p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-300">
            <div className="font-semibold text-slate-100 mb-2">Live session state</div>
            <div className="space-y-2">
              <div>Connection: {connectionStatus}</div>
              <div>Latency: {latency} ms</div>
              <div>FPS: {fps}</div>
              <div>WebSocket: {websocketState}</div>
              <div>Host: {hostResolution}</div>
              <div>Viewer: {viewerResolution}</div>
            </div>
          </div>
          <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-300">
            <div className="font-semibold text-slate-100 mb-2">How to use</div>
            <p className="leading-relaxed">
              Select a common issue or type a custom question about your remote session.
              The AI will explain the cause and recommend fixes.
            </p>
          </div>
        </div>

        <div className="mt-5 space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {COMMON_ISSUES.map((item) => (
              <button
                key={item.type}
                onClick={() => {
                  setSelectedIssue(item);
                  requestExplanation(item.type, item.prompt);
                }}
                className={`rounded-lg border px-3 py-2 text-left text-xs text-slate-200 transition ${
                  item.type === selectedIssue.type
                    ? "border-blue-500 bg-blue-600/10"
                    : "border-slate-800 hover:border-slate-600 hover:bg-slate-800"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-slate-300">Custom question</label>
            <textarea
              value={customQuestion}
              onChange={(event) => setCustomQuestion(event.target.value)}
              rows={4}
              placeholder="Ask a technical question about your remote session..."
              className="w-full resize-none bg-slate-950 border border-slate-800 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <button
              onClick={() =>
                requestExplanation(
                  selectedIssue.type,
                  customQuestion.trim() || selectedIssue.prompt
                )
              }
              disabled={loading}
              className="inline-flex items-center justify-center rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Analyzing..." : "Ask Gemini"}
            </button>
            <div className="text-xs text-slate-500">
              Gemini answers are based on your session status and runtime metrics.
            </div>
          </div>
        </div>

        <div className="mt-4 bg-slate-950 border border-slate-800 rounded-lg p-4 min-h-[140px] text-sm text-slate-200">
          {loading ? (
            <div className="text-slate-400">Waiting for Gemini response...</div>
          ) : error ? (
            <div className="text-rose-400">{error}</div>
          ) : response ? (
            <div className="whitespace-pre-wrap">{response}</div>
          ) : (
            <div className="text-slate-500">Response will appear here after asking the assistant.</div>
          )}
        </div>
      </div>
    </div>
  );
}
