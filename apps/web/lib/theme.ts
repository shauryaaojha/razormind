/**
 * The one place a colour, a radius, a spacing step or a shadow is decided.
 *
 * Before this file the app held 273 literal hex values and 125 `isDark ? a : b`
 * ternaries, which is not a theme -- it is 125 independent decisions about what
 * "muted text" means, and they had already drifted apart. Nothing outside this
 * file should contain a `#`.
 *
 * **Every colour below is Blade's**, read from `@razorpay/blade/tokens` rather
 * than copied out of the design file. The Figma library and this package are
 * two renderings of one palette, and a hex typed in here from the first would
 * be a third -- correct on the day it was typed and quietly wrong after the
 * next brand refresh. Blade already owns the components; this file is the
 * mapping from Blade's palette onto the surfaces those components sit on --
 * the page background, the card, the border, the eight status tints -- which
 * Blade has no opinion about because they are the application's, not the design
 * system's.
 *
 * The mapping is written out per scheme instead of by token name, because
 * Blade's grey ramp is not ordered the same way in both: on light, `intense` is
 * white and belongs to a card, while on dark it is the lightest grey and
 * belongs to a hover. Naming the role on each side is what keeps a token that
 * reads correctly in one scheme from being invisible in the other.
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

import { bladeTheme, elevation } from "@razorpay/blade/tokens";

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

const DARK_TOKENS = bladeTheme.colors.onDark;
const LIGHT_TOKENS = bladeTheme.colors.onLight;

/**
 * The same colour at a different opacity.
 *
 * Blade publishes `hsla(...)` strings, so a translucent variant is the token
 * with its last component replaced -- not a second colour that has to be kept
 * in step with the first by hand.
 */
function alpha(hsla: string, opacity: number): string {
  return hsla.replace(/,\s*[\d.]+\)$/, `, ${opacity})`);
}

const DARK: Palette = {
  canvas: DARK_TOKENS.surface.background.gray.moderate,
  canvasTranslucent: alpha(DARK_TOKENS.surface.background.gray.moderate, 0.82),
  surface: DARK_TOKENS.surface.background.gray.subtle,
  surfaceHover: DARK_TOKENS.surface.background.gray.intense,
  // One step *below* the card rather than above it, which on a dark scheme is
  // the page's own colour.
  sunken: DARK_TOKENS.surface.background.gray.moderate,

  border: DARK_TOKENS.surface.border.gray.subtle,
  borderStrong: DARK_TOKENS.surface.border.gray.normal,

  text: DARK_TOKENS.surface.text.gray.normal,
  textMuted: DARK_TOKENS.surface.text.gray.subtle,
  textFaint: DARK_TOKENS.surface.text.gray.muted,
  textOnAccent: DARK_TOKENS.surface.text.staticWhite.normal,

  accent: DARK_TOKENS.interactive.background.primary.default,
  accentHover: DARK_TOKENS.interactive.text.primary.normal,
  accentSoft: DARK_TOKENS.interactive.background.primary.faded,
  accentBorder: DARK_TOKENS.interactive.background.primary.fadedHighlighted,

  positive: DARK_TOKENS.feedback.text.positive.intense,
  positiveSoft: DARK_TOKENS.feedback.background.positive.subtle,
  negative: DARK_TOKENS.feedback.text.negative.intense,
  negativeSoft: DARK_TOKENS.feedback.background.negative.subtle,
  warning: DARK_TOKENS.feedback.text.notice.intense,
  warningSoft: DARK_TOKENS.feedback.background.notice.subtle,
  info: DARK_TOKENS.feedback.text.information.intense,
  infoSoft: DARK_TOKENS.feedback.background.information.subtle,

  shadow: elevation.onDark.lowRaised,
  shadowRaised: elevation.onDark.highRaised,
  shadowAccent: `0 2px 12px -2px ${alpha(
    DARK_TOKENS.interactive.background.primary.default,
    0.45,
  )}`,
};

const LIGHT: Palette = {
  canvas: LIGHT_TOKENS.surface.background.gray.subtle,
  canvasTranslucent: alpha(LIGHT_TOKENS.surface.background.gray.subtle, 0.82),
  // White, so a card lifts off the grey page. The dark scheme's ordering is the
  // other way round, which is why these are written per scheme.
  surface: LIGHT_TOKENS.surface.background.gray.intense,
  surfaceHover: LIGHT_TOKENS.feedback.background.neutral.subtle,
  sunken: LIGHT_TOKENS.surface.background.gray.moderate,

  border: LIGHT_TOKENS.surface.border.gray.subtle,
  borderStrong: LIGHT_TOKENS.surface.border.gray.normal,

  text: LIGHT_TOKENS.surface.text.gray.normal,
  textMuted: LIGHT_TOKENS.surface.text.gray.muted,
  textFaint: LIGHT_TOKENS.surface.text.gray.disabled,
  textOnAccent: LIGHT_TOKENS.surface.text.staticWhite.normal,

  // The *text* primary on light, not the background one: this colour is read as
  // often as it is pressed, and the background token is a shade too bright to
  // sit under body copy.
  accent: LIGHT_TOKENS.interactive.text.primary.normal,
  accentHover: LIGHT_TOKENS.interactive.background.primary.default,
  accentSoft: LIGHT_TOKENS.interactive.background.primary.faded,
  accentBorder: LIGHT_TOKENS.interactive.background.primary.fadedHighlighted,

  positive: LIGHT_TOKENS.feedback.text.positive.intense,
  positiveSoft: LIGHT_TOKENS.feedback.background.positive.subtle,
  negative: LIGHT_TOKENS.feedback.text.negative.intense,
  negativeSoft: LIGHT_TOKENS.feedback.background.negative.subtle,
  warning: LIGHT_TOKENS.feedback.text.notice.intense,
  warningSoft: LIGHT_TOKENS.feedback.background.notice.subtle,
  info: LIGHT_TOKENS.feedback.text.information.intense,
  infoSoft: LIGHT_TOKENS.feedback.background.information.subtle,

  shadow: elevation.onLight.lowRaised,
  shadowRaised: elevation.onLight.highRaised,
  shadowAccent: `0 2px 12px -2px ${alpha(
    LIGHT_TOKENS.interactive.background.primary.default,
    0.35,
  )}`,
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
