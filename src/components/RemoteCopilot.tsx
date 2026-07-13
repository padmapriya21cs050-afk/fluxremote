import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Loader, Sparkles, Trash2 } from "lucide-react";

interface RemoteCopilotProps {
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

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

const createId = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `remote-copilot-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
};

export default function RemoteCopilot({
  apiBaseUrl,
  isConnected,
  sessionId,
  connectionStatus,
  latency,
  fps,
  websocketState,
  hostResolution,
  viewerResolution,
}: RemoteCopilotProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const sessionSummary = useMemo(
    () => ({
      connectionStatus,
      latency,
      fps,
      websocketState,
      hostResolution,
      viewerResolution,
    }),
    [connectionStatus, latency, fps, websocketState, hostResolution, viewerResolution]
  );

  useEffect(() => {
    if (!isConnected) {
      setMessages([]);
      setDraft("");
      setError("");
      return;
    }

    setMessages([
      {
        id: createId(),
        role: "assistant",
        content: "AI: Hello! Ask me anything.",
      },
    ]);
  }, [isConnected, sessionId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    }
  }, [messages, isLoading]);

  const clearChat = () => {
    setMessages([
      {
        id: createId(),
        role: "assistant",
        content: "The chat has been cleared. Ask me anything and I’ll help right away.",
      },
    ]);
    setError("");
  };

  const sendMessage = async (messageText?: string) => {
    const trimmed = (messageText ?? draft).trim();
    if (!trimmed || isLoading || !isConnected) {
      return;
    }

    const userMessage: ChatMessage = { id: createId(), role: "user", content: trimmed };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setDraft("");
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch(`${apiBaseUrl}/api/copilot/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          history: nextMessages.map(({ role, content }) => ({ role, content })),
          session_id: sessionId,
          context: sessionSummary,
        }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(body || "AI service was unavailable.");
      }

      const json = await response.json();
      const reply = json.reply || json.message || "I’m here and ready to help. Try again in a moment.";
      setMessages([...nextMessages, { id: createId(), role: "assistant", content: reply }]);
    } catch (err) {
      const fallback = "The AI service is currently unavailable. Please try again in a moment.";
      setMessages([...nextMessages, { id: createId(), role: "assistant", content: fallback }]);
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  if (!isConnected) {
    return null;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950/95 shadow-xl">
      <div className="flex items-center justify-between border-b border-slate-800/80 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Sparkles className="h-4 w-4 text-cyan-400" />
            🤖 Flux AI Copilot
          </div>
          <p className="text-xs text-slate-400">Embedded below the session dashboard while the session is live</p>
        </div>
        <button
          onClick={clearChat}
          className="rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
          title="Clear chat"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex min-h-[320px] flex-col">
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] rounded-2xl px-3 py-2.5 text-sm leading-relaxed shadow-sm ${
                  message.role === "user"
                    ? "bg-cyan-500 text-white"
                    : "border border-slate-800 bg-slate-900/95 text-slate-200"
                }`}
              >
                {message.content}
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start">
              <div className="rounded-2xl border border-slate-800 bg-slate-900/95 px-3 py-2.5 text-sm text-slate-300">
                <div className="flex items-center gap-2">
                  <Loader className="h-4 w-4 animate-spin text-cyan-400" />
                  Thinking...
                </div>
              </div>
            </div>
          )}

          {error && !isLoading && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              {error}
            </div>
          )}
        </div>

        <div className="border-t border-slate-800/80 bg-slate-900/70 px-3 py-3">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={2}
            placeholder="Type your message..."
            className="w-full resize-none rounded-2xl border border-slate-700 bg-slate-950/90 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500"
          />
          <div className="mt-2 flex items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500">Press Enter to send · Shift+Enter for a new line</p>
            <button
              onClick={() => void sendMessage()}
              disabled={!draft.trim() || isLoading}
              className="inline-flex items-center gap-2 rounded-full bg-cyan-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700"
            >
              {isLoading ? <Loader className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
