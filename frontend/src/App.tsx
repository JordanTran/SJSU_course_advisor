import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { GraduationCap, Send } from "lucide-react";
import ReactMarkdown from "react-markdown";

const API_URL = "/ask";

interface BubbleProps {
  role: string;
  content: string;
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
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Hi! I'm the SJSU Curriculum Advisor. What would you like to know?",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, loading]);

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
        body: JSON.stringify({ question: userText }),
      });

      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.answer }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Could not reach advisor service." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center px-6 py-8">
      <div className="w-full max-w-2xl">
        <Card className="rounded-2xl">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
                <GraduationCap className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-lg font-semibold">SJSU Advisor</CardTitle>
                <CardDescription>Ask anything about your courses</CardDescription>
              </div>
            </div>
          </CardHeader>

          <CardContent className="space-y-5 pt-2">
            <div className="rounded-2xl border bg-muted/20">
              <ScrollArea className="h-[420px] rounded-2xl md:h-[480px]">
                <div ref={scrollRef} className="space-y-3 px-4 py-4">
                  {messages.map((m, i) => (
                    <Bubble key={i} role={m.role} content={m.content} />
                  ))}
                  {loading && <Bubble role="assistant" content="Thinking…" />}
                </div>
              </ScrollArea>
            </div>

            <Separator />

            <div className="flex items-center gap-2 pt-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Ask a question…"
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
