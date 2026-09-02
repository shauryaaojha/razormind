"use client";

import { BladeProvider } from "@razorpay/blade/components";
import { bladeTheme } from "@razorpay/blade/tokens";
import type { ReactNode } from "react";
import React, { createContext, useContext, useEffect, useState } from "react";

import { AnimatedBackground } from "@/components/AnimatedBackground";
import { StyledComponentsRegistry } from "./registry";

type ColorScheme = "dark" | "light";

interface ThemeContextType {
  colorScheme: ColorScheme;
  toggleTheme: () => void;
  setTheme: (theme: ColorScheme) => void;
  isDark: boolean;
}

const ThemeContext = createContext<ThemeContextType>({
  colorScheme: "dark",
  toggleTheme: () => undefined,
  setTheme: () => undefined,
  isDark: true,
});

export function useAppTheme() {
  return useContext(ThemeContext);
}

export function Providers({ children }: { children: ReactNode }) {
  const [colorScheme, setColorScheme] = useState<ColorScheme>("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem("razormind-theme") as ColorScheme | null;
    if (saved === "light" || saved === "dark") {
      setColorScheme(saved);
    }
  }, []);

  const setTheme = (scheme: ColorScheme) => {
    setColorScheme(scheme);
    localStorage.setItem("razormind-theme", scheme);
  };

  const toggleTheme = () => {
    setTheme(colorScheme === "dark" ? "light" : "dark");
  };

  const isDark = colorScheme === "dark";

  return (
    <ThemeContext.Provider value={{ colorScheme, toggleTheme, setTheme, isDark }}>
      <StyledComponentsRegistry>
        <BladeProvider themeTokens={bladeTheme} colorScheme={colorScheme}>
          <div
            style={{
              minHeight: "100vh",
              backgroundColor: isDark ? "#080B11" : "#F8FAFC",
              color: isDark ? "#F1F5F9" : "#0F172A",
              transition: "background-color 0.3s ease, color 0.3s ease",
              position: "relative",
            }}
          >
            {mounted && <AnimatedBackground isDark={isDark} />}
            <div style={{ position: "relative", zIndex: 1 }}>{children}</div>
          </div>
        </BladeProvider>
      </StyledComponentsRegistry>
    </ThemeContext.Provider>
  );
}
