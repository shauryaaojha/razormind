"use client";

import { useAppTheme } from "@/app/providers";
import React from "react";

export function RevenueWaterfall() {
  const { isDark } = useAppTheme();

  const items = [
    { label: "Prior Period Net Revenue", amount: 473424, display: "₹4,73,424.00", type: "start" },
    { label: "Attempt Volume Decline", amount: -77452, display: "-₹77,452.00", type: "neg", pct: "93.0%" },
    { label: "Success Rate Decline", amount: -3207, display: "-₹3,207.00", type: "neg", pct: "3.8%" },
    { label: "Refund Increase", amount: -2336, display: "-₹2,336.00", type: "neg", pct: "2.8%" },
    { label: "Chargeback Increase", amount: -724, display: "-₹724.00", type: "neg", pct: "0.9%" },
    { label: "Fee Decrease (Offset)", amount: 418, display: "+₹418.00", type: "pos", pct: "+0.5%" },
    { label: "Rounding Residual", amount: 0, display: "₹0.00", type: "neutral", pct: "0.0%" },
    { label: "Current Net Revenue", amount: 390122.95, display: "₹3,90,122.95", type: "end" },
  ];

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "16px",
        padding: "20px",
        borderRadius: "12px",
        backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
        border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>
            Revenue Attribution Waterfall Bridge
          </h3>
          <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: isDark ? "#94A3B8" : "#64748B" }}>
            Total delta: <strong style={{ color: "#EF4444" }}>-₹83,301.00 (-17.60%)</strong> · Attributed with exact zero residual
          </p>
        </div>
        <span
          style={{
            fontSize: "11px",
            fontWeight: 600,
            padding: "4px 8px",
            borderRadius: "6px",
            backgroundColor: "rgba(16, 185, 129, 0.12)",
            color: "#10B981",
            border: "1px solid rgba(16, 185, 129, 0.25)",
          }}
        >
          ZERO RESIDUAL VERIFIED
        </span>
      </div>

      {/* Waterfall Rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        {items.map((row, idx) => {
          const isPos = row.type === "pos" || row.type === "start" || row.type === "end";
          const isNeg = row.type === "neg";
          const barColor =
            row.type === "start"
              ? "#3B82F6"
              : row.type === "end"
                ? "#0C83FF"
                : isNeg
                  ? "#EF4444"
                  : isPos
                    ? "#10B981"
                    : "#64748B";

          return (
            <div
              key={idx}
              style={{
                display: "grid",
                gridTemplateColumns: "220px 1fr 140px",
                alignItems: "center",
                gap: "16px",
                fontSize: "13px",
              }}
            >
              <div style={{ fontWeight: row.type === "start" || row.type === "end" ? 600 : 400 }}>
                {row.label}
              </div>

              {/* Bar visualization */}
              <div
                style={{
                  height: "22px",
                  borderRadius: "6px",
                  backgroundColor: isDark ? "#141C2B" : "#F1F5F9",
                  position: "relative",
                  overflow: "hidden",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    width:
                      row.type === "start" || row.type === "end"
                        ? "100%"
                        : `${Math.min(100, Math.max(4, (Math.abs(row.amount) / 80000) * 100))}%`,
                    backgroundColor: barColor,
                    borderRadius: "4px",
                    transition: "width 0.4s ease",
                  }}
                />
              </div>

              <div
                style={{
                  textAlign: "right",
                  fontFamily: "JetBrains Mono, monospace",
                  fontWeight: 600,
                  color:
                    row.type === "start" || row.type === "end"
                      ? isDark
                        ? "#F8FAFC"
                        : "#0F172A"
                      : barColor,
                }}
              >
                {row.display} {row.pct && <span style={{ fontSize: "11px", opacity: 0.75 }}>({row.pct})</span>}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: "6px",
          padding: "10px 14px",
          borderRadius: "8px",
          backgroundColor: isDark ? "rgba(12, 131, 255, 0.08)" : "rgba(12, 131, 255, 0.05)",
          border: `1px solid ${isDark ? "rgba(12, 131, 255, 0.2)" : "rgba(12, 131, 255, 0.15)"}`,
          fontSize: "12px",
          color: isDark ? "#94A3B8" : "#475569",
          lineHeight: 1.5,
        }}
      >
        <strong style={{ color: "#0C83FF" }}>Key Finding:</strong> Attempt volume movement accounted for <strong>93%</strong> of the decline (-₹77,452). The technical outage at Bank A/B/C contributed only <strong>3.8%</strong> (-₹3,207).
      </div>
    </div>
  );
}
