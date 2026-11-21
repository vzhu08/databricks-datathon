export function GET() {
  return Response.json(
    {
      status: 'ready',
      mode: 'local',
      dependencies: [],
      note: 'Base transformation requires no external service. Add checks for selected live integrations explicitly.',
    },
    { headers: { 'cache-control': 'no-store' } },
  );
}
