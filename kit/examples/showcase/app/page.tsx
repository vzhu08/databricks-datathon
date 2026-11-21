export default function Home() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">THE CAPABILITY STUDIO</p>
        <h1>
          Find your starting point.
          <br />
          <span>Make it your own.</span>
        </h1>
        <p className="lede">
          Three complete workflows, built from the same reusable modules. Explore the behavior,
          follow the evidence, and take only what your idea needs.
        </p>
        <div className="meta">
          <span>Real local behavior</span>
          <span>Explicit fixture labels</span>
          <span>Portable source</span>
        </div>
      </section>
      <div className="studio-cards">
        {[
          {
            number: '01',
            icon: '▤',
            name: 'Document workbench',
            href: '/document',
            description: 'From an upload to a result you can inspect, edit, and share.',
            tags: 'Ingestion · retrieval · extraction · export',
          },
          {
            number: '02',
            icon: '◈',
            name: 'Group decisions',
            href: '/group',
            description: 'Find the common ground in a group’s different priorities.',
            tags: 'Preferences · ranking · votes · realtime',
          },
          {
            number: '03',
            icon: '◉',
            name: 'Media assistant',
            href: '/media',
            description: 'Bring voice and images into a transparent processing flow.',
            tags: 'Recording · vision · playback · jobs',
          },
        ].map((c) => (
          <a className="studio-card" key={c.href} href={c.href}>
            <div>
              <span>{c.number}</span>
              <span className="studio-symbol">{c.icon}</span>
            </div>
            <h2>{c.name}</h2>
            <p>{c.description}</p>
            <small>{c.tags}</small>
            <span className="studio-arrow">Explore workflow ↗</span>
          </a>
        ))}
      </div>
      <section className="studio-bottom">
        <div>
          <p className="eyebrow">THE BUILDING BLOCKS</p>
          <h2>Useful patterns. Thoughtful states.</h2>
          <p className="panel-note">
            Upload controls, evidence viewers, tables, charts, streaming output, and the error
            states that make them usable.
          </p>
        </div>
        <a className="button-link" href="/gallery">
          Open pattern gallery ↗
        </a>
      </section>
    </>
  );
}
