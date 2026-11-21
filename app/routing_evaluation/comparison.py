"""Offline preference evaluation. Outcomes concern reviewer acceptability only."""

from collections import Counter, defaultdict
from math import exp, floor
from random import Random

from app.ranking.urgency import WEIGHTS

from .preferences import FEATURES, SERVICES, prepare

MODELS = ("nearest", "fixed", "learned")
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 17
L2 = 0.1


def _dot(weights, features):
    return sum(w * x for w, x in zip(weights, features))


def _differences(case):
    rows = case["rows"]
    # Ties are usable symmetric targets. Abstentions provide no directional observation.
    pairs = []
    for review in case["reviews"]:
        per_reviewer = []
        for pair in review["preferences"]:
            if pair["choice"] == "abstain":
                continue
            left = rows[pair["left"]]["factors"]
            right = rows[pair["right"]]["factors"]
            x = [left[name] - right[name] for name in FEATURES]
            target = {"left": 1.0, "right": 0.0, "tie": 0.5}[pair["choice"]]
            per_reviewer.append((x, target))
        if per_reviewer:
            pairs.append(per_reviewer)
    if len(pairs) < 2:
        return []
    # Weight each scenario equally, and each participating reviewer equally within it.
    return [(x, target, 1 / len(pairs) / len(observations))
            for observations in pairs for x, target in observations]


def _fit(training):
    fitted = {}
    directional_cases = Counter()
    for urgency, defaults in WEIGHTS.items():
        prior = [defaults[name] / 100 for name in FEATURES]
        weights = prior[:]
        examples = []
        for case in training:
            if case["urgency"] != urgency:
                continue
            pairs = _differences(case)
            if any(y != 0.5 and any(x) for x, y, _ in pairs):
                directional_cases[urgency] += 1
            examples.extend(pairs)
        mass = sum(size for _, _, size in examples)
        if mass:
            # Projected, regularized pairwise logistic regression; all factors favor larger values.
            for _ in range(250):
                grad = [L2 * (w - p) for w, p in zip(weights, prior)]
                for x, target, size in examples:
                    error = (1 / (1 + exp(-_dot(weights, x))) - target) * size / mass
                    for i, value in enumerate(x):
                        grad[i] += error * value
                weights = [max(0.0, w - 0.5 * g) for w, g in zip(weights, grad)]
        fitted[urgency] = weights
    return fitted, directional_cases


def _orders(case, weights):
    rows = list(case["rows"].values())
    nearest = sorted(rows, key=lambda r: (r["travel"], r["facility_id"]))
    def learned_order(row):
        factors = [row["factors"][name] for name in FEATURES]
        return (-_dot(weights[case["urgency"]], factors), row["travel"], row["facility_id"])
    return {name: [r["facility_id"] for r in ranked] for name, ranked in (
        ("nearest", nearest), ("fixed", rows), ("learned", sorted(rows, key=learned_order)))}


def _interval(scores, baseline):
    clusters = defaultdict(list)
    for case, rates in scores:
        clusters[case["cluster"]].append(rates["learned"] - rates[baseline])
    if not clusters:
        return {"delta": None, "ci95": None, "clusters": 0}
    by_cluster = [(sum(values), len(values)) for _, values in sorted(clusters.items())]
    delta = sum(v for v, _ in by_cluster) / sum(n for _, n in by_cluster)
    result = {"delta": delta, "ci95": None, "clusters": len(by_cluster)}
    if len(by_cluster) < 2:
        return result
    rng = Random(BOOTSTRAP_SEED)
    changes = []
    for _ in range(BOOTSTRAP_REPLICATES):
        draw = rng.choices(by_cluster, k=len(by_cluster))
        changes.append(sum(v for v, _ in draw) / sum(n for _, n in draw))
    changes.sort()
    result["ci95"] = [changes[floor(p * (len(changes) - 1))] for p in (0.025, 0.975)]
    return result


def _rate_summary(scores):
    n = len(scores)
    return {"scored_scenarios": n, "top1_acceptable": {
        model: sum(rates[model] for _, rates in scores) / n if n else None for model in MODELS}}


