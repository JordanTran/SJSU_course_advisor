import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  GraduationCap,
  ThumbsUp,
  ThumbsDown,
  Search,
  X,
  ChevronDown,
  ChevronUp,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FeedbackItem {
  feedback_id: number;
  session_id: string;
  question: string;
  answer: string;
  is_positive: boolean;
  created_at: string;
}

interface FeedbackResponse {
  total: number;
  positive: number;
  negative: number;
  filtered_total: number;
  items: FeedbackItem[];
}

type VoteFilter = "all" | "up" | "down";

const PAGE_SIZE = 20;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pct(numerator: number, denominator: number): string {
  if (denominator === 0) return "—";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon,
  accent,
}: {
  label: string;
  value: number | string;
  sub?: string;
  icon: React.ReactNode;
  accent: string;
}) {
  return (
    <Card className="rounded-2xl">
      <CardContent className="flex items-center gap-4 pt-5 pb-5">
        <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${accent}`}>
          {icon}
        </div>
        <div>
          <p className="text-2xl font-semibold leading-none">{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{label}</p>
          {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function ExpandableText({
  text,
  markdown = false,
  maxChars = 160,
}: {
  text: string;
  markdown?: boolean;
  maxChars?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = text.length > maxChars;

  return (
    <div className="text-sm leading-relaxed">
      {expanded && markdown ? (
        <ReactMarkdown
          components={{
            p:      ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
            ul:     ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-1">{children}</ul>,
            ol:     ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-1">{children}</ol>,
            li:     ({ children }) => <li>{children}</li>,
            strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
            h3:     ({ children }) => <h3 className="mt-2 mb-1 font-semibold">{children}</h3>,
          }}
        >
          {text}
        </ReactMarkdown>
      ) : (
        <span className="whitespace-pre-wrap">
          {needsTruncation && !expanded ? `${text.slice(0, maxChars)}…` : text}
        </span>
      )}
      {needsTruncation && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-2 inline-flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? (
            <>Less <ChevronUp className="h-3 w-3" /></>
          ) : (
            <>More <ChevronDown className="h-3 w-3" /></>
          )}
        </button>
      )}
    </div>
  );
}

function VoteChip({ isPositive }: { isPositive: boolean }) {
  return isPositive ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
      <ThumbsUp className="h-3 w-3" /> Up
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
      <ThumbsDown className="h-3 w-3" /> Down
    </span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function AdminPage() {
  const [data, setData]           = useState<FeedbackResponse | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [voteFilter, setVoteFilter] = useState<VoteFilter>("all");
  const [searchDraft, setSearchDraft] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [sessionDraft, setSessionDraft] = useState("");
  const [activeSession, setActiveSession] = useState("");
  const [page, setPage]           = useState(0);
  const debounceRef               = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce text search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setPage(0);
      setActiveSearch(searchDraft);
    }, 400);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchDraft]);

  // Debounce session id search
  const sessionDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (sessionDebounceRef.current) clearTimeout(sessionDebounceRef.current);
    sessionDebounceRef.current = setTimeout(() => {
      setPage(0);
      setActiveSession(sessionDraft);
    }, 400);
    return () => {
      if (sessionDebounceRef.current) clearTimeout(sessionDebounceRef.current);
    };
  }, [sessionDraft]);

  // Reset page when filters change.
  useEffect(() => {
    setPage(0);
  }, [voteFilter]);

  // Fetch whenever filters or page changes.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({
      limit:  String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (voteFilter !== "all") params.set("vote", voteFilter);
    if (activeSearch.trim())  params.set("search", activeSearch.trim());
    if (activeSession.trim()) params.set("session_id", activeSession.trim());

    fetch(`/feedback?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        return res.json() as Promise<FeedbackResponse>;
      })
      .then((json) => { if (!cancelled) setData(json); })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [voteFilter, activeSearch, activeSession, page]);

  const totalPages = data ? Math.ceil(data.filtered_total / PAGE_SIZE) : 0;

  return (
    <div className="min-h-screen bg-background text-foreground px-6 py-8">
      <div className="mx-auto max-w-5xl space-y-6">

        {/* ── Header ── */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-lg font-semibold">Admin Dashboard</h1>
            <p className="text-sm text-muted-foreground">Review user feedback</p>
          </div>
          <a
            href="/"
            className="ml-auto text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            ← Back to advisor
          </a>
        </div>

        {/* ── Stat cards ── */}
        {data && (
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              label="Total responses rated"
              value={data.total}
              icon={<span className="text-sm font-bold">#</span>}
              accent="bg-primary/10"
            />
            <StatCard
              label="Thumbs up"
              value={data.positive}
              sub={pct(data.positive, data.total)}
              icon={<ThumbsUp className="h-4 w-4 text-green-600" />}
              accent="bg-green-100"
            />
            <StatCard
              label="Thumbs down"
              value={data.negative}
              sub={pct(data.negative, data.total)}
              icon={<ThumbsDown className="h-4 w-4 text-red-600" />}
              accent="bg-red-100"
            />
          </div>
        )}

        {/* ── Filters ── */}
        <Card className="rounded-2xl">
          <CardContent className="flex flex-col gap-3 pt-5 pb-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchDraft}
                  onChange={(e) => setSearchDraft(e.target.value)}
                  placeholder="Search questions and answers…"
                  className="h-9 rounded-xl pl-9 pr-8"
                />
                {searchDraft && (
                  <button
                    type="button"
                    onClick={() => setSearchDraft("")}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <div className="relative sm:w-64">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={sessionDraft}
                  onChange={(e) => setSessionDraft(e.target.value)}
                  placeholder="Filter by session ID…"
                  className="h-9 rounded-xl pl-9 pr-8 font-mono text-xs"
                />
                {sessionDraft && (
                  <button
                    type="button"
                    onClick={() => setSessionDraft("")}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Clear session filter"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>

            <div className="flex gap-2">
              {(["all", "up", "down"] as VoteFilter[]).map((v) => (
                <Button
                  key={v}
                  type="button"
                  variant={voteFilter === v ? "default" : "outline"}
                  size="sm"
                  className="rounded-xl gap-1.5"
                  onClick={() => setVoteFilter(v)}
                >
                  {v === "up"   && <ThumbsUp   className="h-3.5 w-3.5" />}
                  {v === "down" && <ThumbsDown  className="h-3.5 w-3.5" />}
                  {v === "all"  ? "All" : v === "up" ? "Thumbs up" : "Thumbs down"}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* ── Table ── */}
        <Card className="rounded-2xl">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {loading
                ? "Loading…"
                : data
                ? `${data.filtered_total} result${data.filtered_total !== 1 ? "s" : ""}`
                : ""}
            </CardTitle>
          </CardHeader>

          <CardContent className="p-0">
            {error && (
              <p className="px-6 py-8 text-sm text-red-600">Error: {error}</p>
            )}

            {!error && !loading && data?.items.length === 0 && (
              <p className="px-6 py-8 text-sm text-muted-foreground">No results match your filters.</p>
            )}

            {!error && data && data.items.length > 0 && (
              <>
                {/* Column headers */}
                <div className="grid grid-cols-[1fr_1fr_160px_80px_140px] gap-4 border-b px-6 py-2 text-xs font-medium text-muted-foreground">
                  <span>Question</span>
                  <span>Answer</span>
                  <span>Session ID</span>
                  <span>Vote</span>
                  <span>Date</span>
                </div>

                {data.items.map((item, idx) => (
                  <div key={item.feedback_id}>
                    <div className="grid grid-cols-[1fr_1fr_160px_80px_140px] gap-4 px-6 py-4 hover:bg-muted/30 transition-colors">
                      <ExpandableText text={item.question} maxChars={120} />
                      <ExpandableText text={item.answer} maxChars={160} markdown />
                      <span
                        className="pt-0.5 font-mono text-xs text-muted-foreground truncate cursor-pointer hover:text-foreground transition-colors"
                        title={item.session_id}
                        onClick={() => setSessionDraft(item.session_id)}
                      >
                        {item.session_id.slice(0, 8)}…
                      </span>
                      <div className="pt-0.5">
                        <VoteChip isPositive={item.is_positive} />
                      </div>
                      <span className="pt-0.5 text-xs text-muted-foreground">
                        {formatDate(item.created_at)}
                      </span>
                    </div>
                    {idx < data.items.length - 1 && <Separator />}
                  </div>
                ))}

                {/* Pagination */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between border-t px-6 py-3">
                    <span className="text-xs text-muted-foreground">
                      Page {page + 1} of {totalPages}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="rounded-xl"
                        disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}
                      >
                        <ChevronLeft className="h-4 w-4" />
                        Prev
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="rounded-xl"
                        disabled={page >= totalPages - 1}
                        onClick={() => setPage((p) => p + 1)}
                      >
                        Next
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
