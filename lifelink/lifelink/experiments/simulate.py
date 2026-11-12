"""Offline simulation used to evaluate the matching strategies (blueprint section 8).

It imports `app.matching` unchanged, so the algorithm under test is exactly the
one the API runs. Everything else (people, demand, supply, behaviour) is
synthetic and is described in ASSUMPTIONS below; results are therefore
*simulated* results and must be reported as such.

Fair-comparison rules
  * All strategies use the SAME hard eligibility filter (category, condition,
    capacity, radius, collectable before deadline).  They differ only in the
    ORDER in which eligible requests are offered the listing.
  * Common random numbers: acceptance, response latency and volunteer delay for a
    given (seed, listing, request) are identical across strategies, so
    differences between strategies are not sampling noise in behaviour.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import matching
from app.matching import Candidate, Listing

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
LAT0, LON0 = 16.50, 80.65
KM_PER_DEG = 111.19
CATEGORIES = ["food", "books", "clothes", "household"]
ORG_TYPES = ["food_bank", "shelter", "orphanage", "school", "library", "ngo", "community"]
URGENCY_WEIGHTS = [0.15, 0.30, 0.30, 0.15, 0.10]       # levels 1..5

ASSUMPTIONS = [
    "Recipients: 40 organisations. 25% are 'hubs' near the city centre (where providers also sit): they "
    "have 2.5x the weekly capacity and file about twice as many requests ('well-connected' organisations).",
    "Demand: Poisson number of requests per recipient over the period (mean 3, hubs 6); quantity log-normal "
    "(median 40, clipped 10-150); urgency 1-5 with probabilities 15/30/30/15/10%; 20% require condition 'good'.",
    "Supply: 160 listings spread uniformly in time; category, provider and condition random; "
    "quantities are rescaled per category so total supply = supply_ratio x total demand.",
    "Deadlines: food 6-48 h, other categories 3-14 days after listing.",
    "Acceptance: probability 0.95 - 0.004 x distance_km (floor 0.5). Response latency is exponential with "
    "mean 8/urgency hours. A rejection or timeout passes the listing to the next-ranked request.",
    "Delivery: volunteer delay uniform 1-10 h plus travel at 25 km/h. Deliveries that arrive after the "
    "deadline are lost (quantity wasted) and the request is re-opened.",
    "Requests expire 7 days after creation. Weekly capacity is enforced on a trailing 168 h window.",
    "Fairness history uses all allocations so far (the whole run is shorter than the 30-day window).",
]


@dataclass
class SimConfig:
    seed: int = 0
    n_recipients: int = 40
    n_providers: int = 8
    days: int = 21
    n_listings: int = 160
    supply_ratio: float = 1.0
    geography: str = "central_hubs"          # or "uniform"
    request_ttl_days: float = 7.0
    hub_fraction: float = 0.25
    radius_km: float = 25.0


@dataclass
class Recipient:
    id: int
    x: float
    y: float
    org_type: str
    capacity: int
    hub: bool
    lat: float = 0.0
    lon: float = 0.0


@dataclass
class Req:
    id: int
    recipient: int
    category: str
    needed: int
    urgency: int
    min_condition: str
    created_h: float
    remaining: int = 0
    received: int = 0


@dataclass
class Lst:
    id: int
    category: str
    qty: int
    condition: str
    t_h: float
    deadline_h: float
    x: float
    y: float
    lat: float = 0.0
    lon: float = 0.0


@dataclass
class Alloc:
    recipient: int
    qty: int
    reserved_h: float
    ok: bool = True


def _to_latlon(x: float, y: float) -> tuple[float, float]:
    lat = LAT0 + y / KM_PER_DEG
    lon = LON0 + x / (KM_PER_DEG * math.cos(math.radians(LAT0)))
    return lat, lon


def _disk(rng: random.Random, radius: float) -> tuple[float, float]:
    r, a = radius * math.sqrt(rng.random()), rng.random() * 2 * math.pi
    return r * math.cos(a), r * math.sin(a)


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def generate(cfg: SimConfig):
    rng = random.Random(cfg.seed * 7919 + 13)
    providers = []
    for _ in range(cfg.n_providers):
        if cfg.geography == "central_hubs":
            providers.append((rng.gauss(0, 4), rng.gauss(0, 4)))
        else:
            providers.append(_disk(rng, cfg.radius_km))
    n_hubs = round(cfg.n_recipients * cfg.hub_fraction)
    recipients = []
    for i in range(cfg.n_recipients):
        hub = cfg.geography == "central_hubs" and i < n_hubs
        if cfg.geography == "central_hubs":
            x, y = (rng.gauss(0, 3), rng.gauss(0, 3)) if hub else _disk(rng, cfg.radius_km)
        else:
            x, y = _disk(rng, cfg.radius_km)
            hub = i < n_hubs                         # hubs still file more requests / have more capacity
        r = Recipient(i, x, y, rng.choice(ORG_TYPES), 300 if hub else 120, hub)
        r.lat, r.lon = _to_latlon(x, y)
        recipients.append(r)

    horizon = cfg.days * 24.0
    requests: list[Req] = []
    for rec in recipients:
        for _ in range(_poisson(rng, 6 if rec.hub else 3)):
            needed = int(min(150, max(10, rng.lognormvariate(math.log(40), 0.6))))
            requests.append(Req(len(requests), rec.id, rng.choice(CATEGORIES), needed,
                                rng.choices([1, 2, 3, 4, 5], URGENCY_WEIGHTS)[0],
                                "good" if rng.random() < 0.2 else "any", rng.random() * horizon, needed, 0))
    demand = {c: sum(q.needed for q in requests if q.category == c) for c in CATEGORIES}

    raw = []
    for i in range(cfg.n_listings):
        cat = rng.choice(CATEGORIES)
        t = rng.random() * horizon
        life = rng.uniform(6, 48) if cat == "food" else rng.uniform(72, 336)
        px, py = rng.choice(providers)
        cond = rng.choices(["new", "good", "fair"], [0.1, 0.6, 0.3])[0]
        raw.append([i, cat, rng.lognormvariate(math.log(60), 0.5), cond, t, t + life, px, py])
    base = {c: sum(r[2] for r in raw if r[1] == c) for c in CATEGORIES}
    listings = []
    for i, cat, q, cond, t, dl, px, py in sorted(raw, key=lambda r: r[4]):
        if base[cat] <= 0 or demand[cat] <= 0:
            continue
        qty = max(1, round(q * cfg.supply_ratio * demand[cat] / base[cat]))
        l = Lst(i, cat, qty, cond, t, dl, px, py)
        l.lat, l.lon = _to_latlon(px, py)
        listings.append(l)
    return recipients, requests, listings


def _crn(seed: int, listing_id: int, request_id: int):
    r = random.Random((seed * 1_000_003 + listing_id) * 1_000_033 + request_id)
    return r.random(), r.expovariate(1.0), r.random()


def run(cfg: SimConfig, strategy: str, weights: Optional[dict] = None,
        fairness_lambda: float = matching.FAIRNESS_LAMBDA) -> dict:
    recipients, requests, listings = generate(cfg)
    by_rec: dict[int, list[Req]] = {}
    for q in requests:
        by_rec.setdefault(q.recipient, []).append(q)
    allocs: dict[int, list[Alloc]] = {r.id: [] for r in recipients}
    ttl_h = cfg.request_ttl_days * 24

    delivered = late_loss = listed = 0
    accept_delays, dist_weighted = [], 0.0
    delivered_to_req: dict[int, int] = {}

    def capacity_left(rid: int, t: float) -> int:
        used = sum(a.qty for a in allocs[rid] if a.ok and a.reserved_h >= t - 168.0)
        return recipients[rid].capacity - used

    for L in listings:
        listed += L.qty
        now = EPOCH + timedelta(hours=L.t_h)
        listing = Listing(L.id, L.category, L.condition, L.qty, EPOCH + timedelta(hours=L.deadline_h), L.lat, L.lon)
        cands = []
        for q in requests:
            if q.category != L.category or q.remaining <= 0 or not (q.created_h <= L.t_h < q.created_h + ttl_h):
                continue
            rec = recipients[q.recipient]
            asked = sum(x.needed for x in by_rec[q.recipient] if x.created_h <= L.t_h)
            got = sum(a.qty for a in allocs[q.recipient] if a.ok)
            cands.append(Candidate(
                request_id=q.id, recipient_id=rec.id, org_id=rec.id, org_name=f"org{rec.id}", org_type=rec.org_type,
                lat=rec.lat, lon=rec.lon, category=q.category, quantity_needed=q.needed, remaining_need=q.remaining,
                urgency=q.urgency, min_condition=q.min_condition, created_at=EPOCH + timedelta(hours=q.created_h),
                capacity_remaining=capacity_left(rec.id, L.t_h), requested_30d=asked, received_30d=got))
        if not cands:
            continue
        ranked, _ = matching.rank_candidates(listing, cands, now, strategy, weights, fairness_lambda)
        avail, t_offer = L.qty, L.t_h
        for r in ranked:
            if avail <= 0 or t_offer + matching.PREP_HOURS > L.deadline_h:
                break
            c, q = r.candidate, requests[r.candidate.request_id]
            if r.distance_km / matching.AVG_SPEED_KMH + matching.PREP_HOURS > L.deadline_h - t_offer:
                continue
            qty = min(avail, q.remaining, capacity_left(c.recipient_id, t_offer))
            if qty <= 0:
                continue
            u_acc, u_lat, u_delay = _crn(cfg.seed, L.id, q.id)
            p_accept = min(0.95, max(0.5, 0.95 - 0.004 * r.distance_km))
            t_resp = t_offer + u_lat * (8.0 / q.urgency)
            if u_acc > p_accept or t_resp > L.deadline_h:
                t_offer = t_resp                      # rejected / timed out: next candidate
                continue
            avail -= qty
            q.remaining -= qty
            a = Alloc(c.recipient_id, qty, t_offer)
            allocs[c.recipient_id].append(a)
            accept_delays.append(t_resp - L.t_h)
            t_del = t_resp + 1.0 + 9.0 * u_delay + r.distance_km / matching.AVG_SPEED_KMH
            if t_del <= L.deadline_h:
                delivered += qty
                q.received += qty
                delivered_to_req[q.id] = delivered_to_req.get(q.id, 0) + qty
                dist_weighted += qty * r.distance_km
            else:
                late_loss += qty
                q.remaining += qty                    # transfer failed: request re-opens
                a.ok = False
            t_offer = t_resp

    # ---- metrics
    total_demand = sum(q.needed for q in requests)
    urgent_demand = sum(q.needed for q in requests if q.urgency >= 4)
    urgent_got = sum(q.received for q in requests if q.urgency >= 4)
    per_rec = {}
    for q in requests:
        d = per_rec.setdefault(q.recipient, [0, 0])
        d[0] += q.needed
        d[1] += q.received
    ratios = [min(1.0, got / need) for need, got in per_rec.values() if need > 0]
    s, sq = sum(ratios), sum(x * x for x in ratios)
    jain = (s * s) / (len(ratios) * sq) if sq > 0 else 0.0
    need_total = sum(n for n, _ in per_rec.values()) or 1
    got_total = sum(g for _, g in per_rec.values())
    tvd = (0.5 * sum(abs(n / need_total - (g / got_total if got_total else 0.0)) for n, g in per_rec.values())
           if got_total else 1.0)
    hub_ids = {r.id for r in recipients if r.hub}
    hub_need = sum(n for rid, (n, _) in per_rec.items() if rid in hub_ids) / need_total
    hub_got = (sum(g for rid, (_, g) in per_rec.items() if rid in hub_ids) / got_total) if got_total else 0.0
    unclaimed = listed - delivered - late_loss
    return {
        "redistribution_rate": 100.0 * delivered / listed if listed else 0.0,
        "deadline_success": 100.0 * delivered / (delivered + late_loss) if (delivered + late_loss) else 100.0,
        "unclaimed_rate": 100.0 * unclaimed / listed if listed else 0.0,
        "late_loss_rate": 100.0 * late_loss / listed if listed else 0.0,
        "hours_to_acceptance": statistics.fmean(accept_delays) if accept_delays else float("nan"),
        "demand_fulfilment": 100.0 * delivered / total_demand if total_demand else 0.0,
        "urgent_fulfilment": 100.0 * urgent_got / urgent_demand if urgent_demand else 0.0,
        "jain_fairness": jain,
        "need_share_deviation": tvd,
        "hub_share_gap": 100.0 * (hub_got - hub_need),
        "mean_distance_km": dist_weighted / delivered if delivered else float("nan"),
        "listed": listed, "delivered": delivered,
    }
