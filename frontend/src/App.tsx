import React, { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { GraduationCap, Send, Sparkles, AlertTriangle } from "lucide-react";

const DEPTS = ["CMPE"];

function Bubble({ role, children }) {
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
        {children}
      </div>
    </div>
  );
}

function normalizeCourseNumber(v) {
  return (v || "")
    .toUpperCase()
    .replace(/\s+/g, "")
    .replace(/[^0-9A-Z]/g, "");
}

export default function SJSUAdvisorChatMVP() {
  const [dept, setDept] = useState("");
  const [courseNumber, setCourseNumber] = useState("");
  const [courseLocked, setCourseLocked] = useState(false);

  const normalizedCourse = normalizeCourseNumber(courseNumber);

  const courseValid = useMemo(() => {
    const courseOk = /^[0-9]{1,3}[A-Z]{0,2}$/.test(normalizedCourse);
    return !!dept && courseOk;
  }, [dept, normalizedCourse]);

  const courseCode = courseValid ? `${dept} ${normalizedCourse}` : "";
  const chatEnabled = courseLocked && courseValid;

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hi! I’m the SJSU Curriculum Advisor. Please select a department and enter a course number (e.g., CMPE 180B) to begin.",
    },
  ]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length, loading]);

  async function send(text) {
    const userText = (text ?? draft).trim();
    if (!userText || loading || !chatEnabled) return;

    setMessages((prev) => [...prev, { role: "user", content: userText }]);
    setDraft("");
    setLoading(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: userText,
          course_name: courseCode,
        }),
      });

      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Could not reach advisor service." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function lockCourse() {
    if (!courseValid) return;
    setCourseLocked(true);
    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: `Got it — we’ll focus on ${courseCode}. What would you like to know?`,
      },
    ]);
  }

  function changeCourse() {
    setCourseLocked(false);
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <div className="space-y-4">
            <Card className="rounded-2xl">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
                    <GraduationCap className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-lg font-semibold">SJSU Advisor</CardTitle>
                    <CardDescription>Course required to chat</CardDescription>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4 pt-0">
                <div className="space-y-3 rounded-2xl border p-4">
                  <div className="font-semibold">Course</div>

                  <div className="space-y-2">
                    <Label>Department</Label>
                    <Select value={dept} onValueChange={setDept} disabled={courseLocked}>
                      <SelectTrigger className="h-10 rounded-xl px-3">
                        <SelectValue placeholder="Select dept" />
                      </SelectTrigger>
                      <SelectContent>
                        {DEPTS.map((d) => (
                          <SelectItem key={d} value={d}>
                            {d}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Course Number</Label>
                    <Input
                      placeholder="180B"
                      value={courseNumber}
                      onChange={(e) => setCourseNumber(e.target.value)}
                      disabled={courseLocked}
                      className="h-10 rounded-xl px-3"
                    />
                  </div>

                  <div className="text-sm text-muted-foreground">
                    Preview: <span className="font-semibold text-foreground">{courseCode || "—"}</span>
                  </div>

                  {!courseLocked ? (
                    <Button
                      className="h-10 w-full rounded-xl px-4"
                      onClick={lockCourse}
                      disabled={!courseValid}
                    >
                      <Sparkles className="mr-2 h-4 w-4" />
                      Start Chat
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      className="h-10 w-full rounded-xl px-4"
                      onClick={changeCourse}
                    >
                      Change Course
                    </Button>
                  )}

                  {!courseValid && !courseLocked && (
                    <div className="flex gap-2 text-xs text-muted-foreground">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>Dept + valid course number required (e.g., 46A, 151, 180B).</span>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <div>
            <Card className="rounded-2xl">
              <CardHeader className="pb-3">
                <CardTitle className="text-lg font-semibold">Advisor Chat</CardTitle>
                <CardDescription>
                  {chatEnabled ? `Course: ${courseCode}` : "Select a course to begin chatting."}
                </CardDescription>
              </CardHeader>

              <CardContent className="space-y-5 pt-2">
                <div className="rounded-2xl border bg-muted/20">
                  <ScrollArea className="h-[380px] rounded-2xl md:h-[420px]">
                    <div ref={scrollRef} className="space-y-3 px-4 py-4">
                      {messages.map((m, i) => (
                        <Bubble key={i} role={m.role}>
                          {m.content}
                        </Bubble>
                      ))}
                      {loading && <Bubble role="assistant">Thinking…</Bubble>}
                    </div>
                  </ScrollArea>
                </div>

                <Separator />

                <div className="flex items-center gap-2 pt-2">
                  <Input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder={chatEnabled ? "Ask about this course…" : "Select course first…"}
                    disabled={!chatEnabled || loading}
                    className="h-10 rounded-xl px-3"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        send();
                      }
                    }}
                  />
                  <Button
                    onClick={() => send()}
                    disabled={!chatEnabled || loading}
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
      </div>
    </div>
  );
}