"use client";

/**
 * Blade, wired once.
 *
 * The whole interface is Razorpay's own design system: `bladeTheme` tokens,
 * Blade components, Blade spacing. Nothing here defines a colour, a radius or a
 * font size of its own, and that is deliberate — a finance console that invents
 * its own visual language is one more thing a reader has to learn before they
 * can trust what it says.
 */

import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import type { ReactNode } from "react";

import { StyledComponentsRegistry } from "./registry";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <StyledComponentsRegistry>
      <BladeProvider themeTokens={bladeTheme} colorScheme="light">
        {children}
      </BladeProvider>
    </StyledComponentsRegistry>
  );
}
