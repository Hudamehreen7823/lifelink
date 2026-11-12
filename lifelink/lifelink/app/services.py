"""Business logic: allocation lifecycle, delivery tracking, audit, analytics.

Lifecycle of an allocation:

    offered --accept--> accepted --pickup--> picked_up --deliver--> delivered --confirm--> completed
       |  \\--reject--> rejected  (quantity released, auto-offers re-filled)
       \\---expiry---> expired    (quantity released, auto-offers re-filled)
    accepted + deadline passed without pickup --> expired (lapsed; quantity is lost)

Quantity safety: a reservation does
    UPDATE resources SET quantity_available = quantity_available - :q
    WHERE id = :id AND quantity_available >= :q
inside a BEGIN IMMEDIATE transaction; the CHECK constraint on the table is the
last line of defence.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import matching, notifier
from .db import tx
from .matching import Candidate, Listing

OFFER_TTL = timedelta(hours=24)
COMMITTING = ("offered", "accepted", "picked_up", "delivered", "completed")
COMMITTING_SQL = "('offered','accepted','picked_up','delivered','completed')"


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------------- time
def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------- audit / notify
def audit(conn, actor_id: Optional[int], entity_type: str, entity_id: int, action: str,
          details: Optional[dict] = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs(actor_id, entity_type, entity_id, action, details, timestamp) VALUES (?,?,?,?,?,?)",
        (actor_id, entity_type, entity_id, action, json.dumps(details) if details else None, iso(utcnow())),
    )


def notify(conn, user_id: Optional[int], message: str) -> None:
    if user_id is None:
        return
    ts = iso(utcnow())
    conn.execute("INSERT INTO notifications(user_id, message, channel, sent_at, status) VALUES (?,?,?,?,?)",
                 (user_id, message, "in_app", ts, "sent"))
    if notifier.smtp_configured():
        conn.execute("INSERT INTO notifications(user_id, message, channel, sent_at, status) VALUES (?,?,?,?,?)",
                     (user_id, message, "email", ts, "pending"))


# --------------------------------------------------------------------------- listings & requests
def _need(conn, resource_id: int):
    r = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    if not r:
        raise ServiceError(404, "Listing not found")
    return r


def _own_resource(conn, actor, resource_id: int):
    r = _need(conn, resource_id)
    if actor["role"] != "admin" and r["provider_id"] != actor["id"]:
        raise ServiceError(403, "You can only manage your own listings")
    return r


def create_resource(conn, actor, data: dict) -> dict:
    now = utcnow()
    deadline = parse_dt(data["deadline"])
    if deadline <= now:
        raise ServiceError(422, "The deadline must be in the future")
    lat, lon = data.get("latitude"), data.get("longitude")
    if lat is None or lon is None:
        org = conn.execute("SELECT o.latitude, o.longitude FROM organizations o JOIN users u ON u.organization_id=o.id "
                           "WHERE u.id = ?", (actor["id"],)).fetchone()
        if not org:
            raise ServiceError(422, "Provide a pickup location (latitude and longitude)")
        lat, lon = org["latitude"], org["longitude"]
    with tx(conn):
        cur = conn.execute(
            """INSERT INTO resources(provider_id, category, title, quantity, quantity_available, unit, condition,
                                      deadline, latitude, longitude, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
            (actor["id"], data["category"], data["title"], data["quantity"], data["quantity"],
             data.get("unit", "items"), data.get("condition", "good"), iso(deadline), lat, lon, iso(now)),
        )
        rid = cur.lastrowid
        audit(conn, actor["id"], "resource", rid, "created", {"quantity": data["quantity"], "category": data["category"]})
    return get_resource(conn, rid)


def _resource_select() -> str:
    return f"""SELECT r.*, COALESCE(o.name, u.name) AS provider_name,
                      COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                                WHERE a.resource_id = r.id AND a.status IN {COMMITTING_SQL}), 0) AS allocated_qty,
                      COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                                WHERE a.resource_id = r.id AND a.status = 'completed'), 0) AS delivered_qty
               FROM resources r JOIN users u ON u.id = r.provider_id
               LEFT JOIN organizations o ON o.id = u.organization_id"""


def _decorate_resource(row: dict, now: datetime) -> dict:
    if row["status"] == "withdrawn":
        state = "withdrawn"
    elif parse_dt(row["deadline"]) <= now:
        state = "expired"
    elif row["quantity_available"] == 0:
        state = "fully_allocated"
    else:
        state = "available"
    row["state"] = state
    return row


def get_resource(conn, resource_id: int) -> dict:
    row = conn.execute(_resource_select() + " WHERE r.id = ?", (resource_id,)).fetchone()
    if not row:
        raise ServiceError(404, "Listing not found")
    return _decorate_resource(dict(row), utcnow())


