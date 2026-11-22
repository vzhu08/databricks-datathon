"""Compare J's November OSM edition with the frozen October candidates."""
import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from .collector_editions import verify
from .hot_adapter import frozen_hot_links
from .ledger import SERVICES, attach_joint_trace, build, canonical, lines, pinned, require, sha, write_release

PACKET = 'c462210064b3f64921b0ec567b9eb856a414f0212fbddd6605a4f14fcd1160af'
PREVIOUS = '191fbfae50f42c32e14faacf064d7b72bcc67b83b62b7f61f850d4e477cc2fa8'
LANE = 'J_OSM_20261101'
HOT_LANE = 'J_HOT_20261009_v3'
STATEMENT_MANIFEST = '2d1e2293733b309d86ebe4fdf6a909b6f5c0ef3dd43368b43d5225e5b2a6a491'


def november_observation(row, edition_id, candidates):
    survey = row['tags'].get('source')
    require(row['campus_id'] is None and row['facility_id'] is None and
            row['patient_status'] == 'unconfirmed' and row['source_family'] == 'osm' and
            row['independence'] == 'shared_origin', 'unexpected_pbf_scope')
    require(row['service_observation_date'] is None and row['service_observed_date'] is None,
            'unexpected_pbf_service_date')
    # Every link names the *older* matched feature and preserves its stage and rank.
    links = [dict(link, link_basis='same_typed_osm_id_across_editions')
             for _, link in sorted(candidates.items())]
    return dict(observation_id=row['observation_id'], edition_id=edition_id, source_facility_id=row['osm_id'],
                modality=row['service'], claim_type='map_' + row['category'], claim_scope=row['source_key'],
                claim_value=row['raw_value'], units=None, raw_text=row['raw_value'],
                locator={'source_key':row['source_key'], 'all_original_locators':row['locators'],
                         'payload_sha256':row['payload_sha256'], 'version':row['version']},
                original_occurrence_key=None, source_date=None, effective_from=None, effective_until=None,
                source_attribution=survey, historical_survey_year=2019 if survey=='2C_Indore Field Visit 2019' else None,
                polarity='inconclusive', independence_status='shared_origin', multi_campus=False,
                mirror_of=[], supersedes=[], target_links=links, source_record=row)


def load_packet(directory, joint_rows, candidates, previous_hot):
    outer = verify(directory, PACKET)
    children = {r['directory']:r['manifest_sha256'] for r in outer['packets']}
    manifest = verify(directory/'pbf', children['pbf'])
    hot = verify(directory/'hot', children['hot'])
    prior_rows = {r['observation_id']:r['source_record'] for r in previous_hot['observations']}
    bundled = lines(directory/'hot'/'ledger.jsonl')
    require({r['observation_id']: r for r in bundled} == prior_rows and len(bundled) == len(prior_rows),
            'different_october_comparator')
    drift = json.loads((directory/'pbf'/'edition-drift.json').read_bytes())
    absent = set(drift['hot_ids_absent_from_pbf'])
    new_objects = set(drift['pbf_retained_ids_not_in_hot'])
    rows = lines(directory/'pbf'/'ledger.jsonl')
    ids = {r['osm_id'] for r in rows}
    require(not ids.intersection(absent) and len(rows)==manifest['ledger_observations'], 'invalid_pbf_edition')
    snapshot = 'hot_osm_health:'+hot['source_edition']['sha256']
    trace = frozen_hot_links(ids-new_objects,snapshot,joint_rows,candidates)
    source = manifest['source_edition']
    eid = 'geofabrik-osm:'+source['sha256']
    edition = dict(edition_id=eid, content_sha256=source['sha256'], publisher=source['publisher'],
                   source_url=source['source_url'], reuse_terms=manifest['attribution']+'; '+manifest['license_url'],
                   sharing_scope='private_datathon_four_readers', geographic_scope=source['scope'],
                   source_family='osm', origin_status='known', published_date=source['publication_date'],
                   retrieved_at=source['first_retrieved_at'], source_manifest=manifest,
                   outer_manifest_sha256=PACKET, october_snapshot=snapshot, observed_map_date=source['snapshot_date'])
    out = []
    for row in rows:
        require(row['edition_sha256']==source['sha256'] and row['locators'], 'invalid_pbf_source_reference')
        out.append(november_observation(row,eid,trace.get(row['osm_id'],{})))
    return dict(schema_version='service-evidence-lane-v1', lane=LANE, editions=[edition], observations=out)


