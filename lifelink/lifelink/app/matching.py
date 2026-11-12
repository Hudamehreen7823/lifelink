"""Matching and fairness engine.

Pure functions only (no database, no clock): the same code is used by the REST
service *and* by the offline experiment harness, so the evaluation measures the
algorithm that is actually deployed.

Scoring (blueprint section 5). Every component is normalised to 0-100:

    S(i, r) = w_d*D + w_u*U + w_n*N + w_c*C + w_t*T

    D  proximity            100 * (1 - distance / MAX_RADIUS_KM)
    U  urgency              20 * urgency_level            (1..5 -> 20..100)
    N  unmet need           100 * remaining_need / quantity_requested
    C  compatibility        100 * (0.5 * org_type_affinity + 0.5 * quantity_fit)
    T  deadline suitability 100 * min(1, slack_hours / SLACK_TARGET_HOURS)

Fairness-aware variant ("lifelink_fair"):

    S_fair = (1 - lambda) * S + lambda * F

    F  fairness  100 * (1 - received_30d / requested_30d)  -- the share of this
                 recipient's recent demand that is still unmet.  Recipients who
                 have already received a lot recently are pushed down, so
                 well-connected organisations cannot absorb every listing.
                 Urgent requests (urgency 5) always get F = 100: history never
                 penalises an urgent need.

Hard eligibility filters are applied *before* scoring and are never overridden
by fairness: category, recipient verification, minimum condition, remaining
need, weekly capacity, service radius, and collectability before the deadline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

DEFAULT_WEIGHTS = {
    "proximity": 0.20,
    "urgency": 0.25,
    "unmet_need": 0.25,
    "compatibility": 0.20,
    "deadline": 0.10,
}
FAIRNESS_LAMBDA = 0.20
URGENT_LEVEL = 5
MAX_RADIUS_KM = 50.0
AVG_SPEED_KMH = 25.0
PREP_HOURS = 1.0
SLACK_TARGET_HOURS = 24.0

STRATEGIES = ("lifelink_fair", "lifelink", "nearest", "chronological")
CONDITION_RANK = {"any": 0, "fair": 1, "good": 2, "new": 3}

TYPE_AFFINITY = {
    "food": {"food_bank": 1.0, "shelter": 1.0, "orphanage": 1.0, "community": 0.7, "ngo": 0.6,
             "school": 0.5, "library": 0.1},
    "books": {"school": 1.0, "library": 1.0, "orphanage": 0.8, "community": 0.7, "ngo": 0.6,
              "shelter": 0.5, "food_bank": 0.3},
    "clothes": {"shelter": 1.0, "orphanage": 1.0, "ngo": 0.8, "community": 0.8, "food_bank": 0.6,
                "school": 0.5, "library": 0.2},
    "household": {"shelter": 1.0, "community": 0.8, "ngo": 0.8, "orphanage": 0.8, "food_bank": 0.5,
                  "school": 0.4, "library": 0.2},
}
DEFAULT_AFFINITY = 0.6


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Listing:
    id: int
    category: str
    condition: str
    quantity_available: int
    deadline: datetime
    lat: float
    lon: float


@dataclass
class Candidate:
    request_id: int
    recipient_id: int
    org_id: int
    org_name: str
    org_type: str
    lat: float
    lon: float
    category: str
    quantity_needed: int
    remaining_need: int
    urgency: int
    min_condition: str
    created_at: datetime
    capacity_remaining: int
    requested_30d: int = 0
    received_30d: int = 0
    verified: bool = True


@dataclass
class Ranked:
    candidate: Candidate
    components: dict
    score_weighted: float
    score_fair: float
    distance_km: float
    travel_hours: float
    slack_hours: float
    rank: int = 0
    ranks: dict = field(default_factory=dict)
    score: float = 0.0

    @property
    def request_id(self) -> int:
        return self.candidate.request_id


@dataclass
class Exclusion:
    candidate: Candidate
    reason: str


def assess(listing: Listing, cand: Candidate, now: datetime):
    """Return (reason_or_None, distance_km, travel_hours, slack_hours)."""
    d = haversine_km(listing.lat, listing.lon, cand.lat, cand.lon)
    travel = d / AVG_SPEED_KMH
    left = (listing.deadline - now).total_seconds() / 3600.0
    slack = left - PREP_HOURS - travel
    if not cand.verified:
        return "recipient is not verified", d, travel, slack
    if cand.category != listing.category:
        return "category mismatch", d, travel, slack
    if cand.remaining_need <= 0:
        return "request already fully covered", d, travel, slack
    if CONDITION_RANK[listing.condition] < CONDITION_RANK[cand.min_condition]:
        return "item condition is below the minimum required", d, travel, slack
    if cand.capacity_remaining <= 0:
        return "weekly capacity reached", d, travel, slack
    if d > MAX_RADIUS_KM:
        return f"outside the {MAX_RADIUS_KM:.0f} km service radius", d, travel, slack
    if slack < 0:
        return "cannot be collected before the deadline", d, travel, slack
    return None, d, travel, slack


def _components(listing: Listing, cand: Candidate, d: float, slack: float) -> dict:
    proximity = 100.0 * max(0.0, 1.0 - d / MAX_RADIUS_KM)
    urgency = 20.0 * cand.urgency
    unmet = 100.0 * min(1.0, cand.remaining_need / max(1, cand.quantity_needed))
    hi = max(listing.quantity_available, cand.remaining_need, 1)
    lo = min(listing.quantity_available, cand.remaining_need)
    qty_fit = lo / hi
    affinity = TYPE_AFFINITY.get(listing.category, {}).get(cand.org_type, DEFAULT_AFFINITY)
    compat = 100.0 * (0.5 * affinity + 0.5 * qty_fit)
    deadline = 100.0 * max(0.0, min(1.0, slack / SLACK_TARGET_HOURS))
    if cand.urgency >= URGENT_LEVEL:
        fairness = 100.0
    else:
        requested = max(cand.requested_30d, cand.quantity_needed, 1)
        fairness = 100.0 * (1.0 - min(1.0, cand.received_30d / requested))
    return {
        "proximity": round(proximity, 2),
        "urgency": round(urgency, 2),
        "unmet_need": round(unmet, 2),
        "compatibility": round(compat, 2),
        "deadline": round(deadline, 2),
        "fairness": round(fairness, 2),
    }


def _weighted(components: dict, weights: dict) -> float:
    total = sum(weights.values()) or 1.0
    return sum(weights[k] * components[k] for k in DEFAULT_WEIGHTS) / total


def evaluate(listing: Listing, candidates, now: datetime, weights: Optional[dict] = None,
             fairness_lambda: float = FAIRNESS_LAMBDA):
    """Filter + score. Returns (eligible: list[Ranked] unordered, excluded: list[Exclusion])."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    eligible, excluded = [], []
    for cand in candidates:
        reason, d, travel, slack = assess(listing, cand, now)
        if reason:
            excluded.append(Exclusion(cand, reason))
            continue
        comps = _components(listing, cand, d, slack)
        s = _weighted(comps, w)
        s_fair = (1.0 - fairness_lambda) * s + fairness_lambda * comps["fairness"]
        eligible.append(Ranked(cand, comps, round(s, 3), round(s_fair, 3), d, travel, slack))
    return eligible, excluded


