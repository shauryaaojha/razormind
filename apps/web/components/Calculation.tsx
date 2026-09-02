"use client";

/**
 * The arithmetic, worked.
 *
 * A derived metric already showed its expression and its operands on separate
 * lines, which asks the reader to do the substitution in their head — and the
 * substitution is the interesting part, because it is the step layer 4 of
 * verification re-performs against the tool's own declared formula.
 *
 * **Nothing here evaluates anything.** The substitution is textual: operand
 * names are replaced by the values the API served, and the result line is the
 * node's own stored value, not a number this file worked out. A second
 * arithmetic implementation in TypeScript would be a second answer to "what is
 * this metric", and the first time the two disagreed the screen would be
 * showing a figure that no verification layer had ever seen. The line under the
 * steps says so, because a reader is entitled to know whether the browser is
 * computing or reporting.
 *
 * The substituted line is shown only when every name in the expression has an
 * operand to stand in for it. A half-substituted formula reads as though some
 * of the inputs were unknown.
 */

import { useTheme } from "@/app/providers";
import { SectionLabel } from "@/components/ui";
import { numeric, radius, space } from "@/lib/theme";
import type { ProvenanceLevel } from "@shared/api";

const IDENTIFIER = /[A-Za-z_][A-Za-z0-9_]*/g;

export function Calculation({ node }: { node: ProvenanceLevel }) {
  const { t } = useTheme();
  const values = new Map(node.operands.map((operand) => [operand.name, String(operand.value)]));
  const names = [...(node.detail.match(IDENTIFIER) ?? [])];
  const complete = names.length > 0 && names.every((name) => values.has(name));

  const substituted = complete
    ? node.detail.replace(IDENTIFIER, (name) => values.get(name) ?? name)
    : null;

  return (
    <div
      data-testid="calculation"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: space(1.5),
        padding: `${space(2.5)} ${space(3)}`,
        borderRadius: radius.sm,
        backgroundColor: t.sunken,
        border: `1px solid ${t.border}`,
      }}
    >
      <SectionLabel>How it is computed</SectionLabel>

      <Step label="formula" value={node.detail} />
      {substituted ? <Step label="with values" value={substituted} /> : null}
      <Step label="result" value={`${node.value} ${node.unit}`} strong />

      <span style={{ fontSize: "10.5px", color: t.textFaint, lineHeight: 1.5 }}>
        Layer 4 re-evaluated this expression against these operands — through a grammar with no
        function calls, so it cannot re-run the tool — and required the same result. The
        substitution above is textual; this page performs no arithmetic.
      </span>
    </div>
  );
}

function Step({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  const { t } = useTheme();
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: space(2.5) }}>
      <span
        style={{
          fontSize: "10.5px",
          color: t.textFaint,
          width: "68px",
          flexShrink: 0,
          textAlign: "right",
        }}
      >
        {label}
      </span>
      <span
        style={{
          ...numeric,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
          fontSize: "11.5px",
          lineHeight: 1.6,
          color: strong ? t.text : t.textMuted,
          fontWeight: strong ? 650 : 400,
          wordBreak: "break-word",
        }}
      >
        {value}
      </span>
    </div>
  );
}
