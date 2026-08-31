"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { parseCV, type ParsedCV } from "@/lib/api";
import { Note } from "./Shell";

export interface UploadRow {
  file: File;
  status: "waiting" | "reading" | "done" | "skipped" | "not_cv" | "failed";
  parsed?: ParsedCV;
  detail?: string;
}

const LABEL: Record<UploadRow["status"], string> = {
  waiting: "Waiting",
  reading: "Reading",
  done: "Read",
  skipped: "Duplicate",
  not_cv: "Not a CV",
  failed: "Failed",
};

const CHIP: Record<UploadRow["status"], string> = {
  waiting: "text-muted raised",
  reading: "text-ink raised",
  done: "text-good bg-good-wash",
  skipped: "text-muted raised",
  not_cv: "text-warn bg-warn-wash",
  failed: "text-bad bg-bad-wash",
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
  // A link to each file as it sits in the browser. Built once per file rather
  // than per render: createObjectURL in a render body mints a new URL on every
  // keystroke elsewhere on the page and never releases any of them.
  const poolKey = rows.map((r) => `${r.file.name}|${r.file.size}`).join(";");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const urls = useMemo(() => rows.map((r) => URL.createObjectURL(r.file)), [poolKey]);
  useEffect(() => () => urls.forEach(URL.revokeObjectURL), [urls]);

  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const input = useRef<HTMLInputElement>(null);

  function add(files: FileList | null) {
    if (!files) return;
    const seen = new Set(rows.map((r) => `${r.file.name}|${r.file.size}`));
    const fresh = Array.from(files)
      .filter((f) => !seen.has(`${f.name}|${f.size}`))
      .map((file) => ({ file, status: "waiting" as const }));
    if (fresh.length) setRows([...rows, ...fresh]);
  }

  // One CV per request: a single call for a hundred would exceed the function
  // timeout, and this way each row resolves as it lands.
  async function readAll() {
    const pending = rows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => row.status === "waiting" || row.status === "failed");
    if (!pending.length) return;

    setBusy(true);
    setProgress({ done: 0, total: pending.length });
    const next = [...rows];
    const keys = new Set(rows.filter((r) => r.parsed).map((r) => r.parsed!.key));

    for (let i = 0; i < pending.length; i++) {
      const { row, index } = pending[i];
      next[index] = { ...next[index], status: "reading", detail: undefined };
      setRows([...next]);

      try {
        const parsed = await parseCV(row.file, provider);
        if (keys.has(parsed.key)) {
          next[index] = {
            ...next[index],
            parsed,
            status: "skipped",
            detail: "same content as another file",
          };
        } else {
          keys.add(parsed.key);
          next[index] = {
            ...next[index],
            parsed,
            status: parsed.profile.is_cv ? "done" : "not_cv",
            detail: parsed.profile.is_cv
              ? [parsed.profile.full_name, parsed.profile.headline]
                  .filter(Boolean)
                  .join(" · ")
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
  const failed = rows.filter((r) => r.status === "failed").length;

  return (
    <div className="space-y-4">
      <div
        className={`card flex flex-col items-center gap-3 border-2 border-dashed p-10 text-center transition ${
          over ? "border-accent/40 raised" : ""
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          add(e.dataTransfer.files);
        }}
      >
        <p className="text-sm text-muted">Drop CVs here</p>
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
        <p className="text-xs text-muted">PDF, DOCX, TXT, MD, RTF · up to 8 MB each</p>
      </div>

      {rows.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary" onClick={readAll} disabled={busy || !waiting}>
              {busy
                ? `Reading ${progress.done} of ${progress.total}`
                : waiting
                  ? `Read ${waiting} CV${waiting === 1 ? "" : "s"}`
                  : "All read"}
            </button>
            <button className="btn-ghost" onClick={() => setRows([])} disabled={busy}>
              Clear
            </button>
            <span className="text-sm text-muted">
              {ready} ready
              {rows.length - ready > 0 && ` · ${rows.length - ready} other`}
            </span>
          </div>

          {busy && (
            <div className="h-1 w-full overflow-hidden rounded-full bg-line">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-300"
                style={{
                  width: `${(progress.done / Math.max(1, progress.total)) * 100}%`,
                }}
              />
            </div>
          )}

          {failed > 0 && !busy && (
            <Note tone="warn">
              {failed} file{failed === 1 ? "" : "s"} failed. Press{" "}
              <strong>Read</strong> again to retry only those — everything already
              read is kept.
            </Note>
          )}

          <div className="card scroll-thin max-h-[22rem] divide-y overflow-auto">
            {rows.map((row, index) => (
              <div
                key={`${row.file.name}-${index}`}
                className="flex items-center gap-3 px-4 py-2.5 text-sm"
              >
                <span className="w-6 shrink-0 text-right text-xs tabular-nums text-muted">
                  {index + 1}
                </span>
                <a
                  href={urls[index]}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 basis-56 truncate underline decoration-dotted underline-offset-2 hover:text-ink"
                  title={`Open ${row.file.name}`}
                >
                  {row.file.name}
                </a>
                <span className="min-w-0 flex-1 truncate text-muted">
                  {row.detail ?? ""}
                </span>
                <span className={`chip shrink-0 ${CHIP[row.status]}`}>
                  {row.status === "reading" && (
                    <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                  )}
                  {LABEL[row.status]}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
