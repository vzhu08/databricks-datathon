// Browser port of cc_index.py + extract.py, used for the 2026-11-22 prototype run.
//
// Why a browser: the cloud workers that build this repo cannot reach Common Crawl, and
// index.commoncrawl.org's CDX server returned HTTP 504 for every query that night. A browser
// tab opened on https://index.commoncrawl.org/collinfo.json can read data.commoncrawl.org
// (CORS is open) with range requests and DecompressionStream. Run from Python where the
// network allows: cc_index.Crawl + extract.mentions do the same thing.
//
// Politeness: one shared throttle, at most ~3 requests a second. An unthrottled run with six
// parallel workers was blocked by CloudFront (HTTP 403) after ~900 domains for ~20 minutes.
//
// Usage in the tab's console:
//   await CC.load('CC-MAIN-2026-39'); CC.queue.push(...domains); await CC.run(2);
//   then read CC.results (per domain: captures, html captures, pages read, thin pages, hits).

window.CC = {results: {}, queue: [], blockCache: new Map(), last: 0};

CC.load = async crawl => {
  CC.crawl = crawl;
  CC.IDX = `https://data.commoncrawl.org/cc-index/collections/${crawl}/indexes/`;
  const txt = await (await fetch(CC.IDX + 'cluster.idx')).text();
  CC.keys = []; CC.meta = [];
  for (const line of txt.split('\n')) {
    if (!line) continue;
    const p = line.split('\t');
    CC.keys.push(p[0].split(' ')[0]); CC.meta.push([p[1], +p[2], +p[3]]);
  }
};

CC.throttle = async () => {
  const now = Date.now(), wait = Math.max(0, CC.last + 350 - now);
  CC.last = now + wait;
  if (wait) await new Promise(r => setTimeout(r, wait));
};
CC.range = async (url, start, len) => {
  await CC.throttle();
  const r = await fetch(url, {headers: {Range: `bytes=${start}-${start + len - 1}`}});
  if (r.status !== 206 && r.status !== 200) throw new Error('http ' + r.status);
  return await new Response(r.body.pipeThrough(new DecompressionStream('gzip'))).text();
};

CC.surt = d => d.toLowerCase().replace(/^www\./, '').split('.').reverse().join(',');
CC.findBlock = k => { let lo = 0, hi = CC.keys.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (CC.keys[m] <= k) lo = m; else hi = m - 1; } return lo; };
CC.getBlock = i => {
  if (!CC.blockCache.has(i)) { const [f, o, l] = CC.meta[i]; CC.blockCache.set(i, CC.range(CC.IDX + f, o, l).then(t => t.split('\n'))); }
  return CC.blockCache.get(i);
};
CC.lookup = async d => {
  const s = CC.surt(d), lo = s + ')', hi = s + '-', rows = [];
  let i = CC.findBlock(lo);
  for (let n = 0; n < 6 && i < CC.keys.length; n++, i++) {
    if (n > 0 && CC.keys[i] > hi) break;
    for (const L of await CC.getBlock(i)) {
      if (!L) continue;
      const i1 = L.indexOf(' '), sk = L.slice(0, i1);
      if (!(sk.startsWith(s + ')') || sk.startsWith(s + ','))) continue;
      const i2 = L.indexOf(' ', i1 + 1);
      let j; try { j = JSON.parse(L.slice(i2 + 1)); } catch (e) { continue; }
      rows.push({u: j.url, ts: L.slice(i1 + 1, i2), st: j.status, m: j.mime || j['mime-detected'], f: j.filename, o: +j.offset, l: +j.length});
    }
    if (i + 1 < CC.keys.length && CC.keys[i + 1] > hi) break;
  }
  return rows;
};

CC.KW = /(dialysis|kidney|nephro|mri|radiology|imaging|scan|trauma|emergency|casualty|accident|service|facilit|department|speciali|about|infrastructure|our-|treatment)/i;
CC.pick = rows => {
  const h = rows.filter(r => r.st === '200' && /html/.test(r.m || ''));
  const path = r => { try { return new URL(r.u).pathname.replace(/\/+$/, '') || '/'; } catch (e) { return r.u; } };
  h.sort((a, b) => path(a).length - path(b).length);
  const seen = new Set(), out = [];
  for (const r of h) { const p = path(r); if (!seen.has(p) && ['/', '/index.html', '/index.php', '/index.htm', '/home'].includes(p)) { seen.add(p); out.push(r); break; } }
  for (const r of h) { const p = path(r); if (seen.has(p)) continue; if (CC.KW.test(p)) { seen.add(p); out.push(r); } if (out.length >= 8) break; }
  return {n: h.length, pages: out.slice(0, 8)};
};

