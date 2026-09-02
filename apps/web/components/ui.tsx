"use client";

/**
 * The handful of surfaces this app repeats, built once.
 *
 * Blade owns buttons, inputs, alerts, badges, spinners and the drawer. It has
 * no opinion about "a panel with a title and a right-aligned action", or "a
 * metric tile you can click down into evidence", because those are this
 * application's shapes rather than a design system's. They were each open-coded
 * four or five times with slightly different padding, and that is what made the
 * pages look like different products.
 *
 * Everything here reads `useTheme()`. Nothing here contains a `#`.
 */

import type { CSSProperties, ReactNode } from "react";
import React from "react";

import { useTheme } from "@/app/providers";
import { numeric, radius, space, toneColors, transition, type Tone } from "@/lib/theme";

/* -------------------------------------------------------------------- panel */

export function Panel({
  children,
  padding = 5,
  style,
  testID,
}: {
  children: ReactNode;
  /** In 4px steps. */
  padding?: number;
  style?: CSSProperties;
  testID?: string;
}) {
  const { t } = useTheme();
  return (
    <section
      data-testid={testID}
      style={{
        backgroundColor: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: radius.lg,
        boxShadow: t.shadow,
        padding: space(padding),
        ...style,
      }}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  hint,
  icon,
  action,
}: {
  title: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  const { t } = useTheme();
  return (
    <header
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: space(4),
        marginBottom: space(4),
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: space(1), minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: space(2) }}>
          {icon ? <span style={{ color: t.accent, display: "flex" }}>{icon}</span> : null}
          <h2
            style={{
              margin: 0,
              fontSize: "14px",
              fontWeight: 600,
              letterSpacing: "-0.01em",
              color: t.text,
            }}
          >
            {title}
          </h2>
        </div>
        {hint ? (
          <p style={{ margin: 0, fontSize: "12.5px", lineHeight: 1.5, color: t.textMuted }}>
            {hint}
          </p>
        ) : null}
      </div>
      {action}
    </header>
  );
}

/* --------------------------------------------------------------------- pill */

