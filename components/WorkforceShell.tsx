"use client";

/**
 * Kept as a name, not as a thing.
 *
 * Workforce planning had its own header and its own row of tabs, which made
 * "which half does this live in" a question anybody using it had to answer
 * before finding anything. There is one shell now. This re-exports it so the
 * pages that grew up calling it do not all have to be rewritten to say so.
 */

export { AppShell as WorkforceShell } from "./AppShell";

/**
 * The caveat these pages used to open with, seven times over.
 *
 * It is a line at the foot of the shell now. This stays as a no-op so the
 * pages that call it keep compiling; new pages should not.
 */
export function ForecastNote() {
  return null;
}
