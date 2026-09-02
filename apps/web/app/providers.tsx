"use client";

/**
 * Theme state, and the tokens every component reads from.
 *
 * `useTheme()` returns the resolved palette rather than a boolean, so a
 * component never re-decides what "muted text in dark mode" is. The boolean is
 * still exposed for the few places that genuinely branch on scheme (an
 * illustration, an image asset), not for picking colours.
 */

import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import type { ReactNode } from "react";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { AnimatedBackground } from "@/components/AnimatedBackground";
import { PALETTES, type Palette, type Scheme } from "@/lib/theme";
import { StyledComponentsRegistry } from "./registry";

export const STORAGE_KEY = "razormind-theme";
const DEFAULT_SCHEME: Scheme = "dark";

interface ThemeContextValue {
  scheme: Scheme;
  /** The resolved palette. This is what components should read. */
  t: Palette;
  isDark: boolean;
  toggle: () => void;
  setScheme: (scheme: Scheme) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  scheme: DEFAULT_SCHEME,
  t: PALETTES[DEFAULT_SCHEME],
  isDark: true,
  toggle: () => undefined,
  setScheme: () => undefined,
});

/** The palette and the scheme. Prefer `t` over `isDark` for anything visual. */
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

/** @deprecated Kept so older call sites keep compiling. Use `useTheme`. */
export const useAppTheme = useTheme;

/**
 * Paints the saved background before React hydrates.
 *
 * Without this a light-mode reader gets a black page for one frame on every
 * navigation, because the server has no way to know the preference and React
 * can only correct it after mount. Only the two colours that cover the whole
 * viewport are set here -- everything else arrives with the first render, where
 * it is invisible.
 */
const PRE_PAINT = `(function(){try{
var s=localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
if(s!=="light"&&s!=="dark")s=${JSON.stringify(DEFAULT_SCHEME)};
var p=${JSON.stringify({ dark: PALETTES.dark, light: PALETTES.light })}[s];
var d=document.documentElement;
d.dataset.scheme=s;d.style.backgroundColor=p.canvas;d.style.colorScheme=s;
}catch(e){}})();`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: PRE_PAINT }} />;
}

export function Providers({ children }: { children: ReactNode }) {
  const [scheme, setSchemeState] = useState<Scheme>(DEFAULT_SCHEME);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark") setSchemeState(saved);
  }, []);

  const setScheme = useCallback((next: Scheme) => {
    setSchemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // A private window with storage blocked still gets a working toggle;
      // it just does not survive the next navigation.
    }
    const root = document.documentElement;
    root.dataset.scheme = next;
    root.style.backgroundColor = PALETTES[next].canvas;
    root.style.colorScheme = next;
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({
      scheme,
      t: PALETTES[scheme],
      isDark: scheme === "dark",
      toggle: () => setScheme(scheme === "dark" ? "light" : "dark"),
      setScheme,
    }),
    [scheme, setScheme],
  );

  return (
    <ThemeContext.Provider value={value}>
      <StyledComponentsRegistry>
        <BladeProvider themeTokens={bladeTheme} colorScheme={scheme}>
          <div
            style={{
              minHeight: "100vh",
              backgroundColor: value.t.canvas,
              color: value.t.text,
              position: "relative",
            }}
          >
            {mounted && <AnimatedBackground isDark={value.isDark} />}
            <div style={{ position: "relative", zIndex: 1 }}>{children}</div>
          </div>
        </BladeProvider>
      </StyledComponentsRegistry>
    </ThemeContext.Provider>
  );
}
