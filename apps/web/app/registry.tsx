"use client";

/**
 * styled-components' server-side stylesheet, collected into the streamed HTML.
 *
 * Blade is built on styled-components v5, which generates its CSS at render
 * time. Without this the server renders correct markup with no styles, the
 * browser hydrates and applies them, and the page flashes unstyled — on a
 * dashboard of financial figures, a layout that jumps after paint reads as a
 * page that is still loading numbers.
 *
 * This is the pattern Next documents for the App Router: collect into a sheet
 * during render, flush it through `useServerInsertedHTML`, and hand the
 * children through untouched on the client.
 */

import { useServerInsertedHTML } from "next/navigation";
import { useState, type ReactNode } from "react";
import { ServerStyleSheet, StyleSheetManager } from "styled-components";

export function StyledComponentsRegistry({ children }: { children: ReactNode }) {
  // useState with an initialiser so the sheet is created once per render pass
  // rather than on every re-render.
  const [sheet] = useState(() => new ServerStyleSheet());

  useServerInsertedHTML(() => {
    const styles = sheet.getStyleElement();
    // Clearing the tag is what stops the same rules being emitted again on the
    // next flush of a streamed response.
    sheet.instance.clearTag();
    return <>{styles}</>;
  });

  if (typeof window !== "undefined") {
    return <>{children}</>;
  }

  return (
    <StyleSheetManager sheet={sheet.instance}>{children}</StyleSheetManager>
  );
}
