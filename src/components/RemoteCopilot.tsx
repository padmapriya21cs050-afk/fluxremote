import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Bot, Check, Copy, Loader, Plus, Sparkles, Trash2, X } from "lucide-react";
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

const DEFAULT_PROMPTS = [
  { label: "Explain Screen", prompt: "Explain what is happening on the screen and what I should focus on next." },
  { label: "Diagnose", prompt: "Diagnose the issue I’m seeing in this session and suggest practical next steps." },
  { label: "Generate Code", prompt: "Generate a clean, production-ready code example for the task I’m working on." },
  { label: "Translate", prompt: "Translate this request or code snippet into the target language and explain it clearly." },
  { label: "Summarize", prompt: "Summarize the current situation, key details, and the best next action." },
];

const CodeBlock = ({ content, language }: { content: string; language: string }) => {
  const [copied, setCopied] = useState(false);

  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Ignore clipboard errors quietly.
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-slate-700 bg-slate-950/80">
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/70 px-3 py-2 text-[11px] uppercase tracking-[0.2em] text-slate-400">
        <span>{language}</span>
        <button
          type="button"
          onClick={() => void copyCode()}
          className="rounded-md border border-slate-700 bg-slate-950/80 px-2 py-1 text-[11px] font-semibold text-slate-300 transition hover:border-slate-500 hover:text-white"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={oneDark as Record<string, unknown>}
        customStyle={{ margin: 0, borderRadius: 0, background: "transparent" }}
        wrapLongLines
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
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
  mode = "general",
  title = "Flux AI",
  subtitle = "Ask anything",
  welcomeMessage = "Hello! I can help with coding, debugging, writing, math, system questions, and general knowledge.",
  placeholder = "Ask anything...",
  quickPrompts,
  compact = false,
  className = "",
}: RemoteCopilotProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [screenshot, setScreenshot] = useState<{ name: string; preview: string; type: string; size: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const sessionSummary = useMemo(
    () => ({
      connectionStatus,
      latency,
      fps,
      websocketState,
      hostResolution,
      viewerResolution,
      device: sessionId,
    }),
    [connectionStatus, latency, fps, websocketState, hostResolution, viewerResolution, sessionId]
  );

  const effectivePrompts = quickPrompts ?? DEFAULT_PROMPTS;

  useEffect(() => {
    setMessages([
      {
        id: createId(),
        role: "assistant",
        content: welcomeMessage,
      },
    ]);
    setDraft("");
    setError("");
    setCopiedMessageId(null);
  }, [sessionId, welcomeMessage]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const focusTimer = window.setTimeout(() => {
      textareaRef.current?.focus({ preventScroll: true });
    }, 80);
    return () => window.clearTimeout(focusTimer);
  }, [isOpen]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      const target = scrollRef.current;
      target.scrollTo({ top: target.scrollHeight, behavior: "smooth" });
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
    if (!trimmed && !screenshot) {
      return;
    }

    const effectiveMessage = `${trimmed}${screenshot ? `\n\n[Attached screenshot: ${screenshot.name}]` : ""}`.trim();
    const nextMessagesWithAttachment: ChatMessage[] = [
      ...messages,
      { id: createId(), role: "user", content: effectiveMessage },
    ];
    const assistantMessageId = createId();
    const streamingMessages: ChatMessage[] = [...nextMessagesWithAttachment, { id: assistantMessageId, role: "assistant", content: "" }];

    setMessages(streamingMessages);
    setDraft("");
    setError("");
    setIsLoading(true);

    try {
      const requestContext = screenshot
        ? {
            ...sessionSummary,
            screenshot: {
              filename: screenshot.name,
              type: screenshot.type,
              size: screenshot.size,
            },
          }
        : sessionSummary;

      const response = await fetch(`${apiBaseUrl}/api/copilot/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: effectiveMessage,
          history: nextMessagesWithAttachment.map(({ role, content }) => ({ role, content })),
          session_id: sessionId,
          context: requestContext,
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
      if (screenshot) {
        removeScreenshot();
      }
    } catch (err) {
      const fallback = "The AI service is temporarily unavailable. Please try again in a moment.";
      setMessages((current) =>
        current.map((message) => (message.id === assistantMessageId ? { ...message, content: fallback } : message))
      );
      setError(err instanceof Error ? err.message : fallback);
    } finally {
      setIsLoading(false);
    }
  };

  const triggerScreenshotPicker = () => {
    fileInputRef.current?.click();
  };

  const handleScreenshotSelect = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const preview = String(reader.result || "");
      setScreenshot({
        name: file.name,
        preview,
        type: file.type,
        size: file.size,
      });
    };
    reader.readAsDataURL(file);
  };

  const removeScreenshot = () => {
    setScreenshot(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const clipboardItems = Array.from(event.clipboardData?.items ?? []);
    const imageItem = clipboardItems.find((item) => item.type.startsWith("image/"));

    if (!imageItem) {
      return;
    }

    event.preventDefault();
    const file = imageItem.getAsFile();
    if (file) {
      handleScreenshotSelect(file);
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        aria-label="Open AI Copilot"
        className={`assistant-float-button fixed bottom-6 right-6 z-[70] flex h-16 w-16 items-center justify-center rounded-full border border-white/20 bg-gradient-to-br from-sky-500 via-cyan-500 to-violet-600 text-white shadow-[0_20px_45px_rgba(15,23,42,0.45)] transition-all duration-300 hover:scale-110 ${className}`}
      >
        <Bot className="h-7 w-7" />
      </button>

      {isOpen && (
        <div
          className="fixed inset-0 z-[55] bg-slate-950/60 backdrop-blur-sm"
          onMouseDown={() => setIsOpen(false)}
        />
      )}

      <div
        className={`fixed inset-y-0 right-0 z-[60] flex w-full justify-end transition-transform duration-300 ease-out sm:max-w-[420px] ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div
          className="assistant-panel-enter flex h-full w-full max-w-[420px] flex-col overflow-hidden rounded-l-[24px] border border-slate-800/80 bg-slate-950/95 shadow-2xl shadow-black/50"
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="flex items-start justify-between border-b border-slate-800/80 px-4 py-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-semibold text-white">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-sky-500/20 to-violet-500/20 text-sky-300">
                  <Bot className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-[15px]">{title}</div>
                  <div className="text-xs font-normal text-slate-400">{subtitle}</div>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">
                <span className="h-2 w-2 rounded-full bg-emerald-400" />
                Online
              </span>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-full border border-slate-700 bg-slate-900/70 p-2 text-slate-300 transition hover:border-slate-500 hover:text-white"
                aria-label="Close AI assistant"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between border-b border-slate-800/80 bg-slate-900/70 px-4 py-3">
            <div className="flex flex-wrap gap-2">
              {effectivePrompts.map((suggestion) => (
                <button
                  key={suggestion.label}
                  type="button"
                  onClick={() => void sendMessage(suggestion.prompt)}
                  className="rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition hover:border-sky-500/40 hover:bg-sky-500/10 hover:text-sky-200"
                >
                  {suggestion.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={triggerScreenshotPicker}
                className="inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-950/80 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition hover:border-sky-500/40 hover:bg-sky-500/10 hover:text-sky-200"
              >
                <Plus className="h-3.5 w-3.5" />
                Add screenshot
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) {
                    handleScreenshotSelect(file);
                  }
                }}
              />
            </div>
          </div>

          {screenshot && (
            <div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/95 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-white">Screenshot attached</p>
                  <p className="text-xs text-slate-500">{screenshot.name} • {(screenshot.size / 1024).toFixed(1)} KB</p>
                </div>
                <button
                  type="button"
                  onClick={removeScreenshot}
                  className="rounded-full border border-slate-700 bg-slate-950/80 px-2 py-1 text-xs font-semibold text-slate-300 transition hover:border-slate-500 hover:text-white"
                >
                  Remove
                </button>
              </div>
              <div className="mt-3 overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
                <img
                  src={screenshot.preview}
                  alt="Screenshot preview"
                  className="h-48 w-full object-contain"
                />
              </div>
            </div>
          )}

          <div ref={scrollRef} className="flex-1 overflow-y-auto overscroll-contain px-4 py-4">
            <div className="space-y-3">
              {messages.map((message) => (
                <div key={message.id} className={`assistant-message-enter flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[92%] rounded-2xl px-3.5 py-3 text-sm leading-relaxed shadow-sm ${
                      message.role === "user"
                        ? "bg-gradient-to-br from-sky-500 to-violet-600 text-white"
                        : "border border-slate-800 bg-slate-900/95 text-slate-200"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1 break-words">
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
                                  return <CodeBlock content={content} language={language} />;
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
                <div className="assistant-message-enter flex justify-start">
                  <div className="rounded-2xl border border-slate-800 bg-slate-900/95 px-3.5 py-3 text-sm text-slate-300">
                    <div className="flex items-center gap-2">
                      <Loader className="h-4 w-4 animate-spin text-sky-400" />
                      <span className="flex items-center gap-1">
                        <span className="assistant-typing-dot h-2 w-2 rounded-full bg-slate-400" />
                        <span className="assistant-typing-dot h-2 w-2 rounded-full bg-slate-400" />
                        <span className="assistant-typing-dot h-2 w-2 rounded-full bg-slate-400" />
                      </span>
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
          </div>

          <div className="border-t border-slate-800/80 bg-slate-900/80 px-3 py-3 backdrop-blur">
            <div className="flex items-end gap-2 rounded-2xl border border-slate-700 bg-slate-950/90 p-2">
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onPaste={handlePaste}
                onKeyDown={handleKeyDown}
                rows={compact ? 2 : 3}
                placeholder={placeholder}
                className="max-h-36 min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-white outline-none placeholder:text-slate-500"
              />
              <button
                type="button"
                onClick={() => void sendMessage()}
                disabled={!draft.trim() || isLoading}
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-violet-600 text-white transition hover:scale-105 disabled:cursor-not-allowed disabled:from-slate-700 disabled:to-slate-700"
              >
                {isLoading ? <Loader className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
              </button>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2 px-1">
              <p className="text-[11px] text-slate-500">Enter to send · Shift+Enter for a new line</p>
              <button
                type="button"
                onClick={clearChat}
                className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-[11px] text-slate-300 transition hover:border-slate-500 hover:text-white"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
