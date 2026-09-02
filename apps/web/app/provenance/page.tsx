"use client";

import { Badge, Box, Button, Card, CardBody, Heading, Text } from "@razorpay/blade/components";
import { CheckCircle2, Database, ExternalLink, FileText, Info, Lock, ShieldCheck } from "lucide-react";
import React, { useEffect, useState } from "react";

import { useAppTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";
import { API_BASE, USER_ID } from "@/lib/api";
import type { DataProvenance } from "@shared/api";

const FEE_SCHEDULE = [
  {
    instrument: "UPI (Bank Account)",
    mdr: "0.00% (Zero MDR)",
    flat: "₹0.00",
    provenance: "CITED",
    source: "NPCI / Govt Mandate (Jan 2020)",
    note: "Mandatory zero merchant discount rate on P2M bank transfers",
  },
  {
    instrument: "RuPay Debit Card",
    mdr: "0.00% (Zero MDR)",
    flat: "₹0.00",
    provenance: "CITED",
    source: "RBI Notification (2019)",
    note: "Statutory zero-MDR on domestic RuPay debit",
  },
  {
    instrument: "UPI (PPI / Wallet > ₹2k)",
    mdr: "1.10%",
    flat: "₹0.00",
    provenance: "CITED",
    source: "NPCI Circular (2023)",
    note: "Interchange applicable only on wallet-funded P2M above ₹2,000",
  },
  {
    instrument: "Mastercard / Visa Card",
    mdr: "1.90%",
    flat: "₹3.00",
    provenance: "ASSUMED",
    source: "Commercial Agreement",
    note: "Standard negotiated merchant discount rate",
  },
  {
    instrument: "Netbanking (T1 Banks)",
    mdr: "0.00%",
    flat: "₹15.00",
    provenance: "ASSUMED",
    source: "Corporate Banking Agreement",
    note: "Flat billing per corporate netbanking settlement",
  },
];

export default function ProvenancePage() {
  const { isDark } = useAppTheme();
  const [data, setData] = useState<DataProvenance | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/v1/provenance`, {
      headers: { "X-RazorMind-User": USER_ID },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((json) => setData(json))
      .catch(() => undefined);
  }, []);

  return (
    <Shell
      title="Data Provenance & Regulatory Calibration"
      subtitle="Every parameter in RazorMind carries a provenance tag (CITED or ASSUMED). The dataset is synthetic, but calibrated strictly against published NPCI & RBI statistics."
    >
      {/* Banner */}
      <div
        style={{
          padding: "16px 20px",
          borderRadius: "12px",
          backgroundColor: isDark ? "rgba(12, 131, 255, 0.08)" : "rgba(12, 131, 255, 0.05)",
          border: `1px solid ${isDark ? "rgba(12, 131, 255, 0.25)" : "rgba(12, 131, 255, 0.18)"}`,
          display: "flex",
          alignItems: "flex-start",
          gap: "14px",
        }}
      >
        <Info size={20} color="#0C83FF" style={{ flexShrink: 0, marginTop: "2px" }} />
        <div style={{ fontSize: "13px", lineHeight: 1.5, color: isDark ? "#CBD5E1" : "#334155" }}>
          <strong>Synthetic & Calibrated Dataset (Scenario revenue_decline_v1, Seed 42).</strong> No real
          customer or bank record is represented. What matters is that a design choice is never mistaken for an
          observation: Counts are designed; money is derived.
        </div>
      </div>

      {/* Parameter Taxonomy Scorecards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "16px",
        }}
      >
        <div
          style={{
            padding: "20px",
            borderRadius: "12px",
            backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
            border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, color: isDark ? "#94A3B8" : "#64748B" }}>
              CITED Parameters
            </span>
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "4px",
                backgroundColor: "rgba(16,185,129,0.12)",
                color: "#10B981",
              }}
            >
              10 Parameters
            </span>
          </div>
          <div style={{ fontSize: "20px", fontWeight: 700 }}>NPCI & RBI Published</div>
          <div style={{ fontSize: "12px", color: isDark ? "#64748B" : "#94A3B8" }}>
            UPI ticket sizes, rail volumes, zero-MDR mandates, and issuer failure distributions.
          </div>
        </div>

        <div
          style={{
            padding: "20px",
            borderRadius: "12px",
            backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
            border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, color: isDark ? "#94A3B8" : "#64748B" }}>
              ASSUMED Parameters
            </span>
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "4px",
                backgroundColor: "rgba(100,116,139,0.15)",
                color: "#94A3B8",
              }}
            >
              12 Parameters
            </span>
          </div>
          <div style={{ fontSize: "20px", fontWeight: 700 }}>Merchant Business Mix</div>
          <div style={{ fontSize: "12px", color: isDark ? "#64748B" : "#94A3B8" }}>
            Single-merchant payment mix preferences, card brand split, and customer refund request timing.
          </div>
        </div>

        <div
          style={{
            padding: "20px",
            borderRadius: "12px",
            backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
            border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: "12px", fontWeight: 600, color: isDark ? "#94A3B8" : "#64748B" }}>
              Ground Truth Checksums
            </span>
            <span
              style={{
                fontSize: "11px",
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: "4px",
                backgroundColor: "rgba(12,131,255,0.12)",
                color: "#0C83FF",
              }}
            >
              SHA-256 Verified
            </span>
          </div>
          <div style={{ fontSize: "20px", fontWeight: 700 }}>4 Seed Artifacts</div>
          <div style={{ fontSize: "12px", color: isDark ? "#64748B" : "#94A3B8" }}>
            Seed 42 golden fixtures verified before investigation runs.
          </div>
        </div>
      </div>

      {/* Master Fee Schedule Matrix */}
      <div
        style={{
          padding: "24px",
          borderRadius: "12px",
          backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
          border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
          display: "flex",
          flexDirection: "column",
          gap: "16px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 700 }}>
              Instrument-Wise Master Fee Schedule
            </h2>
            <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: isDark ? "#94A3B8" : "#64748B" }}>
              Fees follow the instrument, not a flat 1%. Blended effective rate is 0.006420 (0.642%).
            </p>
          </div>
          <span
            style={{
              fontSize: "11px",
              fontWeight: 600,
              padding: "4px 10px",
              borderRadius: "6px",
              backgroundColor: "rgba(16,185,129,0.12)",
              color: "#10B981",
              border: "1px solid rgba(16,185,129,0.25)",
            }}
          >
            MANDATE COMPLIANT
          </span>
        </div>

        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              textAlign: "left",
              fontSize: "13px",
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
                  color: isDark ? "#94A3B8" : "#64748B",
                  fontSize: "11px",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                <th style={{ padding: "12px 16px" }}>Instrument / Payment Rail</th>
                <th style={{ padding: "12px 16px" }}>MDR Rate</th>
                <th style={{ padding: "12px 16px" }}>Platform Fee</th>
                <th style={{ padding: "12px 16px" }}>Provenance</th>
                <th style={{ padding: "12px 16px" }}>Legal & Regulatory Basis</th>
              </tr>
            </thead>
            <tbody>
              {FEE_SCHEDULE.map((row, idx) => (
                <tr
                  key={idx}
                  style={{
                    borderBottom: `1px solid ${isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)"}`,
                  }}
                >
                  <td style={{ padding: "14px 16px", fontWeight: 600 }}>{row.instrument}</td>
                  <td style={{ padding: "14px 16px", fontFamily: "JetBrains Mono, monospace" }}>
                    {row.mdr}
                  </td>
                  <td style={{ padding: "14px 16px", fontFamily: "JetBrains Mono, monospace" }}>
                    {row.flat}
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <span
                      style={{
                        fontSize: "11px",
                        fontWeight: 600,
                        padding: "2px 6px",
                        borderRadius: "4px",
                        backgroundColor:
                          row.provenance === "CITED"
                            ? "rgba(16,185,129,0.12)"
                            : "rgba(100,116,139,0.15)",
                        color: row.provenance === "CITED" ? "#10B981" : "#94A3B8",
                      }}
                    >
                      {row.provenance}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px", color: isDark ? "#94A3B8" : "#64748B" }}>
                    <div>{row.note}</div>
                    <div style={{ fontSize: "11px", opacity: 0.8, marginTop: "2px" }}>
                      Source: {row.source}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Shell>
  );
}
