import { z } from 'zod';
const Cell = z.union([z.string(), z.number().finite(), z.boolean(), z.null()]);
/** Prefix untrusted formula-like text, including whitespace/control-character evasion. */
export function safeCSVCell(input: unknown): string {
  const value = Cell.parse(input);
  let text = value === null ? '' : String(value);
  // eslint-disable-next-line no-control-regex -- spreadsheet engines ignore these prefixes
  if (typeof value === 'string' && /^[\s\u0000-\u001f\uFEFF]*[=+\-@]/u.test(text))
    text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}
export function toCSV(input: Record<string, unknown>[], columns?: string[]): string {
  if (input.length > 100_000) throw new Error('Export row limit exceeded');
  const keys = columns ?? [...new Set(input.flatMap((row) => Object.keys(row)))];
  if (!keys.length) return '';
  return (
    [
      keys.map(safeCSVCell).join(','),
      ...input.map((row) => keys.map((key) => safeCSVCell(row[key] ?? null)).join(',')),
    ].join('\r\n') + '\r\n'
  );
}
export function escapeHTML(text: string) {
  return text.replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!,
  );
}
