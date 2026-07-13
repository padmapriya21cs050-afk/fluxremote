import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Check, Copy, Loader, Sparkles, Trash2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

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
  mode?: "general" | "support";
  title?: string;
  subtitle?: string;
  welcomeMessage?: string;
  placeholder?: string;
  quickPrompts?: Array<{ label: string; prompt: string }>;
  compact?: boolean;
  className?: string;
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

const DEFAULT_GENERAL_PROMPTS = [
  { label: "Explain Java OOP", prompt: "Explain Java object-oriented programming in a concise, practical way." },
  { label: "Write Python code", prompt: "Write a clean Python example for the task I am working on." },
  { label: "Debugging help", prompt: "Help me debug this issue and suggest concrete next steps." },
  { label: "Docker basics", prompt: "Explain Docker concepts clearly and show a simple example." },
  { label: "Math help", prompt: "Solve the math problem step by step and explain the reasoning." },
];

const DEFAULT_SUPPORT_PROMPTS = [
  { label: "Device Connectivity", prompt: "Help me troubleshoot device connection problems in FluxRemote." },
  { label: "Host Problems", prompt: "What should I check if the FluxRemote host is offline or unreachable?" },
  { label: "Keyboard & Mouse", prompt: "Help me fix keyboard and mouse input issues in FluxRemote." },
  { label: "Screen Sharing", prompt: "Help me fix screen sharing or display issues in FluxRemote." },
  { label: "Network", prompt: "Help me diagnose network or latency issues affecting FluxRemote." },
  { label: "Authentication", prompt: "Help me resolve authentication or permission problems in FluxRemote." },
];

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
  mode = "general",
  title = "🤖 AI Copilot",
  subtitle = "Ask anything and I’ll respond like a full AI assistant.",
  welcomeMessage = "Hello! I can help with coding, debugging, writing, math, system questions, and general knowledge.",
  placeholder = "Ask anything…",
  quickPrompts,
  compact = false,
  className = "",
}: RemoteCopilotProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  const effectivePrompts = quickPrompts ?? (mode === "support" ? DEFAULT_SUPPORT_PROMPTS : DEFAULT_GENERAL_PROMPTS);

  useEffect(() => {
    if (!isConnected) {
      setMessages([]);
      setDraft("");
      setError("");
      setCopiedMessageId(null);
      return;
    }

    setMessages([
      {
        id: createId(),
        role: "assistant",
        content: welcomeMessage,
      },
    ]);
    setError("");
    setCopiedMessageId(null);
  }, [isConnected, sessionId, welcomeMessage]);

  useEffect(() => {
    textareaRef.current?.focus({ preventScroll: true });
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
        content: welcomeMessage,
      },
    ]);
    setError("");
    setCopiedMessageId(null);
  };

  const copyMessage = async (content: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageId(messageId);
      window.setTimeout(() => setCopiedMessageId((current) => (current === messageId ? null : current)), 1600);
    } catch {
      setError("Clipboard access was blocked.");
    }
  };

  const sendMessage = async (messageText?: string) => {
    const trimmed = (messageText ?? draft).trim();
    if (!trimmed || isLoading || !isConnected) {
      return;
    }

    const userMessage: ChatMessage = { id: createId(), role: "user", content: trimmed };
    const nextMessages: ChatMessage[] = [...messages, userMessage];
    const assistantMessageId = createId();
    const streamingMessages: ChatMessage[] = [...nextMessages, { id: assistantMessageId, role: "assistant", content: "" }];

    setMessages(streamingMessages);
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

      const contentType = response.headers.get("content-type") || "";
      let reply = "";

      if (contentType.includes("text/event-stream") && response.body) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffered = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffered += decoder.decode(value, { stream: true });
          const chunks = buffered.split("\n\n");
          buffered = chunks.pop() ?? "";
          for (const chunk of chunks) {
            const lines = chunk.split("\n");
            const dataLine = lines.find((line) => line.startsWith("data:"));
            if (dataLine) {
              reply = `${reply}${dataLine.replace(/^data:\s*/, "")}`;
              setMessages((current) =>
                current.map((message) => (message.id === assistantMessageId ? { ...message, content: reply } : message))
              );
            }
          }
        }
        reply += decoder.decode();
        reply = reply.trim();
      } else {
        const json = await response.json();
        reply = json.reply || json.message || "I’m here and ready to help. Try again in a moment.";
      }

      if (!reply.trim()) {
        reply = "I’m here and ready to help. Try again in a moment.";
      }

      setMessages((current) =>
        current.map((message) => (message.id === assistantMessageId ? { ...message, content: reply } : message))
      );
    } catch (err) {
      const fallback = "The AI service is temporarily unavailable. Please try again in a moment.";
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantMessageId ? { ...message, content: fallback } : message
        )
      );
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
    <div className={`overflow-hidden rounded-2xl border border-slate-800 bg-slate-950/95 shadow-2xl shadow-black/30 ${className}`}>
      <div className={`flex items-center justify-between border-b border-slate-800/80 px-4 py-3 ${compact ? "px-3 py-2.5" : "px-4 py-3"}`}>
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Sparkles className="h-4 w-4 text-cyan-400" />
            {title}
          </div>
          <p className="text-xs text-slate-400">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={clearChat}
          className="rounded-lg border border-slate-700 bg-slate-900/70 px-2.5 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
          title="Clear chat"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="flex min-h-[320px] flex-col">
        {effectivePrompts.length > 0 && (
          <div className="flex flex-wrap gap-2 border-b border-slate-800/80 px-3 py-3">
            {effectivePrompts.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                onClick={() => void sendMessage(suggestion.prompt)}
                className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 transition hover:border-cyan-400 hover:bg-cyan-500/20"
              >
                {suggestion.label}
              </button>
            ))}
          </div>
        )}

        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[92%] rounded-2xl px-3 py-2.5 text-sm leading-relaxed shadow-sm ${
                  message.role === "user"
                    ? "bg-cyan-500 text-white"
                    : "border border-slate-800 bg-slate-900/95 text-slate-200"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    {message.role === "assistant" ? (
                      <div className="prose prose-invert max-w-none prose-p:my-1 prose-pre:my-2 prose-pre:overflow-x-auto prose-code:before:hidden prose-code:after:hidden">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            code({ inline, className, children, ...props }: { inline?: boolean; className?: string; children?: React.ReactNode; [key: string]: unknown }) {
                              const content = String(children).replace(/\n$/, "");
                              if (inline) {
                                return (
                                  <code className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[0.9em]" {...props}>
                                    {content}
                                  </code>
                                );
                              }
                              const language = /language-(\w+)/.exec(className || "")?.[1] ?? "text";
                              return (
                                <SyntaxHighlighter
                                  language={language}
                                  style={oneDark as Record<string, unknown>}
                                  customStyle={{ margin: "0.5rem 0", borderRadius: "0.75rem" }}
                                  wrapLongLines
                                >
                                  {content}
                                </SyntaxHighlighter>
                              );
                            },
                          }}
                        >
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div className="whitespace-pre-wrap">{message.content}</div>
                    )}
                  </div>
                  {message.role === "assistant" && message.content.trim() && (
                    <button
                      type="button"
                      onClick={() => void copyMessage(message.content, message.id)}
                      className="mt-0.5 rounded-lg border border-slate-700 bg-slate-950/80 p-1.5 text-slate-300 transition hover:border-slate-500 hover:text-white"
                      title="Copy message"
                    >
                      {copiedMessageId === message.id ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  )}
                </div>
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

        <div className="sticky bottom-0 border-t border-slate-800/80 bg-slate-900/80 px-3 py-3 backdrop-blur">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={compact ? 2 : 3}
            placeholder={placeholder}
            className="w-full resize-none rounded-2xl border border-slate-700 bg-slate-950/90 px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-500"
          />
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[11px] text-slate-500">Press Enter to send · Shift+Enter for a new line</p>
            <button
              type="button"
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