def list_resources(conn, actor, category=None, state=None, mine=False, q=None, lat=None, lon=None,
                   radius_km=None, limit=200) -> list[dict]:
    sql, args = _resource_select() + " WHERE 1=1", []
    if category:
        sql += " AND r.category = ?"; args.append(category)
    if mine:
        sql += " AND r.provider_id = ?"; args.append(actor["id"])
    if q:
        sql += " AND r.title LIKE ?"; args.append(f"%{q}%")
    sql += " ORDER BY r.id DESC LIMIT ?"; args.append(limit)
    now = utcnow()
    out = []
    for row in conn.execute(sql, args).fetchall():
        d = _decorate_resource(dict(row), now)
        if state and d["state"] != state:
            continue
        if lat is not None and lon is not None:
            d["distance_km"] = round(matching.haversine_km(lat, lon, d["latitude"], d["longitude"]), 2)
            if radius_km is not None and d["distance_km"] > radius_km:
                continue
        out.append(d)
    if lat is not None and lon is not None:
        out.sort(key=lambda x: x["distance_km"])
    return out


def update_resource(conn, actor, resource_id: int, data: dict) -> dict:
    with tx(conn):
        r = _own_resource(conn, actor, resource_id)
        reserved = r["quantity"] - r["quantity_available"]
        if data.get("withdraw"):
            active = conn.execute(f"SELECT COUNT(*) c FROM allocations WHERE resource_id=? AND status IN "
                                  f"('offered','accepted','picked_up','delivered')", (resource_id,)).fetchone()["c"]
            if active:
                raise ServiceError(409, "Cannot withdraw a listing while offers or deliveries are in progress")
            conn.execute("UPDATE resources SET status='withdrawn' WHERE id=?", (resource_id,))
            audit(conn, actor["id"], "resource", resource_id, "withdrawn")
        if data.get("quantity") is not None:
            new_q = data["quantity"]
            if new_q < reserved or new_q <= 0:
                raise ServiceError(409, f"Quantity cannot go below the {reserved} already reserved")
            conn.execute("UPDATE resources SET quantity=?, quantity_available=quantity_available + (? - quantity) "
                         "WHERE id=?", (new_q, new_q, resource_id))
            audit(conn, actor["id"], "resource", resource_id, "quantity_changed", {"from": r["quantity"], "to": new_q})
        if data.get("deadline"):
            dl = parse_dt(data["deadline"])
            if dl <= utcnow():
                raise ServiceError(422, "The deadline must be in the future")
            conn.execute("UPDATE resources SET deadline=? WHERE id=?", (iso(dl), resource_id))
            audit(conn, actor["id"], "resource", resource_id, "deadline_changed", {"to": iso(dl)})
        if data.get("title"):
            conn.execute("UPDATE resources SET title=? WHERE id=?", (data["title"], resource_id))
    return get_resource(conn, resource_id)


def create_request(conn, actor, data: dict) -> dict:
    with tx(conn):
        cur = conn.execute(
            """INSERT INTO resource_requests(recipient_id, category, description, quantity_needed, urgency,
                                              min_condition, status, created_at) VALUES (?,?,?,?,?,?, 'open', ?)""",
            (actor["id"], data["category"], data.get("description", ""), data["quantity_needed"], data["urgency"],
             data.get("min_condition", "any"), iso(utcnow())),
        )
        rid = cur.lastrowid
        audit(conn, actor["id"], "request", rid, "created", {"quantity": data["quantity_needed"], "urgency": data["urgency"]})
    return get_request(conn, rid)


def _request_select() -> str:
    return f"""SELECT rr.*, o.name AS org_name, o.type AS org_type,
               COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                         WHERE a.request_id = rr.id AND a.status IN {COMMITTING_SQL}), 0) AS committed_qty,
               COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                         WHERE a.request_id = rr.id AND a.status = 'completed'), 0) AS received_qty
               FROM resource_requests rr JOIN users u ON u.id = rr.recipient_id
               LEFT JOIN organizations o ON o.id = u.organization_id"""


def get_request(conn, request_id: int) -> dict:
    row = conn.execute(_request_select() + " WHERE rr.id = ?", (request_id,)).fetchone()
    if not row:
        raise ServiceError(404, "Request not found")
    d = dict(row)
    d["remaining_need"] = max(0, d["quantity_needed"] - d["committed_qty"])
    return d


def list_requests(conn, actor, status=None, limit=200) -> list[dict]:
    sql, args = _request_select() + " WHERE 1=1", []
    if actor["role"] == "recipient":
        sql += " AND rr.recipient_id = ?"; args.append(actor["id"])
    elif actor["role"] != "admin":
        raise ServiceError(403, "Only recipients and admins can view requests")
    if status:
        sql += " AND rr.status = ?"; args.append(status)
    sql += " ORDER BY rr.id DESC LIMIT ?"; args.append(limit)
    out = []
    for row in conn.execute(sql, args).fetchall():
        d = dict(row)
        d["remaining_need"] = max(0, d["quantity_needed"] - d["committed_qty"])
        out.append(d)
    return out


