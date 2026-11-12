"""LifeLink REST API (FastAPI). Interactive docs: /docs (Swagger UI) and /redoc."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator

from . import matching, notifier, services
from .db import connect, get_conn, init_db, tx
from .security import create_token, decode_token, hash_password, verify_password
from .services import ServiceError, audit, iso, rows, utcnow

CATEGORY = Literal["food", "books", "clothes", "household"]
CONDITION = Literal["new", "good", "fair"]
ORG_TYPE = Literal["food_bank", "shelter", "orphanage", "school", "library", "ngo", "community", "business",
                   "individual"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT, "static")
EXPERIMENT_FILE = os.path.join(ROOT, "results", "results.json")


# --------------------------------------------------------------------------- background worker
def _worker(stop: threading.Event) -> None:
    while not stop.wait(30):
        try:
            conn = connect()
            try:
                services.expire_stale(conn)
                if notifier.smtp_configured():
                    notifier.dispatch_pending_emails(conn)
            finally:
                conn.close()
        except Exception:  # noqa: BLE001 - keep the worker alive
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = threading.Event()
    if os.environ.get("LIFELINK_BACKGROUND", "1") == "1":
        threading.Thread(target=_worker, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(
    title="LifeLink API",
    version="1.0.0",
    description="Fairness-aware intelligent resource redistribution: multi-criteria matching, "
                "verified delivery and impact measurement.",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
)


@app.exception_handler(ServiceError)
async def service_error_handler(_, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --------------------------------------------------------------------------- auth plumbing
bearer = HTTPBearer(auto_error=False)


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer), conn=Depends(get_conn)):
    if not creds:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(creds.credentials)
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = conn.execute("SELECT * FROM users WHERE id = ?", (int(payload["sub"]),)).fetchone()
    if not user:
        raise HTTPException(401, "Account no longer exists")
    return user


def require(*roles: str):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, f"This action requires one of these roles: {', '.join(roles)}")
        return user
    return dep


def public_user(conn, user) -> dict:
    d = {k: user[k] for k in ("id", "name", "email", "role", "verification_status", "organization_id")}
    if user["organization_id"]:
        org = conn.execute("SELECT * FROM organizations WHERE id=?", (user["organization_id"],)).fetchone()
        d["organization"] = dict(org) if org else None
    return d


# --------------------------------------------------------------------------- schemas
class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: ORG_TYPE
    address: str = Field(default="", max_length=250)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    capacity_per_week: int = Field(default=100, ge=0, le=100000)


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["provider", "recipient", "volunteer"]
    organization: Optional[OrgIn] = None


class LoginIn(BaseModel):
    # plain string: login is a lookup, and demo accounts use the reserved .test domain
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ResourceIn(BaseModel):
    category: CATEGORY
    title: str = Field(min_length=2, max_length=150)
    quantity: int = Field(gt=0, le=1_000_000)
    unit: str = Field(default="items", max_length=30)
    condition: CONDITION = "good"
    deadline: str
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @field_validator("deadline")
    @classmethod
    def _valid_deadline(cls, v: str) -> str:
        try:
            services.parse_dt(v)
        except ValueError as exc:
            raise ValueError("deadline must be an ISO-8601 date-time") from exc
        return v


class ResourcePatch(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0, le=1_000_000)
    deadline: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=2, max_length=150)
    withdraw: Optional[bool] = None


class RequestIn(BaseModel):
    category: CATEGORY
    quantity_needed: int = Field(gt=0, le=1_000_000)
    urgency: int = Field(ge=1, le=5)
    description: str = Field(default="", max_length=500)
    min_condition: Literal["any", "fair", "good", "new"] = "any"


class OfferIn(BaseModel):
    request_id: int
    quantity: Optional[int] = Field(default=None, gt=0)


class AssignIn(BaseModel):
    volunteer_id: Optional[int] = None


class DeliveryStatusIn(BaseModel):
    status: Literal["picked_up", "delivered"]


class ConfirmIn(BaseModel):
    confirmed: bool = True
    note: str = Field(default="", max_length=500)


class RespondIn(BaseModel):
    note: str = Field(default="", max_length=500)


class VerifyIn(BaseModel):
    status: Literal["verified", "rejected", "pending"]


# --------------------------------------------------------------------------- routes
API = "/api/v1"


@app.get(f"{API}/health", tags=["system"])
def health():
    return {"status": "ok", "time": iso(utcnow())}


@app.post(f"{API}/auth/register", status_code=201, tags=["auth"])
def register(body: RegisterIn, conn=Depends(get_conn)):
    if body.role in ("provider", "recipient") and body.organization is None:
        raise HTTPException(422, "Providers and recipients must supply an organization")
    with tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (body.email.lower(),)).fetchone():
            raise HTTPException(409, "An account with this email already exists")
        org_id = None
        if body.organization:
            o = body.organization
            cur = conn.execute(
                "INSERT INTO organizations(name, type, address, latitude, longitude, capacity_per_week) VALUES (?,?,?,?,?,?)",
                (o.name, o.type, o.address, o.latitude, o.longitude, o.capacity_per_week))
            org_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO users(name, email, password_hash, role, verification_status, organization_id, created_at) "
            "VALUES (?,?,?,?, 'pending', ?, ?)",
            (body.name, body.email.lower(), hash_password(body.password), body.role, org_id, iso(utcnow())))
        uid = cur.lastrowid
        audit(conn, uid, "user", uid, "registered", {"role": body.role})
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return {"access_token": create_token(uid, body.role), "token_type": "bearer", "user": public_user(conn, user)}


@app.post(f"{API}/auth/login", tags=["auth"])
def login(body: LoginIn, conn=Depends(get_conn)):
    user = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.lower(),)).fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    return {"access_token": create_token(user["id"], user["role"]), "token_type": "bearer",
            "user": public_user(conn, user)}


@app.get(f"{API}/auth/me", tags=["auth"])
def me(user=Depends(current_user), conn=Depends(get_conn)):
    return public_user(conn, user)


# ---- resources
@app.post(f"{API}/resources", status_code=201, tags=["resources"])
def create_resource(body: ResourceIn, user=Depends(require("provider", "admin")), conn=Depends(get_conn)):
    return services.create_resource(conn, user, body.model_dump())


@app.get(f"{API}/resources", tags=["resources"])
def list_resources(category: Optional[CATEGORY] = None,
                   state: Optional[Literal["available", "fully_allocated", "expired", "withdrawn"]] = None,
                   mine: bool = False, q: Optional[str] = Query(default=None, max_length=100),
                   lat: Optional[float] = None, lon: Optional[float] = None, radius_km: Optional[float] = None,
                   user=Depends(current_user), conn=Depends(get_conn)):
    return services.list_resources(conn, user, category, state, mine, q, lat, lon, radius_km)


@app.get(f"{API}/resources/{{resource_id}}", tags=["resources"])
def get_resource(resource_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    return services.get_resource(conn, resource_id)


@app.patch(f"{API}/resources/{{resource_id}}", tags=["resources"])
def patch_resource(resource_id: int, body: ResourcePatch, user=Depends(require("provider", "admin")),
                   conn=Depends(get_conn)):
    return services.update_resource(conn, user, resource_id, body.model_dump(exclude_none=True))


# ---- requests
@app.post(f"{API}/requests", status_code=201, tags=["requests"])
def create_request(body: RequestIn, user=Depends(require("recipient")), conn=Depends(get_conn)):
    return services.create_request(conn, user, body.model_dump())


@app.get(f"{API}/requests", tags=["requests"])
def list_requests(status: Optional[Literal["open", "fulfilled", "cancelled"]] = None,
                  user=Depends(require("recipient", "admin")), conn=Depends(get_conn)):
    return services.list_requests(conn, user, status)


@app.post(f"{API}/requests/{{request_id}}/cancel", tags=["requests"])
def cancel_request(request_id: int, user=Depends(require("recipient", "admin")), conn=Depends(get_conn)):
    return services.cancel_request(conn, user, request_id)


# ---- matching & allocation
@app.get(f"{API}/resources/{{resource_id}}/matches", tags=["matching"])
def resource_matches(resource_id: int,
                     strategy: Literal["lifelink_fair", "lifelink", "nearest", "chronological"] = "lifelink_fair",
                     user=Depends(require("provider", "admin")), conn=Depends(get_conn)):
    """Ranked recipient candidates with per-factor score breakdown and baseline ranks."""
    return services.get_matches(conn, user, resource_id, strategy)


@app.post(f"{API}/resources/{{resource_id}}/offer", status_code=201, tags=["matching"])
def offer(resource_id: int, body: OfferIn, user=Depends(require("provider", "admin")), conn=Depends(get_conn)):
    return services.create_offer(conn, user, resource_id, body.request_id, body.quantity)


@app.post(f"{API}/resources/{{resource_id}}/auto-allocate", status_code=201, tags=["matching"])
def auto_allocate(resource_id: int, user=Depends(require("provider", "admin")), conn=Depends(get_conn)):
    """Offer the listing to the best-ranked recipients until all quantity is reserved."""
    return services.auto_allocate(conn, user, resource_id)


@app.post(f"{API}/matches/{{match_id}}/accept", tags=["matching"])
def accept_match(match_id: int, user=Depends(require("recipient")), conn=Depends(get_conn)):
    return services.respond_to_offer(conn, user, match_id, True)


@app.post(f"{API}/matches/{{match_id}}/reject", tags=["matching"])
def reject_match(match_id: int, body: RespondIn = RespondIn(), user=Depends(require("recipient")),
                 conn=Depends(get_conn)):
    return services.respond_to_offer(conn, user, match_id, False, body.note)


@app.get(f"{API}/allocations", tags=["allocations"])
def list_allocations(status: Optional[str] = None, scope: Optional[Literal["open", "mine"]] = None,
                     user=Depends(current_user), conn=Depends(get_conn)):
    return services.list_allocations(conn, user, status, scope)


@app.post(f"{API}/allocations/{{allocation_id}}/assign-volunteer", tags=["delivery"])
def assign_volunteer(allocation_id: int, body: AssignIn = AssignIn(),
                     user=Depends(require("provider", "admin", "volunteer")), conn=Depends(get_conn)):
    return services.assign_volunteer(conn, user, allocation_id, body.volunteer_id)


@app.get(f"{API}/volunteers", tags=["delivery"])
def list_volunteers(user=Depends(require("provider", "admin")), conn=Depends(get_conn)):
    return rows(conn.execute("SELECT id, name, email, verification_status FROM users WHERE role='volunteer' "
                             "AND verification_status='verified' ORDER BY name"))


@app.patch(f"{API}/deliveries/{{delivery_id}}/status", tags=["delivery"])
def delivery_status(delivery_id: int, body: DeliveryStatusIn, user=Depends(require("volunteer", "admin")),
                    conn=Depends(get_conn)):
    return services.update_delivery_status(conn, user, delivery_id, body.status)


@app.post(f"{API}/deliveries/{{delivery_id}}/confirm", tags=["delivery"])
def confirm(delivery_id: int, body: ConfirmIn = ConfirmIn(), user=Depends(require("recipient")),
            conn=Depends(get_conn)):
    return services.confirm_delivery(conn, user, delivery_id, body.confirmed, body.note)


# ---- notifications
@app.get(f"{API}/notifications", tags=["notifications"])
def notifications(unread: bool = False, user=Depends(current_user), conn=Depends(get_conn)):
    sql = "SELECT id, message, sent_at, is_read FROM notifications WHERE user_id=? AND channel='in_app'"
    if unread:
        sql += " AND is_read=0"
    return rows(conn.execute(sql + " ORDER BY id DESC LIMIT 100", (user["id"],)))


@app.post(f"{API}/notifications/read-all", tags=["notifications"])
def read_all(user=Depends(current_user), conn=Depends(get_conn)):
    with tx(conn):
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
    return {"ok": True}


# ---- analytics
@app.get(f"{API}/analytics/impact", tags=["analytics"])
def analytics_impact(user=Depends(current_user), conn=Depends(get_conn)):
    return services.impact(conn)


@app.get(f"{API}/analytics/experiment", tags=["analytics"])
def analytics_experiment(user=Depends(current_user)):
    """Results of the offline simulation (run `python -m experiments.run_experiment`)."""
    if not os.path.exists(EXPERIMENT_FILE):
        raise HTTPException(404, "No experiment results yet. Run: python -m experiments.run_experiment")
    with open(EXPERIMENT_FILE) as fh:
        return json.load(fh)


@app.get(f"{API}/analytics/algorithm", tags=["analytics"])
def algorithm_info(user=Depends(current_user)):
    return {"weights": matching.DEFAULT_WEIGHTS, "fairness_lambda": matching.FAIRNESS_LAMBDA,
            "max_radius_km": matching.MAX_RADIUS_KM, "avg_speed_kmh": matching.AVG_SPEED_KMH,
            "strategies": list(matching.STRATEGIES)}


# ---- admin
@app.get(f"{API}/admin/users", tags=["admin"])
def admin_users(user=Depends(require("admin")), conn=Depends(get_conn)):
    return rows(conn.execute(
        """SELECT u.id, u.name, u.email, u.role, u.verification_status, u.created_at, o.name AS organization,
                  o.type AS org_type FROM users u LEFT JOIN organizations o ON o.id=u.organization_id
           ORDER BY u.id DESC"""))


@app.post(f"{API}/admin/users/{{user_id}}/verification", tags=["admin"])
def admin_verify(user_id: int, body: VerifyIn, user=Depends(require("admin")), conn=Depends(get_conn)):
    with tx(conn):
        target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE users SET verification_status=? WHERE id=?", (body.status, user_id))
        audit(conn, user["id"], "user", user_id, f"verification_{body.status}")
        services.notify(conn, user_id, f"Your LifeLink account is now {body.status}.")
    return {"id": user_id, "verification_status": body.status}


@app.get(f"{API}/admin/audit-logs", tags=["admin"])
def audit_logs(entity_type: Optional[str] = None, entity_id: Optional[int] = None,
               limit: int = Query(default=100, ge=1, le=500), user=Depends(require("admin")),
               conn=Depends(get_conn)):
    sql, args = "SELECT a.*, u.name AS actor_name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id WHERE 1=1", []
    if entity_type:
        sql += " AND a.entity_type=?"; args.append(entity_type)
    if entity_id is not None:
        sql += " AND a.entity_id=?"; args.append(entity_id)
    return rows(conn.execute(sql + " ORDER BY a.id DESC LIMIT ?", (*args, limit)))


# --------------------------------------------------------------------------- static frontend
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
