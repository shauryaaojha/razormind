"use client";

import React from "react";

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
  const dims =
    size === "small"
      ? { icon: 26, font: "16px", sub: "10px" }
      : size === "large"
        ? { icon: 44, font: "24px", sub: "12px" }
        : { icon: 34, font: "20px", sub: "11px" };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "10px", userSelect: "none" }}>
      <div
        style={{
          width: dims.icon,
          height: dims.icon,
          borderRadius: "8px",
          background: "linear-gradient(135deg, #0C83FF 0%, #002970 100%)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 0 16px rgba(12, 131, 255, 0.45)",
          flexShrink: 0,
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Abstract Lightning Blade & Neural Geometry */}
        <svg
          width={dims.icon * 0.75}
          height={dims.icon * 0.75}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path
            d="M13 2L3 14H12L11 22L21 10H12L13 2Z"
            fill="#FFFFFF"
            stroke="#99CCFF"
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="18" cy="5" r="1.5" fill="#60A5FA" />
          <circle cx="6" cy="19" r="1.5" fill="#60A5FA" />
          <line x1="18" y1="5" x2="13" y2="8" stroke="rgba(255,255,255,0.4)" strokeWidth="0.8" />
          <line x1="6" y1="19" x2="11" y2="16" stroke="rgba(255,255,255,0.4)" strokeWidth="0.8" />
        </svg>
      </div>

      {showText && (
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            <span
              style={{
                fontFamily: "Inter, -apple-system, sans-serif",
                fontWeight: 700,
                fontSize: dims.font,
                letterSpacing: "-0.03em",
                color: "inherit",
              }}
            >
              Razor<span style={{ color: "#0C83FF" }}>Mind</span>
            </span>
            {showTag ? (
            <span
              style={{
                fontSize: "10px",
                fontWeight: 700,
                padding: "2px 6px",
                borderRadius: "999px",
                background: "rgba(12, 131, 255, 0.15)",
                color: "#0C83FF",
                border: "1px solid rgba(12, 131, 255, 0.3)",
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
