"use client";

import { useRef, useState } from "react";
import { parseCV, type ParsedCV } from "@/lib/api";

export interface UploadRow {
  file: File;
  status: "waiting" | "reading" | "done" | "skipped" | "not_cv" | "failed";
  parsed?: ParsedCV;
  detail?: string;
}

const LABEL: Record<UploadRow["status"], string> = {
  waiting: "Waiting",
  reading: "Reading…",
  done: "Read",
  skipped: "Already added",
  not_cv: "Not a CV",
  failed: "Failed",
};

const TONE: Record<UploadRow["status"], string> = {
  waiting: "text-muted",
  reading: "text-ink",
  done: "text-good",
  skipped: "text-muted",
  not_cv: "text-warn",
  failed: "text-bad",
};

export default function Uploads({
  rows,
  setRows,
  provider,
}: {
  rows: UploadRow[];
  setRows: (rows: UploadRow[]) => void;
  provider: string;
}) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const input = useRef<HTMLInputElement>(null);

  function add(files: FileList | null) {
    if (!files) return;
    const existing = new Set(rows.map((r) => `${r.file.name}|${r.file.size}`));
    const fresh = Array.from(files)
      .filter((f) => !existing.has(`${f.name}|${f.size}`))
      .map((file) => ({ file, status: "waiting" as const }));
    setRows([...rows, ...fresh]);
  }

  // One CV per request. A single call for a hundred would exceed the function
  // timeout, and this way each row updates as it lands rather than the whole
  // batch appearing at the end.
  async function readAll() {
    const pending = rows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => row.status === "waiting" || row.status === "failed");
    if (!pending.length) return;

    setBusy(true);
    setProgress({ done: 0, total: pending.length });
    const next = [...rows];
    const seenKeys = new Set(
      rows.filter((r) => r.parsed).map((r) => r.parsed!.key)
    );

    for (let i = 0; i < pending.length; i++) {
      const { row, index } = pending[i];
      next[index] = { ...next[index], status: "reading" };
      setRows([...next]);

      try {
        const parsed = await parseCV(row.file, provider);
        if (seenKeys.has(parsed.key)) {
          // Same content under a different name - the same person twice.
          next[index] = { ...next[index], status: "skipped", parsed };
        } else {
          seenKeys.add(parsed.key);
          next[index] = {
            ...next[index],
            parsed,
            status: parsed.profile.is_cv ? "done" : "not_cv",
            detail: parsed.profile.is_cv
              ? [parsed.profile.full_name, parsed.profile.headline]
                  .filter(Boolean)
                  .join(" — ")
              : parsed.profile.document_type.replace(/_/g, " "),
          };
        }
      } catch (error) {
        next[index] = {
          ...next[index],
          status: "failed",
          detail: error instanceof Error ? error.message : "Could not read it",
        };
      }
      setRows([...next]);
      setProgress({ done: i + 1, total: pending.length });
    }
    setBusy(false);
  }

  const waiting = rows.filter(
    (r) => r.status === "waiting" || r.status === "failed"
  ).length;
  const ready = rows.filter((r) => r.status === "done").length;

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">1. Add the CVs</h2>
        <p className="text-sm text-muted">
          Each CV is read once, here in your browser session. Nothing is stored on
          the server.
        </p>
      </div>

      <div
        className="card flex flex-col items-center gap-3 border-dashed p-8 text-center"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          add(e.dataTransfer.files);
        }}
      >
        <p className="text-sm text-muted">Drop CVs here, or</p>
        <button className="btn-ghost" onClick={() => input.current?.click()}>
          Choose files
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md,.rtf"
          className="hidden"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-muted">PDF, DOCX, TXT, MD, RTF — up to 8 MB each</p>
      </div>

      {rows.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <button
              className="btn-primary"
              onClick={readAll}
              disabled={busy || waiting === 0}
            >
              {busy
                ? `Reading ${progress.done} of ${progress.total}…`
                : waiting > 0
                  ? `Read ${waiting} CV${waiting === 1 ? "" : "s"}`
                  : "All read"}
            </button>
            <button
              className="btn-ghost"
              onClick={() => setRows([])}
              disabled={busy}
            >
              Clear
            </button>
            <span className="text-sm text-muted">
              {ready} ready to match
              {rows.length - ready > 0 && ` · ${rows.length - ready} other`}
            </span>
          </div>

          {busy && (
            <div className="h-1 w-full overflow-hidden rounded bg-line">
              <div
                className="h-full bg-ink transition-all"
                style={{
                  width: `${(progress.done / Math.max(1, progress.total)) * 100}%`,
                }}
              />
            </div>
          )}

          <div className="card max-h-80 divide-y divide-line overflow-auto">
            {rows.map((row, index) => (
              <div
                key={`${row.file.name}-${index}`}
                className="flex items-center gap-3 px-4 py-2 text-sm"
              >
                <span className="w-6 shrink-0 text-center text-muted">
                  {index + 1}
                </span>
                <span className="min-w-0 flex-1 truncate">{row.file.name}</span>
                <span className="min-w-0 flex-1 truncate text-muted">
                  {row.detail ?? ""}
                </span>
                <span className={`w-28 shrink-0 text-right ${TONE[row.status]}`}>
                  {LABEL[row.status]}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