def cancel_request(conn, actor, request_id: int) -> dict:
    with tx(conn):
        r = conn.execute("SELECT * FROM resource_requests WHERE id=?", (request_id,)).fetchone()
        if not r:
            raise ServiceError(404, "Request not found")
        if actor["role"] != "admin" and r["recipient_id"] != actor["id"]:
            raise ServiceError(403, "You can only cancel your own requests")
        active = conn.execute("SELECT COUNT(*) c FROM allocations WHERE request_id=? AND status IN "
                              "('offered','accepted','picked_up','delivered')", (request_id,)).fetchone()["c"]
        if active:
            raise ServiceError(409, "Cannot cancel while offers or deliveries are in progress")
        if r["status"] != "open":
            raise ServiceError(409, f"Request is already {r['status']}")
        conn.execute("UPDATE resource_requests SET status='cancelled' WHERE id=?", (request_id,))
        audit(conn, actor["id"], "request", request_id, "cancelled")
    return get_request(conn, request_id)


# --------------------------------------------------------------------------- matching
def load_candidates(conn, res, now: datetime) -> list[Candidate]:
    since7, since30 = iso(now - timedelta(days=7)), iso(now - timedelta(days=30))
    base = conn.execute(
        f"""SELECT rr.id request_id, rr.recipient_id, rr.category, rr.quantity_needed, rr.urgency, rr.min_condition,
                   rr.created_at, u.verification_status, o.id org_id, o.name org_name, o.type org_type,
                   o.latitude, o.longitude, o.capacity_per_week,
                   rr.quantity_needed - COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                        WHERE a.request_id = rr.id AND a.status IN {COMMITTING_SQL}), 0) AS remaining
            FROM resource_requests rr JOIN users u ON u.id = rr.recipient_id
            JOIN organizations o ON o.id = u.organization_id
            WHERE rr.status = 'open' AND rr.category = ?
              AND NOT EXISTS (SELECT 1 FROM allocations a WHERE a.request_id = rr.id AND a.resource_id = ?
                              AND a.status IN ('rejected','expired'))""",
        (res["category"], res["id"]),
    ).fetchall()
    if not base:
        return []

    def per_recipient(sql, *args):
        return {r["rid"]: r["q"] for r in conn.execute(sql, args).fetchall()}

    used7 = per_recipient(
        f"""SELECT rr.recipient_id rid, SUM(a.quantity_allocated) q FROM allocations a
            JOIN resource_requests rr ON rr.id = a.request_id
            WHERE a.status IN {COMMITTING_SQL} AND a.reserved_at >= ? GROUP BY rr.recipient_id""", since7)
    got30 = per_recipient(
        f"""SELECT rr.recipient_id rid, SUM(a.quantity_allocated) q FROM allocations a
            JOIN resource_requests rr ON rr.id = a.request_id
            WHERE a.status IN {COMMITTING_SQL} AND a.reserved_at >= ? GROUP BY rr.recipient_id""", since30)
    asked30 = per_recipient(
        """SELECT recipient_id rid, SUM(quantity_needed) q FROM resource_requests
           WHERE created_at >= ? AND status != 'cancelled' GROUP BY recipient_id""", since30)
    out = []
    for r in base:
        rid = r["recipient_id"]
        out.append(Candidate(
            request_id=r["request_id"], recipient_id=rid, org_id=r["org_id"], org_name=r["org_name"],
            org_type=r["org_type"], lat=r["latitude"], lon=r["longitude"], category=r["category"],
            quantity_needed=r["quantity_needed"], remaining_need=r["remaining"], urgency=r["urgency"],
            min_condition=r["min_condition"], created_at=parse_dt(r["created_at"]),
            capacity_remaining=r["capacity_per_week"] - used7.get(rid, 0),
            requested_30d=asked30.get(rid, 0), received_30d=got30.get(rid, 0),
            verified=r["verification_status"] == "verified",
        ))
    return out


def _listing(res) -> Listing:
    return Listing(res["id"], res["category"], res["condition"], res["quantity_available"],
                   parse_dt(res["deadline"]), res["latitude"], res["longitude"])


def compute_ranking(conn, res, now: datetime, strategy: str = "lifelink_fair"):
    return matching.rank_candidates(_listing(res), load_candidates(conn, res, now), now, strategy, with_ranks=True)


def _persist_matches(conn, resource_id: int, ranked, strategy: str, now: datetime) -> dict[int, int]:
    ids = {}
    for r in ranked:
        conn.execute(
            """INSERT INTO matches(resource_id, request_id, score, rank, components, algorithm_version, created_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(resource_id, request_id) DO UPDATE SET score=excluded.score, rank=excluded.rank,
                   components=excluded.components, algorithm_version=excluded.algorithm_version,
                   created_at=excluded.created_at""",
            (resource_id, r.request_id, r.score, r.rank, json.dumps(r.components), strategy, iso(now)),
        )
        ids[r.request_id] = conn.execute("SELECT id FROM matches WHERE resource_id=? AND request_id=?",
                                         (resource_id, r.request_id)).fetchone()["id"]
    return ids


