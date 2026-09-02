"use client";

/**
 * Where a number comes from, all the way down.
 *
 * One recursive renderer with no knowledge of revenue, refunds or
 * reconciliation. Every level either declares a formula -- in which case its
 * operands are more levels -- or declares a fold, in which case it cites records
 * and the walk stops.
 *
 * The verification summary is read from `detail.verification_checks`. It used to
 * be a hardcoded "5/5 layers passed" banner sitting directly above the array
 * that actually says which checks ran, which is a decoration asserting the one
 * thing this whole product exists to prove rather than showing it.
 */

import { Alert, Badge, Drawer, DrawerBody, DrawerHeader, Spinner } from "@razorpay/blade/components";
import type { EvidenceDetail, ProvenanceLevel } from "@shared/api";
import { ChevronRight, Database, ShieldCheck } from "lucide-react";
import React, { useEffect, useState } from "react";

import { useTheme } from "@/app/providers";
import { Calculation } from "@/components/Calculation";
import { Mono, Pill, Row, SectionLabel, Stack } from "@/components/ui";
import { readEvidence } from "@/lib/api";
import { numeric, radius, space } from "@/lib/theme";

export function ProvenanceDrawer({
  executionId,
  evidenceId,
  onDismiss,
}: {
  executionId: string;
  evidenceId: string | null;
  onDismiss: () => void;
}) {
  const { t } = useTheme();
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showChecks, setShowChecks] = useState(false);

  useEffect(() => {
    if (!evidenceId) return;
    let live = true;
    setDetail(null);
    setError(null);
    setSearch("");
    setShowChecks(false);
    readEvidence(executionId, evidenceId)
      .then((loaded) => live && setDetail(loaded))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, [executionId, evidenceId]);

  const records = detail?.source_record_ids ?? [];
  const filtered = records.filter((id) =>
    search ? id.toLowerCase().includes(search.toLowerCase()) : true,
  );

  return (
    <Drawer isOpen={evidenceId !== null} onDismiss={onDismiss}>
      <DrawerHeader title="Where this number comes from" subtitle={evidenceId ?? ""} />
      <DrawerBody>
        {error ? (
          <Alert isFullWidth color="negative" title="Cannot show this" description={error} />
        ) : !detail ? (
          <Spinner accessibilityLabel="Loading the evidence chain" size="medium" />
        ) : (
          <Stack gap={5}>
            {detail.verification_checks.length > 0 ? (
              <div
                style={{
                  borderRadius: radius.md,
                  backgroundColor: t.positiveSoft,
                  border: `1px solid ${t.border}`,
                  overflow: "hidden",
                }}
              >
                <button
                  type="button"
                  onClick={() => setShowChecks((open) => !open)}
                  aria-expanded={showChecks}
                  style={{
                    appearance: "none",
                    font: "inherit",
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    gap: space(2),
                    padding: `${space(2.5)} ${space(3)}`,
                    background: "none",
                    border: "none",
                    color: t.positive,
                    fontSize: "12.5px",
                    fontWeight: 600,
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <ShieldCheck size={15} />
                  <span style={{ flex: 1 }}>
                    {detail.verification_checks.length.toLocaleString("en-IN")} verification checks
                    passed
                  </span>
                  <ChevronRight
                    size={14}
                    style={{
                      transform: showChecks ? "rotate(90deg)" : "none",
                      transition: "transform 120ms",
                    }}
                  />
                </button>
                {showChecks ? (
                  <ul
                    style={{
                      margin: 0,
                      padding: `0 ${space(3)} ${space(3)} ${space(8)}`,
                      listStyle: "none",
                      display: "flex",
                      flexDirection: "column",
                      gap: space(1),
                    }}
                  >
                    {detail.verification_checks.map((check) => (
                      <li key={check} style={{ fontSize: "11.5px", color: t.textMuted }}>
                        {check}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}

            <Level node={detail.provenance} depth={0} />

            {detail.rules_applied.length > 0 ? (
              <Stack gap={2}>
                <SectionLabel>Rules applied</SectionLabel>
                <Stack gap={1}>
                  {detail.rules_applied.map((rule) => (
                    <span key={rule} style={{ fontSize: "12px", color: t.textMuted, lineHeight: 1.5 }}>
                      {rule}
                    </span>
                  ))}
                </Stack>
              </Stack>
            ) : null}

            <Stack gap={2.5}>
              <Row gap={3} style={{ justifyContent: "space-between" }}>
                <SectionLabel>
                  {records.length.toLocaleString("en-IN")} source records
                </SectionLabel>
                {records.length > 20 ? (
                  <input
                    type="search"
                    placeholder="Filter…"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    style={{
                      padding: `${space(1)} ${space(2)}`,
                      borderRadius: radius.sm,
                      border: `1px solid ${t.border}`,
                      backgroundColor: t.sunken,
                      color: t.text,
                      font: "inherit",
                      fontSize: "11.5px",
                      outline: "none",
                      width: "140px",
                    }}
                  />
                ) : null}
              </Row>

              <span style={{ fontSize: "11.5px", color: t.textFaint, lineHeight: 1.5 }}>
                Every record the whole chain reaches, however deep. This is the answer to
                &ldquo;show me the transactions behind this percentage&rdquo;.
              </span>

              <div
                data-testid="source-records"
                style={{ display: "flex", flexWrap: "wrap", gap: space(1.5) }}
              >
                {filtered.slice(0, 60).map((record) => (
                  <Badge key={record} color="neutral" size="small">
                    {record}
                  </Badge>
                ))}
                {filtered.length > 60 ? (
                  <span style={{ fontSize: "11.5px", color: t.textFaint, alignSelf: "center" }}>
                    + {(filtered.length - 60).toLocaleString("en-IN")} more
                  </span>
                ) : null}
                {filtered.length === 0 ? (
                  <span style={{ fontSize: "11.5px", color: t.textFaint }}>
                    <Database size={12} style={{ verticalAlign: "-2px" }} /> nothing matches
                    &ldquo;{search}&rdquo;
                  </span>
                ) : null}
              </div>
            </Stack>
          </Stack>
        )}
      </DrawerBody>
    </Drawer>
  );
}

/** One node, then its operands, then theirs. The whole recursive renderer. */
export function Level({ node, depth }: { node: ProvenanceLevel; depth: number }) {
  const { t } = useTheme();
  const derived = node.support === "FORMULA";
  return (
    <div
      data-testid="provenance-node"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: space(1.5),
        paddingLeft: depth === 0 ? 0 : space(4),
        borderLeft: depth === 0 ? "none" : `1px solid ${t.border}`,
        marginLeft: depth === 0 ? 0 : space(1),
      }}
    >
      <Row gap={2.5}>
        <span style={{ ...numeric, fontSize: "15px", fontWeight: 650, color: t.text }}>
          {node.display}
        </span>
        <span style={{ fontSize: "12px", color: t.textMuted }}>
          {node.metric_id}
          {node.dimension_value ? ` · ${node.dimension_value}` : ""}
        </span>
        <Pill tone={derived ? "info" : "neutral"}>{derived ? "derived" : "fold"}</Pill>
      </Row>

      {derived ? (
        <Calculation node={node} />
      ) : (
        <span style={{ fontSize: "11.5px", color: t.textMuted, lineHeight: 1.5 }}>
          {node.detail}
        </span>
      )}
      <span style={{ fontSize: "11px", color: t.textFaint }}>
        {node.tool_name} · [{node.period_from}, {node.period_to})
      </span>

      {node.operands.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: space(2), marginTop: space(1) }}>
          {node.operands.map((operand) => (
            <div
              key={`${operand.name}:${operand.reference}`}
              style={{ display: "flex", flexDirection: "column", gap: space(1.5) }}
            >
              <span style={{ ...numeric, fontSize: "12px", color: t.textMuted }}>
                {operand.name} = {operand.display}
              </span>
              {operand.node ? <Level node={operand.node} depth={depth + 1} /> : null}
            </div>
          ))}
        </div>
      ) : null}

      {node.support === "AGGREGATION" && node.source_record_ids.length > 0 ? (
        <span style={{ fontSize: "11px", color: t.textFaint }}>
          folds {node.source_record_ids.length.toLocaleString("en-IN")} records
        </span>
      ) : null}
    </div>
  );
}

/** Kept exported for pages that want an inline evidence id chip. */
export function EvidenceId({ id }: { id: string }) {
  return <Mono muted>{id}</Mono>;
}
