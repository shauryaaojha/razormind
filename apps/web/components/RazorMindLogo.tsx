"use client";

/**
 * The mark.
 *
 * Its blues are the theme's accent rather than literals, so the logo tracks a
 * brand refresh with everything else. A logo is the one place an app can
 * reasonably keep its own colours, which is exactly why it is the place they
 * get left behind -- ours was still holding the hexes the rest of the app had
 * already stopped using.
 *
 * The glyph's own white and the two node dots stay fixed: they sit on the
 * accent gradient, not on the page, so they must not follow the page's scheme.
 * They are read off `textOnAccent` and a translucent white for the same reason
 * -- the mark is legible on the gradient in both schemes because the gradient
 * is the same in both.
 */

import React from "react";

import { useTheme } from "@/app/providers";
import { radius, space } from "@/lib/theme";

export function RazorMindLogo({
  size = "medium",
  showText = true,
  showTag = true,
}: {
  size?: "small" | "medium" | "large";
  showText?: boolean;
  /** The "Deterministic" chip. Off in the header, where the merchant pill
      already occupies that slot and two chips read as noise. */
  showTag?: boolean;
}) {
  const { t } = useTheme();
  const dims =
    size === "small"
      ? { icon: 26, font: "16px", sub: "10px" }
      : size === "large"
        ? { icon: 44, font: "24px", sub: "12px" }
        : { icon: 34, font: "20px", sub: "11px" };

  const onMark = t.textOnAccent;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: space(2.5), userSelect: "none" }}>
      <div
        style={{
          width: dims.icon,
          height: dims.icon,
          borderRadius: "8px",
          background: `linear-gradient(135deg, ${t.accentHover} 0%, ${t.accent} 100%)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: t.shadowAccent,
          flexShrink: 0,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <svg
          width={dims.icon * 0.75}
          height={dims.icon * 0.75}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
        >
          <path
            d="M13 2L3 14H12L11 22L21 10H12L13 2Z"
            fill={onMark}
            stroke="rgba(255,255,255,0.55)"
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="18" cy="5" r="1.5" fill="rgba(255,255,255,0.75)" />
          <circle cx="6" cy="19" r="1.5" fill="rgba(255,255,255,0.75)" />
          <line x1="18" y1="5" x2="13" y2="8" stroke="rgba(255,255,255,0.4)" strokeWidth="0.8" />
          <line x1="6" y1="19" x2="11" y2="16" stroke="rgba(255,255,255,0.4)" strokeWidth="0.8" />
        </svg>
      </div>

      {showText && (
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: space(1.5) }}>
            <span
              style={{
                fontWeight: 700,
                fontSize: dims.font,
                letterSpacing: "-0.03em",
                color: "inherit",
              }}
            >
              Razor<span style={{ color: t.accent }}>Mind</span>
            </span>
            {showTag ? (
              <span
                style={{
                  fontSize: "10px",
                  fontWeight: 700,
                  padding: `2px ${space(1.5)}`,
                  borderRadius: radius.pill,
                  background: t.accentSoft,
                  color: t.accent,
                  border: `1px solid ${t.accentBorder}`,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                }}
              >
                Deterministic
              </span>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