def _sort_key(strategy: str):
    if strategy == "chronological":
        return lambda r: (r.candidate.created_at, r.candidate.request_id)
    if strategy == "nearest":
        return lambda r: (r.distance_km, r.candidate.request_id)
    if strategy == "lifelink":
        return lambda r: (-r.score_weighted, r.distance_km, r.candidate.request_id)
    if strategy == "lifelink_fair":
        return lambda r: (-r.score_fair, r.distance_km, r.candidate.request_id)
    raise ValueError(f"unknown strategy {strategy!r}")


def order(eligible, strategy: str):
    return sorted(eligible, key=_sort_key(strategy))


def rank_candidates(listing: Listing, candidates, now: datetime, strategy: str = "lifelink_fair",
                    weights: Optional[dict] = None, fairness_lambda: float = FAIRNESS_LAMBDA,
                    with_ranks: bool = False):
    """Ranked list (best first) under `strategy`, plus exclusions with reasons."""
    eligible, excluded = evaluate(listing, candidates, now, weights, fairness_lambda)
    ranked = order(eligible, strategy)
    if with_ranks:
        for s in STRATEGIES:
            for pos, r in enumerate(order(eligible, s), start=1):
                r.ranks[s] = pos
    for pos, r in enumerate(ranked, start=1):
        r.rank = pos
        r.score = r.score_fair if strategy == "lifelink_fair" else r.score_weighted
    return ranked, excluded
