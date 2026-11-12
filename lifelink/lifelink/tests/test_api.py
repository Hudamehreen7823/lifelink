import sqlite3
import threading
from datetime import timedelta

import pytest

from app import notifier, services
from app.db import connect
from tests.conftest import food_listing_id, login, match_for

API = "/api/v1"


# ----------------------------------------------------------------------------- auth & validation
def test_login_and_protected_routes(client):
    assert client.get(f"{API}/resources").status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "admin@lifelink.test", "password": "wrong-pass"}).status_code == 401
    h = login(client, "admin@lifelink.test")
    me = client.get(f"{API}/auth/me", headers=h).json()
    assert me["role"] == "admin"
    assert client.get(f"{API}/resources", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_register_duplicate_and_unverified_recipient_not_matched(client, H):
    body = {"name": "New Home", "email": "newhome@example.org", "password": "longenough1", "role": "recipient",
            "organization": {"name": "New Home", "type": "shelter", "latitude": 16.5, "longitude": 80.65,
                             "capacity_per_week": 100}}
    r = client.post(f"{API}/auth/register", json=body)
    assert r.status_code == 201 and r.json()["user"]["verification_status"] == "pending"
    assert client.post(f"{API}/auth/register", json=body).status_code == 409
    token = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post(f"{API}/requests", headers=token, json={"category": "food", "quantity_needed": 10, "urgency": 5})

    p = H("provider1")
    rid = food_listing_id(client, p)
    data = client.get(f"{API}/resources/{rid}/matches", headers=p).json()
    assert all(c["recipient_org"] != "New Home" for c in data["candidates"])
    assert any(e["recipient_org"] == "New Home" and "not verified" in e["reason"] for e in data["excluded"])

    # once the admin verifies, the organisation becomes eligible
    uid = r.json()["user"]["id"]
    assert client.post(f"{API}/admin/users/{uid}/verification", headers=H("admin"), json={"status": "verified"}).status_code == 200
    data = client.get(f"{API}/resources/{rid}/matches", headers=p).json()
    assert any(c["recipient_org"] == "New Home" for c in data["candidates"])


@pytest.mark.parametrize("payload", [
    {"category": "food", "title": "x", "quantity": 5, "deadline": "2000-01-01T00:00:00Z"},
    {"category": "medicine", "title": "pills", "quantity": 5, "deadline": "2099-01-01T00:00:00Z"},
    {"category": "food", "title": "bad qty", "quantity": -3, "deadline": "2099-01-01T00:00:00Z"},
    {"category": "food", "title": "bad date", "quantity": 3, "deadline": "tomorrow-ish"},
])
def test_resource_validation(client, H, payload):
    assert client.post(f"{API}/resources", headers=H("provider1"), json=payload).status_code == 422


def test_request_validation(client, H):
    h = H("asha")
    assert client.post(f"{API}/requests", headers=h, json={"category": "food", "quantity_needed": 5, "urgency": 9}).status_code == 422
    assert client.post(f"{API}/requests", headers=h, json={"category": "food", "quantity_needed": 0, "urgency": 3}).status_code == 422


# ----------------------------------------------------------------------------- authorisation
def test_role_and_ownership_enforced(client, H):
    rid = food_listing_id(client, H("provider1"))
    body = {"category": "food", "title": "Hack", "quantity": 5, "deadline": "2099-01-01T00:00:00Z"}
    assert client.post(f"{API}/resources", headers=H("asha"), json=body).status_code == 403          # recipient can't list
    assert client.patch(f"{API}/resources/{rid}", headers=H("provider2"), json={"quantity": 999}).status_code == 403
    assert client.get(f"{API}/resources/{rid}/matches", headers=H("provider2")).status_code == 403
    assert client.post(f"{API}/resources/{rid}/auto-allocate", headers=H("provider2")).status_code == 403
    assert client.get(f"{API}/admin/users", headers=H("provider1")).status_code == 403
    assert client.get(f"{API}/requests", headers=H("provider1")).status_code == 403
    assert client.post(f"{API}/requests", headers=H("provider1"), json={"category": "food", "quantity_needed": 5, "urgency": 3}).status_code == 403


# ----------------------------------------------------------------------------- core workflow
def test_algorithm_differs_from_nearest_first(client, H):
    p = H("provider1")
    rid = food_listing_id(client, p)
    data = client.get(f"{API}/resources/{rid}/matches", headers=p).json()
    top = data["candidates"][0]
    assert top["recipient_org"] == "Seva Shelter Home"
    asha = match_for(client, p, rid, "Asha")
    assert asha["ranks"]["nearest"] == 1 and asha["ranks"]["lifelink_fair"] > 1
    assert asha["components"]["fairness"] < 50
    baseline = client.get(f"{API}/resources/{rid}/matches?strategy=nearest", headers=p).json()
    assert baseline["candidates"][0]["recipient_org"] == "Asha Food Bank"
    assert client.get(f"{API}/resources/{rid}/matches?strategy=bogus", headers=p).status_code == 422


def test_full_lifecycle_and_audit_trail(client, H):
    p, seva, ravi, admin = H("provider1"), H("seva"), H("ravi"), H("admin")
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")

    off = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]})
    assert off.status_code == 201
    alloc = off.json()
    assert alloc["status"] == "offered" and alloc["quantity_allocated"] == 60       # capped by listing quantity
    assert client.get(f"{API}/resources/{rid}", headers=p).json()["quantity_available"] == 0

    assert client.post(f"{API}/matches/{m['match_id']}/accept", headers=seva).json()["status"] == "accepted"

    claimed = client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=ravi, json={})
    assert claimed.status_code == 200 and claimed.json()["volunteer_name"] == "Ravi Kumar"
    did = claimed.json()["delivery_id"]

    # status machine: cannot skip pickup
    assert client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "delivered"}).status_code == 409
    assert client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "picked_up"}).json()["status"] == "picked_up"
    d = client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "delivered"}).json()
    assert d["status"] == "delivered" and d["deadline_met"] == 1

    # impact only counts confirmed transfers
    before = client.get(f"{API}/analytics/impact", headers=admin).json()
    done = client.post(f"{API}/deliveries/{did}/confirm", headers=seva, json={}).json()
    assert done["status"] == "completed" and done["confirmation_status"] == "confirmed"
    after = client.get(f"{API}/analytics/impact", headers=admin).json()
    assert after["quantity_delivered"] - before["quantity_delivered"] == 60
    assert after["deadline_success_rate"] == 100.0
    assert after["avg_hours_to_acceptance"] is not None

    # audit trail records each transition
    logs = client.get(f"{API}/admin/audit-logs?entity_type=allocation&entity_id={alloc['id']}", headers=admin).json()
    assert {l["action"] for l in logs} >= {"offered", "accepted"}
    dlogs = client.get(f"{API}/admin/audit-logs?entity_type=delivery&entity_id={did}", headers=admin).json()
    assert {l["action"] for l in dlogs} >= {"volunteer_assigned", "picked_up", "delivered", "confirmed"}

    # participants were notified
    notes = client.get(f"{API}/notifications", headers=seva).json()
    assert any("New offer" in n["message"] for n in notes)


