"""Demo data. Usage:  python -m app.seed [--reset]

All organisations are fictional; coordinates are approximate points around
Vijayawada so the map looks realistic. Every demo account uses password
`demo1234` -- change or delete them before any real deployment.

The scenario is built so the matching algorithm visibly differs from naive
baselines: "Asha Food Bank" is the closest recipient to the food provider but has
already received a large share of recent supply, while "Seva Shelter Home" is a
little farther away with an urgent, mostly unmet need.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

from .db import connect, db_path, init_db, tx
from .security import hash_password
from .services import iso, utcnow

PASSWORD = "demo1234"

ORGS = {
    "greenleaf": ("Greenleaf Catering", "business", "Benz Circle, Vijayawada", 16.5060, 80.6480, 0),
    "bookex": ("Patamata Book Exchange", "business", "Patamata, Vijayawada", 16.4950, 80.6700, 0),
    "asha": ("Asha Food Bank", "food_bank", "Governorpet, Vijayawada", 16.5100, 80.6450, 400),
    "seva": ("Seva Shelter Home", "shelter", "Ajit Singh Nagar, Vijayawada", 16.4700, 80.6200, 250),
    "bright": ("Bright Future Orphanage", "orphanage", "Poranki, Vijayawada", 16.5000, 80.7100, 200),
    "school": ("Gannavaram Village School", "school", "Gannavaram", 16.5400, 80.8000, 300),
    "mangal": ("Mangalagiri Community Centre", "community", "Mangalagiri", 16.4300, 80.5700, 150),
    "guntur": ("Guntur Women's Collective", "ngo", "Guntur", 16.3067, 80.4365, 200),
    "riverside": ("Riverside Relief (pending)", "ngo", "Bhavanipuram, Vijayawada", 16.5200, 80.5900, 100),
}

USERS = [
    ("Admin", "admin@lifelink.test", "admin", None, "verified"),
    ("Greenleaf Catering", "provider1@lifelink.test", "provider", "greenleaf", "verified"),
    ("Patamata Book Exchange", "provider2@lifelink.test", "provider", "bookex", "verified"),
    ("Asha Food Bank", "asha@lifelink.test", "recipient", "asha", "verified"),
    ("Seva Shelter Home", "seva@lifelink.test", "recipient", "seva", "verified"),
    ("Bright Future Orphanage", "bright@lifelink.test", "recipient", "bright", "verified"),
    ("Gannavaram Village School", "school@lifelink.test", "recipient", "school", "verified"),
    ("Mangalagiri Community Centre", "mangal@lifelink.test", "recipient", "mangal", "verified"),
    ("Guntur Women's Collective", "guntur@lifelink.test", "recipient", "guntur", "verified"),
    ("Riverside Relief", "riverside@lifelink.test", "recipient", "riverside", "pending"),
    ("Ravi Kumar", "ravi@lifelink.test", "volunteer", None, "verified"),
    ("Sneha Reddy", "sneha@lifelink.test", "volunteer", None, "verified"),
    ("Imran Shaik", "imran@lifelink.test", "volunteer", None, "pending"),
]

# (recipient key, category, qty, urgency, min_condition, description)
OPEN_REQUESTS = [
    ("asha", "food", 80, 2, "any", "Weekly stock for community kitchen"),
    ("seva", "food", 70, 5, "any", "Evening meals - supplies ran out yesterday"),
    ("bright", "food", 50, 3, "any", "Meals for 50 children"),
    ("school", "food", 40, 2, "any", "Mid-day meal top-up"),
    ("guntur", "food", 60, 4, "any", "Meals for the women's training camp"),
    ("school", "books", 100, 3, "good", "Textbooks and readers, classes 3-8"),
    ("bright", "books", 40, 2, "any", "Story books for the reading room"),
    ("mangal", "books", 60, 2, "any", "Community library restock"),
    ("seva", "clothes", 120, 4, "good", "Winter clothing for residents"),
    ("guntur", "clothes", 80, 3, "any", "Clothes for the tailoring programme"),
    ("mangal", "household", 30, 2, "any", "Blankets and utensils for flood-hit families"),
]


def seed_demo(conn) -> bool:
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False
    now = utcnow()
    pw = hash_password(PASSWORD)
    with tx(conn):
        org_ids, user_ids = {}, {}
        for key, (name, typ, addr, lat, lon, cap) in ORGS.items():
            org_ids[key] = conn.execute(
                "INSERT INTO organizations(name,type,address,latitude,longitude,capacity_per_week) VALUES (?,?,?,?,?,?)",
                (name, typ, addr, lat, lon, cap)).lastrowid
        for name, email, role, org, status in USERS:
            user_ids[email] = conn.execute(
                "INSERT INTO users(name,email,password_hash,role,verification_status,organization_id,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (name, email, pw, role, status, org_ids.get(org) if org else None, iso(now - timedelta(days=30)))).lastrowid
        uid = lambda key: user_ids[f"{key}@lifelink.test"]
        provider1, provider2, volunteer = user_ids["provider1@lifelink.test"], user_ids["provider2@lifelink.test"], \
            user_ids["ravi@lifelink.test"]

        # Recent history: Asha already received a large share of recent supply (completed, confirmed).
        for days_ago, qty in ((6, 150), (4, 120)):
            created = now - timedelta(days=days_ago)
            rid = conn.execute(
                """INSERT INTO resources(provider_id,category,title,quantity,quantity_available,unit,condition,deadline,
                                         latitude,longitude,status,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (provider1, "food", "Banquet surplus (past)", qty, 0, "meals", "good",
                 iso(created + timedelta(hours=30)), 16.5060, 80.6480, iso(created))).lastrowid
            req = conn.execute(
                """INSERT INTO resource_requests(recipient_id,category,description,quantity_needed,urgency,min_condition,
                                                  status,created_at) VALUES (?,?,?,?,?,?, 'fulfilled', ?)""",
                (uid("asha"), "food", "Past request", qty, 2, "any", iso(created - timedelta(hours=2)))).lastrowid
            mid = conn.execute(
                "INSERT INTO matches(resource_id,request_id,score,rank,components,algorithm_version,created_at) "
                "VALUES (?,?,?,?,?,?,?)", (rid, req, 70.0, 1, "{}", "lifelink_fair", iso(created))).lastrowid
            aid = conn.execute(
                """INSERT INTO allocations(match_id,resource_id,request_id,quantity_allocated,status,auto,reserved_at,
                                           expires_at,responded_at) VALUES (?,?,?,?, 'completed', 0, ?, ?, ?)""",
                (mid, rid, req, qty, iso(created + timedelta(minutes=5)), iso(created + timedelta(hours=24)),
                 iso(created + timedelta(minutes=30)))).lastrowid
            did = conn.execute(
                """INSERT INTO deliveries(allocation_id,volunteer_id,status,assigned_at,pickup_time,delivery_time,
                                          deadline_met,confirmation_status) VALUES (?,?, 'delivered', ?, ?, ?, 1, 'confirmed')""",
                (aid, volunteer, iso(created + timedelta(hours=1)), iso(created + timedelta(hours=2)),
                 iso(created + timedelta(hours=3)))).lastrowid
            conn.execute("INSERT INTO audit_logs(actor_id,entity_type,entity_id,action,details,timestamp) VALUES "
                         "(NULL,'delivery',?,'confirmed','{\"seeded\": true}',?)", (did, iso(created + timedelta(hours=4))))

        for key, cat, qty, urg, cond, desc in OPEN_REQUESTS:
            conn.execute(
                """INSERT INTO resource_requests(recipient_id,category,description,quantity_needed,urgency,min_condition,
                                                  status,created_at) VALUES (?,?,?,?,?,?, 'open', ?)""",
                (uid(key), cat, desc, qty, urg, cond, iso(now - timedelta(hours=3))))

        listings = [
            (provider1, "food", "Surplus lunch boxes", 60, "meals", "good", timedelta(hours=20), 16.5060, 80.6480),
            (provider2, "books", "Used school textbooks", 120, "books", "good", timedelta(days=10), 16.4950, 80.6700),
            (provider2, "clothes", "Winter jackets and sweaters", 90, "items", "good", timedelta(days=7), 16.4950, 80.6700),
        ]
        for pid, cat, title, qty, unit, cond, delta, lat, lon in listings:
            conn.execute(
                """INSERT INTO resources(provider_id,category,title,quantity,quantity_available,unit,condition,deadline,
                                         latitude,longitude,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
                (pid, cat, title, qty, qty, unit, cond, iso(now + delta), lat, lon, iso(now - timedelta(hours=1))))
        conn.execute("INSERT INTO audit_logs(actor_id,entity_type,entity_id,action,details,timestamp) VALUES "
                     "(NULL,'system',0,'demo_seeded',NULL,?)", (iso(now),))
    return True


def main() -> None:
    if "--reset" in sys.argv:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path() + suffix)
            except FileNotFoundError:
                pass
    init_db()
    conn = connect()
    try:
        created = seed_demo(conn)
    finally:
        conn.close()
    print(("Seeded demo data into " if created else "Database already has data: ") + db_path())
    if created:
        print(f"Demo logins (password '{PASSWORD}'): admin@lifelink.test, provider1@lifelink.test, "
              f"asha@lifelink.test, seva@lifelink.test, ravi@lifelink.test")


if __name__ == "__main__":
    main()
