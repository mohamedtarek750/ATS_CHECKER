"use client";

import { useEffect, useState } from "react";

/**
 * The ACUD mark: their own logo file, served from this app.
 *
 * public/acud-logo.png is the real artwork - black and #ED1C24 red on a
 * transparent ground. It is served from here rather than hot-linked from
 * acud.eg, which refuses automated requests anyway and would break the day
 * they move the file.
 *
 * The wordmark below is a fallback for a deployment where the file is missing,
 * and it renders FIRST, with the image swapping in only once it has actually
 * loaded. The obvious way round - an <img> with onError - put a broken-image
 * icon in every header, because the request fails before React has hydrated
 * and the handler never sees the error.
 *
 * The logo already carries the organisation's full name, in English and in
 * Arabic, so the text beside it says only which part of the system this is.
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
    <div className="flex min-w-0 items-center gap-3">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logo}
          alt="Administrative Capital for Urban Development"
          className="h-10 w-auto shrink-0"
        />
      ) : (
        <span className="shrink-0 text-[19px] font-bold leading-none tracking-[0.12em]">
          AC<span className="text-brand">U</span>D
        </span>
      )}

      {subtitle && (
        <>
          <span
            className="h-7 w-px shrink-0"
            style={{ background: "rgb(var(--line))" }}
            aria-hidden
          />
          <span className="min-w-0 truncate text-[13px] font-medium text-muted">
            {subtitle}
          </span>
        </>
      )}
    </div>
  );
}
