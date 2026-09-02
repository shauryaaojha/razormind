import "@razorpay/blade/fonts.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { Providers, ThemeScript } from "./providers";

export const metadata: Metadata = {
  title: "RazorMind",
  description:
    "AI controls the investigation. Deterministic systems control the numbers. Evidence controls trust.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // `suppressHydrationWarning` because ThemeScript writes `data-scheme` on
    // this element before React hydrates, which is the entire point of it.
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body style={{ margin: 0 }}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
