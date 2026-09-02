/**
 * The one place a colour, a radius, a spacing step or a shadow is decided.
 *
 * Before this file the app held 273 literal hex values and 125 `isDark ? a : b`
 * ternaries, which is not a theme -- it is 125 independent decisions about what
 * "muted text" means, and they had already drifted apart. Nothing below
 * `useTokens()` should contain a `#`.
 *
 * Blade still owns the *components*. This owns the surface they sit on: the
 * page background, the card, the border, the eight status tints, and the
 * numeric type treatment. Blade has no opinion about those because they are the
 * application's, not the design system's.
 *
 * Two rules for anything added here:
 *
 * * **Semantic, not descriptive.** `border` and `textMuted`, never `slate700`.
 *   A name that describes the colour has to be renamed when the colour changes,
 *   so in practice it never changes.
 * * **Both schemes, together.** Every token is defined once for dark and once
 *   for light on adjacent lines, so a token that looks right in one and
 *   invisible in the other is visible here rather than in a screenshot.
 */

export type Scheme = "dark" | "light";

export interface Palette {
  /** The page itself. */
  canvas: string;
  /** The same, see-through, for a sticky bar that blurs what scrolls under it. */
  canvasTranslucent: string;
  /** A card, a panel, a row -- one step up from the canvas. */
  surface: string;
  /** The same, under the cursor. */
  surfaceHover: string;
  /** Pressed *into* the surface: code, evidence ids, formula strings. */
  sunken: string;

  border: string;
  /** For a divider that has to be seen rather than felt. */
  borderStrong: string;

  /** Body copy and figures. */
  text: string;
  /** Labels, captions, secondary detail. */
  textMuted: string;
  /** Present but not competing: units, timestamps, ids. */
  textFaint: string;
  /** On top of `accent`, `positive`, `negative` -- always readable. */
  textOnAccent: string;

  accent: string;
  accentHover: string;
  /** A tint of the accent, for a selected nav item or an active pill. */
  accentSoft: string;
  accentBorder: string;

  positive: string;
  positiveSoft: string;
  negative: string;
  negativeSoft: string;
  warning: string;
  warningSoft: string;
  info: string;
  infoSoft: string;

  /** Resting elevation for a card. */
  shadow: string;
  /** A drawer, a popover -- something that floats over the page. */
  shadowRaised: string;
  /** The accent's own glow, for the one primary button on a screen. */
  shadowAccent: string;
}

const RAZORPAY_BLUE = "#0C83FF";

const DARK: Palette = {
  canvas: "#080B11",
  canvasTranslucent: "rgba(8, 11, 17, 0.82)",
  surface: "#0E131F",
  surfaceHover: "#141C2B",
  sunken: "#070A10",

  border: "#1C2434",
  borderStrong: "#2A3547",

  text: "#F1F5F9",
  textMuted: "#94A3B8",
  textFaint: "#64748B",
  textOnAccent: "#FFFFFF",

  accent: RAZORPAY_BLUE,
  accentHover: "#3D9BFF",
  accentSoft: "rgba(12, 131, 255, 0.13)",
  accentBorder: "rgba(12, 131, 255, 0.32)",

  positive: "#34D399",
  positiveSoft: "rgba(52, 211, 153, 0.12)",
  negative: "#F87171",
  negativeSoft: "rgba(248, 113, 113, 0.12)",
  warning: "#FBBF24",
  warningSoft: "rgba(251, 191, 36, 0.12)",
  info: "#60A5FA",
  infoSoft: "rgba(96, 165, 250, 0.12)",

  shadow: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)",
  shadowRaised: "0 8px 40px -8px rgba(0,0,0,0.7)",
  shadowAccent: "0 2px 12px -2px rgba(12, 131, 255, 0.45)",
};

const LIGHT: Palette = {
  canvas: "#F7F9FC",
  canvasTranslucent: "rgba(247, 249, 252, 0.82)",
  surface: "#FFFFFF",
  surfaceHover: "#F1F5F9",
  sunken: "#F1F5F9",

  border: "#E3E8EF",
  borderStrong: "#CBD5E1",

  text: "#0F172A",
  textMuted: "#5A6B85",
  textFaint: "#8695AB",
  textOnAccent: "#FFFFFF",

  accent: "#0A6FD8",
  accentHover: "#0C83FF",
  accentSoft: "rgba(12, 131, 255, 0.09)",
  accentBorder: "rgba(12, 131, 255, 0.28)",

  // Darker than the dark scheme's: these sit on white and have to pass as text.
  positive: "#047857",
  positiveSoft: "rgba(4, 120, 87, 0.09)",
  negative: "#BE123C",
  negativeSoft: "rgba(190, 18, 60, 0.08)",
  warning: "#B45309",
  warningSoft: "rgba(180, 83, 9, 0.10)",
  info: "#1D4ED8",
  infoSoft: "rgba(29, 78, 216, 0.08)",

  shadow: "0 1px 2px rgba(15,23,42,0.04), 0 8px 24px -16px rgba(15,23,42,0.16)",
  shadowRaised: "0 12px 48px -12px rgba(15,23,42,0.22)",
  shadowAccent: "0 2px 12px -2px rgba(12, 131, 255, 0.35)",
};

export const PALETTES: Record<Scheme, Palette> = { dark: DARK, light: LIGHT };

/**
 * A 4px grid. `space(3)` rather than `"12px"` so a layout cannot drift to 13.
 */
export const space = (steps: number): string => `${steps * 4}px`;

export const radius = {
  sm: "6px",
  md: "10px",
  lg: "14px",
  xl: "20px",
  pill: "999px",
} as const;

export const font = {
  sans: '"Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  mono: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
} as const;

/**
 * Figures are tabular, everywhere, without exception.
 *
 * Proportional digits make a column of rupee amounts ragged, and a reader
 * comparing two numbers in a finance console is doing it by eye down a column.
 * This is the cheapest correctness-adjacent thing in the whole interface.
 */
export const numeric = {
  fontVariantNumeric: "tabular-nums",
  fontFeatureSettings: '"tnum" 1',
} as const;

export const transition = {
  fast: "120ms cubic-bezier(0.4, 0, 0.2, 1)",
  base: "200ms cubic-bezier(0.4, 0, 0.2, 1)",
} as const;

/** Semantic status, mapped once, so a badge and a bar cannot disagree. */
export type Tone = "positive" | "negative" | "warning" | "info" | "neutral" | "accent";

export function toneColors(palette: Palette, tone: Tone): { fg: string; bg: string } {
  switch (tone) {
    case "positive":
      return { fg: palette.positive, bg: palette.positiveSoft };
    case "negative":
      return { fg: palette.negative, bg: palette.negativeSoft };
    case "warning":
      return { fg: palette.warning, bg: palette.warningSoft };
    case "info":
      return { fg: palette.info, bg: palette.infoSoft };
    case "accent":
      return { fg: palette.accent, bg: palette.accentSoft };
    case "neutral":
      return { fg: palette.textMuted, bg: palette.surfaceHover };
  }
}
