"use client";

/**
 * A button that looks like nothing.
 *
 * Blade's `Box` is a layout primitive and deliberately will not become a
 * `<button>` — a container that could silently be interactive is how a div ends
 * up with a click handler and no keyboard access. So the button is a real one,
 * stripped of its own appearance, and everything visible inside it is still
 * Blade.
 *
 * That keeps two things true at once: a metric tile is reachable by Tab and
 * announced as a button, and it carries no colour, radius or spacing this
 * project invented.
 */

import type { ReactNode } from "react";

const RESET = {
  background: "none",
  border: 0,
  padding: 0,
  margin: 0,
  font: "inherit",
  color: "inherit",
  textAlign: "left",
  cursor: "pointer",
  display: "block",
  width: "100%",
} as const;

export function Clickable({
  onClick,
  label,
  children,
  ...rest
}: {
  onClick: () => void;
  label: string;
  children: ReactNode;
} & Record<`data-${string}`, string | undefined>) {
  return (
    <button type="button" onClick={onClick} aria-label={label} style={RESET} {...rest}>
      {children}
    </button>
  );
}
