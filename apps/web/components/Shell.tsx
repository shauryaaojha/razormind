"use client";

/** The frame every page sits in. Nothing here knows anything about money. */

import { Box, Heading, Link, Text } from "@razorpay/blade/components";
import type { ReactNode } from "react";

const PAGES = [
  { href: "/", label: "Ask" },
  { href: "/reconciliation", label: "Reconciliation" },
  { href: "/history", label: "History" },
] as const;

export function Shell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Box
      display="flex"
      flexDirection="column"
      gap="spacing.6"
      padding={["spacing.7", "spacing.6"]}
      maxWidth="1024px"
      margin="auto"
    >
      <Box display="flex" flexDirection="column" gap="spacing.3">
        <Box display="flex" alignItems="baseline" gap="spacing.5" flexWrap="wrap">
          <Heading size="large">RazorMind</Heading>
          {PAGES.map((page) => (
            <Link key={page.href} href={page.href} size="small">
              {page.label}
            </Link>
          ))}
        </Box>
        <Box display="flex" flexDirection="column">
          <Heading size="medium">{title}</Heading>
          {subtitle ? (
            <Text size="small" color="surface.text.gray.muted">
              {subtitle}
            </Text>
          ) : null}
        </Box>
      </Box>
      {children}
    </Box>
  );
}