def test_wrong_parties_cannot_act(client, H):
    p, seva, asha, ravi, sneha, imran = (H(n) for n in ("provider1", "seva", "asha", "ravi", "sneha", "imran"))
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")
    alloc = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]}).json()

    assert client.post(f"{API}/matches/{m['match_id']}/accept", headers=asha).status_code == 403      # not their request
    assert client.post(f"{API}/matches/{m['match_id']}/accept", headers=p).status_code == 403         # provider can't accept
    client.post(f"{API}/matches/{m['match_id']}/accept", headers=seva)

    assert client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=imran, json={}).status_code == 409  # unverified
    did = client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=ravi, json={}).json()["delivery_id"]
    assert client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=sneha, json={}).status_code == 409  # taken

    assert client.patch(f"{API}/deliveries/{did}/status", headers=sneha, json={"status": "picked_up"}).status_code == 403
    client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "picked_up"})
    client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "delivered"})
    assert client.post(f"{API}/deliveries/{did}/confirm", headers=asha, json={}).status_code == 403   # other recipient
    assert client.post(f"{API}/deliveries/{did}/confirm", headers=p, json={}).status_code == 403      # provider
    assert client.post(f"{API}/deliveries/{did}/confirm", headers=seva, json={}).status_code == 200
    assert client.post(f"{API}/deliveries/{did}/confirm", headers=seva, json={}).status_code == 409   # already confirmed


def test_disputed_delivery_is_not_counted(client, H):
    p, seva, ravi, admin = H("provider1"), H("seva"), H("ravi"), H("admin")
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")
    alloc = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]}).json()
    client.post(f"{API}/matches/{m['match_id']}/accept", headers=seva)
    did = client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=ravi, json={}).json()["delivery_id"]
    client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "picked_up"})
    client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "delivered"})
    base = client.get(f"{API}/analytics/impact", headers=admin).json()["quantity_delivered"]
    r = client.post(f"{API}/deliveries/{did}/confirm", headers=seva, json={"confirmed": False, "note": "box was empty"})
    assert r.json()["confirmation_status"] == "disputed" and r.json()["status"] == "delivered"
    assert client.get(f"{API}/analytics/impact", headers=admin).json()["quantity_delivered"] == base