def _ranked_to_dict(r, match_id: Optional[int]) -> dict:
    c = r.candidate
    return {
        "match_id": match_id, "request_id": c.request_id, "recipient_org": c.org_name, "org_type": c.org_type,
        "rank": r.rank, "score": round(r.score, 2), "score_weighted": r.score_weighted, "score_fair": r.score_fair,
        "components": r.components, "ranks": r.ranks, "distance_km": round(r.distance_km, 2),
        "travel_hours": round(r.travel_hours, 2), "slack_hours": round(r.slack_hours, 1),
        "urgency": c.urgency, "quantity_needed": c.quantity_needed, "remaining_need": c.remaining_need,
        "capacity_remaining": c.capacity_remaining, "received_30d": c.received_30d,
        "requested_30d": c.requested_30d, "request_created_at": iso(c.created_at),
        "latitude": c.lat, "longitude": c.lon,
        "suggested_quantity": max(0, min(r.candidate.remaining_need, r.candidate.capacity_remaining)),
    }


def get_matches(conn, actor, resource_id: int, strategy: str = "lifelink_fair") -> dict:
    if strategy not in matching.STRATEGIES:
        raise ServiceError(422, f"strategy must be one of {', '.join(matching.STRATEGIES)}")
    expire_stale(conn)
    now = utcnow()
    with tx(conn):
        res = _own_resource(conn, actor, resource_id)
        ranked, excluded = compute_ranking(conn, res, now, strategy)
        ids = _persist_matches(conn, resource_id, ranked, strategy, now)
    return {
        "resource_id": resource_id, "strategy": strategy, "quantity_available": res["quantity_available"],
        "listing": {"title": res["title"], "latitude": res["latitude"], "longitude": res["longitude"],
                    "deadline": res["deadline"]},
        "weights": matching.DEFAULT_WEIGHTS, "fairness_lambda": matching.FAIRNESS_LAMBDA,
        "candidates": [_ranked_to_dict(r, ids[r.request_id]) for r in ranked],
        "excluded": [{"request_id": e.candidate.request_id, "recipient_org": e.candidate.org_name, "reason": e.reason}
                     for e in excluded],
    }


# --------------------------------------------------------------------------- allocation
def _offer(conn, actor_id: Optional[int], resource_id: int, request_id: int, quantity: Optional[int],
           auto: bool, now: datetime) -> int:
    """Reserve quantity and create an 'offered' allocation. Caller holds the transaction."""
    res = _need(conn, resource_id)
    if res["status"] != "open":
        raise ServiceError(409, "Listing has been withdrawn")
    deadline = parse_dt(res["deadline"])
    if deadline <= now:
        raise ServiceError(409, "Listing deadline has passed")
    ranked, excluded = compute_ranking(conn, res, now)
    target = next((r for r in ranked if r.request_id == request_id), None)
    if target is None:
        reason = next((e.reason for e in excluded if e.candidate.request_id == request_id),
                      "request is not open or does not match this listing")
        raise ServiceError(409, f"This recipient is not eligible: {reason}")
    cand = target.candidate
    qty = min(res["quantity_available"], cand.remaining_need, cand.capacity_remaining)
    if quantity is not None:
        qty = min(qty, quantity)
    if qty <= 0:
        raise ServiceError(409, "Nothing left to allocate")
    cur = conn.execute("UPDATE resources SET quantity_available = quantity_available - ? "
                       "WHERE id = ? AND quantity_available >= ?", (qty, resource_id, qty))
    if cur.rowcount != 1:
        raise ServiceError(409, "Not enough quantity left on this listing")
    match_ids = _persist_matches(conn, resource_id, ranked, "lifelink_fair", now)
    expires = min(now + OFFER_TTL, deadline)
    cur = conn.execute(
        """INSERT INTO allocations(match_id, resource_id, request_id, quantity_allocated, status, auto,
                                   reserved_at, expires_at) VALUES (?,?,?,?, 'offered', ?, ?, ?)""",
        (match_ids[request_id], resource_id, request_id, qty, 1 if auto else 0, iso(now), iso(expires)),
    )
    aid = cur.lastrowid
    audit(conn, actor_id, "allocation", aid, "offered",
          {"resource_id": resource_id, "request_id": request_id, "quantity": qty, "rank": target.rank,
           "score": round(target.score, 2), "auto": auto})
    notify(conn, cand.recipient_id,
           f"New offer: {qty} × {res['title']} ({res['category']}). Respond before {iso(expires)}.")
    return aid


