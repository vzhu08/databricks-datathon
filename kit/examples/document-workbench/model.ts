import type { NormalizedDocument } from '../../packages/contracts/src/index';
import type { ExtractionResult } from '../../modules/extraction/src/index';
export function reviewedReport(document: NormalizedDocument, result: ExtractionResult) {
  const rows = result.fields.map((field) => ({
    field: field.label,
    value: field.value ?? '',
    status: field.status,
    review: field.review
      ? field.review.supported
        ? 'Human reviewed; source-supported'
        : 'Human reviewed; NOT supported by source'
      : 'Unedited extraction',
    editor: field.review?.editor ?? '',
    note: field.review?.note ?? '',
    source: document.filename,
    documentHash: document.hash,
    evidence: field.candidates.map((c) => c.evidence.quote).join(' | '),
    sourceOffsets: field.candidates.map((c) => `${c.evidence.start}-${c.evidence.end}`).join(' | '),
  }));
  return {
    rows,
    report: {
      title: `Document review: ${document.filename}`.slice(0, 200),
      summary:
        rows
          .map((row) => `${row.field}: ${row.value || row.status} [${row.status}; ${row.review}]`)
          .join('\n') +
        '\n\nCitations below describe the original source. A human-edited value marked NOT supported does not become source evidence.',
      documents: [document],
      citations: result.fields.flatMap((f) => f.candidates.map((c) => c.evidence)),
    },
  };
}
