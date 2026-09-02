"use client";

/** Every investigation this merchant has run, newest first. */

import {
  Alert,
  Badge,
  Box,
  Card,
  CardBody,
  EmptyState,
  Spinner,
  Text,
} from "@razorpay/blade/components";
import { ArrowRight, Clock, FileText, History as HistoryIcon, Play, Search } from "lucide-react";
import Link from "next/link";
import type { ExecutionLine } from "@shared/api";
import { useEffect, useState } from "react";

import { useAppTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";
import { listExecutions } from "@/lib/api";

const COLOUR: Record<string, "positive" | "negative" | "notice" | "neutral"> = {
  COMPLETED: "positive",
  BLOCKED: "negative",
  FAILED: "negative",
  REJECTED: "negative",
  NEEDS_CLARIFICATION: "notice",
};

export default function HistoryPage() {
  const { isDark } = useAppTheme();
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
      title="Investigation History & Audit Trail"
      subtitle="Every run is replayable through the exact append-only execution event log."
    >
      {/* Search & Filter Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "16px",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "8px 14px",
            borderRadius: "8px",
            backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
            border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
            flex: 1,
            maxWidth: "400px",
          }}
        >
          <Search size={15} color={isDark ? "#94A3B8" : "#64748B"} />
          <input
            type="text"
            placeholder="Search past questions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              background: "transparent",
              border: "none",
              outline: "none",
              color: isDark ? "#F8FAFC" : "#0F172A",
              fontSize: "13px",
              width: "100%",
            }}
          />
        </div>

        <span style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B" }}>
          Showing <strong>{filtered.length}</strong> past investigations
        </span>
      </div>

      {error ? (
        <Alert isFullWidth color="negative" title="Cannot list runs" description={error} />
      ) : null}

      {!items ? (
        <Spinner accessibilityLabel="Loading history" size="medium" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No investigations found"
          description="Ask a financial question in the AI Studio and it will appear here."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {filtered.map((item) => (
            <div
              key={item.execution_id}
              style={{
                padding: "16px 20px",
                borderRadius: "10px",
                backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
                border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "12px",
                transition: "all 0.15s ease",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: "6px", flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                  <Badge color={COLOUR[item.status] ?? "neutral"}>{item.status}</Badge>
                  {item.response_source ? (
                    <Badge color="neutral" size="small">
                      {item.response_source === "LLM" ? "model" : "template"}
                    </Badge>
                  ) : null}
                  <span style={{ fontSize: "11px", color: isDark ? "#94A3B8" : "#64748B", fontFamily: "JetBrains Mono, monospace" }}>
                    {item.created_at.slice(0, 19).replace("T", " ")}
                  </span>
                </div>

                <Link
                  href={`/history/${item.execution_id}`}
                  style={{
                    fontSize: "14px",
                    fontWeight: 600,
                    color: "#0C83FF",
                    textDecoration: "none",
                  }}
                >
                  {item.question}
                </Link>

                {item.period_from ? (
                  <span style={{ fontSize: "11px", color: isDark ? "#64748B" : "#94A3B8", fontFamily: "JetBrains Mono, monospace" }}>
                    Window: [{item.period_from}, {item.period_to})
                  </span>
                ) : null}
              </div>

              <Link
                href={`/history/${item.execution_id}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "6px 14px",
                  borderRadius: "6px",
                  backgroundColor: isDark ? "#141C2B" : "#F1F5F9",
                  color: isDark ? "#F8FAFC" : "#0F172A",
                  fontSize: "12px",
                  fontWeight: 600,
                  textDecoration: "none",
                  border: `1px solid ${isDark ? "#1E293B" : "#CBD5E1"}`,
                }}
              >
                <span>Replay Trace</span>
                <Play size={12} fill="#0C83FF" color="#0C83FF" />
              </Link>
            </div>
          ))}
        </div>
      )}
    </Shell>
  );
}
