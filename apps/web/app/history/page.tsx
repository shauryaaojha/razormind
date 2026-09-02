"use client";

/** Every investigation this merchant has run, newest first. */

import { Alert, Badge, Spinner } from "@razorpay/blade/components";
import type { ExecutionLine } from "@shared/api";
import { History as HistoryIcon, Play, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";
import { EmptyState, Panel, Pill, Row, Stack } from "@/components/ui";
import { listExecutions } from "@/lib/api";
import { numeric, radius, space, transition } from "@/lib/theme";

const COLOUR: Record<string, "positive" | "negative" | "notice" | "neutral"> = {
  COMPLETED: "positive",
  BLOCKED: "negative",
  FAILED: "negative",
  REJECTED: "negative",
  NEEDS_CLARIFICATION: "notice",
};

export default function HistoryPage() {
  const { t } = useTheme();
  const [items, setItems] = useState<ExecutionLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let live = true;
    listExecutions(50)
      .then((page) => live && setItems(page.items))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, []);

  const filtered = (items ?? []).filter((item) =>
    search ? item.question.toLowerCase().includes(search.toLowerCase()) : true,
  );

  return (
    <Shell
      title="History"
      subtitle="Every run replays from the same append-only event log the live page reads, through the same component."
      action={
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: space(2),
            padding: `${space(2)} ${space(3)}`,
            borderRadius: radius.md,
            backgroundColor: t.surface,
            border: `1px solid ${t.border}`,
            minWidth: "260px",
          }}
        >
          <Search size={15} color={t.textFaint} />
          <input
            type="search"
            placeholder="Search past questions…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{
              background: "transparent",
              border: "none",
              outline: "none",
              color: t.text,
              font: "inherit",
              fontSize: "13px",
              width: "100%",
            }}
          />
        </div>
      }
    >
      {error ? (
        <Alert isFullWidth color="negative" title="Cannot list runs" description={error} />
      ) : null}

      {!items ? (
        <Spinner accessibilityLabel="Loading history" size="medium" />
      ) : filtered.length === 0 ? (
        <Panel>
          <EmptyState
            icon={<HistoryIcon size={26} />}
            title={search ? "No run matches that" : "No investigations yet"}
            body={
              search
                ? "Try a different word, or clear the search to see everything."
                : "Ask a question on the Ask page and every run will be listed here, replayable."
            }
          />
        </Panel>
      ) : (
        <Stack gap={2.5}>
          {filtered.map((item) => (
            <Link
              key={item.execution_id}
              href={`/history/${item.execution_id}`}
              style={{
                textDecoration: "none",
                color: "inherit",
                display: "block",
                padding: `${space(4)} ${space(5)}`,
                borderRadius: radius.md,
                backgroundColor: t.surface,
                border: `1px solid ${t.border}`,
                transition: `border-color ${transition.fast}, background-color ${transition.fast}`,
              }}
              onMouseEnter={(event) => {
                event.currentTarget.style.borderColor = t.accentBorder;
                event.currentTarget.style.backgroundColor = t.surfaceHover;
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.borderColor = t.border;
                event.currentTarget.style.backgroundColor = t.surface;
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: space(4),
                  flexWrap: "wrap",
                }}
              >
                <Stack gap={2} style={{ flex: 1, minWidth: "min(100%, 320px)" }}>
                  <Row gap={2}>
                    <Badge color={COLOUR[item.status] ?? "neutral"}>{item.status}</Badge>
                    {item.response_source ? (
                      <Pill tone={item.response_source === "LLM" ? "info" : "neutral"}>
                        {item.response_source === "LLM" ? "model" : "template"}
                      </Pill>
                    ) : null}
                    <span style={{ ...numeric, fontSize: "11.5px", color: t.textFaint }}>
                      {item.created_at.slice(0, 19).replace("T", " ")}
                    </span>
                  </Row>

                  <span style={{ fontSize: "14.5px", fontWeight: 600, color: t.text, lineHeight: 1.45 }}>
                    {item.question}
                  </span>

                  {item.period_from ? (
                    <span style={{ ...numeric, fontSize: "11.5px", color: t.textFaint }}>
                      [{item.period_from}, {item.period_to})
                    </span>
                  ) : null}
                </Stack>

                <span
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: space(1.5),
                    fontSize: "12px",
                    fontWeight: 600,
                    color: t.accent,
                    whiteSpace: "nowrap",
                  }}
                >
                  Replay <Play size={12} fill="currentColor" />
                </span>
              </div>
            </Link>
          ))}
        </Stack>
      )}
    </Shell>
  );
}