def create_offer(conn, actor, resource_id: int, request_id: int, quantity: Optional[int] = None) -> dict:
    expire_stale(conn)
    with tx(conn):
        _own_resource(conn, actor, resource_id)
        aid = _offer(conn, actor["id"], resource_id, request_id, quantity, False, utcnow())
    return get_allocation(conn, aid)


def _auto_fill(conn, resource_id: int, actor_id: Optional[int], now: datetime) -> list[int]:
    made = []
    for _ in range(100):
        res = _need(conn, resource_id)
        if res["status"] != "open" or res["quantity_available"] <= 0 or parse_dt(res["deadline"]) <= now:
            break
        ranked, _ = compute_ranking(conn, res, now)
        if not ranked:
            break
        try:
            made.append(_offer(conn, actor_id, resource_id, ranked[0].request_id, None, True, now))
        except ServiceError:
            break
    return made


def auto_allocate(conn, actor, resource_id: int) -> list[dict]:
    expire_stale(conn)
    with tx(conn):
        _own_resource(conn, actor, resource_id)
        ids = _auto_fill(conn, resource_id, actor["id"], utcnow())
    if not ids:
        raise ServiceError(409, "No eligible recipients for this listing right now")
    return [get_allocation(conn, i) for i in ids]


def _release(conn, alloc, new_status: str, now: datetime, actor_id: Optional[int], note: str = "") -> None:
    cur = conn.execute("UPDATE allocations SET status=?, responded_at=? WHERE id=? AND status='offered'",
                       (new_status, iso(now), alloc["id"]))
    if cur.rowcount != 1:
        return
    conn.execute("UPDATE resources SET quantity_available = quantity_available + ? WHERE id = ?",
                 (alloc["quantity_allocated"], alloc["resource_id"]))
    audit(conn, actor_id, "allocation", alloc["id"], new_status, {"released": alloc["quantity_allocated"], "note": note})
    res = _need(conn, alloc["resource_id"])
    notify(conn, res["provider_id"], f"Offer #{alloc['id']} for '{res['title']}' was {new_status}; "
                                      f"{alloc['quantity_allocated']} units are available again.")
    if alloc["auto"]:
        _auto_fill(conn, alloc["resource_id"], None, now)


def respond_to_offer(conn, actor, match_id: int, accept: bool, note: str = "") -> dict:
    expire_stale(conn)
    now = utcnow()
    expired_now = False
    with tx(conn):
        m = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not m:
            raise ServiceError(404, "Match not found")
        req = conn.execute("SELECT * FROM resource_requests WHERE id=?", (m["request_id"],)).fetchone()
        if req["recipient_id"] != actor["id"]:
            raise ServiceError(403, "Only the requesting organisation can respond to this offer")
        alloc = conn.execute("SELECT * FROM allocations WHERE match_id=? AND status='offered' "
                             "ORDER BY id DESC LIMIT 1", (match_id,)).fetchone()
        if not alloc:
            raise ServiceError(409, "There is no pending offer for this match")
        if parse_dt(alloc["expires_at"]) <= now:
            _release(conn, alloc, "expired", now, None)
            expired_now = True
        elif accept:
            conn.execute("UPDATE allocations SET status='accepted', responded_at=? WHERE id=?", (iso(now), alloc["id"]))
            audit(conn, actor["id"], "allocation", alloc["id"], "accepted")
            res = _need(conn, alloc["resource_id"])
            notify(conn, res["provider_id"], f"Offer #{alloc['id']} for '{res['title']}' was accepted. "
                                              f"A volunteer can now be assigned.")
        else:
            _release(conn, alloc, "rejected", now, actor["id"], note)
    if expired_now:
        raise ServiceError(409, "This offer has expired")
    return get_allocation(conn, alloc["id"])


def expire_stale(conn) -> int:
    """Expire overdue offers and lapse accepted allocations that missed the resource deadline."""
    now = utcnow()
    n = iso(now)
    pending = conn.execute("SELECT id FROM allocations WHERE status='offered' AND expires_at <= ?", (n,)).fetchall()
    lapsed = conn.execute(
        """SELECT a.id FROM allocations a JOIN resources r ON r.id = a.resource_id
           WHERE a.status = 'accepted' AND r.deadline <= ?""", (n,)).fetchall()
    if not pending and not lapsed:
        return 0
    count = 0
    with tx(conn):
        for row in pending:
            alloc = conn.execute("SELECT * FROM allocations WHERE id=?", (row["id"],)).fetchone()
            if alloc and alloc["status"] == "offered":
                _release(conn, alloc, "expired", now, None, "offer timed out")
                count += 1
        for row in lapsed:
            alloc = conn.execute("SELECT * FROM allocations WHERE id=?", (row["id"],)).fetchone()
            if alloc and alloc["status"] == "accepted":
                conn.execute("UPDATE allocations SET status='expired' WHERE id=?", (alloc["id"],))
                conn.execute("UPDATE deliveries SET status='cancelled' WHERE allocation_id=? AND status='assigned'",
                             (alloc["id"],))
                audit(conn, None, "allocation", alloc["id"], "lapsed", {"reason": "deadline passed before pickup"})
                res = _need(conn, alloc["resource_id"])
                req = conn.execute("SELECT recipient_id FROM resource_requests WHERE id=?", (alloc["request_id"],)).fetchone()
                notify(conn, res["provider_id"], f"Allocation #{alloc['id']} lapsed: '{res['title']}' passed its deadline.")
                notify(conn, req["recipient_id"], f"Allocation #{alloc['id']} lapsed: '{res['title']}' passed its deadline.")
                count += 1
    return count