# ----------------------------------------------------------------------------- quantity safety
def test_cannot_over_allocate_a_listing(client, H):
    p = H("provider1")
    rid = food_listing_id(client, p)
    seva = match_for(client, p, rid, "Seva")
    asha = match_for(client, p, rid, "Asha")
    assert client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": seva["request_id"]}).status_code == 201
    second = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": asha["request_id"]})
    assert second.status_code == 409


def test_database_constraint_blocks_negative_stock(tmp_path, client):
    conn = connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE resources SET quantity_available = -1 WHERE id = 3")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE resources SET quantity_available = quantity + 1 WHERE id = 3")
    conn.close()


def test_concurrent_offers_never_exceed_stock(client):
    conn = connect()
    provider = conn.execute("SELECT * FROM users WHERE email='provider1@lifelink.test'").fetchone()
    rid = conn.execute("SELECT id FROM resources WHERE title='Surplus lunch boxes'").fetchone()[0]
    reqs = [r[0] for r in conn.execute("SELECT id FROM resource_requests WHERE category='food' AND status='open'")]
    conn.close()
    results, barrier = [], threading.Barrier(len(reqs))

    def worker(req_id):
        c = connect()
        p = c.execute("SELECT * FROM users WHERE id=?", (provider["id"],)).fetchone()
        barrier.wait()
        try:
            results.append(("ok", services.create_offer(c, p, rid, req_id)["quantity_allocated"]))
        except services.ServiceError as exc:
            results.append(("err", exc.status_code))
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(r,)) for r in reqs]
    [t.start() for t in threads]
    [t.join() for t in threads]
    granted = sum(q for kind, q in results if kind == "ok")
    assert granted == 60                                  # exactly the listing quantity, never more
    assert all(code == 409 for kind, code in results if kind == "err")
    c = connect()
    assert c.execute("SELECT quantity_available FROM resources WHERE id=?", (rid,)).fetchone()[0] == 0
    c.close()


def test_quantity_edit_rules(client, H):
    p = H("provider1")
    rid = food_listing_id(client, p)
    seva = match_for(client, p, rid, "Seva")
    client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": seva["request_id"], "quantity": 40})
    assert client.patch(f"{API}/resources/{rid}", headers=p, json={"quantity": 30}).status_code == 409   # below reserved
    r = client.patch(f"{API}/resources/{rid}", headers=p, json={"quantity": 100})
    assert r.status_code == 200 and r.json()["quantity_available"] == 60
    assert client.patch(f"{API}/resources/{rid}", headers=p, json={"withdraw": True}).status_code == 409  # offer in flight


# ----------------------------------------------------------------------------- reject / expiry / reassignment
def _auto(client, p, rid):
    r = client.post(f"{API}/resources/{rid}/auto-allocate", headers=p)
    assert r.status_code == 201, r.text
    return r.json()


def test_auto_allocate_splits_in_rank_order(client, H):
    p = H("provider2")                                      # books listing: 120 units
    rid = client.get(f"{API}/resources?mine=true&category=books", headers=p).json()[0]["id"]
    allocs = _auto(client, p, rid)
    assert sum(a["quantity_allocated"] for a in allocs) == 120
    assert [a["match_rank"] for a in allocs] == sorted(a["match_rank"] for a in allocs)
    assert len({a["recipient_org"] for a in allocs}) == len(allocs)


def test_rejection_releases_quantity_and_reassigns(client, H):
    p = H("provider1")
    rid = food_listing_id(client, p)
    first = _auto(client, p, rid)
    assert len(first) == 1 and first[0]["recipient_org"] == "Seva Shelter Home" and first[0]["quantity_allocated"] == 60
    r = client.post(f"{API}/matches/{first[0]['match_id']}/reject", headers=H("seva"), json={"note": "no storage"})
    assert r.json()["status"] == "rejected"
    allocs = client.get(f"{API}/allocations", headers=p).json()
    live = [a for a in allocs if a["resource_id"] == rid and a["status"] == "offered"]
    # the released 60 units are re-offered down the ranking (50 to the next org, remaining 10 to the one after)
    assert all(a["recipient_org"] != "Seva Shelter Home" for a in live)
    assert sorted(a["quantity_allocated"] for a in live) == [10, 50]
    assert client.get(f"{API}/resources/{rid}", headers=p).json()["quantity_available"] == 0
    # the rejecting organisation is not offered the same listing again
    data = client.get(f"{API}/resources/{rid}/matches", headers=p).json()
    assert all(c["recipient_org"] != "Seva Shelter Home" for c in data["candidates"])


