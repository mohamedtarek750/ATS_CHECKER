"use client";

import { useEffect, useState } from "react";

/**
 * The ACUD mark.
 *
 * Shows the real logo when one has been placed at /acud-logo.png, and a
 * wordmark in the house colours when it has not. Deliberately not hot-linked
 * from acud.eg: an image served from somebody else's site breaks the day they
 * move it, and their logo file is theirs to place. Drop acud-logo.png into
 * public/ and it appears in every header.
 *
 * The wordmark is what renders first, and the image only replaces it once it
 * has actually loaded. The obvious way round - render the <img> and swap on
 * its onError - puts a broken-image icon in every header on this project,
 * because the request fails before React has hydrated and attached the
 * handler, so the error never reaches it.
 */
export function AcudMark({ subtitle }: { subtitle?: string }) {
  const [logo, setLogo] = useState<string | null>(null);

  useEffect(() => {
    const probe = new Image();
    probe.onload = () => setLogo("/acud-logo.png");
    probe.src = "/acud-logo.png";
    return () => {
      probe.onload = null;
    };
  }, []);

  return (
    <div className="flex min-w-0 items-center gap-2.5">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="ACUD" className="h-9 w-auto shrink-0" />
      ) : (
        <span
          className="shrink-0 border-b-2 pb-0.5 text-[17px] font-bold leading-none tracking-[0.18em]"
          style={{ borderColor: "rgb(var(--gold))" }}
        >
          ACUD
        </span>
      )}

      <span className="min-w-0">
        <span className="block truncate text-[13px] font-semibold leading-tight">
          Recruitment
        </span>
        <span className="block truncate text-[11px] leading-tight text-muted">
          {subtitle ?? "Administrative Capital for Urban Development"}
        </span>
      </span>
    </div>
  );
}
