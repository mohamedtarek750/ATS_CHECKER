/**
 * ACUD ATS — the sheet's own backend.
 *
 * Paste this into the spreadsheet's Apps Script editor and deploy it as a Web
 * app. The app then reads and writes through this script instead of through the
 * Google Sheets API, which means no Google Cloud project, no service account,
 * no OAuth client and no API key: the script runs as you, with the access you
 * already have to your own sheet and Drive.
 *
 * ── HOW TO INSTALL ───────────────────────────────────────────────────────────
 *
 *  1. Open the spreadsheet → Extensions → Apps Script.
 *  2. Delete whatever is in Code.gs and paste this file in its place. Save.
 *  3. Deploy → New deployment → gear icon → Web app.
 *       Execute as:      Me
 *       Who has access:  Anyone            ← must be "Anyone", not "Anyone with
 *                                            Google account"
 *  4. Deploy → Authorize access → pick your account → Advanced → Go to (unsafe)
 *     → Allow. (That warning is Google telling you the script is unreviewed and
 *     yours; it is asking whether you trust what you just pasted.)
 *  5. Copy the Web app URL. It ends in /exec. That is ATS_SCRIPT_URL.
 *
 * Nothing else is needed. Tabs and headers are created on first use, and a
 * folder for the CVs is created next to the spreadsheet.
 *
 * ── WHAT "ANYONE" MEANS ──────────────────────────────────────────────────────
 *
 * The URL is an open endpoint: whoever holds it can read and write this sheet.
 * That is the trade for having no credentials to manage, and it is fine for a
 * prototype carrying test data. Before real applicants use it, set a SHARED_KEY
 * below and put the same value in ATS_SCRIPT_KEY; requests without it are then
 * refused.
 */

/** Optional. Leave empty for an open prototype; set it before real data. */
var SHARED_KEY = "";

/** Created beside the spreadsheet on first use. CVs and parsed profiles live here. */
var FOLDER_NAME = "ACUD_ATS_files";

var POSTING_COLUMNS = [
  "slug", "title", "summary", "status", "created", "created_by", "profile_json",
];

var APPLICATION_COLUMNS = [
  "id", "job_slug", "full_name", "email", "phone", "applied_at",
  "cv_filename", "cv_ref", "cv_url",
  "status", "detail", "read_at",
  "percent", "required_percent", "preferred_percent", "tier", "reason",
  "engine_version", "decision", "decided_by", "decided_at", "note",
  "security_flags",
];

// ── plumbing ────────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    var request = JSON.parse(e.postData.contents);
    if (SHARED_KEY && request.key !== SHARED_KEY) {
      return reply({ error: "Wrong or missing key." });
    }
    var handler = HANDLERS[request.op];
    if (!handler) return reply({ error: "Unknown operation: " + request.op });
    return reply({ ok: true, result: handler(request) });
  } catch (err) {
    return reply({ error: String(err) });
  }
}

/** A browser opening the URL should see something other than an error. */
function doGet() {
  return reply({ ok: true, service: "ACUD ATS sheet backend" });
}

function reply(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(
    ContentService.MimeType.JSON
  );
}

function book() {
  return SpreadsheetApp.getActiveSpreadsheet();
}

