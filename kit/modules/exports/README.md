# Exports and deliberate sharing

## 1. What problem does this solve, and when should I use it?

Produce safe CSV, evidence-linked PDF reports, QR codes and deliberately shared result pages. Use this at the end of a workbench flow after a user has reviewed the result. Private source data is not automatically made public.

## 2. What is the smallest working example?

```sh
node --import tsx modules/exports/examples/demo.ts
```

This writes actual CSV, PDF, SVG QR and HTML files under `.kit/exports-demo`. Pass an output directory as the final argument. Checked-in download samples are in `fixtures/downloads`.

## 3. How do I add it to a fresh project or an existing project?

Select `exports` with its documents dependency. `toCSV` and safe text helpers are browser-safe; PDF/QR/share functions live in server.ts. An existing UI can download `toCSV(rows)` as a text/csv Blob. Return PDF Uint8Array from a server route with application/pdf and an attachment filename.

## 4. What does the API accept and return?

`toCSV(rows,columns?)` writes quoted cells with CRLF separators. String cells beginning with formula triggers after whitespace/control prefixes receive a leading apostrophe; numbers remain numeric text. `createPDFReport({title,summary?,documents,citations,metadata?})` returns Uint8Array and validates every citation against exact source text. Reports retain filename/page/row/section, source hash and offsets. An attached evidence.json preserves original Unicode citation strings and metadata. `createQRCode(httpURL)` returns an SVG string.

`ShareStore.create({ownerId,value:{title,summary,sources?},ttlMs?,confirmed:true})` returns an unpredictable token and expiration. Only token hashes are stored; `get(token)` returns the deliberately shared projection, `revoke(token,ownerId)` requires its owner. `shareResponse(store,token)` creates an escaped HTML page or 404 after expiration/revocation.

## 5. What prerequisites, environment variables, or credentials are needed?

Node and pdf-lib/qrcode/Zod; no credentials. Production share links require your public origin and an owner-authenticated create/revoke route. The demo QR points to example.org and demonstrates encoding, not a hosted result. No storage or deployment is performed implicitly.

## 6. What changes must I make to routes, schema, storage, or UI?

Wire GET `/share/:token` to shareResponse. Derive owner ID from your session. Private result routes still require authentication; an explicit Share action creates a separate minimum necessary public projection with bounded TTL. The demo store is capped at 100 entries and expires within seven days; it is ephemeral and clears on restart. Replace it with a persistent store preserving token hashing, owner checks, expiry and revocation for multi-instance deployments. Never log share tokens or put sensitive fields into QR targets. Share pages use no-store, noindex and no-referrer headers.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/exports/tests
node --import tsx modules/exports/examples/demo.ts
```

Tests roundtrip the generated PDF through real PDF extraction and check title, source filename and quoted evidence. CSV tests include control-prefix formula evasion, quoting, embedded newlines and numeric negatives. Sharing tests cover explicit intent, wrong owner, expiry, revocation, HTML escaping and private cache headers. Invalid evidence prevents export; unsupported QR schemes are rejected. Rendering samples are checked locally; inspect multilingual report typography before delivery.

Implementation: implemented. Local: tests passed 2026-10-09; real sample files generated; one-page PDF rendered with Poppler and visually checked for clipping/wrapping. Exported project: passed 2026-10-09 in the standalone full recipe (clean install, types, module tests, build and local HTTP). Live hosting/share route: not run — application must wire a durable store and route. Base revision 0fcd52a plus implementation commit.

## 8. What does it depend on, and what are its limits?

PDF standard Helvetica supports WinAnsi typography, not every script/emoji; unsupported visible characters become `?` and exact evidence survives in the attached JSON. Supply an embedded Unicode font when typography requires it. PDF lines paginate and wrap by font width, but this is a simple report renderer without rich tables. CSV caps rows at 100,000. Spreadsheet software may display the protective apostrophe; do not remove it from untrusted data. Token possession grants read access until revocation/expiry; it is not authentication. Export generation costs local CPU only. Original code and synthetic reports: MIT. [pdf-lib PDFDocument](https://pdf-lib.js.org/docs/api/classes/pdfdocument), [node-qrcode](https://github.com/soldair/node-qrcode), official docs inspected 2026-10-09.
