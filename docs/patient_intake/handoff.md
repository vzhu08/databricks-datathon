# Reviewed destinations for patient navigation

The patient assessment and destination review make separate decisions. A provider's
suggestion to consult a specialty can be useful whether or not reviewed destinations
exist. MRI, dialysis and trauma care need independent clinical authority for the
current encounter. The application must carry unrepresented needs separately.

The existing warehouse search remains withheld for real destinations. The source-only
pilot in #221 may produce service evidence, while campus identity, reviewed coordinates,
onsite service and display permission each need their own reviewed decision before a
campus can enter the patient finder. The evidence owner must reconcile these decisions
in a pinned, private release and record the source locators, effective dates and the scope
of each permission. Availability has its own evidence and effective window. An unknown
availability value must stay unknown.

`handoff._screen_reviewed_destinations` consumes an internal projection of that release.
The loader must authenticate the release independently and supply the exact release
reference and evaluation date. Each campus carries its identity and coordinate reviews,
its display permission, and the per-service review beside the existing scorer inputs.
The screen checks each prerequisite and reuses the scorer's dated service and mandatory
capability rules before any travel lookup. The returned records are private server
inputs. A public result needs a separate display projection of permitted fields.

With no approved release or eligible campus, the expected patient outcome is
`no_reviewed_destination` with zero routing attempts. The existing TomTom adapter
has its own geographic shortlist and budget gates. Patient-purpose permission,
approved attribution, and origin consent remain prerequisites for an adapter that
sends coordinates. Current integration and provider decisions are tracked on #223 and #227.

## Runtime callback

Pass `PatientHandoff()` as the optional `handoff` callable to
`PatientIntakeService`. The service validates the encounter-bound confirmation
before invoking the callback. The callback re-reads the server-owned handle
and checks the completed assessment against that revision. Only a completed
consultation disposition can initiate order or evidence lookup. The default result
for a current completion is `{"state": "no_reviewed_destination"}`. Continue
showing the original assessment guidance independently. A stale or mismatched
completion returns `assessment_blocked`. Session exceptions from a deleted or
expired handle follow the session boundary's content-free error path.

For an integration control, inject `read_verified_order(handle, revision)`
and `read_reviewed_release(as_of)` on the server. The order reader resolves
authority for that exact encounter revision and returns a supported `service`
and explicit `required_capabilities`, or no order. The release reader resolves
the private reviewed release at the supplied date. Its display permission must
cover the returned facility identifier. A release or order read failure yields
`navigation_unavailable`. An unrepresented order service yields
`unsupported_service`. The callback checks the encounter again after
reading the release and returns `reviewed_destinations` with only eligible
display identifiers and unknown availability. The test uses fictional records
via the same ports. Current product composition supplies neither port.

The optional ports are an engineering boundary for reviewed destination
eligibility. The confirmation receipt and a provider's consultation suggestion
do not enter the order reader as evidence. Availability, origin consent, travel
provider terms, display approval, and conservative routing configuration need
their own integration decisions before travel is offered.
