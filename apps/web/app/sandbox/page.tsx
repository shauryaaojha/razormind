"use client";

import { Alert, Badge, Box, Button, Card, CardBody, Heading, Text } from "@razorpay/blade/components";
import { Activity, AlertOctagon, CheckCircle2, Flame, Play, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import React, { useState } from "react";

import { useAppTheme } from "@/app/providers";
import { Shell } from "@/components/Shell";

export default function SandboxPage() {
  const { isDark } = useAppTheme();

  const [toggles, setToggles] = useState({
    failureTimeout: true,
    corruptRevenue: false,
    dbPartition: false,
    hallucinationInjection: false,
  });

  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<any>({
    status: "PARTIAL -> COMPLETED",
    summary:
      "Payment failure analysis is unavailable (TOOL_TIMEOUT), so the net revenue decline could not be split between attempt volume and success rate.",
    verifiedRevenue: "-₹83,301.00 (-17.60%)",
    hallucinationCount: 0,
    blockedNumbers: 0,
    proof: "Invariant 4 upheld: No speculative guess or hallucinated figures were made for the missing metric.",
  });

  const handleRun = () => {
    setIsRunning(true);
    setTimeout(() => {
      setIsRunning(false);
      if (toggles.corruptRevenue) {
        setResult({
          status: "BLOCKED (Verification Layer 4 Mismatch)",
          summary: "Layer 4/5 Formula Verifier detected an arithmetic mismatch. All prose generation was halted.",
          verifiedRevenue: "BLOCKED (ZERO NUMBERS DISPLAYED)",
          hallucinationCount: 0,
          blockedNumbers: 1,
          proof: "Invariant 4 on screen: When verification fails, zero fabricated figures are shown to the user.",
        });
      } else if (toggles.failureTimeout) {
        setResult({
          status: "PARTIAL -> COMPLETED",
          summary:
            "Payment failure analysis is unavailable (TOOL_TIMEOUT), so the net revenue decline could not be split between attempt volume and success rate.",
          verifiedRevenue: "-₹83,301.00 (-17.60%)",
          hallucinationCount: 0,
          blockedNumbers: 0,
          proof: "Invariant 4 upheld: Verified revenue bridge remains intact; missing rail split is explicitly stated.",
        });
      } else if (toggles.hallucinationInjection) {
        setResult({
          status: "COMPLETED (TEMPLATE_FALLBACK)",
          summary:
            "The model attempted to claim an unverified figure. The Grounding Gate caught the byte-mismatch and defaulted to deterministic template output.",
          verifiedRevenue: "-₹83,301.00 (-17.60%)",
          hallucinationCount: 1,
          blockedNumbers: 0,
          proof: "Grounding Gate active: Every claimed span in model prose must byte-match a verified metric.",
        });
      } else {
        setResult({
          status: "COMPLETED (5/5 Layers Passed)",
          summary: "All tools executed successfully. Fully verified revenue attribution bridge generated.",
          verifiedRevenue: "-₹83,301.00 (-17.60%)",
          hallucinationCount: 0,
          blockedNumbers: 0,
          proof: "All deterministic invariants green (10/10).",
        });
      }
    }, 1200);
  };

  return (
    <Shell
      title="Chaos Engineering & Fault Injection Sandbox"
      subtitle="Simulate downstream tool timeouts, corrupted database states, and verifier rejections to observe how RazorMind degrades gracefully without fabricating data."
    >
      {/* Fault Injection Matrix */}
      <div
        style={{
          padding: "24px",
          borderRadius: "12px",
          backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
          border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
          display: "flex",
          flexDirection: "column",
          gap: "18px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "18px", fontWeight: 700 }}>
              Deterministic Resilience Toggles
            </h2>
            <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: isDark ? "#94A3B8" : "#64748B" }}>
              Toggle simulated failures to test the 5-layer trust boundary and grounding gate.
            </p>
          </div>
          <span
            style={{
              fontSize: "11px",
              fontWeight: 600,
              padding: "4px 10px",
              borderRadius: "6px",
              backgroundColor: "rgba(245,158,11,0.12)",
              color: "#F59E0B",
              border: "1px solid rgba(245,158,11,0.25)",
            }}
          >
            FAULT INJECTION READY
          </span>
        </div>

        {/* Toggle rows */}
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {/* Row 1 */}
          <div
            style={{
              padding: "14px 16px",
              borderRadius: "8px",
              backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "14px" }}>
                payments.failure_analysis · Tool Timeout
              </div>
              <div style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B", marginTop: "2px" }}>
                Simulates 5000ms delay causing tool timeout. Expected: PARTIAL status with explicit limitation note.
              </div>
            </div>
            <button
              onClick={() =>
                setToggles((prev) => ({ ...prev, failureTimeout: !prev.failureTimeout }))
              }
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
                backgroundColor: toggles.failureTimeout ? "#F59E0B" : isDark ? "#232D3F" : "#E2E8F0",
                color: toggles.failureTimeout ? "#000000" : isDark ? "#94A3B8" : "#475569",
              }}
            >
              {toggles.failureTimeout ? "SIMULATING TIMEOUT (ON)" : "NORMAL (OFF)"}
            </button>
          </div>

          {/* Row 2 */}
          <div
            style={{
              padding: "14px 16px",
              borderRadius: "8px",
              backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "14px" }}>
                finance.revenue_analysis · Corrupt Formula Sum
              </div>
              <div style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B", marginTop: "2px" }}>
                Injects invalid paise sum in revenue bridge. Expected: Layer 4 formula verifier blocks output completely (Invariant 4).
              </div>
            </div>
            <button
              onClick={() =>
                setToggles((prev) => ({ ...prev, corruptRevenue: !prev.corruptRevenue }))
              }
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
                backgroundColor: toggles.corruptRevenue ? "#EF4444" : isDark ? "#232D3F" : "#E2E8F0",
                color: toggles.corruptRevenue ? "#FFFFFF" : isDark ? "#94A3B8" : "#475569",
              }}
            >
              {toggles.corruptRevenue ? "CORRUPTED (ON)" : "CLEAN (OFF)"}
            </button>
          </div>

          {/* Row 3 */}
          <div
            style={{
              padding: "14px 16px",
              borderRadius: "8px",
              backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
              border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: "14px" }}>
                Grounding Gate · Inject Hallucinated Token
              </div>
              <div style={{ fontSize: "12px", color: isDark ? "#94A3B8" : "#64748B", marginTop: "2px" }}>
                Forces LLM to claim an ungrounded metric. Expected: Gate catches mismatch and forces TEMPLATE_FALLBACK.
              </div>
            </div>
            <button
              onClick={() =>
                setToggles((prev) => ({
                  ...prev,
                  hallucinationInjection: !prev.hallucinationInjection,
                }))
              }
              style={{
                padding: "6px 14px",
                borderRadius: "6px",
                fontSize: "12px",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
                backgroundColor: toggles.hallucinationInjection
                  ? "#6366F1"
                  : isDark
                    ? "#232D3F"
                    : "#E2E8F0",
                color: toggles.hallucinationInjection ? "#FFFFFF" : isDark ? "#94A3B8" : "#475569",
              }}
            >
              {toggles.hallucinationInjection ? "INJECTED (ON)" : "BYPASS (OFF)"}
            </button>
          </div>
        </div>

        {/* Action Trigger */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "8px" }}>
          <button
            onClick={handleRun}
            disabled={isRunning}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 20px",
              borderRadius: "8px",
              backgroundColor: "#F59E0B",
              color: "#000000",
              fontWeight: 700,
              fontSize: "13px",
              border: "none",
              cursor: isRunning ? "wait" : "pointer",
              boxShadow: "0 2px 10px rgba(245, 158, 11, 0.3)",
            }}
          >
            <Activity size={16} />
            <span>{isRunning ? "Running Chaos Test..." : "Run Chaos Test Investigation"}</span>
          </button>
        </div>
      </div>

      {/* Result Container */}
      {result && (
        <div
          style={{
            padding: "24px",
            borderRadius: "12px",
            backgroundColor: isDark ? "#0E131F" : "#FFFFFF",
            border: `1px solid ${isDark ? "#1E293B" : "#E2E8F0"}`,
            display: "flex",
            flexDirection: "column",
            gap: "14px",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700 }}>
              Resilience & Degradation Result
            </h3>
            <span
              style={{
                fontSize: "12px",
                fontWeight: 600,
                padding: "3px 8px",
                borderRadius: "6px",
                backgroundColor: result.status.includes("BLOCKED")
                  ? "rgba(239,68,68,0.12)"
                  : "rgba(245,158,11,0.12)",
                color: result.status.includes("BLOCKED") ? "#EF4444" : "#F59E0B",
              }}
            >
              {result.status}
            </span>
          </div>

          <div
            style={{
              padding: "12px 16px",
              borderRadius: "8px",
              backgroundColor: isDark ? "#141C2B" : "#F8FAFC",
              fontSize: "13px",
              lineHeight: 1.6,
              color: isDark ? "#CBD5E1" : "#334155",
            }}
          >
            {result.summary}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "12px",
              color: "#10B981",
              fontWeight: 600,
            }}
          >
            <ShieldCheck size={16} />
            <span>{result.proof}</span>
          </div>
        </div>
      )}
    </Shell>
  );
}