_ALLOC_SELECT = """
    SELECT a.id, a.match_id, a.resource_id, a.request_id, a.quantity_allocated, a.status, a.auto,
           a.reserved_at, a.expires_at, a.responded_at,
           r.title AS resource_title, r.category, r.unit, r.deadline AS resource_deadline, r.condition,
           r.latitude AS pickup_lat, r.longitude AS pickup_lon, r.provider_id,
           COALESCE(po.name, pu.name) AS provider_name,
           rr.recipient_id, rr.urgency, ro.name AS recipient_org, ro.latitude AS dropoff_lat,
           ro.longitude AS dropoff_lon, ro.address AS dropoff_address, po.address AS pickup_address,
           m.rank AS match_rank, m.score AS match_score,
           d.id AS delivery_id, d.volunteer_id, vu.name AS volunteer_name, d.status AS delivery_status,
           d.confirmation_status, d.pickup_time, d.delivery_time, d.deadline_met
    FROM allocations a
    JOIN resources r ON r.id = a.resource_id
    JOIN users pu ON pu.id = r.provider_id
    LEFT JOIN organizations po ON po.id = pu.organization_id
    JOIN resource_requests rr ON rr.id = a.request_id
    JOIN users ru ON ru.id = rr.recipient_id
    LEFT JOIN organizations ro ON ro.id = ru.organization_id
    JOIN matches m ON m.id = a.match_id
    LEFT JOIN deliveries d ON d.allocation_id = a.id
    LEFT JOIN users vu ON vu.id = d.volunteer_id
"""


def get_allocation(conn, allocation_id: int) -> dict:
    row = conn.execute(_ALLOC_SELECT + " WHERE a.id = ?", (allocation_id,)).fetchone()
    if not row:
        raise ServiceError(404, "Allocation not found")
    return dict(row)


def list_allocations(conn, actor, status=None, scope=None, limit=300) -> list[dict]:
    expire_stale(conn)
    sql, args = _ALLOC_SELECT + " WHERE 1=1", []
    role = actor["role"]
    if role == "recipient":
        sql += " AND rr.recipient_id = ?"; args.append(actor["id"])
    elif role == "provider":
        sql += " AND r.provider_id = ?"; args.append(actor["id"])
    elif role == "volunteer":
        mine = "d.volunteer_id = ?"
        open_ = "(a.status = 'accepted' AND d.id IS NULL)"
        if scope == "open":
            sql += f" AND {open_}"
        elif scope == "mine":
            sql += f" AND {mine}"; args.append(actor["id"])
        else:
            sql += f" AND ({open_} OR {mine})"; args.append(actor["id"])
    if status:
        sql += " AND a.status = ?"; args.append(status)
    sql += " ORDER BY a.id DESC LIMIT ?"; args.append(limit)
    return rows(conn.execute(sql, args))


# --------------------------------------------------------------------------- delivery
def assign_volunteer(conn, actor, allocation_id: int, volunteer_id: Optional[int] = None) -> dict:
    expire_stale(conn)
    now = utcnow()
    with tx(conn):
        a = conn.execute("SELECT * FROM allocations WHERE id=?", (allocation_id,)).fetchone()
        if not a:
            raise ServiceError(404, "Allocation not found")
        res = _need(conn, a["resource_id"])
        if actor["role"] == "volunteer":
            volunteer_id = actor["id"]
        elif actor["role"] == "provider":
            if res["provider_id"] != actor["id"]:
                raise ServiceError(403, "You can only assign volunteers to your own listings")
        elif actor["role"] != "admin":
            raise ServiceError(403, "Not allowed to assign volunteers")
        if volunteer_id is None:
            raise ServiceError(422, "volunteer_id is required")
        vol = conn.execute("SELECT * FROM users WHERE id=? AND role='volunteer'", (volunteer_id,)).fetchone()
        if not vol:
            raise ServiceError(404, "Volunteer not found")
        if vol["verification_status"] != "verified":
            raise ServiceError(409, "Volunteer has not been verified yet")
        if a["status"] != "accepted":
            raise ServiceError(409, "Only accepted allocations can be assigned to a volunteer")
        if conn.execute("SELECT 1 FROM deliveries WHERE allocation_id=?", (allocation_id,)).fetchone():
            raise ServiceError(409, "A volunteer is already assigned")
        cur = conn.execute("INSERT INTO deliveries(allocation_id, volunteer_id, status, assigned_at) "
                           "VALUES (?,?, 'assigned', ?)", (allocation_id, volunteer_id, iso(now)))
        audit(conn, actor["id"], "delivery", cur.lastrowid, "volunteer_assigned",
              {"allocation_id": allocation_id, "volunteer_id": volunteer_id})
        req = conn.execute("SELECT recipient_id FROM resource_requests WHERE id=?", (a["request_id"],)).fetchone()
        notify(conn, volunteer_id, f"Delivery task: pick up '{res['title']}' before {res['deadline']}.")
        notify(conn, req["recipient_id"], f"{vol['name']} will deliver '{res['title']}'.")
        notify(conn, res["provider_id"], f"{vol['name']} will collect '{res['title']}'.")
    return get_allocation(conn, allocation_id)


