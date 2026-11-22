# Competition notebook

Open the root submission.ipynb and run all cells with Python 3.10 or later. The notebook verifies
the embedded source and synthetic fixtures, then executes them in an isolated Python process with
the network blocked. Streamlit and the separate enrichment schema validator are optional.
The first cell links to the executable Exploration, Modeling and Impact sections. Exploration
uses published aggregates. Modeling leads with the released Pune maintenance-haemodialysis
lookup and KEM's operator-specific claim. Impact pairs the public contact and verification step
with the separate Pune four-care benchmark. The fictional finder, seed-17 invented-site batch,
and eight-request replay remain under engineering controls. For Free Edition, import the notebook
in the authorized workspace and run all Python cells. Record that workspace check separately from
local notebook execution.

From the submission branch based on a clean, integrated main:

```sh
python tools/submission_notebook.py --source-ref origin/main
python tools/submission_notebook.py --check --execute
```

The check compares the embedded manifest with tracked inputs, their pinned source revision and the
exact generated notebook bytes. The input digest covers the selected source, neutral fixture,
demo driver and generator. It excludes submission.ipynb. An unrelated revision or board update leaves the inputs
unchanged. After an included workflow changes on main, refresh on the submission branch, repeat
the isolated execution and hand the new pin to Oliver on #307.

The packaged scope is the app, contracts, enrichment and ingestion implementations, the service
status implementation and its shared helpers, and the explicit synthetic fixture set in the
generator. Existing live adapters appear as human-readable implementation source and have no
configured credentials or calls in the replay. The packaged Overpass assets retain their SIL Open Font License. The notebook stores no executed cell outputs.

The published national written-area counts, all 57 capability coverage rows, and the five issuer
and lineage examples are notebook Markdown. Their published receipts are linked in the cells and
the narrative does not supply simulation inputs. Refresh when an integrated scenario changes
its allocator, roster or attribution manifest, seeded workload, or verified expected outputs.
Tracked files under app/ and contracts/ already trigger the check. For scenario inputs outside
those roots, add the exact reviewed paths to the generator after integration and clearance.
The deployment-only national directory, named Storm plan and road data are separate from the
notebook. The checked `tools/pune_four_care_neutral.json` is the [#354 neutral input
edition](https://github.com/vzhu08/databricks-datathon/issues/354#issuecomment-7082572887),
SHA-256 `43ee208c8f5c042a90792624cf7f7d9def187ae6a90d949c78257ae97b1f0a07`.
It contains neutral site codes, simulated requests and staffed slots, and modeled travel seconds.
