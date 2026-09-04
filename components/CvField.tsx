"use client";

import { useRef, useState } from "react";

const ACCEPT = ".pdf,.docx,.doc,.txt,.md,.rtf";
const MAX_BYTES = 8 * 1024 * 1024;

/**
 * Choosing a CV.
 *
 * The browser's own file input is the one control on the applicant's page that
 * cannot be styled, and next to everything else it reads as unfinished - on the
 * only screen a candidate ever sees. This is the same input, kept for keyboard
 * and screen-reader behaviour, with a label drawn over it and the real one
 * hidden.
 *
 * It also takes a drop, and says the file's name and size once chosen, because
 * "No file chosen" next to a Send button is the moment somebody submits an
 * empty form.
 */
export function CvField({
  file,
  onFile,
}: {
  file: File | null;
  onFile: (file: File | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [tooBig, setTooBig] = useState(false);

  function take(chosen: File | null) {
    if (chosen && chosen.size > MAX_BYTES) {
      setTooBig(true);
      onFile(null);
      return;
    }
    setTooBig(false);
    onFile(chosen);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files?.[0] ?? null);
        }}
        onClick={() => input.current?.click()}
        className={`flex cursor-pointer items-center gap-3 rounded-lg border border-dashed px-4 py-4 transition ${
          over ? "border-brand bg-brand-wash" : "raised hover:border-muted/60"
        }`}
      >
        <span
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-lg"
          style={{
            background: file ? "rgb(var(--good-wash))" : "rgb(var(--surface))",
            color: file ? "rgb(var(--good))" : "rgb(var(--muted))",
          }}
          aria-hidden
        >
          {file ? "✓" : "↑"}
        </span>

        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {file ? file.name : "Choose your CV, or drop it here"}
          </span>
          <span className="mt-0.5 block text-xs text-muted">
            {file
              ? `${(file.size / 1024).toFixed(0)} KB · click to change`
              : "PDF, DOCX, TXT, MD or RTF · up to 8 MB"}
          </span>
        </span>
      </div>

      {/* The real control. Hidden from view, not from assistive technology or
          the keyboard - `display: none` would take it out of the tab order. */}
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        required={!file}
        onChange={(e) => take(e.target.files?.[0] ?? null)}
        className="sr-only"
        aria-label="Your CV"
      />

      {tooBig && (
        <p className="mt-2 text-xs text-bad">
          That file is over 8 MB. Send a smaller one — a CV rarely needs more.
        </p>
      )}
    </div>
  );
}
