# Contribution record

Git shows 39 commits on `main` with the author `Claude <noreply@anthropic.com>`.
All 39 are Andrew Gu's work (Developer C, GitHub
[@andrewhgu](https://github.com/andrewhgu)). He directed them through Claude
Code cloud sessions that committed under the tool's default identity until
07:32 UTC on 22 November 2026. From then on his commits carry his own name.

The history of `main` is shared and is left as it is. This file is the record
that ties those commits to him.

## How the commits were identified

Checked against `main` at `8e035f3` on 22 November 2026.

- Every commit on `main` with the author email `noreply@anthropic.com` was
  listed with `git log origin/main --author=noreply@anthropic.com`. There are
  39.
- Each one was looked up on GitHub by its full hash. Every one belongs to a
  pull request opened by `andrewhgu`, shown in the table below. The four
  commits of #29 also appear in #31, which merged the same branch.
- 34 of the 39 carry the same `Claude-Session` trailer, so they come from one
  session. The other five are merge commits made on his pull-request branches
  (`7832e42`, `9db585b`, `cc3b894`, `52964c1`, `bf87cf4`).
- No commit on `main` with this author belongs to a pull request opened by
  anyone else.

## Commits

Times are the author times in UTC.

| Pull request | Commit | Authored | Subject |
| --- | --- | --- | --- |
| [#29](https://github.com/vzhu08/databricks-datathon/pull/29) | [`0ac5941`](https://github.com/vzhu08/databricks-datathon/commit/0ac59413897779242e798f9e85ebc10a24d12e69) | 2026-11-21 18:34 | Add conservative identity matching and geographic checks for ACQ-C01 |
| [#29](https://github.com/vzhu08/databricks-datathon/pull/29) | [`e784637`](https://github.com/vzhu08/databricks-datathon/commit/e7846375fc8cbdabb59b84a5790d728f5e821b01) | 2026-11-21 18:37 | Document the matching workflow and keep combining marks in folded names |
| [#29](https://github.com/vzhu08/databricks-datathon/pull/29) | [`a87ad07`](https://github.com/vzhu08/databricks-datathon/commit/a87ad0752b5cf0dbd5d5d410b59500ee32dffc6b) | 2026-11-21 18:38 | Accept D's source metadata as the observed base mapping |
| [#29](https://github.com/vzhu08/databricks-datathon/pull/29) | [`d64c7cb`](https://github.com/vzhu08/databricks-datathon/commit/d64c7cbf86907d1fb6b4f4dc84f91ec5cd5145b7) | 2026-11-21 18:41 | Hand off ACQ-C01 with fixture results and real-data blockers |
| [#43](https://github.com/vzhu08/databricks-datathon/pull/43) | [`eb110d1`](https://github.com/vzhu08/databricks-datathon/commit/eb110d1fb40df5ab2d7f88b0ec61f1728f2191e1) | 2026-11-21 19:21 | Measure building-footprint coverage on a frozen public Rajasthan sample |
| [#43](https://github.com/vzhu08/databricks-datathon/pull/43) | [`63a03fb`](https://github.com/vzhu08/databricks-datathon/commit/63a03fbca766919b437eaf6d33aea584f0d8a40c) | 2026-11-21 19:26 | Hand off ACQ-C02 with public-source coverage results and hashes |
| [#43](https://github.com/vzhu08/databricks-datathon/pull/43) | [`b21c41e`](https://github.com/vzhu08/databricks-datathon/commit/b21c41e3d6aabd179a1e4ada83ca76a6fe5bce3b) | 2026-11-21 19:47 | Record the version 1.1 replay of the ACQ-C02 Google comparison |
| [#62](https://github.com/vzhu08/databricks-datathon/pull/62) | [`53b3122`](https://github.com/vzhu08/databricks-datathon/commit/53b31227efff11fb26508887595fc773a4267790) | 2026-11-21 21:02 | Add the nationwide matching run with one output row per original base row |
| [#62](https://github.com/vzhu08/databricks-datathon/pull/62) | [`7832e42`](https://github.com/vzhu08/databricks-datathon/commit/7832e42dd7c5a50962b6ebab571dff01a2dda96c) | 2026-11-21 21:14 | Merge remote-tracking branch 'origin/main' into codex/acq-c-matching |
| [#62](https://github.com/vzhu08/databricks-datathon/pull/62) | [`6ee81bc`](https://github.com/vzhu08/databricks-datathon/commit/6ee81bc60f921140878f9f964cf89825e45b962c) | 2026-11-21 21:16 | Count identifiers over the full base and verify D's metadata hash and sidecar |
| [#62](https://github.com/vzhu08/databricks-datathon/pull/62) | [`275718f`](https://github.com/vzhu08/databricks-datathon/commit/275718fe3979c3a5a490af8c3ee8bbe29fabf0d9) | 2026-11-21 21:25 | Fold Latin accents in names and states, read D's sidecar fields, count campus conflicts |
| [#78](https://github.com/vzhu08/databricks-datathon/pull/78) | [`1b77f87`](https://github.com/vzhu08/databricks-datathon/commit/1b77f87305a9edbe9ae1853d0544d5fd5888057c) | 2026-11-21 21:30 | Bucket state-column text that is not a state or union territory in the national report |
| [#80](https://github.com/vzhu08/databricks-datathon/pull/80) | [`caa529f`](https://github.com/vzhu08/databricks-datathon/commit/caa529fd74aaf61e7060643f151567d82d68fdcd) | 2026-11-21 21:45 | Add the PMNDP dialysis roster importer (SRC-C01) |
| [#80](https://github.com/vzhu08/databricks-datathon/pull/80) | [`bc18596`](https://github.com/vzhu08/databricks-datathon/commit/bc1859630ea48cbbb3e99b477ab5f8afbf514778) | 2026-11-21 21:45 | Say that a profile's date formats replace the defaults |
| [#80](https://github.com/vzhu08/databricks-datathon/pull/80) | [`14dccb1`](https://github.com/vzhu08/databricks-datathon/commit/14dccb1aac527070f51fe99a602cb466541dd681) | 2026-11-21 22:04 | Read the real Andhra Pradesh annex layouts in the PMNDP importer |
| [#80](https://github.com/vzhu08/databricks-datathon/pull/80) | [`172e60c`](https://github.com/vzhu08/databricks-datathon/commit/172e60c2831f4c71637c4ff4aac93ced5d4b64d1) | 2026-11-21 22:12 | Keep campuses apart when documents print different addresses for one name |
| [#80](https://github.com/vzhu08/databricks-datathon/pull/80) | [`acf82f6`](https://github.com/vzhu08/databricks-datathon/commit/acf82f6bfcc257e3e84cdad59ffa481a4fd31a6e) | 2026-11-21 22:17 | Compare roster addresses as ordered words so swapped unit numbers stay apart |
| [#84](https://github.com/vzhu08/databricks-datathon/pull/84) | [`da0713b`](https://github.com/vzhu08/databricks-datathon/commit/da0713b72b9d4a72aa47ebf28ad6e168d384cb53) | 2026-11-21 21:58 | Treat a state label that is not a state as unknown for matching (NAT-C01 second pass) |
| [#84](https://github.com/vzhu08/databricks-datathon/pull/84) | [`7b55d2d`](https://github.com/vzhu08/databricks-datathon/commit/7b55d2da5c488c2b673a474cdd9ac4a8bfa6a0a9) | 2026-11-21 22:11 | Keep unrecognised and missing postal state labels out of PIN state findings |
| [#103](https://github.com/vzhu08/databricks-datathon/pull/103) | [`00236ed`](https://github.com/vzhu08/databricks-datathon/commit/00236ed657ed7b6d4f623795dd89b859cca2f572) | 2026-11-22 00:21 | Add the storm routing replay page (first playable) |
| [#103](https://github.com/vzhu08/databricks-datathon/pull/103) | [`331467c`](https://github.com/vzhu08/databricks-datathon/commit/331467c9933013d88fd28ebfe20ff751caa5e133) | 2026-11-22 00:37 | Compare storm outcomes request by request and refuse malformed replay files |
| [#107](https://github.com/vzhu08/databricks-datathon/pull/107) | [`0c42d9b`](https://github.com/vzhu08/databricks-datathon/commit/0c42d9be245d1968ee4f665aa38022702c43b713) | 2026-11-22 00:30 | Add the campus finder page for driving-time responses |
| [#107](https://github.com/vzhu08/databricks-datathon/pull/107) | [`9db585b`](https://github.com/vzhu08/databricks-datathon/commit/9db585bb857d85c3cb0c3952c2942928b074ab1f) | 2026-11-22 00:38 | Merge branch 'codex/demo-c-storm-ui' into codex/demo-c-live-finder-ui |
| [#107](https://github.com/vzhu08/databricks-datathon/pull/107) | [`075f77b`](https://github.com/vzhu08/databricks-datathon/commit/075f77be378e5942eeb046c2637aea281624c231) | 2026-11-22 00:40 | Tie finder results to their request and label each source on the finder page |
| [#107](https://github.com/vzhu08/databricks-datathon/pull/107) | [`cd09671`](https://github.com/vzhu08/databricks-datathon/commit/cd09671378945cbc5c20b7d1c1d8329b6d1582e3) | 2026-11-22 00:43 | Validate a finder response before wording it, on the file and search paths |
| [#113](https://github.com/vzhu08/databricks-datathon/pull/113) | [`42b2c2c`](https://github.com/vzhu08/databricks-datathon/commit/42b2c2c24532d94b672c3336bdf9c90b1a16c435) | 2026-11-22 01:19 | Make Find care the first demo screen and the storm replay its stress test |
| [#113](https://github.com/vzhu08/databricks-datathon/pull/113) | [`b34acd8`](https://github.com/vzhu08/databricks-datathon/commit/b34acd8ce3c85484afc2158bb102798d5037ab2b) | 2026-11-22 01:30 | Keep an out-of-date answer from being copied or printed |
| [#118](https://github.com/vzhu08/databricks-datathon/pull/118) | [`93604e1`](https://github.com/vzhu08/databricks-datathon/commit/93604e1d8c149805398e21093483c1e0f98269de) | 2026-11-22 02:44 | Add the Find care screen for Databricks Apps over the team's search |
| [#118](https://github.com/vzhu08/databricks-datathon/pull/118) | [`f37589d`](https://github.com/vzhu08/databricks-datathon/commit/f37589dc9362244c738aaa1679edbe13109aefa7) | 2026-11-22 03:12 | Withhold recommendations on real records and make the data mode explicit |
| [#118](https://github.com/vzhu08/databricks-datathon/pull/118) | [`268a605`](https://github.com/vzhu08/databricks-datathon/commit/268a6056ab7d718307f1b2dc612245a503accea2) | 2026-11-22 03:20 | Treat the host or app credentials alone as a warehouse setup problem |
| [#138](https://github.com/vzhu08/databricks-datathon/pull/138) | [`8147310`](https://github.com/vzhu08/databricks-datathon/commit/81473109469c4c8727a3403874abec431ef7db14) | 2026-11-22 03:42 | Redesign the Find care screen around a judge's first minutes |
| [#141](https://github.com/vzhu08/databricks-datathon/pull/141) | [`014eeae`](https://github.com/vzhu08/databricks-datathon/commit/014eeae1f7803737b8f58f828f93e4b01b93a77b) | 2026-11-22 03:52 | Add the operator walkthrough and five demo captures |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`9846cfa`](https://github.com/vzhu08/databricks-datathon/commit/9846cfa054c3f4819039b7bcdebf997063cfeefb) | 2026-11-22 04:20 | Add a fictional patient intake before the Find care answer |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`17d3b94`](https://github.com/vzhu08/databricks-datathon/commit/17d3b948b8ff47d91ac72f7fc7cae76abf89f971) | 2026-11-22 04:28 | Check the confirmed summary before the intake asks for a campus |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`cc3b894`](https://github.com/vzhu08/databricks-datathon/commit/cc3b894b031258cfe3c2b39c5b4fa06b6cbd5eaa) | 2026-11-22 05:25 | Merge remote-tracking branch 'origin/main' into codex/andrew-intake-ui |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`52964c1`](https://github.com/vzhu08/databricks-datathon/commit/52964c1ab449cabece4ceffe0a3ee1be70ec5de0) | 2026-11-22 05:25 | Merge remote-tracking branch 'origin/codex/intake-r-journeys' into codex/andrew-intake-ui |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`bf87cf4`](https://github.com/vzhu08/databricks-datathon/commit/bf87cf4fe5b0279e0e9d3b77254e7016575c84d6) | 2026-11-22 05:35 | Merge remote-tracking branch 'origin/main' into codex/andrew-intake-ui |
| [#153](https://github.com/vzhu08/databricks-datathon/pull/153) | [`b749ea2`](https://github.com/vzhu08/databricks-datathon/commit/b749ea28bd8d76c9f988552bcb0b1c63973e4748) | 2026-11-22 05:41 | Connect the offline intake page to the team's intake engine |
| [#213](https://github.com/vzhu08/databricks-datathon/pull/213) | [`37c92dc`](https://github.com/vzhu08/databricks-datathon/commit/37c92dc711d8f105dc48a8e3c358fac38f9bca3c) | 2026-11-22 05:45 | Trim the extra blank line at the end of the storm UI design notes |

## Not yet on `main`

Two open pull requests by `andrewhgu` hold further commits with the same
author. They are his as well and belong in the table once those pull requests
merge.

- #217: `9a10f8f`, `4752775`
- #316: three merge commits, `9c60043`, `5e35de8`, `e9f0fa9`