export function Pill({
  children,
  tone = "neutral",
  icon,
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  title?: string;
}) {
  const { t } = useTheme();
  const { fg, bg } = toneColors(t, tone);
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: space(1.5),
        padding: `${space(1)} ${space(2.5)}`,
        borderRadius: radius.pill,
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${tone === "neutral" ? t.border : "transparent"}`,
        fontSize: "11.5px",
        fontWeight: 600,
        lineHeight: 1.4,
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ figures */

/**
 * A number, set the way a finance console has to set numbers.
 *
 * `size="display"` is the one on a tile; `size="body"` is the one inside a
 * sentence. Both are tabular, so a column of them lines up.
 */
export function Figure({
  children,
  size = "body",
  tone,
  title,
}: {
  children: ReactNode;
  size?: "display" | "body" | "small";
  tone?: Tone;
  title?: string;
}) {
  const { t } = useTheme();
  const sizes = { display: "26px", body: "14px", small: "12.5px" } as const;
  return (
    <span
      title={title}
      style={{
        ...numeric,
        fontSize: sizes[size],
        fontWeight: size === "display" ? 650 : 600,
        letterSpacing: size === "display" ? "-0.02em" : "0",
        color: tone ? toneColors(t, tone).fg : t.text,
        lineHeight: 1.2,
      }}
    >
      {children}
    </span>
  );
}

/** An id, a formula, an evidence key -- anything the reader may need to copy. */
export function Mono({ children, muted = false }: { children: ReactNode; muted?: boolean }) {
  const { t } = useTheme();
  return (
    <code
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        fontSize: "11.5px",
        color: muted ? t.textFaint : t.textMuted,
        backgroundColor: t.sunken,
        border: `1px solid ${t.border}`,
        borderRadius: radius.sm,
        padding: `1px ${space(1.5)}`,
        wordBreak: "break-all",
      }}
    >
      {children}
    </code>
  );
}

/* --------------------------------------------------------------------- tile */

/**
 * One verified metric. Clickable when it can be opened down to its records,
 * and visibly inert when it cannot -- a tile that looks clickable and is not is
 * how a reader stops trusting the ones that are.
 */
export function MetricTile({
  label,
  value,
  caption,
  tone,
  onOpen,
  testID,
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
  tone?: Tone;
  onOpen?: () => void;
  testID?: string;
}) {
  const { t } = useTheme();
  const interactive = Boolean(onOpen);
  return (
    <button
      type="button"
      data-testid={testID}
      onClick={onOpen}
      disabled={!interactive}
      style={{
        appearance: "none",
        font: "inherit",
        textAlign: "left",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        gap: space(1.5),
        padding: space(4),
        backgroundColor: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: radius.md,
        cursor: interactive ? "pointer" : "default",
        transition: `border-color ${transition.fast}, background-color ${transition.fast}, transform ${transition.fast}`,
      }}
      onMouseEnter={(event) => {
        if (!interactive) return;
        event.currentTarget.style.borderColor = t.accentBorder;
        event.currentTarget.style.backgroundColor = t.surfaceHover;
      }}
      onMouseLeave={(event) => {
        event.currentTarget.style.borderColor = t.border;
        event.currentTarget.style.backgroundColor = t.surface;
      }}
    >
      <span
        style={{
          fontSize: "11.5px",
          fontWeight: 500,
          color: t.textMuted,
          letterSpacing: "0.01em",
        }}
      >
        {label}
      </span>
      <Figure size="display" tone={tone}>
        {value}
      </Figure>
      {caption ? (
        <span style={{ fontSize: "11.5px", color: t.textFaint, lineHeight: 1.4 }}>{caption}</span>
      ) : null}
    </button>
  );
}

/* ------------------------------------------------------------------- layout */

export function Grid({
  children,
  min = "220px",
  gap = 3,
}: {
  children: ReactNode;
  min?: string;
  gap?: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fill, minmax(${min}, 1fr))`,
        gap: space(gap),
      }}
    >
      {children}
    </div>
  );
}

export function Stack({
  children,
  gap = 4,
  style,
}: {
  children: ReactNode;
  gap?: number;
  style?: CSSProperties;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space(gap), ...style }}>
      {children}
    </div>
  );
}

export function Row({
  children,
  gap = 2,
  wrap = true,
  align = "center",
  style,
}: {
  children: ReactNode;
  gap?: number;
  wrap?: boolean;
  align?: CSSProperties["alignItems"];
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: align,
        gap: space(gap),
        flexWrap: wrap ? "wrap" : "nowrap",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export function Divider() {
  const { t } = useTheme();
  return <hr style={{ border: 0, borderTop: `1px solid ${t.border}`, margin: 0, width: "100%" }} />;
}

/* -------------------------------------------------------------- empty state */

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  const { t } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: space(2),
        padding: `${space(12)} ${space(6)}`,
        textAlign: "center",
        color: t.textMuted,
      }}
    >
      {icon ? <span style={{ color: t.textFaint, display: "flex" }}>{icon}</span> : null}
      <span style={{ fontSize: "14px", fontWeight: 600, color: t.text }}>{title}</span>
      {body ? (
        <span style={{ fontSize: "13px", lineHeight: 1.6, maxWidth: "46ch" }}>{body}</span>
      ) : null}
      {action ? <div style={{ marginTop: space(2) }}>{action}</div> : null}
    </div>
  );
}

/* ----------------------------------------------------------- section label */

export function SectionLabel({ children }: { children: ReactNode }) {
  const { t } = useTheme();
  return (
    <span
      style={{
        fontSize: "10.5px",
        fontWeight: 700,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: t.textFaint,
      }}
    >
      {children}
    </span>
  );
}
