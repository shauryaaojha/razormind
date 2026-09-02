"use client";

import { Badge, Box, Button, Heading, Text } from "@razorpay/blade/components";
import {
  Activity,
  AlertCircle,
  Database,
  History,
  LayoutDashboard,
  MessageSquare,
  Moon,
  Scale,
  ShieldCheck,
  Sun,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAppTheme } from "@/app/providers";
import { RazorMindLogo } from "@/components/RazorMindLogo";

const NAV_ITEMS = [
  { href: "/", label: "AI Studio", icon: MessageSquare },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/reconciliation", label: "Reconciliation", icon: Scale },
  { href: "/provenance", label: "Data Calibration", icon: Database },
  { href: "/history", label: "Audit History", icon: History },
  { href: "/sandbox", label: "Chaos Sandbox", icon: Activity },
] as const;

export function Shell({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  const pathname = usePathname();
  const { isDark, toggleTheme } = useAppTheme();

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        minHeight: "100vh",
      }}
    >
      {/* Top Navbar */}
      <header
        style={{
          borderBottom: `1px solid ${isDark ? "rgba(255, 255, 255, 0.08)" : "rgba(0, 0, 0, 0.08)"}`,
          backgroundColor: isDark ? "rgba(10, 14, 23, 0.85)" : "rgba(255, 255, 255, 0.85)",
          backdropFilter: "blur(12px)",
          position: "sticky",
          top: 0,
          zIndex: 100,
          padding: "12px 24px",
        }}
      >
        <div
          style={{
            maxWidth: "1280px",
            margin: "0 auto",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "16px",
          }}
        >
          {/* Brand & Context */}
          <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
            <Link href="/" style={{ textDecoration: "none", color: "inherit" }}>
              <RazorMindLogo size="medium" />
            </Link>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                padding: "4px 10px",
                borderRadius: "20px",
                backgroundColor: isDark ? "rgba(255, 255, 255, 0.05)" : "rgba(0, 0, 0, 0.04)",
                border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.1)" : "rgba(0, 0, 0, 0.08)"}`,
                fontSize: "12px",
                fontFamily: "Inter, sans-serif",
              }}
            >
              <span style={{ fontWeight: 600, color: "#0C83FF" }}>M123</span>
              <span style={{ opacity: 0.5 }}>·</span>
              <span style={{ color: isDark ? "#94A3B8" : "#64748B" }}>Razorpay Live Merchant</span>
            </div>

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                fontSize: "11px",
                fontWeight: 600,
                color: "#10B981",
                backgroundColor: "rgba(16, 185, 129, 0.1)",
                padding: "3px 8px",
                borderRadius: "12px",
                border: "1px solid rgba(16, 185, 129, 0.25)",
              }}
            >
              <ShieldCheck size={13} />
              <span>5-LAYER VERIFIED</span>
            </div>
          </div>

          {/* Nav items */}
          <nav style={{ display: "flex", alignItems: "center", gap: "4px" }}>
            {NAV_ITEMS.map((item) => {
              const active = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                    padding: "6px 12px",
                    borderRadius: "8px",
                    fontSize: "13px",
                    fontWeight: active ? 600 : 500,
                    textDecoration: "none",
                    color: active
                      ? "#0C83FF"
                      : isDark
                        ? "#94A3B8"
                        : "#475569",
                    backgroundColor: active
                      ? isDark
                        ? "rgba(12, 131, 255, 0.12)"
                        : "rgba(12, 131, 255, 0.08)"
                      : "transparent",
                    transition: "all 0.15s ease",
                  }}
                >
                  <Icon size={15} />
                  <span>{item.label}</span>
                </Link>
              );
            })}

            {/* Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              title={`Switch to ${isDark ? "Light" : "Dark"} Mode`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "36px",
                height: "36px",
                borderRadius: "8px",
                border: `1px solid ${isDark ? "rgba(255, 255, 255, 0.12)" : "rgba(0, 0, 0, 0.12)"}`,
                backgroundColor: isDark ? "rgba(255, 255, 255, 0.04)" : "rgba(0, 0, 0, 0.03)",
                color: isDark ? "#F1F5F9" : "#1E293B",
                cursor: "pointer",
                marginLeft: "8px",
                transition: "all 0.2s ease",
              }}
            >
              {isDark ? <Sun size={17} color="#F59E0B" /> : <Moon size={17} color="#0C83FF" />}
            </button>
          </nav>
        </div>
      </header>

      {/* Main Page Container */}
      <main
        style={{
          maxWidth: "1280px",
          width: "100%",
          margin: "0 auto",
          padding: "24px 20px 60px 20px",
          display: "flex",
          flexDirection: "column",
          gap: "24px",
          flex: 1,
        }}
      >
        {/* Page Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            flexWrap: "wrap",
            gap: "16px",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            <h1
              style={{
                margin: 0,
                fontSize: "24px",
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: isDark ? "#F8FAFC" : "#0F172A",
              }}
            >
              {title}
            </h1>
            {subtitle && (
              <p
                style={{
                  margin: 0,
                  fontSize: "14px",
                  color: isDark ? "#94A3B8" : "#64748B",
                  maxWidth: "780px",
                  lineHeight: 1.5,
                }}
              >
                {subtitle}
              </p>
            )}
          </div>
          {action && <div>{action}</div>}
        </div>

        {children}
      </main>

      {/* Footer */}
      <footer
        style={{
          borderTop: `1px solid ${isDark ? "rgba(255, 255, 255, 0.06)" : "rgba(0, 0, 0, 0.06)"}`,
          padding: "16px 24px",
          textAlign: "center",
          fontSize: "12px",
          color: isDark ? "#64748B" : "#94A3B8",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: "16px",
          flexWrap: "wrap",
        }}
      >
        <span>
          RazorMind <strong>v1.0</strong> · Deterministic Financial Intelligence
        </span>
        <span>·</span>
        <span>NPCI/RBI Calibrated Synthetic Seed</span>
        <span>·</span>
        <span style={{ color: "#10B981" }}>No LLM Touches Arithmetic (Enforced by Import Linter)</span>
      </footer>
    </div>
  );
}
