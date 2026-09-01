/**
 * CSV that is safe to open in Excel or Google Sheets.
 *
 * Two separate problems, and quoting only solves the first.
 *
 * 1. CSV syntax: a value containing a quote, comma or newline has to be quoted
 *    and its quotes doubled, or the columns shift.
 *
 * 2. Formula injection: a spreadsheet treats a cell beginning with =, +, - or @
 *    as a formula and RUNS it on open. `=HYPERLINK("http://x","Payroll")` is a
 *    working phishing link that a recruiter sees as an ordinary cell.
 *
 * The second matters here because applications arrive from strangers through a
 * public form: the name, the email and the CV's filename are all written by
 * whoever applied. A recruiter exporting the shortlist and opening it is the
 * exact path an attacker would aim at, so those values are neutralised with a
 * leading apostrophe - which spreadsheets strip on display and never execute.
 */

//: A leading one of these turns a cell into a formula.
const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  const safe = FORMULA_START.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}

/** Rows into a CSV document, with a UTF-8 BOM so Excel reads Arabic correctly. */
export function toCSV(headers: string[], rows: unknown[][]): string {
  const body = [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n");
  // Without the BOM, Excel on Windows reads UTF-8 as the local codepage and
  // every non-Latin name in the file becomes mojibake.
  return "﻿" + body;
}

/** Hand the browser a file to save. */
export function downloadCSV(filename: string, content: string): void {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" })
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
