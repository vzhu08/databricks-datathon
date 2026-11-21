import '../../../starters/web/app/globals.css';
import '../../../packages/ui/src/theme.css';
import './showcase.css';
export const metadata = {
  title: 'Hackathon Kit · Capability studio',
  description: 'Working reference compositions and reusable patterns.',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <header>
          <a className="brand" href="/">
            <span className="brand-icon">↗</span>Hackathon Kit
            <span className="studio-label">/ studio</span>
          </a>
          <nav aria-label="Studio">
            <a href="/document">Documents</a>
            <a href="/group">Decisions</a>
            <a href="/media">Media</a>
            <a href="/gallery">Patterns</a>
            <a href="/ai">AI</a>
          </nav>
          <span className="badge">
            <span className="status-dot" />
            Local mode
          </span>
        </header>
        <main id="main">{children}</main>
        <footer>
          Small pieces. Ambitious possibilities.
          <span>Working examples · original synthetic data</span>
        </footer>
      </body>
    </html>
  );
}
