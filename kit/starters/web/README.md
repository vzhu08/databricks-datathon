# Minimal web starter

From the toolkit root: `npm ci`, `npm run dev`, open http://localhost:3000. Normalization is real, deterministic and credential-free. `npm run build` checks the production build. For an independent app: `npm run kit -- create /tmp/my-hackathon --starter web`, then run `npm install`, `npm run check`, `npm run dev` inside it. Record and commit its generated package-lock.json; subsequent installs use npm ci. API routes: POST /api/transform, GET /api/health (liveness), GET /api/ready (selected-service readiness). No auth wall, Python, Docker or provider calls.
