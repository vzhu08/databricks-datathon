import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'Hackathon Kit · Start building',
  description: 'A small, independent starting point for your next build.',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <header>
          <a href="/" className="brand">
            <span className="brand-icon">↗</span> Hackathon Kit
          </a>
          <span className="badge">
            <span className="status-dot" />
            Local mode
          </span>
        </header>
        <main id="main">{children}</main>
        <footer>
          Start small. Ship something that works.
          <span>No keys. No services. Just your next idea.</span>
        </footer>
      </body>
    </html>
  );
}
