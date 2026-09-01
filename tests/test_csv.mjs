/**
 * The CSV export, and the reason it needs its own tests.
 *
 * Applications arrive from strangers through a public form, so the name, the
 * email and the CV's filename are all written by whoever applied. A recruiter
 * exporting the shortlist and opening it in Excel is the exact path an attacker
 * would aim at: a cell beginning with = + - or @ is a formula, and the
 * spreadsheet runs it.
 *
 * Run: node tests/test_csv.mjs
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "..", "lib", "csv.ts"), "utf8");

// lib/csv.ts is TypeScript, and this runs under plain node. The file has no
// types to strip beyond the signatures, so the smallest honest thing is to
// evaluate it with those removed rather than pull in a build step.
const js = source
  .replace(/^import[^\n]*\n/gm, "")
  .replace(/export /g, "")
  .replace(/: unknown\[\]\[\]/g, "")
  .replace(/: string\[\]/g, "")
  .replace(/: unknown/g, "")
  .replace(/: string/g, "")
  .replace(/: void/g, "");
const { toCSV } = await import(
  "data:text/javascript," + encodeURIComponent(js + "\nexport { toCSV };")
);

let failures = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  PASS  ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`  FAIL  ${name}: ${error.message}`);
  }
}

const body = (csv) => csv.replace(/^﻿/, "").split("\r\n");

test("a formula an applicant put in their own name cannot run", () => {
  // Every one of these is a value a candidate can type into the public form.
  const attacks = [
    '=HYPERLINK("http://evil.example","Payroll")',
    "+1+1",
    "-2+3",
    "@SUM(A1:A9)",
    "=cmd|'/c calc'!A1",
  ];
  const csv = toCSV(["name"], attacks.map((a) => [a]));
  const lines = body(csv).slice(1);

  for (const [index, line] of lines.entries()) {
    assert.equal(
      line.startsWith(`"'`),
      true,
      `${attacks[index]} was left executable: ${line}`
    );
  }
});

test("ordinary values are not mangled", () => {
  const csv = toCSV(
    ["name", "email", "percent"],
    [["Omar H. Abdelrahman", "omar@example.com", 86]]
  );
  const [head, row] = body(csv);
  assert.equal(head, '"name","email","percent"');
  assert.equal(row, '"Omar H. Abdelrahman","omar@example.com","86"');
});

test("quotes, commas and newlines keep the columns aligned", () => {
  const csv = toCSV(
    ["note"],
    [['He said "strong SQL", then left'], ["line one\nline two"]]
  );
  const text = csv.replace(/^﻿/, "");
  assert.ok(text.includes('"He said ""strong SQL"", then left"'));
  // A newline inside a quoted field is legal CSV and must stay inside it.
  assert.ok(text.includes('"line one\nline two"'));
});

test("empty and missing values become empty cells, not the word undefined", () => {
  const [, row] = body(toCSV(["a", "b", "c"], [[null, undefined, ""]]));
  assert.equal(row, '"","",""');
});

test("the file starts with a BOM so Excel reads Arabic names correctly", () => {
  const csv = toCSV(["name"], [["محمد طارق"]]);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.ok(csv.includes("محمد طارق"));
});

console.log(
  `\n${failures ? "FAILED" : "ALL PASSED"} (${failures} failure(s))`
);
process.exit(failures ? 1 : 0);