def update_delivery_status(conn, actor, delivery_id: int, status: str) -> dict:
    expire_stale(conn)
    now = utcnow()
    with tx(conn):
        d = conn.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if not d:
            raise ServiceError(404, "Delivery not found")
        if actor["role"] == "volunteer":
            if d["volunteer_id"] != actor["id"]:
                raise ServiceError(403, "This delivery is assigned to another volunteer")
        elif actor["role"] != "admin":
            raise ServiceError(403, "Only the assigned volunteer can update delivery status")
        nxt = {"assigned": "picked_up", "picked_up": "delivered"}
        if nxt.get(d["status"]) != status:
            raise ServiceError(409, f"A delivery that is '{d['status']}' cannot move to '{status}'")
        a = conn.execute("SELECT * FROM allocations WHERE id=?", (d["allocation_id"],)).fetchone()
        res = _need(conn, a["resource_id"])
        req = conn.execute("SELECT recipient_id FROM resource_requests WHERE id=?", (a["request_id"],)).fetchone()
        if status == "picked_up":
            if parse_dt(res["deadline"]) <= now:
                raise ServiceError(409, "The listing deadline has passed; pickup is no longer allowed")
            conn.execute("UPDATE deliveries SET status='picked_up', pickup_time=? WHERE id=?", (iso(now), delivery_id))
            conn.execute("UPDATE allocations SET status='picked_up' WHERE id=?", (a["id"],))
            audit(conn, actor["id"], "delivery", delivery_id, "picked_up")
            notify(conn, req["recipient_id"], f"'{res['title']}' has been picked up and is on its way.")
        else:
            met = 1 if now <= parse_dt(res["deadline"]) else 0
            conn.execute("UPDATE deliveries SET status='delivered', delivery_time=?, deadline_met=? WHERE id=?",
                         (iso(now), met, delivery_id))
            conn.execute("UPDATE allocations SET status='delivered' WHERE id=?", (a["id"],))
            audit(conn, actor["id"], "delivery", delivery_id, "delivered", {"deadline_met": bool(met)})
            notify(conn, req["recipient_id"], f"'{res['title']}' was delivered. Please confirm receipt.")
    return get_allocation(conn, d["allocation_id"])


