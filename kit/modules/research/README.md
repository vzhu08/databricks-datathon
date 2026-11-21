# Web research

## 1. What problem does this solve, and when should I use it?

Search, deduplicate and fetch cited web sources with bounded requests, private-network protection and per-user caching. Use the fixture provider for credential-free development and Tavily for live discovery. Source content is untrusted evidence, never agent instructions.

## 2. What is the smallest working example?

```sh
node --import tsx modules/research/examples/demo.ts
```

The example searches a synthetic result fixture and extracts local HTML. `ResearchClient(fixtureSearchProvider(hits),fixtureFetch)` labels every result `mode:'fixture'`. For live mode, construct `new ResearchClient(tavilySearchProvider(process.env.TAVILY_API_KEY!))` on the server.

## 3. How do I add it to a fresh project or an existing project?

Select `research`. Keep server.ts in server routes. Use an authenticated request's user ID as `scope`; do not trust a user-supplied scope. Browser-safe URL deduplication/provider types are in index.ts. Existing search providers implement `{name,mode,search(query,{limit,signal})}` returning validated `{title,url,snippet,publishedAt?}` hits.

## 4. What does the API accept and return?

`research(query,{scope,limit=5,signal})` returns query, provider, mode, sources and per-URL failures. A source includes title, extracted text, original URL, final URL, retrieval timestamp, optional publication date and explicit cached state. Publication dates come from source metadata/time elements or an explicitly attributed search-provider date (`publicationDateSource`); page metadata takes precedence. Retrieval date is not publication date. The original provider URL is retained separately from the normalized fetch/deduplication URL. `normalizeURL` removes fragments/tracking parameters and sorts query keys. `safeFetchHTML` checks protocol, credentials, ports, DNS ranges and redirects; `extractHTML` removes active/navigation content and chooses article/main/body text.

## 5. What prerequisites, environment variables, or credentials are needed?

Node >=22, Cheerio, ipaddr.js, Zod/shared runtime. Live search needs server-only TAVILY_API_KEY. Tavily adapter uses its real POST search endpoint, bearer authorization, basic search depth and up to 10 results. Fixture mode never contacts search or source sites. Live calls can incur search usage; no current price/allowance is assumed.

## 6. What changes must I make to routes, schema, storage, or UI?

Add a server research route with request/query bounds and cancellation. Results cache is instance-local, capped at 50 entries, five-minute TTL and explicit user scope; call `clear(scope)` when ending a session. The fetcher resolves all DNS addresses, rejects any private/reserved address, pins validated addresses into the connection lookup and checks every redirect. Only HTTP(S) standard ports are allowed. Do not replace this transport with ordinary fetch unless equivalent DNS pinning and redirect checks are preserved. Show original/final URLs, dates, fixture/live/cached markers and per-source failures in the UI.

## 7. How do I verify it and handle expected failures?

```sh
npx vitest run modules/research/tests
node --import tsx modules/research/examples/demo.ts
```

Tests cover IP literals (including integer/mapped IPv6 forms), mixed public/private DNS, URL credentials/ports, deduplication, source extraction, date absence, cache scope, failure visibility, real Tavily request/response contracts and malformed provider output. Fetch timeout defaults to 10 seconds, max three redirects and 2 MB uncompressed HTML. A source failure stays a failure; live errors never become fixture output.

Implementation: implemented. Local: tests passed 2026-10-09. Exported project: passed 2026-10-09 in the standalone full recipe (clean install, types, module tests, build and local HTTP). Live Tavily/site fetch: not run — requires operator credentials/network authorization. Base revision 0fcd52a plus implementation commit.

## 8. What does it depend on, and what are its limits?

Generic HTML extraction cannot execute JavaScript or reliably reconstruct dynamic/paywalled sites. UTF-8 HTML decoding is assumed; compressed responses are deliberately rejected after requesting identity encoding. Search snippet and metadata dates are unverified publisher claims. DNS egress protections are necessary but applications should still use an outbound network firewall in hostile deployments. Fetches run sequentially to bound concurrency; a deployment can add a carefully bounded pool. Only GET source fetches and explicit search queries occur. Original code/fixtures: MIT; fixture articles are original synthetic text. Official API verified 2026-10-09: [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Node HTTP](https://nodejs.org/api/http.html), [ipaddr.js](https://github.com/whitequark/ipaddr.js).
