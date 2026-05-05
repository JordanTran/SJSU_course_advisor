import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { GraduationCap, RefreshCcw, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";

const API_URL = "/ask";
const SESSION_ID_STORAGE_KEY = "sjsu-advisor-session-id";

interface Message {
  role: "assistant" | "user";
  content: string;
}

interface BubbleProps {
  role: string;
  content: string;
}

interface AnswerResponse {
  answer?: string;
  session_id?: string;
  detail?: string;
}

const initialAssistantMessage: Message = {
  role: "assistant",
  content: "Hi! I'm the SJSU Curriculum Advisor. What would you like to know?",
};

function createSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getOrCreateSessionId() {
  const existing = window.sessionStorage.getItem(SESSION_ID_STORAGE_KEY);
  if (existing) return existing;

  const next = createSessionId();
  window.sessionStorage.setItem(SESSION_ID_STORAGE_KEY, next);
  return next;
}

function saveSessionId(sessionId: string) {
  window.sessionStorage.setItem(SESSION_ID_STORAGE_KEY, sessionId);
}

function Bubble({ role, content }: BubbleProps) {
  const isAssistant = role === "assistant";

  return (
    <div className={`flex ${isAssistant ? "justify-start" : "justify-end"}`}>
      <div
        className={[
          "max-w-[85%] md:max-w-[72%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm",
          isAssistant
            ? "border border-border bg-muted/70 text-foreground"
            : "bg-primary text-primary-foreground",
        ].join(" ")}
      >
        {isAssistant ? (
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-1">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
            }}
          >
            {content}
          </ReactMarkdown>
        ) : (
          content
        )}
      </div>
    </div>
  );
}

export default function SJSUAdvisorChat() {
  const [messages, setMessages] = useState<Message[]>([initialAssistantMessage]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId());
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, loading]);

  function resetConversation() {
    const nextSessionId = createSessionId();
    saveSessionId(nextSessionId);
    setSessionId(nextSessionId);
    setMessages([initialAssistantMessage]);
    setDraft("");
  }

  async function send() {
    const userText = draft.trim();
    if (!userText || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setDraft("");
    setLoading(true);

    try {
      const res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: userText, session_id: sessionId }),
      });

      const data = (await res.json().catch(() => ({}))) as AnswerResponse;
      if (!res.ok) {
        throw new Error(data.detail || "Advisor request failed.");
      }

      if (data.session_id && data.session_id !== sessionId) {
        saveSessionId(data.session_id);
        setSessionId(data.session_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.answer || "I did not receive an answer from the advisor service.",
        },
      ]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not reach advisor service.";
      setMessages((prev) => [...prev, { role: "assistant", content: message }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6 py-8">
      <div className="w-full max-w-2xl">
        <Card className="rounded-2xl">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
                  <GraduationCap className="h-5 w-5" />
                </div>
                <div>
                  <CardTitle className="text-lg font-semibold">SJSU Advisor</CardTitle>
                  <CardDescription>Ask anything about your courses</CardDescription>
                </div>
              </div>

              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={resetConversation}
                disabled={loading}
                className="rounded-xl"
              >
                <RefreshCcw className="mr-2 h-4 w-4" />
                New chat
              </Button>
            </div>
          </CardHeader>

          <CardContent className="space-y-5 pt-2">
            <div className="rounded-2xl border bg-muted/20">
              <ScrollArea className="h-[420px] rounded-2xl md:h-[480px]">
                <div ref={scrollRef} className="space-y-3 px-4 py-4">
                  {messages.map((m, i) => (
                    <Bubble key={i} role={m.role} content={m.content} />
                  ))}
                  {loading && <Bubble role="assistant" content="Thinking..." />}
                </div>
              </ScrollArea>
            </div>

            <Separator />

            <div className="flex items-center gap-2 pt-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask a question..."
                disabled={loading}
                className="h-10 rounded-xl px-3"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <Button
                onClick={send}
                disabled={loading}
                className="h-10 rounded-xl px-4"
              >
                <Send className="mr-2 h-4 w-4" />
                Send
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