def confirm_delivery(conn, actor, delivery_id: int, confirmed: bool = True, note: str = "") -> dict:
    now = utcnow()
    with tx(conn):
        d = conn.execute("SELECT * FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
        if not d:
            raise ServiceError(404, "Delivery not found")
        a = conn.execute("SELECT * FROM allocations WHERE id=?", (d["allocation_id"],)).fetchone()
        req = conn.execute("SELECT * FROM resource_requests WHERE id=?", (a["request_id"],)).fetchone()
        if req["recipient_id"] != actor["id"]:
            raise ServiceError(403, "Only the receiving organisation can confirm this delivery")
        if d["status"] != "delivered" or d["confirmation_status"] != "pending":
            raise ServiceError(409, "This delivery is not waiting for confirmation")
        res = _need(conn, a["resource_id"])
        if confirmed:
            conn.execute("UPDATE deliveries SET confirmation_status='confirmed', note=? WHERE id=?", (note, delivery_id))
            conn.execute("UPDATE allocations SET status='completed' WHERE id=?", (a["id"],))
            got = conn.execute("SELECT COALESCE(SUM(quantity_allocated),0) s FROM allocations "
                               "WHERE request_id=? AND status='completed'", (req["id"],)).fetchone()["s"]
            if got >= req["quantity_needed"]:
                conn.execute("UPDATE resource_requests SET status='fulfilled' WHERE id=?", (req["id"],))
            audit(conn, actor["id"], "delivery", delivery_id, "confirmed", {"quantity": a["quantity_allocated"]})
            notify(conn, res["provider_id"], f"Receipt of '{res['title']}' was confirmed. Thank you.")
            notify(conn, d["volunteer_id"], "Delivery confirmed by the recipient. Thank you.")
        else:
            conn.execute("UPDATE deliveries SET confirmation_status='disputed', note=? WHERE id=?", (note, delivery_id))
            audit(conn, actor["id"], "delivery", delivery_id, "disputed", {"note": note})
            notify(conn, res["provider_id"], f"Receipt of '{res['title']}' was disputed: {note or 'no reason given'}")
    return get_allocation(conn, d["allocation_id"])


# --------------------------------------------------------------------------- analytics
def jain_index(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s, sq = sum(values), sum(v * v for v in values)
    return None if sq == 0 else (s * s) / (len(values) * sq)


def impact(conn) -> dict:
    expire_stale(conn)
    now = utcnow()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    listed = one("SELECT COALESCE(SUM(quantity),0) FROM resources WHERE status='open'")
    delivered = one("SELECT COALESCE(SUM(quantity_allocated),0) FROM allocations WHERE status='completed'")
    pipeline = {s: one("SELECT COALESCE(SUM(quantity_allocated),0) FROM allocations WHERE status=?", s)
                for s in ("offered", "accepted", "picked_up", "delivered")}
    unclaimed = one("SELECT COALESCE(SUM(quantity_available),0) FROM resources WHERE status='open' AND deadline <= ?",
                    iso(now))
    lost = one("SELECT COALESCE(SUM(a.quantity_allocated),0) FROM allocations a WHERE a.id IN "
               "(SELECT entity_id FROM audit_logs WHERE entity_type='allocation' AND action='lapsed')")
    tta = conn.execute(
        """SELECT AVG((julianday(a.responded_at) - julianday(r.created_at)) * 24.0)
           FROM allocations a JOIN resources r ON r.id = a.resource_id
           WHERE a.status IN ('accepted','picked_up','delivered','completed') AND a.responded_at IS NOT NULL"""
    ).fetchone()[0]
    dl = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN d.deadline_met = 1 THEN a.quantity_allocated END),0) ok,
                  COALESCE(SUM(a.quantity_allocated),0) total
           FROM deliveries d JOIN allocations a ON a.id = d.allocation_id
           WHERE d.status = 'delivered'""").fetchone()
    by_cat = rows(conn.execute(
        """SELECT r.category, SUM(r.quantity) listed,
                  COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a JOIN resources r2 ON r2.id=a.resource_id
                            WHERE r2.category = r.category AND a.status='completed'),0) delivered
           FROM resources r WHERE r.status='open' GROUP BY r.category"""))
    orgs = rows(conn.execute(
        f"""SELECT o.id org_id, o.name,
                   COALESCE((SELECT SUM(rr.quantity_needed) FROM resource_requests rr
                             WHERE rr.recipient_id = u.id AND rr.status != 'cancelled'),0) AS requested,
                   COALESCE((SELECT SUM(a.quantity_allocated) FROM allocations a
                             JOIN resource_requests rr ON rr.id = a.request_id
                             WHERE rr.recipient_id = u.id AND a.status = 'completed'),0) AS received
            FROM users u JOIN organizations o ON o.id = u.organization_id WHERE u.role = 'recipient'"""))
    orgs = [o for o in orgs if o["requested"] > 0]
    total_req = sum(o["requested"] for o in orgs) or 1
    total_rec = sum(o["received"] for o in orgs)
    for o in orgs:
        o["need_share"] = round(o["requested"] / total_req, 4)
        o["allocation_share"] = round(o["received"] / total_rec, 4) if total_rec else 0.0
        o["fulfilment"] = round(min(1.0, o["received"] / o["requested"]), 4)
    counts = {r["role"]: r["c"] for r in conn.execute("SELECT role, COUNT(*) c FROM users GROUP BY role")}
    return {
        "quantity_listed": listed,
        "quantity_delivered": delivered,
        "redistribution_rate": round(100.0 * delivered / listed, 1) if listed else None,
        "pipeline": pipeline,
        "unclaimed_expired_quantity": unclaimed,
        "lapsed_quantity": lost,
        "avg_hours_to_acceptance": round(tta, 2) if tta is not None else None,
        "deadline_success_rate": round(100.0 * dl["ok"] / dl["total"], 1) if dl["total"] else None,
        "completed_deliveries": one("SELECT COUNT(*) FROM deliveries WHERE confirmation_status='confirmed'"),
        "open_requests": one("SELECT COUNT(*) FROM resource_requests WHERE status='open'"),
        "by_category": by_cat,
        "fairness": {
            "jain_index": round(jain_index([o["fulfilment"] for o in orgs]), 4) if jain_index([o["fulfilment"] for o in orgs]) is not None else None,
            "organisations": sorted(orgs, key=lambda o: -o["requested"]),
        },
        "users": counts,
    }