/** The tab, created with its header row if this is the first time. */
function tab(name, columns) {
  var sheet = book().getSheetByName(name);
  if (!sheet) {
    sheet = book().insertSheet(name);
    sheet.appendRow(columns);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function readTab(name, columns) {
  var sheet = tab(name, columns);
  var rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];

  var header = rows[0];
  var out = [];
  for (var i = 1; i < rows.length; i++) {
    var record = {};
    for (var c = 0; c < header.length; c++) {
      record[String(header[c])] = rows[i][c] === null ? "" : String(rows[i][c]);
    }
    if (record[columns[0]]) out.push(record);
  }
  return out;
}

/** Append, or overwrite the row whose key matches. One write either way. */
function upsert(name, columns, record, keyColumn) {
  var sheet = tab(name, columns);
  var values = [];
  for (var i = 0; i < columns.length; i++) {
    var value = record[columns[i]];
    values.push(value === undefined || value === null ? "" : value);
  }

  var keyIndex = columns.indexOf(keyColumn);
  var existing = sheet.getDataRange().getValues();
  for (var r = 1; r < existing.length; r++) {
    if (String(existing[r][keyIndex]) === String(record[keyColumn])) {
      sheet.getRange(r + 1, 1, 1, columns.length).setValues([values]);
      return;
    }
  }
  sheet.appendRow(values);
}

/** Replace everything under the header with these rows. */
function rewrite(name, columns, records) {
  var sheet = tab(name, columns);
  var rows = sheet.getLastRow();
  if (rows > 1) {
    sheet.getRange(2, 1, rows - 1, columns.length).clearContent();
  }
  if (!records.length) return;

  var values = records.map(function (record) {
    return columns.map(function (column) {
      var value = record[column];
      return value === undefined || value === null ? "" : value;
    });
  });
  sheet.getRange(2, 1, values.length, columns.length).setValues(values);
}

/** The folder holding CVs and parsed profiles, made if it is not there yet. */
function folder() {
  var parents = DriveApp.getFileById(book().getId()).getParents();
  var where = parents.hasNext() ? parents.next() : DriveApp.getRootFolder();
  var found = where.getFoldersByName(FOLDER_NAME);
  return found.hasNext() ? found.next() : where.createFolder(FOLDER_NAME);
}

function fileNamed(name) {
  var found = folder().getFilesByName(name);
  return found.hasNext() ? found.next() : null;
}

// ── operations ──────────────────────────────────────────────────────────────

var HANDLERS = {
  ping: function () {
    return { sheet: book().getName(), folder: folder().getName() };
  },

  postings: function () {
    return readTab("postings", POSTING_COLUMNS);
  },

  save_posting: function (request) {
    upsert("postings", POSTING_COLUMNS, request.record, "slug");
    return request.record;
  },

  /**
   * A vacancy, its applications, and their files.
   *
   * The tabs are rewritten without the removed rows in one setValues call.
   * Deleting rows one at a time renumbers the ones below, so the second
   * delete would land on the wrong row.
   */
  delete_posting: function (request) {
    var slug = String(request.slug || "");
    if (!slug) throw new Error("delete_posting needs a slug.");

    var apps = readTab("applications", APPLICATION_COLUMNS);
    var going = [];
    var staying = [];
    for (var i = 0; i < apps.length; i++) {
      (apps[i].job_slug === slug ? going : staying).push(apps[i]);
    }

    for (var g = 0; g < going.length; g++) {
      var names = [going[g].cv_ref, going[g].id + ".json"];
      for (var n = 0; n < names.length; n++) {
        if (!names[n]) continue;
        var file = fileNamed(names[n]);
        if (file) file.setTrashed(true);
      }
    }

    if (going.length) rewrite("applications", APPLICATION_COLUMNS, staying);

    var postings = readTab("postings", POSTING_COLUMNS);
    var kept = postings.filter(function (row) {
      return row.slug !== slug;
    });
    if (kept.length !== postings.length) {
      rewrite("postings", POSTING_COLUMNS, kept);
    }

    return { slug: slug, applications: going.length };
  },

  applications: function (request) {
    var rows = readTab("applications", APPLICATION_COLUMNS);
    if (!request.job_slug) return rows;
    return rows.filter(function (row) {
      return row.job_slug === request.job_slug;
    });
  },

  save_application: function (request) {
    upsert("applications", APPLICATION_COLUMNS, request.record, "id");
    return request.record;
  },

  /** The CV itself. Sent as base64 because a sheet cell cannot hold a file. */
  put_file: function (request) {
    var name = request.name;
    var existing = fileNamed(name);
    if (existing) existing.setTrashed(true);

    var blob = Utilities.newBlob(
      Utilities.base64Decode(request.data),
      request.mime || "application/octet-stream",
      name
    );
    var file = folder().createFile(blob);
    return { id: file.getId(), url: file.getUrl(), name: name };
  },

  get_file: function (request) {
    var file = fileNamed(request.name);
    if (!file) return null;
    return { data: Utilities.base64Encode(file.getBlob().getBytes()) };
  },
};
