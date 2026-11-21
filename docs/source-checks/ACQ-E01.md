# ACQ-E01 source-link check

Checked the eight registry entry URLs with the web fetcher on 2026-11-21 UTC. Results reflect the HTML or PDF returned by the fetcher, which may serve crawled copies. No dataset downloads were made.

| Source | Exact URL checked | Time (UTC) | Observed title / publisher | Result | Note |
| --- | --- | --- | --- | --- | --- |
| HOT OSM report | <https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/hotosm_ind_health_facilities_report.html> | 18:03:52 | Health Facilities of India · OpenStreetMap | `opens` | The report shows an OpenStreetMap snapshot dated 2026-10-09. |
| NHP mirror | <https://bharatlas.com/view/nhp_hospitals> | 18:03:52 | Hospitals directory (NHP 2025) · bharatlas | `opens` | The landing page credits the National Health Portal as its upstream source. |
| Rajasthan trauma directory | <https://roadsafetycell.rkcl.in/pageView/token=d3doM0tvbjVvNmVEbkJRM2YycHVUdz09> | 18:03:52 | Trauma Centres · RKCL Road Safety Web Portal / Rajasthan State Road Safety Cell | `opens` | The trauma-centre table was visible in the returned page. The fetcher reported the checked URL as the final URL. |
| RGHS hospital PDF | <https://rghs.rajasthan.gov.in/GovernmentHospitalList.pdf> | 18:03:52<br>18:04:09 (retry) | Unavailable | `timeout` | The web fetcher timed out on both attempts. |
| MoHFW trauma PDF | <https://www.mohfw-dohfw.gov.in/static/uploads/2025/11/444e913a7f93a8a4ac9aeaa8658abd62.pdf> | 18:03:52 | National Programme for Prevention and Management of Trauma and Burn Injuries · Ministry of Health and Family Welfare | `opens` | The web fetcher returned a readable 14-page PDF. |
| NABH directory | <https://nabh.co/find-a-healthcare-organisation/> | 18:03:52<br>18:04:09 (retry) | Unavailable | `broken` | The web fetcher returned HTTP 403 on both attempts. No login or CAPTCHA page was visible. |
| Overture getting-data docs | <https://docs.overturemaps.org/getting-data/> | 18:03:52 | Quickstart · Overture Maps Foundation | `opens` | The documentation includes instructions for downloading building footprints by area. |
| India Post PIN directory | <https://www.data.gov.in/resource/all-india-pincode-directory-till-last-month> | 18:03:52<br>18:04:09 (retry) | Unavailable | `timeout` | The web fetcher timed out on both attempts. |

## Demo reference

We check which facility a record refers to separately from what the evidence says about its services. Historical records describe what was reported at the time, and current availability needs up-to-date confirmation. Building footprints can help corroborate a location, and assessing care quality requires separate evidence.

[Acquisition contract v1.0.0](../implementation/ACQUISITION_CONTRACT.md)
