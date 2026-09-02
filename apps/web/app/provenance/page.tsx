"use client";

/**
 * Where the data itself comes from, and which parameters are cited rather than
 * assumed.
 *
 * Everything here is read from `/api/v1/provenance`. The fee schedule was a
 * hardcoded table in this file with prettier labels than the API's own — two
 * descriptions of one rate, on the page whose entire subject is that a
 * parameter must carry a provenance tag. When they drifted, the prettier one
 * would have won, silently.
 */

import { Alert, Spinner } from "@razorpay/blade/components";
import type { DataProvenance, FeeRuleView } from "@shared/api";
import { Info } from "lucide-react";
import React, { useEffect, useState } from "react";

import { useTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";
import { Grid, MetricTile, Mono, Panel, PanelHeader, Pill, Row, SectionLabel, Stack } from "@/components/ui";
import { API_BASE, USER_ID } from "@/lib/api";
import { numeric, radius, space, type Tone } from "@/lib/theme";

const TAG_TONE: Record<string, Tone> = {
  CITED: "positive",
  DERIVED: "info",
  ASSUMED: "warning",
};

/** `UPI_PPI_WALLET` -> `UPI PPI wallet`. The API's name, made readable — not renamed. */
function instrumentLabel(id: string): string {
  const [head, ...rest] = id.split("_");
  return [head, ...rest.map((word) => word.toLowerCase())].join(" ");
}

export default function ProvenancePage() {
  const { t } = useTheme();
  const [data, setData] = useState<DataProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/api/v1/provenance`, { headers: { "X-RazorMind-User": USER_ID } })
      .then((response) => {
        if (!response.ok) throw new Error(`${response.status} from /provenance`);
        return response.json() as Promise<DataProvenance>;
      })
      .then((json) => live && setData(json))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <Shell title="Calibration">
        <Alert isFullWidth color="negative" title="Cannot load provenance" description={error} />
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell title="Calibration">
        <Spinner accessibilityLabel="Loading provenance" size="medium" />
      </Shell>
    );
  }

  const counts = Object.entries(data.parameter_counts).filter(([, n]) => (n ?? 0) > 0);

  return (
    <Shell
      title="Calibration"
      subtitle="Every parameter carries a provenance tag. The records are synthetic; the aggregates they are calibrated against are not."
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: space(3.5),
          padding: `${space(4)} ${space(5)}`,
          borderRadius: radius.lg,
          backgroundColor: t.accentSoft,
          border: `1px solid ${t.accentBorder}`,
        }}
      >
        <Info size={18} color={t.accent} style={{ flexShrink: 0, marginTop: "2px" }} />
        <span style={{ fontSize: "13px", lineHeight: 1.6, color: t.text }}>
          {data.disclaimer}
        </span>
      </div>

      <Grid min="200px">
        <MetricTile label="Scenario" value={data.scenario_id} caption="the seeded storyline" />
        <MetricTile label="Seed" value={data.seed} caption="regeneration is byte-identical" />
        {counts.map(([tag, n]) => (
          <MetricTile
            key={tag}
            label={`${tag.charAt(0)}${tag.slice(1).toLowerCase()} parameters`}
            value={n ?? 0}
            tone={TAG_TONE[tag]}
            caption={
              tag === "CITED"
                ? "traceable to a published source"
                : tag === "ASSUMED"
                  ? "a design choice, stated as one"
                  : "computed from the others"
            }
          />
        ))}
      </Grid>

      <Panel>
        <PanelHeader
          title="Fee schedule"
          hint="Served by the API, not restated here. A rate tagged ASSUMED is a commercial choice; CITED means it traces to a regulator's own notification."
        />
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "12.5px",
              minWidth: "640px",
            }}
          >
            <thead>
              <tr>
                {["Instrument", "MDR", "Flat fee", "Applies above", "Source", ""].map((head) => (
                  <th
                    key={head}
                    style={{
                      textAlign: head === "Instrument" || head === "" ? "left" : "right",
                      padding: `${space(2)} ${space(3)}`,
                      borderBottom: `1px solid ${t.border}`,
                      color: t.textFaint,
                      fontWeight: 700,
                      fontSize: "10.5px",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.fee_schedule.map((rule) => (
                <FeeRow key={rule.instrument} rule={rule} />
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel>
        <PanelHeader
          title="Checksums"
          hint="The generator is deterministic. These are what a regeneration has to reproduce."
        />
        <Stack gap={2}>
          {Object.entries(data.checksums).map(([name, sum]) => (
            <Row key={name} gap={3} style={{ justifyContent: "space-between" }}>
              <span style={{ fontSize: "12.5px", color: t.textMuted }}>{name}</span>
              <Mono>{sum}</Mono>
            </Row>
          ))}
        </Stack>
        <div style={{ marginTop: space(4), paddingTop: space(4), borderTop: `1px solid ${t.border}` }}>
          <Stack gap={2}>
            <SectionLabel>Calibrated against</SectionLabel>
            <span style={{ fontSize: "12.5px", color: t.textMuted, lineHeight: 1.6 }}>
              {data.aggregate_calibration}
            </span>
            <Row gap={2}>
              <Mono muted>{data.sources_document}</Mono>
              <Mono muted>{data.transaction_records}</Mono>
              <Mono muted>{data.ground_truth}</Mono>
            </Row>
          </Stack>
        </div>
      </Panel>
    </Shell>
  );
}

function FeeRow({ rule }: { rule: FeeRuleView }) {
  const { t } = useTheme();
  const cell = {
    padding: `${space(2.5)} ${space(3)}`,
    borderBottom: `1px solid ${t.border}`,
    color: t.text,
  } as const;
  const rate = Number(rule.mdr_rate);
  return (
    <tr>
      <td style={{ ...cell, fontWeight: 550 }}>{instrumentLabel(rule.instrument)}</td>
      {/* Every figure below is the string the API rendered. Nothing here
          divides paise by 100 -- see D-54, and `mdr_display` on the route. */}
      <td style={{ ...cell, ...numeric, textAlign: "right" }}>
        {rate === 0 ? (
          <span style={{ color: t.positive, fontWeight: 600 }}>zero</span>
        ) : (
          rule.mdr_display
        )}
      </td>
      <td style={{ ...cell, ...numeric, textAlign: "right", color: t.textMuted }}>
        {rule.flat_fee_paise === 0 ? "—" : rule.flat_fee_display}
      </td>
      <td style={{ ...cell, ...numeric, textAlign: "right", color: t.textMuted }}>
        {rule.threshold_paise === 0 ? "—" : rule.threshold_display}
      </td>
      <td style={{ ...cell, textAlign: "right" }}>
        <Pill tone={TAG_TONE[rule.provenance] ?? "neutral"}>{rule.provenance}</Pill>
      </td>
      <td style={{ ...cell, color: t.textFaint, fontSize: "11.5px", maxWidth: "34ch", lineHeight: 1.5 }}>
        {rule.note}
      </td>
    </tr>
  );
}