def evaluate(bundle):
    if bundle is None:
        return {"status": "pending_human_labels", "selected": "fixed",
                "reason": "Supply a frozen bundle with independent blinded reviewer judgments."}
    cases = prepare(bundle)
    training = [case for case in cases if case["split"] == "train" and len(case["reviews"]) >= 2]
    testing = [case for case in cases if case["split"] == "test"]
    geo_overlap = sorted({c["geography"] for c in cases if c["split"] == "train"}
                         & {c["geography"] for c in testing})
    if bundle.get("geography_holdout", False) and geo_overlap:
        raise ValueError("Declared geographic holdout includes training geography")
    weights, directional = _fit(training)
    scores = []
    exclusions = Counter()
    selections = []
    travel = defaultdict(lambda: defaultdict(list))
    top3 = []
    for case in testing:
        orders = _orders(case, weights)
        choices = {m: ids[0] if ids else None for m, ids in orders.items()}
        selections.append({"id": case["id"], "choices": choices,
                           "top3": {m: ids[:3] for m, ids in orders.items()}})
        for m, pick in choices.items():
            if pick is not None:
                travel[(case["urgency"], case["travel_metric"])][m].append(case["rows"][pick]["travel"])
        ratings = [r["acceptable_ids"] for r in case["reviews"] if r["acceptable_ids"] is not None]
        if not case["rows"]:
            exclusions["no_eligible_destination"] += 1
        elif len(ratings) < 2:
            exclusions["fewer_than_two_acceptability_judgments"] += 1
        else:
            rates = {model: sum(pick in ballot for ballot in ratings) / len(ratings)
                     for model, pick in choices.items()}
            scores.append((case, rates))
            top3.append({m: sum(bool(set(ids[:3]).intersection(ballot)) for ballot in ratings) / len(ratings)
                         for m, ids in orders.items()})
    intervals = {m: _interval(scores, m) for m in ("nearest", "fixed")}
    scored_ids = {case["id"] for case, _ in scores}
    counts = Counter(c["service"] for c in cases if c["id"] in scored_ids or
                     (c["split"] == "train" and _differences(c)))
    test_services = {case["service"] for case, _ in scores}
    urgency_covered = {case["urgency"] for case, _ in scores} == set(WEIGHTS)
    sufficient = (all(counts[service] >= 20 for service in SERVICES)
                  and test_services == set(SERVICES) and urgency_covered
                  and all(directional[u] > 0 for u in WEIGHTS)
                  and all(v["clusters"] >= 10 for v in intervals.values()))
    benefit = all(v["ci95"] and v["ci95"][0] > 0 for v in intervals.values())
    violations = sum(choice is not None and choice not in case["rows"]
                     for case, rec in zip(testing, selections) for choice in rec["choices"].values())
    if bundle["label_basis"] == "synthetic":
        status = "synthetic_smoke_only"
    elif not any(case["reviews"] for case in cases):
        status = "pending_human_labels"
    elif not sufficient:
        status = "insufficient_evidence"
    else:
        status = "learned_passes_offline_gate" if benefit and violations == 0 else "retain_fixed"
    return {
        "status": status, "selected": "learned" if status == "learned_passes_offline_gate" else "fixed",
        "freeze_id": bundle["freeze_id"], "label_basis": bundle["label_basis"],
        "train_scenarios_with_two_reviewers": len(training), "test_scenarios": len(testing),
        "reviewed_by_service": dict(counts),
        "directional_train_scenarios_by_urgency": dict(directional),
        "test_exclusions": dict(exclusions), "test": _rate_summary(scores),
        "training_test_geography_overlap": geo_overlap,
        "reviewer_pair_outcomes": {part: dict(Counter(p["choice"] for c in cases if c["split"] == part
                                                       for r in c["reviews"] for p in r["preferences"]))
                                   for part in ("train", "test")},
        "top3_acceptable": {m: sum(r[m] for r in top3) / len(top3) if top3 else None for m in MODELS},
        "test_by_urgency": {u: _rate_summary([(c, r) for c, r in scores if c["urgency"] == u])
                            for u in WEIGHTS},
        "mean_top1_travel": [{"urgency": u, "unit": unit, "ranked_scenarios": len(results["fixed"]),
                              "means": {m: sum(v) / len(v) for m, v in results.items()}}
                             for (u, unit), results in sorted(travel.items())],
        "test_by_service": {service: _rate_summary([(c, r) for c, r in scores if c["service"] == service])
                            for service in SERVICES},
        "test_by_geography": {g: _rate_summary([(c, r) for c, r in scores if c["geography"] == g])
                              for g in sorted({c["geography"] for c in testing})},
        "model_coefficients": {u: dict(zip(FEATURES, w)) for u, w in weights.items()},
        "intervals_learned_minus_baseline": intervals,
        "paired_cluster_bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED},
        "eligibility_violations": violations,
        "held_out_choices": selections,
    }
