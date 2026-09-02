"use client";

/**
 * The frame every page sits in: brand, navigation, page heading, footer.
 *
 * The merchant chip and the footer say what this build actually is -- synthetic
 * data, calibrated against published aggregates. A finance console that
 * describes a seeded fixture as a "live merchant" has told its first lie before
 * the reader has read a number.
 */

import { Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useTheme } from "@/app/providers";
import { RazorMindLogo } from "@/components/RazorMindLogo";
import { Pill } from "@/components/ui";
import { MERCHANT_ID } from "@/lib/api";
import { radius, space, transition } from "@/lib/theme";
import {
  Activity,
  Database,
  History,
  LayoutDashboard,
  MessageSquare,
  Scale,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Ask", icon: MessageSquare },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/reconciliation", label: "Reconciliation", icon: Scale },
  { href: "/provenance", label: "Calibration", icon: Database },
  { href: "/history", label: "History", icon: History },
  { href: "/sandbox", label: "Sandbox", icon: Activity },
] as const;

const MAX_WIDTH = "1280px";

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
  const { t, isDark, toggle } = useTheme();

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <header
        style={{
          position: "sticky",
          top: 0,
          zIndex: 100,
          borderBottom: `1px solid ${t.border}`,
          backgroundColor: t.canvasTranslucent,
          backdropFilter: "blur(14px) saturate(160%)",
          WebkitBackdropFilter: "blur(14px) saturate(160%)",
        }}
      >
        <div
          style={{
            maxWidth: MAX_WIDTH,
            margin: "0 auto",
            padding: `${space(2.5)} ${space(5)}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: space(4),
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: space(3) }}>
            <Link href="/" style={{ textDecoration: "none", color: "inherit", display: "flex" }}>
              <RazorMindLogo size="medium" showTag={false} />
            </Link>
            <Pill tone="neutral" title={`Merchant ${MERCHANT_ID}`}>
              <span style={{ color: t.accent }}>Demo merchant</span>
              <span style={{ color: t.textFaint, fontWeight: 500 }}>· synthetic data</span>
            </Pill>
          </div>

          <nav style={{ display: "flex", alignItems: "center", gap: space(0.5) }}>
            {NAV_ITEMS.map((item) => {
              const active = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: space(1.5),
                    padding: `${space(1.5)} ${space(3)}`,
                    borderRadius: radius.md,
                    fontSize: "13px",
                    fontWeight: active ? 600 : 500,
                    textDecoration: "none",
                    color: active ? t.accent : t.textMuted,
                    backgroundColor: active ? t.accentSoft : "transparent",
                    transition: `color ${transition.fast}, background-color ${transition.fast}`,
                  }}
                >
                  <Icon size={15} strokeWidth={active ? 2.4 : 2} />
                  <span>{item.label}</span>
                </Link>
              );
            })}

            <button
              type="button"
              onClick={toggle}
              aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
              title={`Switch to ${isDark ? "light" : "dark"} mode`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: "34px",
                height: "34px",
                marginLeft: space(2),
                borderRadius: radius.md,
                border: `1px solid ${t.border}`,
                backgroundColor: "transparent",
                color: t.textMuted,
                cursor: "pointer",
                transition: `color ${transition.fast}, border-color ${transition.fast}`,
              }}
            >
              {isDark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </div>
      </header>

      <main
        style={{
          maxWidth: MAX_WIDTH,
          width: "100%",
          margin: "0 auto",
          padding: `${space(8)} ${space(5)} ${space(16)}`,
          display: "flex",
          flexDirection: "column",
          gap: space(6),
          flex: 1,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-end",
            flexWrap: "wrap",
            gap: space(4),
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: space(1.5) }}>
            <h1
              style={{
                margin: 0,
                fontSize: "26px",
                fontWeight: 680,
                letterSpacing: "-0.025em",
                color: t.text,
                lineHeight: 1.15,
              }}
            >
              {title}
            </h1>
            {subtitle ? (
              <p
                style={{
                  margin: 0,
                  fontSize: "14px",
                  lineHeight: 1.55,
                  color: t.textMuted,
                  maxWidth: "72ch",
                }}
              >
                {subtitle}
              </p>
            ) : null}
          </div>
          {action}
        </div>

        {children}
      </main>

      <footer
        style={{
          borderTop: `1px solid ${t.border}`,
          padding: `${space(5)} ${space(5)}`,
        }}
      >
        <div
          style={{
            maxWidth: MAX_WIDTH,
            margin: "0 auto",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: space(3),
            flexWrap: "wrap",
            fontSize: "12px",
            color: t.textFaint,
          }}
        >
          <span>RazorMind · synthetic data calibrated against published aggregates</span>
          <span style={{ display: "flex", alignItems: "center", gap: space(1.5) }}>
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: radius.pill,
                backgroundColor: t.positive,
              }}
            />
            No model computes a number — enforced at build time by import-linter
          </span>
        </div>
      </footer>
    </div>
  );
}
