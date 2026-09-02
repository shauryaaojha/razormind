"use client";

/**
 * The revenue bridge, as bars, from the attribution terms the run published.
 *
 * This component used to hold the figures itself, as literals. That is the one
 * thing this product may not do: a chart of hand-typed numbers sitting beside
 * verified ones, in the same visual language, teaches the reader that the
 * visual language means nothing. Every bar here is an evidence row, and every
 * bar opens onto the records behind it.
 */

import type { EvidenceLine } from "@shared/api";
import React from "react";

import { useTheme } from "@/app/providers";
import { Figure, Panel, PanelHeader, Stack } from "@/components/ui";
import { numeric, radius, space, transition } from "@/lib/theme";

/** `attribution.attempt_volume_effect_paise` -> "Attempt volume". */
export function attributionLabel(metricId: string): string {
  const stem = metricId.replace(/^attribution\./, "").replace(/_effect_paise$/, "");
  const words = stem.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function RevenueWaterfall({
  terms,
  total,
  onInspect,
}: {
  /** The `attribution.*_effect_paise` rows for one window. */
  terms: EvidenceLine[];
  /** `net_revenue_change_paise`, if it was published. */
  total: EvidenceLine | null;
  onInspect?: (evidenceId: string) => void;
}) {
  const { t } = useTheme();

  if (terms.length === 0) return null;

  const magnitudes = terms.map((term) => Math.abs(Number(term.value)));
  const widest = Math.max(...magnitudes, 1);

  return (
    <Panel>
      <PanelHeader
        title="What moved net revenue"
        hint="Each term is a verified evidence row. They sum to the total change with a zero residual — that is checked, not asserted."
        action={
          total ? (
            <Figure tone={Number(total.value) < 0 ? "negative" : "positive"}>{total.display}</Figure>
          ) : null
        }
      />

      <Stack gap={3}>
        {terms.map((term) => {
          const amount = Number(term.value);
          const negative = amount < 0;
          const width = `${Math.max((Math.abs(amount) / widest) * 100, 2)}%`;
          return (
            <button
              key={term.evidence_id}
              type="button"
              onClick={() => onInspect?.(term.evidence_id)}
              disabled={!onInspect}
              style={{
                appearance: "none",
                font: "inherit",
                textAlign: "left",
                width: "100%",
                display: "flex",
                flexDirection: "column",
                gap: space(1.5),
                padding: `${space(2)} ${space(2.5)}`,
                borderRadius: radius.sm,
                border: "1px solid transparent",
                background: "none",
                cursor: onInspect ? "pointer" : "default",
                transition: `background-color ${transition.fast}, border-color ${transition.fast}`,
              }}
              onMouseEnter={(event) => {
                if (!onInspect) return;
                event.currentTarget.style.backgroundColor = t.surfaceHover;
                event.currentTarget.style.borderColor = t.border;
              }}
              onMouseLeave={(event) => {
                event.currentTarget.style.backgroundColor = "transparent";
                event.currentTarget.style.borderColor = "transparent";
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: space(3),
                }}
              >
                <span style={{ fontSize: "13px", color: t.text, fontWeight: 500 }}>
                  {attributionLabel(term.metric_id)}
                </span>
                <span
                  style={{
                    ...numeric,
                    fontSize: "13px",
                    fontWeight: 600,
                    color: negative ? t.negative : t.positive,
                  }}
                >
                  {term.display}
                </span>
              </div>

              {/* A centre line, with the bar growing left for a loss and right
                  for a gain, so sign is legible before the digits are read. */}
              <div
                style={{
                  position: "relative",
                  height: "8px",
                  borderRadius: radius.pill,
                  backgroundColor: t.sunken,
                  overflow: "hidden",
                }}
              >
                <span
                  style={{
                    position: "absolute",
                    top: 0,
                    bottom: 0,
                    left: negative ? "auto" : "50%",
                    right: negative ? "50%" : "auto",
                    width: `calc(${width} / 2)`,
                    backgroundColor: negative ? t.negative : t.positive,
                    borderRadius: radius.pill,
                    opacity: 0.85,
                  }}
                />
                <span
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: 0,
                    bottom: 0,
                    width: "1px",
                    backgroundColor: t.borderStrong,
                  }}
                />
              </div>
            </button>
          );
        })}
      </Stack>
    </Panel>
  );
}