def pairs(rows):
    return {(l['occurrence_key'], r['modality']) for r in rows for l in r['target_links']}


def comparison(artifact, previous_dir, previous):
    current = artifact['observations']
    prior_again = [r for r in current if r['lane'] != LANE]
    require(prior_again==previous, 'prior_observations_changed')
    for table in ('occurrences','decisions','editions','source_register'):
        values = artifact[table]
        if table=='editions':
            added = {r['raw']['edition_id'] for r in current if r['lane']==LANE}
            values = [r for r in values if r['edition_id'] not in added]
        with gzip.open(previous_dir/(table+'.jsonl.gz'),'rb') as stream:
            require(all(line == canonical(row)+b'\n' for line,row in zip(stream,values,strict=True)),
                    'prior_'+table+'_changed')
    old = [r['raw'] for r in previous]
    hot = [r['raw'] for r in previous if r['lane']==HOT_LANE]
    pbf = [r['raw'] for r in current if r['lane']==LANE]
    hot_ids = {r['source_facility_id'] for r in hot}
    pbf_ids = {r['source_facility_id'] for r in pbf}
    before, after = pairs(old), pairs(pbf)
    fid_state = {r['original']['facility_id']:r['identity']['state'] for r in artifact['occurrences']}
    extra = after - before
    new_by_state = Counter((fid_state[key], service) for key, service in extra)
    new_by_modality = Counter(service for key, service in extra)
    target_services = set(SERVICES)
    previous_target = {pair for pair in before if pair[1] in target_services}
    additional_target = {pair for pair in extra if pair[1] in target_services}
    measures = []
    for s in SERVICES:
        h = [r for r in hot if r['modality']==s and r['claim_type']=='map_explicit_service_tag']
        p = [r for r in pbf if r['modality']==s and r['claim_type']=='map_explicit_service_tag']
        hi, pi = ({r['source_facility_id'] for r in subset} for subset in (h,p))
        measures.append(dict(service=s, october_objects=len(hi), november_objects=len(pi),
                             shared_typed_ids=len(pi&hi), additional_november_objects=len(pi-hi),
                             november_explicit_candidate_occurrences=len(pairs(p)),
                             additional_explicit_candidate_occurrences_vs_hot=len(pairs(p)-pairs(h)),
                             first_candidate_modality_pairs_vs_previous=len(pairs(p)-before)))
    survey = Counter((r['claim_scope'],r['claim_value']) for r in pbf if r['historical_survey_year']==2019)
    return dict(prior_manifest_sha256=PREVIOUS, packet_sha256=PACKET, previously_loaded=len(previous),
                pbf_observations=len(pbf), pbf_locators=sum(len(r['locator']['all_original_locators']) for r in pbf),
                pbf_linked_observations=sum(bool(r['target_links']) for r in pbf),
                pbf_unlinked_observations=sum(not r['target_links'] for r in pbf),
                pbf_source_objects=len(pbf_ids), observation_bearing_objects_in_both_editions=len(hot_ids&pbf_ids),
                prior_candidate_occurrence_modality_pairs=len(before), pbf_candidate_occurrence_modality_pairs=len(after),
                shared_candidate_occurrence_modality_pairs=len(after&before),
                additional_candidate_occurrence_modality_pairs=len(after-before),
                combined_candidate_occurrence_modality_pairs=len(after|before),
                first_candidate_occurrences_over_prior_collector_evidence=len({f for f,_ in after}-{f for f,_ in before}),
                target_decision_denominator=len(artifact['decisions']),
                prior_target_candidate_pairs=len(previous_target),
                additional_target_candidate_pairs=len(additional_target),
                combined_target_candidate_pairs=len(previous_target | additional_target),
                additional_by_modality=dict(sorted(new_by_modality.items())),
                exact_service_tags=measures, shared_osm_origin_families=1,
                indore_facility_tags=[dict(field=k,value=v,count=n) for (k,v),n in sorted(survey.items()) if k in {'facility:mri','facility:trauma'}],
                marginal_candidates_by_state_service=[dict(state=r['state'],service=r['service'],originals=r['original_occurrences'],
                    additional_pairs=new_by_state[r['state'],r['service']]) for r in artifact['report']['state_service']],
                marginal_confirmed_campuses=0, marginal_admitted_campus_service_pairs=0,
                clinical_decision_transitions=0, original_statement_comparison=None)


