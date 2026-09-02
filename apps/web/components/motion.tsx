"use client";

/**
 * The four animations the trace uses, defined once.
 *
 * Inline `style` cannot express a keyframe, and the alternative -- a library,
 * or a styled-component per animated element -- would put motion in ten files
 * and let them drift. They are here, together, so that "what moves in this app"
 * is a list somebody can read.
 *
 * Every one of them is *reporting*, not decoration: a pulse means a node is
 * running right now, a flowing edge means a value is on its way between two
 * tools, a rise means a row just arrived. Nothing animates to fill time, which
 * matters more here than in most interfaces -- a progress animation on a run
 * that has stalled is a lie told by a spinner.
 *
 * The whole sheet is suspended under `prefers-reduced-motion`. Everything the
 * motion says is also said by a colour and a word, so nothing is lost.
 */

export const MOTION_CSS = `
@keyframes rm-pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--rm-pulse); }
  50%      { box-shadow: 0 0 0 6px transparent; }
}
@keyframes rm-flow {
  to { stroke-dashoffset: -14; }
}
@keyframes rm-rise {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: none; }
}
@keyframes rm-sweep {
  from { transform: translateX(-100%); }
  to   { transform: translateX(300%); }
}
@media (prefers-reduced-motion: reduce) {
  .rm-pulse, .rm-flow, .rm-rise, .rm-sweep { animation: none !important; }
}
`;

/** Mount once per screen that animates. Duplicated rules are harmless. */
export function Motion() {
  return <style>{MOTION_CSS}</style>;
}