def test_offer_expiry_releases_quantity(client, H, monkeypatch):
    p = H("provider2")
    rid = client.get(f"{API}/resources?mine=true&category=books", headers=p).json()[0]["id"]
    cand = match_for(client, p, rid, "Gannavaram")
    client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": cand["request_id"]})
    assert client.get(f"{API}/resources/{rid}", headers=p).json()["quantity_available"] == 20
    real = services.utcnow
    monkeypatch.setattr(services, "utcnow", lambda: real() + timedelta(hours=25))
    allocs = client.get(f"{API}/allocations", headers=p).json()
    assert [a["status"] for a in allocs if a["resource_id"] == rid] == ["expired"]
    assert client.get(f"{API}/resources/{rid}", headers=p).json()["quantity_available"] == 120
    # an expired offer cannot be accepted
    assert client.post(f"{API}/matches/{cand['match_id']}/accept", headers=H("school")).status_code == 409


def test_accepted_allocation_lapses_after_deadline(client, H, monkeypatch):
    p, seva, ravi = H("provider1"), H("seva"), H("ravi")
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")
    alloc = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]}).json()
    client.post(f"{API}/matches/{m['match_id']}/accept", headers=seva)
    client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=ravi, json={})
    real = services.utcnow
    monkeypatch.setattr(services, "utcnow", lambda: real() + timedelta(hours=21))   # listing deadline is +20h
    a = [x for x in client.get(f"{API}/allocations", headers=p).json() if x["id"] == alloc["id"]][0]
    assert a["status"] == "expired" and a["delivery_status"] == "cancelled"
    imp = client.get(f"{API}/analytics/impact", headers=H("admin")).json()
    assert imp["lapsed_quantity"] == 60 and imp["quantity_delivered"] == 270   # only seeded history counts


def test_pickup_blocked_after_deadline(client, H, monkeypatch):
    p, seva, ravi = H("provider1"), H("seva"), H("ravi")
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")
    alloc = client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]}).json()
    client.post(f"{API}/matches/{m['match_id']}/accept", headers=seva)
    did = client.post(f"{API}/allocations/{alloc['id']}/assign-volunteer", headers=ravi, json={}).json()["delivery_id"]
    real = services.utcnow
    monkeypatch.setattr(services, "utcnow", lambda: real() + timedelta(hours=21))
    # expire_stale lapses it first, so the delivery is cancelled and cannot move
    assert client.patch(f"{API}/deliveries/{did}/status", headers=ravi, json={"status": "picked_up"}).status_code == 409


# ----------------------------------------------------------------------------- analytics & notifications
def test_impact_metrics_on_seed_data(client, H):
    imp = client.get(f"{API}/analytics/impact", headers=H("asha")).json()
    assert imp["quantity_delivered"] == 270
    assert imp["quantity_listed"] == 270 + 60 + 120 + 90
    assert imp["redistribution_rate"] == pytest.approx(100 * 270 / 540, abs=0.1)
    assert 0 < imp["fairness"]["jain_index"] <= 1
    asha = next(o for o in imp["fairness"]["organisations"] if o["name"] == "Asha Food Bank")
    assert asha["allocation_share"] == 1.0                  # all history so far went to one organisation


def test_email_dispatch_uses_smtp_when_configured(client, H, monkeypatch):
    monkeypatch.setenv("LIFELINK_SMTP_HOST", "smtp.invalid")
    sent = []
    monkeypatch.setattr(notifier, "send_email", lambda to, subject, body: sent.append(to))
    p = H("provider1")
    rid = food_listing_id(client, p)
    m = match_for(client, p, rid, "Seva")
    client.post(f"{API}/resources/{rid}/offer", headers=p, json={"request_id": m["request_id"]})
    conn = connect()
    assert notifier.dispatch_pending_emails(conn) >= 1
    conn.close()
    assert "seva@lifelink.test" in sent


def test_experiment_endpoint_404_without_results(client, H, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "EXPERIMENT_FILE", "/nonexistent/results.json")
    assert client.get(f"{API}/analytics/experiment", headers=H("admin")).status_code == 404