def record_statement_totals(directory, report):
    manifest = verify(directory, STATEMENT_MANIFEST)
    name = 'statement-grain-aggregate.json'
    aggregate = json.loads((directory / name).read_bytes())
    population = report['population']
    require(aggregate['whole_dataset_digests']['original_payload_multiset'] ==
            population['original_payload_multiset_sha256'], 'statement_population_hash_changed')
    require(aggregate['population']['original_occurrences'] == population['occurrences'] and
            aggregate['population']['distinct_upstream_ids'] == population['distinct_upstream_ids'] and
            aggregate['decisions']['decision_count'] == population['decisions'], 'statement_population_changed')
    assignments = {s: aggregate['by_service'][s]['distinct_span_service_assignments'] for s in SERVICES}
    require(assignments == report['expected_original_field_spans'], 'statement_service_totals_changed')
    # The producer verified the locators inside the narrower audience. This edition receives counts only.
    report['original_statement_coverage'] = 'owner_verified_aggregate_only'
    report['original_statement_aggregate'] = {
        'manifest_sha256': STATEMENT_MANIFEST,
        'payload_sha256': manifest['files'][name]['sha256'],
        'distinct_original_spans': aggregate['span_assignment_totals']['distinct_original_spans'],
        'distinct_span_service_assignments': sum(assignments.values()),
        'spans_assigned_to_multiple_services': aggregate['span_assignment_totals']['spans_assigned_to_multiple_services'],
        'assignments_by_service': assignments,
        'occurrence_missingness': aggregate['occurrence_missingness'],
        'by_service': aggregate['by_service'],
        'source_scope': manifest['scope'],
        'row_level_locators_received': False,
    }


def extend(previous_dir, packet_dir, candidate_trace, statement_dir, output):
    manifest = verify(previous_dir, PREVIOUS)
    trace_pin = manifest["inputs"]["joint_archive"]["members"]["candidate-delta.jsonl.gz"]
    pinned(candidate_trace, trace_pin["sha256"])
    population = lines(previous_dir / "occurrences.jsonl.gz")
    prior_observations = lines(previous_dir / "observations.jsonl.gz")
    editions = {e["edition_id"]: e for e in lines(previous_dir / "editions.jsonl.gz")}
    rows_by_lane = defaultdict(list)
    for entry in prior_observations:
        rows_by_lane[entry["lane"]].append(entry["raw"])

    packages = []
    for lane, rows in sorted(rows_by_lane.items()):
        sources = sorted({row["edition_id"] for row in rows})
        packages.append(dict(schema_version="service-evidence-lane-v1", lane=lane,
                             observations=rows, editions=[editions[s] for s in sources]))
    hot = next(pkg for pkg in packages if pkg["lane"] == HOT_LANE)
    joint = [row["joint_identity"] for row in population]
    with gzip.open(candidate_trace, "rt", encoding="utf-8") as stream:
        additional = load_packet(packet_dir, joint, map(json.loads, stream), hot)
    packages.append(additional)

    report = json.loads((previous_dir / "report.json").read_bytes())
    states = {row["state"] for row in report["state_service"]}
    artifact = build([row["original"] for row in population], [row["identity"] for row in population],
                     lines(previous_dir / "decisions.jsonl.gz"), packages, geography_buckets=states)
    attach_joint_trace(artifact, joint)
    artifact["source_register"] = lines(previous_dir / "source_register.jsonl.gz")
    artifact["report"]["november_osm_comparison"] = comparison(artifact, previous_dir, prior_observations)
    record_statement_totals(statement_dir, artifact["report"])
    provenance = dict(manifest["inputs"])
    provenance["statement_grain_manifest_sha256"] = STATEMENT_MANIFEST
    provenance["prior_manifest_sha256"] = PREVIOUS
    provenance["lanes"] = provenance["lanes"] + [{"lane": LANE, "source_manifest_sha256": PACKET}]
    provenance["code_sha256"] = {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}
    return write_release(output, artifact, provenance)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--previous", type=Path, required=True)
    cli.add_argument("--packet", type=Path, required=True)
    cli.add_argument("--candidate-trace", type=Path, required=True)
    cli.add_argument("--statement-aggregate", type=Path, required=True)
    cli.add_argument("--out-dir", type=Path, required=True)
    args = cli.parse_args()
    print(extend(args.previous, args.packet, args.candidate_trace, args.statement_aggregate, args.out_dir))