// Same patterns as extract.py.
CC.SV = {
  dialysis: /\b(h(a)?emo[- ]?dialysis|dialysis|CAPD|peritoneal dialysis)\b/i,
  mri: /\b(MRI|M\.R\.I|magnetic resonance)\b/,
  trauma: /\b(trauma\s*(care|cent(re|er)|unit|ward|team|services?|ICU|surgery)|polytrauma|accident\s*(and|&)\s*emergency|emergency\s*(and|&)\s*trauma|level\s*[I1]+\s*trauma)\b/i,
};
CC.Q = /\b(not available|not provide\w*|no (dialysis|mri)|do not|don't|refer(red|s)? (to|out)|coming soon|upcoming|proposed|planning|plan to|will be (started|available|launched)|under construction|outsourc\w*|tie[- ]?up|should be confirmed)\b/i;
CC.ON = /\b(we|our|us|in[- ]house|available|equipped|offer(s|ing)?|provid(e|es|ing)|facilit(y|ies)|unit|cent(re|er)|department|24\s*[x×*\/]\s*7|24[- ]hours?|round[- ]the[- ]clock|machines?|beds?|tesla|slice)\b/i;
CC.EDU = /\b(may (order|use|be|need)|your doctor|doctors? (may|will|might|can)|is a (painless|procedure|test)|is the process|what is|tests? (like|such as)|diagnosis (involves|typically|includes)|imaging tests|may be ordered|is required to|is very good)\b/i;
CC.rank = s => [!CC.EDU.test(s), CC.ON.test(s), s.length >= 40, !CC.Q.test(s), -Math.abs(s.length - 160)];
CC.cmp = (a, b) => { const x = CC.rank(a), y = CC.rank(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return y[i] > x[i] ? 1 : -1; return 0; };

CC.text = html => {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script,style,noscript,svg,iframe,template').forEach(e => e.remove());
  const parts = [];
  const walk = el => { for (const c of el.childNodes) {
    if (c.nodeType === 3) { const s = c.textContent.replace(/\s+/g, ' ').trim(); if (s) parts.push(s); }
    else if (c.nodeType === 1) { walk(c); if (/^(P|DIV|LI|H[1-6]|TD|TR|BR|SECTION|ARTICLE|A|SPAN)$/.test(c.tagName)) parts.push('\n'); }
  } };
  if (doc.body) walk(doc.body);
  return parts.join(' ').replace(/ *\n[\n ]*/g, '\n');
};
CC.extract = t => {
  const out = {};
  for (const s of t.split(/\n|(?<=[.!?])\s+(?=[A-Z])/).map(s => s.trim()).filter(s => s.length >= 3))
    for (const [k, re] of Object.entries(CC.SV)) if (re.test(s)) (out[k] = out[k] || []).push(s.slice(0, 280));
  return out;
};
CC.page = async p => { const t = await CC.range('https://data.commoncrawl.org/' + p.f, p.o, p.l); const k = t.indexOf('\r\n\r\n'); return t.slice(t.indexOf('\r\n\r\n', k + 4) + 4); };

CC.processDomain = async d => {
  const rows = await CC.lookup(d), {n, pages} = CC.pick(rows);
  const res = {d, cap: rows.length, html: n, pages: 0, thin: 0, hits: {}};
  for (const p of pages) {
    try {
      const text = CC.text(await CC.page(p));
      res.pages++;
      if (text.length < 300) { res.thin++; continue; }  // bot check or JavaScript shell
      for (const [k, arr] of Object.entries(CC.extract(text))) {
        const best = arr.slice().sort(CC.cmp)[0];
        (res.hits[k] = res.hits[k] || []).push({u: p.u, ts: p.ts, q: best, neg: CC.Q.test(best), n: arr.length});
      }
    } catch (e) { res.err = (res.err || 0) + 1; }
  }
  return res;
};

CC.run = async (conc = 2) => {
  CC.running = true;
  const worker = async () => {
    while (CC.queue.length && CC.running) {
      const d = CC.queue.shift();
      try { CC.results[d] = await CC.processDomain(d); }
      catch (e) { if (/403/.test(e)) { CC.running = false; CC.queue.unshift(d); } else CC.results[d] = {d, fail: String(e).slice(0, 80)}; }
      if (CC.blockCache.size > 2000) CC.blockCache.clear();
    }
  };
  await Promise.all(Array.from({length: conc}, worker));
  CC.running = false;
};
