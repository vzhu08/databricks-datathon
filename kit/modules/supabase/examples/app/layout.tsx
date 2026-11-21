import type { ReactNode } from 'react';
export const metadata = {
  title: 'Supabase notes · Hackathon Kit',
  description: 'Optional authenticated CRUD example with explicit fixture and live modes.',
};
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#f7f9f5' }}>{children}</body>
    </html>
  );
}
