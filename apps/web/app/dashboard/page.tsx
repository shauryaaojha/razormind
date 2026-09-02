"use client";

import { Alert, Badge, Box, Button, Card, CardBody, Heading, Text } from "@razorpay/blade/components";
import { ArrowUpRight, CheckCircle2, DollarSign, FileCheck, Layers, PieChart, ShieldAlert, Zap } from "lucide-react";
import Link from "next/link";
import React from "react";

import { useAppTheme } from "@/app/providers";
import { RevenueWaterfall } from "@/components/RevenueWaterfall";
import { Shell } from "@/components/Shell";

export default function DashboardPage() {
  const { isDark } = useAppTheme();

  const kpis = [
    {
      title: "Net Revenue",
      value: "₹3,90,122.95",
      sub: "Prior: ₹4,73,424.00",
      delta: "-17.60% (-₹83,301)",
      isPositive: false,
      unit: "paise",
    },
    {
      title: "Gross Payments",
      value: "₹4,06,260.00",
      sub: "341 captures in window",
      delta: "-16.56%",
      isPositive: false,
      unit: "paise",
    },
    {
      title: "Payment Success Rate",
      value: "94.46%",
      sub: "Tech Declines: 2.22% | Biz: 3.32%",
      delta: "-1.34 pp",
      isPositive: false,
      unit: "ratio",
    },
    {
      title: "Clean Match Rate",
      value: "95.61%",
      sub: "327 Clean / 338 Matched",
      delta: "15 exceptions",
      isPositive: true,
      unit: "ratio",
    },
    {
      title: "Fees & Commercial MDR",
      value: "₹2,608.00",
      sub: "Effective Blended Rate: 0.642%",
      delta: "-₹418 offset",
      isPositive: true,
      unit: "paise",
    },
  ];

  const rails = [
    { method: "UPI", vol: "72.0%", val: "38.8%", mean: "₹640", tag: "Zero-MDR Mandate", color: "#0C83FF" },
    { method: "CARDS", vol: "16.1%", val: "37.9%", mean: "₹2,850", tag: "1.90% MDR", color: "#6366F1" },
    { method: "NETBANKING", vol: "5.8%", val: "20.7%", mean: "₹4,200", tag: "Flat ₹15", color: "#10B981" },
    { method: "WALLET", vol: "6.1%", val: "2.7%", mean: "₹520", tag: "PPI Interchange", color: "#F59E0B" },
  ];

  return (
    <Shell
      title="Financial Analytics & Revenue Attribution"
      subtitle="Calibrated aggregate metrics across Aug 1–23, 2026 vs Jul 1–23, 2026. Every figure is produced deterministically without LLM arithmetic."
      action={
        <div style={{ display: "flex", gap: "10px" }}>
          <Link href="/" style={{ textDecoration: "none" }}>
            <button
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "8px 16px",
                borderRadius: "8px",
                backgroundColor: "#0C83FF",
                color: "#FFFFFF",
                fontWeight: 600,
                fontSize: "13px",
                border: "none",
                cursor: "pointer",
                boxShadow: "0 2px 10px rgba(12, 131, 255, 0.35)",
              }}
            >
              <Zap size={14} />
              <span>Ask RazorMind</span>
            </button>
          </Link>
          <Link href="/reconciliation" style={{ textDecoration: "none" }}>
            <button
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "8px 16px",
                borderRadius: "8px",
                backgroundColor: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.04)",
                color: isDark ? "#F8FAFC" : "#0F172A",
                fontWeight: 600,
                fontSize: "13px",
                border: `1px solid ${isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)"}`,
                cursor: "pointer",
              }}
            >
              <Layers size={14} />
              <span>Reconciliation Hub</span>
            </button>
          </Link>
        </div>
      }
    >
      {/* 5 KPI Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "16px",
        }}
      >
        {kpis.map((kpi, idx) => (
          <div
            key={idx}
            style={{
              padding: "18px 20px",
              borderRadius: "12px",
              backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              flexDirection: "column",
              gap: "8px",
              position: "relative",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: "12px", fontWeight: 600, color: isDark ? "#94A3B8" : "#64748B" }}>
                {kpi.title}
              </span>
              <span
                style={{
                  fontSize: "11px",
                  fontWeight: 600,
                  padding: "2px 6px",
                  borderRadius: "4px",
                  backgroundColor: kpi.isPositive ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                  color: kpi.isPositive ? "#10B981" : "#EF4444",
                }}
              >
                {kpi.delta}
              </span>
            </div>

            <div
              style={{
                fontSize: "22px",
                fontWeight: 700,
                fontFamily: "Inter, sans-serif",
                color: isDark ? "#F8FAFC" : "#0F172A",
                letterSpacing: "-0.02em",
              }}
            >
              {kpi.value}
            </div>

            <div style={{ fontSize: "11px", color: isDark ? "#64748B" : "#94A3B8" }}>
              {kpi.sub}
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid: Waterfall (60%) + Rails & Incidents (40%) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(460px, 1fr))",
          gap: "24px",
        }}
      >
        {/* Waterfall Chart */}
        <RevenueWaterfall />

        {/* Right Column: Rails & Bank Alert */}
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Rail Distribution Card */}
          <div
            style={{
              padding: "20px",
              borderRadius: "12px",
              backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              flexDirection: "column",
              gap: "14px",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 600 }}>
                Payment Rail Mix (Volume vs Value)
              </h3>
              <span style={{ fontSize: "11px", color: isDark ? "#94A3B8" : "#64748B" }}>
                NPCI Calibrated
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {rails.map((rail, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: "10px 12px",
                    borderRadius: "8px",
                    backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
                    border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontSize: "13px",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                    <div
                      style={{
                        width: "10px",
                        height: "10px",
                        borderRadius: "50%",
                        backgroundColor: rail.color,
                      }}
                    />
                    <div>
                      <strong>{rail.method}</strong>
                      <span style={{ fontSize: "11px", color: isDark ? "#94A3B8" : "#64748B", marginLeft: "6px" }}>
                        · Mean Ticket {rail.mean}
                      </span>
                    </div>
                  </div>

                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontWeight: 600 }}>{rail.vol} vol</span> /{" "}
                    <span style={{ color: "#0C83FF", fontWeight: 600 }}>{rail.val} val</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Operational Incident Alert Box */}
          <div
            style={{
              padding: "18px 20px",
              borderRadius: "12px",
              backgroundColor: isDark ? "rgba(239, 68, 68, 0.08)" : "rgba(239, 68, 68, 0.05)",
              border: "1px solid rgba(239, 68, 68, 0.25)",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#EF4444" }}>
              <ShieldAlert size={18} />
              <strong style={{ fontSize: "14px" }}>UPI Issuer Degradation Incident</strong>
            </div>

            <p style={{ margin: 0, fontSize: "13px", color: isDark ? "#CBD5E1" : "#334155", lineHeight: 1.5 }}>
              Active window: <strong>2026-08-09 to 2026-08-19</strong>. Technical declines at{" "}
              <strong>BANK_A, BANK_B, BANK_C</strong> spiked to <strong>9.59%</strong> vs 0.00% across other issuers.
            </p>

            <div style={{ fontSize: "12px", color: "#EF4444", fontWeight: 600, marginTop: "2px" }}>
              Impact on Revenue: -₹3,207.00 (Secondary contributor to -₹83,301 total decline).
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
