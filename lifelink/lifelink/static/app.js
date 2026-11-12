// LifeLink single-page client (no build step). Talks to /api/v1.
const API = "/api/v1";
const state = { token: lsGet("ll_token"), me: null, drawer: false, notes: [], unread: 0, strategy: "lifelink_fair" };

function lsGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function lsSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* storage blocked */ } }
const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n0 = (x) => (x == null ? "–" : Number(x).toLocaleString());

async function api(path, { method = "GET", body } = {}) {
  const r = await fetch(API + path, {
    method,
    headers: { "Content-Type": "application/json", ...(state.token ? { Authorization: "Bearer " + state.token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    if (r.status === 401 && state.token) { logout(false); }
    let msg = r.statusText;
    if (data && typeof data.detail === "string") msg = data.detail;
    else if (data && Array.isArray(data.detail)) msg = data.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    throw new Error(msg);
  }
  return data;
}

function toast(msg, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.setAttribute("role", bad ? "alert" : "status");
  el.textContent = msg;
  $("#toast-host").appendChild(el);
  setTimeout(() => el.remove(), bad ? 6500 : 3500);
}

// ---------------------------------------------------------------- formatting
function rel(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  const a = Math.abs(ms) / 60000;
  const t = a < 60 ? `${Math.round(a)}m` : a < 2880 ? `${Math.floor(a / 60)}h ${Math.round(a % 60)}m` : `${Math.round(a / 1440)}d`;
  return ms >= 0 ? `in ${t}` : `${t} ago`;
}
const when = (iso) => (iso ? `<span title="${esc(new Date(iso).toLocaleString())}">${rel(iso)}</span>` : "–");
const CAT = { food: "Food", books: "Books", clothes: "Clothes", household: "Household" };
const ORG = { food_bank: "Food bank", shelter: "Shelter", orphanage: "Orphanage", school: "School", library: "Library", ngo: "NGO", community: "Community group", business: "Business", individual: "Individual" };
const STATUS_CHIP = {
  available: ["good", "Available"], fully_allocated: ["", "Fully allocated"], expired: ["bad", "Expired"], withdrawn: ["", "Withdrawn"],
  offered: ["warn", "Offered"], accepted: ["", "Accepted"], picked_up: ["", "Picked up"], delivered: ["warn", "Awaiting confirmation"],
  completed: ["good", "Completed"], rejected: ["bad", "Declined"], open: ["good", "Open"], fulfilled: ["good", "Fulfilled"],
  cancelled: ["", "Cancelled"], verified: ["good", "Verified"], pending: ["warn", "Pending"], assigned: ["", "Assigned"],
};
const chip = (s, label) => { const [c, l] = STATUS_CHIP[s] || ["", s]; return `<span class="chip ${c}">${esc(label || l)}</span>`; };
const urgency = (u) => `<span class="urg" role="img" aria-label="Urgency ${u} of 5" title="Urgency ${u} of 5">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= u ? "on" : ""}"></i>`).join("")}</span>`;
const empty = (title, hint) => `<div class="empty"><b>${esc(title)}</b>${esc(hint || "")}</div>`;
const opt = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${esc(v)}</option>`).join("");
const localDefault = (hours) => { const d = new Date(Date.now() + hours * 3600e3); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };

// ---------------------------------------------------------------- maps
function showMap(el, points, opts = {}) {
  if (!window.L) { el.outerHTML = `<p class="muted small">The map could not load (map tiles need an internet connection).</p>`; return; }
  const map = L.map(el, { scrollWheelZoom: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
  const b = [];
  points.forEach((p) => {
    const icon = L.divIcon({ className: "", html: `<div class="pin ${p.cls || ""}">${esc(p.label)}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
    L.marker([p.lat, p.lon], { icon, title: p.title || "" }).addTo(map).bindPopup(esc(p.title || ""));
    b.push([p.lat, p.lon]);
  });
  if (b.length > 1) map.fitBounds(b, { padding: [30, 30] }); else map.setView(b[0] || [16.5062, 80.648], opts.zoom || 12);
  return map;
}

function attachPicker(prefix) {
  const el = $(`#${prefix}-map`);
  if (!el || !window.L) return;
  const lat = $(`#${prefix}-lat`), lon = $(`#${prefix}-lon`);
  const map = L.map(el).setView([parseFloat(lat.value) || 16.5062, parseFloat(lon.value) || 80.648], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(map);
  let marker = null;
  const put = (la, lo) => { lat.value = la.toFixed(5); lon.value = lo.toFixed(5); marker ? marker.setLatLng([la, lo]) : (marker = L.marker([la, lo]).addTo(map)); };
  if (lat.value && lon.value) put(parseFloat(lat.value), parseFloat(lon.value));
  map.on("click", (e) => put(e.latlng.lat, e.latlng.lng));
  el._put = (la, lo) => { put(la, lo); map.setView([la, lo], 14); };
  setTimeout(() => map.invalidateSize(), 50);
}

function locationFields(prefix, required) {
  return `<div class="row">
    <div class="field"><label for="${prefix}-addr">Address (optional, for lookup)</label>
      <div class="row" style="flex-wrap:nowrap"><input id="${prefix}-addr" autocomplete="street-address"><button type="button" class="btn secondary" data-act="geocode" data-prefix="${prefix}">Find on map</button></div></div>
    <div class="field" style="flex:0 1 130px"><label for="${prefix}-lat">Latitude</label><input id="${prefix}-lat" type="number" step="any" ${required ? "required" : ""}></div>
    <div class="field" style="flex:0 1 130px"><label for="${prefix}-lon">Longitude</label><input id="${prefix}-lon" type="number" step="any" ${required ? "required" : ""}></div>
  </div><div class="small muted">Click the map to set the exact point.</div><div id="${prefix}-map" class="picker"></div>`;
}

// ---------------------------------------------------------------- auth screen
const DEMO = [["Admin", "admin"], ["Provider", "provider1"], ["Recipient: Asha Food Bank", "asha"], ["Recipient: Seva Shelter", "seva"], ["Volunteer", "ravi"]];

function renderAuth(mode = "login") {
  $("#app").innerHTML = `<div class="auth"><div class="auth-card">
    <section class="auth-pitch">
      <div class="brand">${logo()} LifeLink</div>
      <h1>Surplus goes to the places that need it most.</h1>
      <p>Providers list what they can spare. LifeLink ranks recipients by distance, urgency, unmet need, fit and deadline, then spreads supply fairly. Volunteers deliver, recipients confirm, and the dashboard counts only completed transfers.</p>
      <ul><li>Food, books, clothes and household items</li><li>Transparent scores you can inspect for every match</li><li>Full audit trail from listing to confirmed delivery</li></ul>
    </section>
    <section class="auth-form">
      <div class="tabs" role="group" aria-label="Account"><button data-act="auth-tab" data-mode="login" aria-pressed="${mode === "login"}">Sign in</button><button data-act="auth-tab" data-mode="register" aria-pressed="${mode === "register"}">Create account</button></div>
      ${mode === "login" ? loginForm() : registerForm()}
    </section></div></div>`;
  if (mode === "register") { attachPicker("reg"); regRoleChanged(); }
}
const logo = () => `<svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#eda100"/><path d="M9 16a5 5 0 0 1 5-5h2M23 16a5 5 0 0 1-5 5h-2" stroke="#0e2233" stroke-width="3" fill="none" stroke-linecap="round"/></svg>`;

function loginForm() {
  return `<form class="stack" id="login-form"><div class="field"><label for="l-email">Email</label><input id="l-email" type="text" autocomplete="username" required></div>
    <div class="field"><label for="l-pw">Password</label><input id="l-pw" type="password" autocomplete="current-password" required></div>
    <div class="err" id="auth-err" role="alert"></div><button class="btn">Sign in</button></form>
    <p class="small muted" style="margin-top:14px">Demo accounts (password <b>demo1234</b>):</p>
    <div class="demo-chips">${DEMO.map(([l, u]) => `<button type="button" data-act="demo" data-user="${u}">${esc(l)}</button>`).join("")}</div>`;
}
function registerForm() {
  return `<form class="stack" id="reg-form">
    <div class="row"><div class="field"><label for="r-name">Your name</label><input id="r-name" required minlength="2"></div>
    <div class="field"><label for="r-role">I want to</label><select id="r-role" data-change="reg-role"><option value="recipient">Request resources for my organisation</option><option value="provider">Donate resources</option><option value="volunteer">Volunteer to deliver</option></select></div></div>
    <div class="row"><div class="field"><label for="r-email">Email</label><input id="r-email" type="email" autocomplete="email" required></div>
    <div class="field"><label for="r-pw">Password (8+ characters)</label><input id="r-pw" type="password" minlength="8" autocomplete="new-password" required></div></div>
    <div id="org-fields" class="stack"><div class="row"><div class="field"><label for="r-org">Organisation name</label><input id="r-org"></div>
      <div class="field"><label for="r-type">Organisation type</label><select id="r-type">${opt(ORG, "food_bank")}</select></div>
      <div class="field" id="cap-field"><label for="r-cap">Weekly capacity (items)</label><input id="r-cap" type="number" min="0" value="100"></div></div>
      ${locationFields("reg", false)}</div>
    <div class="err" id="auth-err" role="alert"></div><button class="btn">Create account</button>
    <p class="small muted">New accounts are reviewed by an administrator before they can receive resources or take deliveries.</p></form>`;
}
function regRoleChanged() {
  const role = $("#r-role")?.value; if (!role) return;
  const org = role !== "volunteer";
  $("#org-fields").style.display = org ? "" : "none";
  $("#cap-field").style.display = role === "recipient" ? "" : "none";
  $("#r-org").required = org; $("#reg-lat").required = org; $("#reg-lon").required = org;
  setTimeout(() => $("#reg-map")?.dispatchEvent(new Event("resize")), 0);
}

async function doLogin(email, password) {
  const r = await api("/auth/login", { method: "POST", body: { email, password } });
  state.token = r.access_token; lsSet("ll_token", r.access_token); state.me = r.user;
  location.hash = "#/" + homeRoute(); await boot();
}
function logout(reload = true) { state.token = null; state.me = null; lsSet("ll_token", null); if (reload) { location.hash = ""; renderAuth(); } else renderAuth(); }

// ---------------------------------------------------------------- shell
const NAV = {
  provider: [["listings", "My listings"], ["deliveries", "Offers & deliveries"], ["impact", "Impact"], ["evaluation", "Evaluation"]],
  recipient: [["requests", "My requests"], ["offers", "Offers & deliveries"], ["impact", "Impact"], ["evaluation", "Evaluation"]],
  volunteer: [["tasks", "Delivery tasks"], ["impact", "Impact"], ["evaluation", "Evaluation"]],
  admin: [["impact", "Impact"], ["listings", "All listings"], ["users", "Users"], ["audit", "Audit log"], ["evaluation", "Evaluation"]],
};
const homeRoute = () => NAV[state.me.role][0][0];

function shell() {
  const cur = (location.hash.replace(/^#\//, "").split("/")[0]) || homeRoute();
  $("#app").innerHTML = `<div class="shell"><aside class="side">
    <div class="brand">${logo()} LifeLink</div>
    <nav class="nav" aria-label="Main">${NAV[state.me.role].map(([k, l]) => `<a href="#/${k}" ${k === cur || (k === "listings" && cur === "matches") ? 'aria-current="page"' : ""}>${esc(l)}</a>`).join("")}</nav>
    <button class="bell" data-act="notes" aria-expanded="${state.drawer}">Notifications<span class="count" id="bell-count" ${state.unread ? "" : "hidden"}>${state.unread}</span></button>
    <div class="who"><b>${esc(state.me.name)}</b>${esc(state.me.role)} · ${esc(state.me.verification_status)}<br><button class="link" data-act="logout">Sign out</button></div>
  </aside><main class="main" id="view" tabindex="-1"></main><div id="drawer-host"></div></div>`;
  drawer();
}
function drawer() {
  const h = $("#drawer-host"); if (!h) return;
  h.innerHTML = state.drawer ? `<aside class="drawer" aria-label="Notifications"><div class="row" style="justify-content:space-between;align-items:center"><h2>Notifications</h2><button class="btn secondary small" data-act="notes">Close</button></div>
    ${state.notes.length ? `<ul>${state.notes.map((n) => `<li class="${n.is_read ? "" : "unread"}">${esc(n.message)}<div class="small muted">${when(n.sent_at)}</div></li>`).join("")}</ul>` : empty("Nothing yet", "Offers, deliveries and account updates appear here.")}</aside>` : "";
}
async function loadNotes() {
  try { state.notes = await api("/notifications"); state.unread = state.notes.filter((n) => !n.is_read).length; const c = $("#bell-count"); if (c) { c.textContent = state.unread; c.hidden = !state.unread; } } catch { /* ignore */ }
}

// ---------------------------------------------------------------- router
const routes = { listings: vListings, matches: vMatches, deliveries: vProviderAllocs, requests: vRequests, offers: vOffers, tasks: vTasks, impact: vImpact, evaluation: vEvaluation, users: vUsers, audit: vAudit };

async function route() {
  if (!state.me) return;
  const [name, ...params] = (location.hash.replace(/^#\//, "") || homeRoute()).split("/");
  const allowed = NAV[state.me.role].map(([k]) => k).concat(state.me.role === "provider" || state.me.role === "admin" ? ["matches"] : []);
  const key = allowed.includes(name) ? name : homeRoute();
  shell();
  const host = $("#view");
  host.innerHTML = `<p class="muted">Loading…</p>`;
  try { host.innerHTML = await routes[key](...params); await after[key]?.(...params); host.focus({ preventScroll: true }); }
  catch (e) { host.innerHTML = `<div class="panel"><h2>Something went wrong</h2><p class="err">${esc(e.message)}</p><button class="btn secondary" data-act="reload">Try again</button></div>`; }
}
const after = {};
const head = (t, sub, extra = "") => `<div class="page-head"><div><h1>${esc(t)}</h1>${sub ? `<p>${esc(sub)}</p>` : ""}</div>${extra}</div>`;
const pendingBanner = () => (state.me.verification_status !== "verified" && state.me.role !== "admin"
  ? `<div class="banner" role="status">Your account is waiting for administrator verification. ${state.me.role === "recipient" ? "Until then your requests are not matched to listings." : state.me.role === "volunteer" ? "Until then you cannot claim delivery tasks." : ""}</div>` : "");

// ---------------------------------------------------------------- provider: listings
async function vListings() {
  const mine = state.me.role === "provider";
  const items = await api("/resources" + (mine ? "?mine=true" : ""));
  const form = mine ? `<section class="panel"><h2>List a resource</h2><form class="stack" id="res-form">
    <div class="row"><div class="field"><label for="x-cat">Category</label><select id="x-cat">${opt(CAT)}</select></div>
    <div class="field" style="flex:2 1 220px"><label for="x-title">What is it?</label><input id="x-title" placeholder="e.g. Surplus lunch boxes" required minlength="2"></div>
    <div class="field" style="flex:0 1 110px"><label for="x-qty">Quantity</label><input id="x-qty" type="number" min="1" required></div>
    <div class="field" style="flex:0 1 110px"><label for="x-unit">Unit</label><input id="x-unit" value="items"></div></div>
    <div class="row"><div class="field"><label for="x-cond">Condition</label><select id="x-cond"><option value="new">New</option><option value="good" selected>Good</option><option value="fair">Fair</option></select></div>
    <div class="field"><label for="x-dl">Must be collected by</label><input id="x-dl" type="datetime-local" required value="${localDefault(24)}"></div></div>
    <details><summary>Pickup location (defaults to your organisation)</summary>${locationFields("res", false)}</details>
    <div class="err" id="form-err" role="alert"></div><div><button class="btn">Publish listing</button></div></form></section>` : "";
  const rows = items.map((r) => `<tr><td><b>${esc(r.title)}</b><div class="small muted">${esc(r.provider_name)}</div></td><td>${CAT[r.category]}</td>
    <td class="num">${n0(r.quantity_available)} / ${n0(r.quantity)} ${esc(r.unit)}</td><td>${when(r.deadline)}</td><td>${chip(r.state)}</td>
    <td class="actions">${r.state === "available" || r.state === "fully_allocated" ? `<a class="btn small" href="#/matches/${r.id}">View matches</a>` : ""}
    ${mine && r.state === "available" && r.allocated_qty === 0 ? `<button class="btn small secondary" data-act="withdraw" data-id="${r.id}">Withdraw</button>` : ""}</td></tr>`).join("");
  return head(mine ? "My listings" : "All listings", "Quantity is reserved the moment an offer is made, so the same items can never go to two recipients.") + pendingBanner() + form +
    `<section class="panel"><h2>${mine ? "Your listings" : "Listings"}</h2>${items.length ? `<div class="table-wrap"><table><thead><tr><th>Listing</th><th>Category</th><th>Available / total</th><th>Deadline</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : empty("No listings yet", mine ? "Publish your first listing above and LifeLink will rank the recipients for it." : "")}</section>`;
}
after.listings = () => attachPicker("res");

// ---------------------------------------------------------------- provider: ranking comparison
const PARTS = [["proximity", "Proximity", "--c-prox"], ["urgency", "Urgency", "--c-urg"], ["unmet_need", "Unmet need", "--c-need"], ["compatibility", "Compatibility", "--c-comp"], ["deadline", "Deadline", "--c-dead"]];
const STRAT = { lifelink_fair: "LifeLink + fairness", lifelink: "LifeLink", nearest: "Nearest first", chronological: "Oldest request first" };

function scoreBar(c, m) {
  const wsum = Object.values(m.weights).reduce((a, b) => a + b, 0) || 1;
  const fair = m.strategy === "lifelink_fair";
  const scale = fair ? 1 - m.fairness_lambda : 1;
  const segs = PARTS.map(([k, label, col]) => ({ label, col, w: (m.weights[k] * c.components[k]) / wsum * scale }));
  if (fair) segs.push({ label: "Fairness", col: "--c-fair", w: m.fairness_lambda * c.components.fairness });
  const total = segs.reduce((a, s) => a + s.w, 0);
  return `<div class="bar" role="img" aria-label="${esc(segs.map((s) => `${s.label} ${s.w.toFixed(1)}`).join(", "))}">${segs.map((s) => `<i style="width:${s.w}%;background:var(${s.col})" title="${esc(s.label)}: ${s.w.toFixed(1)} points"></i>`).join("")}</div>
    <div class="small muted" style="margin-top:4px">${segs.map((s) => `${s.label} ${s.w.toFixed(0)}`).join(" · ")}</div>`;
}

async function vMatches(id, strategy) {
  strategy = strategy || state.strategy; state.strategy = strategy;
  const [res, m] = await Promise.all([api(`/resources/${id}`), api(`/resources/${id}/matches?strategy=${strategy}`)]);
  const baseline = strategy === "nearest" ? "lifelink_fair" : "nearest";
  const cards = m.candidates.map((c) => {
    const other = c.ranks[baseline];
    let shift = "";
    if (strategy === "nearest") shift = other === c.rank ? "LifeLink agrees" : `LifeLink: #${other}`;
    else if (strategy === "chronological") shift = `nearest: #${c.ranks.nearest}`;
    else shift = other > c.rank ? `▲ from #${other} nearest-first` : other < c.rank ? `▼ from #${other} nearest-first` : "same as nearest-first";
    const dir = strategy === "nearest" || strategy === "chronological" ? "" : other > c.rank ? "up" : other < c.rank ? "down" : "";
    const sug = Math.min(c.suggested_quantity, m.quantity_available);
    return `<article class="cand"><div><div class="rank">#${c.rank}</div><span class="shift ${dir}">${esc(shift)}</span></div>
      <div><h3>${esc(c.recipient_org)}</h3><div class="facts"><span>${esc(ORG[c.org_type] || c.org_type)}</span><span>${urgency(c.urgency)}</span><span class="num">${c.distance_km} km</span>
        <span class="num">needs ${n0(c.remaining_need)} of ${n0(c.quantity_needed)}</span><span class="num">got ${n0(c.received_30d)} of ${n0(c.requested_30d)} recently</span></div></div>
      <div class="stack"><div class="score-line"><span class="muted small">Score</span><b class="num">${c.score.toFixed(1)}</b></div>${scoreBar(c, m)}</div>
      <form class="actions" data-form="offer" data-resource="${id}" data-request="${c.request_id}"><input type="number" min="1" max="${sug}" value="${sug}" aria-label="Quantity to offer to ${esc(c.recipient_org)}" style="width:84px" ${m.quantity_available ? "" : "disabled"}><button class="btn small" ${m.quantity_available ? "" : "disabled"}>Offer</button></form></article>`;
  }).join("");
  const excluded = m.excluded.length ? `<details class="panel"><summary>${m.excluded.length} request${m.excluded.length > 1 ? "s" : ""} filtered out before scoring</summary><div class="table-wrap"><table><thead><tr><th>Organisation</th><th>Reason</th></tr></thead><tbody>${m.excluded.map((e) => `<tr><td>${esc(e.recipient_org)}</td><td>${esc(e.reason)}</td></tr>`).join("")}</tbody></table></div></details>` : "";
  const legend = PARTS.map(([, l, c]) => `<span style="--c:var(${c})">${l}</span>`).join("") + (strategy === "lifelink_fair" ? `<span style="--c:var(--c-fair)">Fairness (history)</span>` : "");
  return head(res.title, `${n0(res.quantity_available)} of ${n0(res.quantity)} ${res.unit} still unreserved · collect ${rel(res.deadline)}`,
    `<div class="actions"><a class="btn secondary" href="#/listings">Back</a><button class="btn" data-act="auto" data-id="${id}" ${m.quantity_available && m.candidates.length ? "" : "disabled"}>Offer to best matches automatically</button></div>`) +
    `<div class="row" style="margin-bottom:14px;align-items:center"><div class="strategy" role="group" aria-label="Ranking method">${Object.entries(STRAT).map(([k, l]) => `<button data-act="strategy" data-id="${id}" data-s="${k}" aria-pressed="${k === strategy}">${l}</button>`).join("")}</div>
      <span class="muted small">Compare how each method would order the same recipients.</span></div>
    <div id="match-map" class="map" role="img" aria-label="Map of the listing and ranked recipients"></div>
    <div class="legend">${legend}</div>
    ${m.candidates.length ? `<div class="rank-list">${cards}</div>` : `<section class="panel">${empty("No eligible recipients right now", "Requests must match the category, be verified, be within 50 km and be collectable before the deadline.")}</section>`}${excluded}
    <p class="small muted">Score = proximity ${(m.weights.proximity * 100).toFixed(0)}% + urgency ${(m.weights.urgency * 100).toFixed(0)}% + unmet need ${(m.weights.unmet_need * 100).toFixed(0)}% + compatibility ${(m.weights.compatibility * 100).toFixed(0)}% + deadline ${(m.weights.deadline * 100).toFixed(0)}%. With fairness on, ${(m.fairness_lambda * 100).toFixed(0)}% of the score comes from how little the recipient has received recently (urgent requests are never penalised).</p>`;
}
after.matches = async (id) => {
  const m = await api(`/resources/${id}/matches?strategy=${state.strategy}`);
  showMap($("#match-map"), [{ lat: m.listing.latitude, lon: m.listing.longitude, label: "◆", cls: "src", title: "Pickup: " + m.listing.title }, ...m.candidates.map((c) => ({ lat: c.latitude, lon: c.longitude, label: c.rank, title: `#${c.rank} ${c.recipient_org}` }))]);
};

// ---------------------------------------------------------------- provider/admin: allocations & volunteers
async function vProviderAllocs() {
  const [al, vols] = await Promise.all([api("/allocations"), api("/volunteers")]);
  const rows = al.map((a) => `<tr><td><b>${esc(a.resource_title)}</b><div class="small muted">to ${esc(a.recipient_org)}</div></td><td class="num">${n0(a.quantity_allocated)}</td>
    <td>${chip(a.status)}${a.status === "offered" ? `<div class="small muted">expires ${when(a.expires_at)}</div>` : ""}</td>
    <td>${a.volunteer_name ? `${esc(a.volunteer_name)} ${chip(a.delivery_status)}${a.deadline_met === 0 ? ' <span class="chip bad">Late</span>' : ""}` :
      a.status === "accepted" ? `<form class="actions" data-form="assign" data-id="${a.id}"><select aria-label="Volunteer" required><option value="">Choose volunteer…</option>${vols.map((v) => `<option value="${v.id}">${esc(v.name)}</option>`).join("")}</select><button class="btn small">Assign</button></form>` : "–"}</td>
    <td>${when(a.reserved_at)}</td></tr>`).join("");
  return head("Offers & deliveries", "Follow each allocation from offer to confirmed delivery. Volunteers can also claim accepted tasks themselves.") +
    `<section class="panel">${al.length ? `<div class="table-wrap"><table><thead><tr><th>Listing</th><th>Qty</th><th>Status</th><th>Volunteer</th><th>Reserved</th></tr></thead><tbody>${rows}</tbody></table></div>` : empty("No offers yet", "Open a listing and choose View matches to make the first offer.")}</section>`;
}

// ---------------------------------------------------------------- recipient
async function vRequests() {
  const items = await api("/requests");
  const rows = items.map((r) => `<tr><td><b>${CAT[r.category]}</b><div class="small muted">${esc(r.description)}</div></td><td class="num">${n0(r.received_qty)} / ${n0(r.quantity_needed)}</td>
    <td>${urgency(r.urgency)}</td><td>${chip(r.status)}</td><td>${when(r.created_at)}</td>
    <td>${r.status === "open" && r.committed_qty === 0 ? `<button class="btn small secondary" data-act="cancel-request" data-id="${r.id}">Cancel</button>` : ""}</td></tr>`).join("");
  return head("My requests", "Tell providers what you need. Urgency and how much of your need is still unmet both raise your ranking.") + pendingBanner() +
    `<section class="panel"><h2>New request</h2><form class="stack" id="req-form"><div class="row">
      <div class="field"><label for="q-cat">Category</label><select id="q-cat">${opt(CAT)}</select></div>
      <div class="field" style="flex:0 1 120px"><label for="q-qty">Quantity needed</label><input id="q-qty" type="number" min="1" required></div>
      <div class="field" style="flex:0 1 190px"><label for="q-urg">Urgency</label><select id="q-urg"><option value="1">1 · Can wait</option><option value="2">2 · Low</option><option value="3" selected>3 · Normal</option><option value="4">4 · High</option><option value="5">5 · Urgent</option></select></div>
      <div class="field"><label for="q-cond">Minimum condition</label><select id="q-cond"><option value="any">Any</option><option value="fair">Fair or better</option><option value="good">Good or better</option><option value="new">New only</option></select></div></div>
      <div class="field"><label for="q-desc">What is it for?</label><input id="q-desc" maxlength="500" placeholder="e.g. Meals for 50 children this week"></div>
      <div class="err" id="form-err" role="alert"></div><div><button class="btn">Submit request</button></div></form></section>
    <section class="panel"><h2>Your requests</h2>${items.length ? `<div class="table-wrap"><table><thead><tr><th>Request</th><th>Received / needed</th><th>Urgency</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>` : empty("No requests yet", "Submit a request above. You'll be notified when a provider offers you something.")}</section>`;
}

async function vOffers() {
  const al = await api("/allocations");
  const card = (a) => {
    let acts = "";
    if (a.status === "offered") acts = `<button class="btn small" data-act="accept" data-id="${a.match_id}">Accept</button><button class="btn small danger" data-act="reject" data-id="${a.match_id}">Decline</button>`;
    else if (a.status === "delivered" && a.confirmation_status === "pending") acts = `<button class="btn small" data-act="confirm" data-id="${a.delivery_id}">Confirm receipt</button><button class="btn small danger" data-act="dispute" data-id="${a.delivery_id}">Report a problem</button>`;
    return `<tr><td><b>${esc(a.resource_title)}</b><div class="small muted">from ${esc(a.provider_name)} · ${esc(a.pickup_address || "")}</div></td><td class="num">${n0(a.quantity_allocated)} ${esc(a.unit)}</td>
      <td>${chip(a.status)}${a.confirmation_status === "disputed" ? ' <span class="chip bad">Disputed</span>' : ""}${a.status === "offered" ? `<div class="small muted">respond ${when(a.expires_at)}</div>` : ""}</td>
      <td>${a.volunteer_name ? `${esc(a.volunteer_name)} · ${esc(a.delivery_status)}` : a.status === "accepted" ? "Waiting for a volunteer" : "–"}</td><td class="actions">${acts}</td></tr>`;
  };
  return head("Offers & deliveries", "Accept offers you can use. Confirm receipt once the items arrive: only confirmed deliveries count toward impact.") + pendingBanner() +
    `<section class="panel">${al.length ? `<div class="table-wrap"><table><thead><tr><th>Item</th><th>Quantity</th><th>Status</th><th>Delivery</th><th></th></tr></thead><tbody>${al.map(card).join("")}</tbody></table></div>` : empty("No offers yet", "When a provider offers you a listing it will appear here and in your notifications.")}</section>`;
}

// ---------------------------------------------------------------- volunteer
async function vTasks() {
  const al = await api("/allocations");
  const open = al.filter((a) => a.status === "accepted" && !a.delivery_id);
  const mine = al.filter((a) => a.delivery_id && a.volunteer_id === state.me.id);
  const loc = (la, lo) => `https://www.openstreetmap.org/?mlat=${la}&mlon=${lo}#map=15/${la}/${lo}`;
  const task = (a, claim) => `<article class="panel"><div class="row" style="justify-content:space-between;align-items:flex-start"><div><h3>${esc(a.resource_title)} · ${n0(a.quantity_allocated)} ${esc(a.unit)}</h3>
    <p class="muted small">Collect by ${when(a.resource_deadline)}</p></div><div>${chip(a.delivery_status || a.status)}</div></div>
    <div class="grid cols-2"><div><b>Pick up</b><br>${esc(a.provider_name)}<br><span class="small muted">${esc(a.pickup_address || "")}</span><br><a class="small" target="_blank" rel="noopener" href="${loc(a.pickup_lat, a.pickup_lon)}">Open map</a></div>
    <div><b>Deliver to</b><br>${esc(a.recipient_org)}<br><span class="small muted">${esc(a.dropoff_address || "")}</span><br><a class="small" target="_blank" rel="noopener" href="${loc(a.dropoff_lat, a.dropoff_lon)}">Open map</a></div></div>
    <div class="actions" style="margin-top:12px">${claim ? `<button class="btn" data-act="claim" data-id="${a.id}">Claim this task</button>` :
      a.delivery_status === "assigned" ? `<button class="btn" data-act="status" data-id="${a.delivery_id}" data-s="picked_up">Mark as picked up</button>` :
      a.delivery_status === "picked_up" ? `<button class="btn" data-act="status" data-id="${a.delivery_id}" data-s="delivered">Mark as delivered</button>` : ""}</div></article>`;
  return head("Delivery tasks", "Claim an accepted allocation, collect it before the deadline, and mark each step as you go.") + pendingBanner() +
    `<h2 style="margin-bottom:10px">Your deliveries</h2>${mine.length ? mine.map((a) => task(a, false)).join("") : `<section class="panel">${empty("Nothing assigned to you", "Claim a task below to get started.")}</section>`}
    <h2 style="margin:18px 0 10px">Open tasks</h2>${open.length ? open.map((a) => task(a, true)).join("") : `<section class="panel">${empty("No open tasks", "Tasks appear here once a recipient accepts an offer.")}</section>`}`;
}

// ---------------------------------------------------------------- impact
async function vImpact() {
  const d = await api("/analytics/impact");
  const k = (v, l) => `<div class="kpi"><div class="v">${v}</div><div class="l">${esc(l)}</div></div>`;
  const pct = (x) => (x == null ? "–" : x + "%");
  const maxCat = Math.max(1, ...d.by_category.map((c) => c.listed));
  const cats = d.by_category.map((c) => `<div class="bar-row"><span>${CAT[c.category]}</span><div class="bar" role="img" aria-label="${n0(c.delivered)} of ${n0(c.listed)} delivered"><i style="width:${(100 * c.delivered) / maxCat}%;background:var(--c-need)"></i><i style="width:${(100 * (c.listed - c.delivered)) / maxCat}%;background:var(--line)"></i></div><span class="num right">${n0(c.delivered)} / ${n0(c.listed)}</span></div>`).join("");
  const orgs = d.fairness.organisations.map((o) => `<div class="bar-row"><span>${esc(o.name)}</span><div class="stack">
      <div class="bar" title="Share of total need" role="img" aria-label="Need share ${(o.need_share * 100).toFixed(0)}%"><i style="width:${o.need_share * 100}%;background:var(--c-fair)"></i></div>
      <div class="bar" style="margin-top:3px" title="Share of delivered quantity" role="img" aria-label="Delivered share ${(o.allocation_share * 100).toFixed(0)}%"><i style="width:${o.allocation_share * 100}%;background:var(--c-comp)"></i></div></div>
      <span class="num right small">${(o.need_share * 100).toFixed(0)}% / ${(o.allocation_share * 100).toFixed(0)}%</span></div>`).join("");
  const pipe = d.pipeline;
  return head("Impact", "Counts only deliveries the recipient has confirmed, not items that were merely listed.") +
    `<div class="grid cols-4" style="margin-bottom:18px">${k(n0(d.quantity_delivered), "items delivered and confirmed")}${k(pct(d.redistribution_rate), "of listed quantity redistributed")}${k(pct(d.deadline_success_rate), "delivered before the deadline")}${k(d.avg_hours_to_acceptance == null ? "–" : d.avg_hours_to_acceptance + " h", "average time to acceptance")}</div>
    <div class="grid cols-2"><section class="panel"><h2>Still in progress</h2><div class="grid cols-2"><div class="kpi"><div class="v">${n0(pipe.offered)}</div><div class="l">offered, awaiting a reply</div></div><div class="kpi"><div class="v">${n0(pipe.accepted + pipe.picked_up)}</div><div class="l">accepted or in transit</div></div><div class="kpi"><div class="v">${n0(pipe.delivered)}</div><div class="l">delivered, awaiting confirmation</div></div><div class="kpi"><div class="v">${n0(d.unclaimed_expired_quantity + d.lapsed_quantity)}</div><div class="l">expired or lapsed</div></div></div></section>
    <section class="panel"><h2>By category</h2><div class="bars">${cats || empty("No listings yet")}</div><p class="small muted" style="margin-top:10px">Green is delivered; grey is still listed or lost.</p></section></div>
    <section class="panel"><h2>Is supply reaching everyone fairly?</h2><p class="muted small">For each organisation: share of all requested quantity (grey) beside its share of delivered quantity (amber). Jain index of fulfilment: <b>${d.fairness.jain_index == null ? "–" : d.fairness.jain_index}</b> (1 means every organisation has the same share of its need met).</p>
      <div class="bars">${orgs || empty("No requests yet")}</div></section>`;
}

// ---------------------------------------------------------------- evaluation (offline simulation)
async function vEvaluation(sid) {
  let r;
  try { r = await api("/analytics/experiment"); } catch (e) { return head("Evaluation") + `<section class="panel">${empty("No experiment results yet", "Run  python -m experiments.run_experiment  to generate them.")}</section>`; }
  const sc = r.scenarios.find((s) => s.id === sid) || r.scenarios.find((s) => s.id === r.meta.headline_scenario);
  const keys = ["redistribution_rate", "deadline_success", "urgent_fulfilment", "jain_fairness", "need_share_deviation", "hub_share_gap_abs", "hours_to_acceptance", "mean_distance_km"];
  const dec = { jain_fairness: 3, need_share_deviation: 3, hours_to_acceptance: 2 };
  const f = (st, k) => (st.mean == null ? "–" : `${st.mean.toFixed(dec[k] ?? 1)} <span class="muted small">±${st.ci95.toFixed(dec[k] ?? 1)}</span>`);
  const best = (k) => { const hi = r.metrics[k].higher_is_better; const v = r.strategies.map((s) => sc.strategies[s][k].mean); return hi ? Math.max(...v) : Math.min(...v); };
  const rows = keys.map((k) => `<tr><td>${esc(r.metrics[k].label)} ${r.metrics[k].higher_is_better ? "↑" : "↓"}</td>${r.strategies.map((s) => `<td class="num ${sc.strategies[s][k].mean === best(k) ? "best" : ""}" ${sc.strategies[s][k].mean === best(k) ? 'style="font-weight:600"' : ""}>${f(sc.strategies[s][k], k)}</td>`).join("")}</tr>`).join("");
  const scen = r.scenarios.map((s) => `<option value="${s.id}" ${s.id === sc.id ? "selected" : ""}>${s.geography === "central_hubs" ? "Hub-centred city" : "Evenly spread"} · supply ${s.supply_ratio}× demand</option>`).join("");
  return head("Evaluation", `Simulated comparison of four ranking methods on the same synthetic data (${r.meta.seeds_per_scenario} random runs per scenario, mean ± 95% interval). Bold marks the best value in each row.`) +
    `<div class="banner" role="note">These are simulation results on synthetic data. They show how the algorithms behave under stated assumptions; they are not measurements of real-world waste reduction.</div>
    <section class="panel"><div class="row" style="margin-bottom:12px"><div class="field" style="max-width:340px"><label for="scen">Scenario</label><select id="scen" data-change="scenario">${scen}</select></div></div>
    <div class="table-wrap"><table><thead><tr><th>Metric</th>${r.strategies.map((s) => `<th>${esc(r.labels[s])}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></section>
    <section class="panel"><h2>Assumptions</h2><ul class="small muted">${r.meta.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></section>`;
}

// ---------------------------------------------------------------- admin
async function vUsers() {
  const us = await api("/admin/users");
  const rows = us.map((u) => `<tr><td><b>${esc(u.name)}</b><div class="small muted">${esc(u.email)}</div></td><td>${esc(u.role)}</td><td>${esc(u.organization || "–")}${u.org_type ? `<div class="small muted">${esc(ORG[u.org_type] || u.org_type)}</div>` : ""}</td><td>${chip(u.verification_status)}</td>
    <td class="actions">${u.role === "admin" ? "" : `${u.verification_status !== "verified" ? `<button class="btn small" data-act="verify" data-id="${u.id}" data-s="verified">Verify</button>` : ""}${u.verification_status !== "rejected" ? `<button class="btn small danger" data-act="verify" data-id="${u.id}" data-s="rejected">Reject</button>` : ""}`}</td></tr>`).join("");
  return head("Users", "Recipients must be verified before they can be matched; volunteers before they can claim deliveries.") + `<section class="panel"><div class="table-wrap"><table><thead><tr><th>Account</th><th>Role</th><th>Organisation</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
async function vAudit() {
  const logs = await api("/admin/audit-logs?limit=200");
  return head("Audit log", "Every status change, who made it, and when.") + `<section class="panel">${logs.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Actor</th><th>Record</th><th>Action</th><th>Details</th></tr></thead><tbody>${logs.map((l) => `<tr><td>${when(l.timestamp)}</td><td>${esc(l.actor_name || "System")}</td><td>${esc(l.entity_type)} #${l.entity_id}</td><td>${esc(l.action.replace(/_/g, " "))}</td><td class="small muted">${esc(l.details || "")}</td></tr>`).join("")}</tbody></table></div>` : empty("No activity yet")}</section>`;
}

// ---------------------------------------------------------------- events
const iso = (local) => new Date(local).toISOString();
const numOrNull = (v) => (v === "" || v == null ? null : Number(v));

const acts = {
  "auth-tab": (el) => renderAuth(el.dataset.mode),
  demo: async (el) => { try { await doLogin(el.dataset.user + "@lifelink.test", "demo1234"); } catch (e) { toast(e.message, true); } },
  logout: () => logout(),
  reload: () => route(),
  notes: async () => { state.drawer = !state.drawer; if (state.drawer) { await loadNotes(); drawer(); if (state.unread) { await api("/notifications/read-all", { method: "POST" }); state.unread = 0; const c = $("#bell-count"); if (c) c.hidden = true; } } else drawer(); },
  geocode: async (el) => {
    const p = el.dataset.prefix, q = $(`#${p}-addr`).value.trim(); if (!q) return toast("Type an address first", true);
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`);
      const j = await r.json(); if (!j.length) throw new Error("not found");
      const map = $(`#${p}-map`); map._put ? map._put(+j[0].lat, +j[0].lon) : ($(`#${p}-lat`).value = j[0].lat, $(`#${p}-lon`).value = j[0].lon);
    } catch { toast("Couldn't look up that address. Click the map to set the location instead.", true); }
  },
  withdraw: async (el) => { if (!confirm("Withdraw this listing?")) return; await api(`/resources/${el.dataset.id}`, { method: "PATCH", body: { withdraw: true } }); toast("Listing withdrawn"); route(); },
  strategy: (el) => { state.strategy = el.dataset.s; location.hash = `#/matches/${el.dataset.id}`; route(); },
  auto: async (el) => { const r = await api(`/resources/${el.dataset.id}/auto-allocate`, { method: "POST" }); toast(`Offered to ${r.length} recipient${r.length > 1 ? "s" : ""}`); route(); },
  "cancel-request": async (el) => { await api(`/requests/${el.dataset.id}/cancel`, { method: "POST" }); toast("Request cancelled"); route(); },
  accept: async (el) => { await api(`/matches/${el.dataset.id}/accept`, { method: "POST" }); toast("Offer accepted"); route(); },
  reject: async (el) => { const note = prompt("Reason for declining (optional)") ?? null; if (note === null) return; await api(`/matches/${el.dataset.id}/reject`, { method: "POST", body: { note } }); toast("Offer declined"); route(); },
  confirm: async (el) => { await api(`/deliveries/${el.dataset.id}/confirm`, { method: "POST", body: { confirmed: true } }); toast("Receipt confirmed"); route(); },
  dispute: async (el) => { const note = prompt("What went wrong?"); if (note === null) return; await api(`/deliveries/${el.dataset.id}/confirm`, { method: "POST", body: { confirmed: false, note } }); toast("Problem reported"); route(); },
  claim: async (el) => { await api(`/allocations/${el.dataset.id}/assign-volunteer`, { method: "POST", body: {} }); toast("Task claimed"); route(); },
  status: async (el) => { await api(`/deliveries/${el.dataset.id}/status`, { method: "PATCH", body: { status: el.dataset.s } }); toast(el.dataset.s === "picked_up" ? "Marked as picked up" : "Marked as delivered"); route(); },
  verify: async (el) => { await api(`/admin/users/${el.dataset.id}/verification`, { method: "POST", body: { status: el.dataset.s } }); toast(el.dataset.s === "verified" ? "Verified" : "Rejected"); route(); },
};

document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]"); if (!el) return;
  e.preventDefault();
  try { await acts[el.dataset.act]?.(el); } catch (err) { toast(err.message, true); }
});
document.addEventListener("change", (e) => {
  const t = e.target.dataset?.change;
  if (t === "reg-role") regRoleChanged();
  if (t === "scenario") { location.hash = `#/evaluation/${e.target.value}`; }
});
document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, err = $("#form-err") || $("#auth-err");
  const fail = (m) => { if (err) err.textContent = m; else toast(m, true); };
  if (err) err.textContent = "";
  try {
    if (f.id === "login-form") await doLogin($("#l-email").value.trim(), $("#l-pw").value);
    else if (f.id === "reg-form") {
      const role = $("#r-role").value;
      const body = { name: $("#r-name").value.trim(), email: $("#r-email").value.trim(), password: $("#r-pw").value, role };
      if (role !== "volunteer") body.organization = { name: $("#r-org").value.trim(), type: $("#r-type").value, address: $("#reg-addr").value.trim(), latitude: numOrNull($("#reg-lat").value), longitude: numOrNull($("#reg-lon").value), capacity_per_week: role === "recipient" ? Number($("#r-cap").value || 0) : 0 };
      const r = await api("/auth/register", { method: "POST", body });
      state.token = r.access_token; lsSet("ll_token", r.access_token); state.me = r.user; location.hash = "#/" + homeRoute(); await boot();
    } else if (f.id === "res-form") {
      const body = { category: $("#x-cat").value, title: $("#x-title").value.trim(), quantity: Number($("#x-qty").value), unit: $("#x-unit").value.trim() || "items", condition: $("#x-cond").value, deadline: iso($("#x-dl").value) };
      const la = numOrNull($("#res-lat").value), lo = numOrNull($("#res-lon").value); if (la != null && lo != null) { body.latitude = la; body.longitude = lo; }
      await api("/resources", { method: "POST", body }); toast("Listing published"); route();
    } else if (f.id === "req-form") {
      await api("/requests", { method: "POST", body: { category: $("#q-cat").value, quantity_needed: Number($("#q-qty").value), urgency: Number($("#q-urg").value), min_condition: $("#q-cond").value, description: $("#q-desc").value.trim() } });
      toast("Request submitted"); route();
    } else if (f.dataset.form === "offer") {
      const q = Number($("input", f).value);
      await api(`/resources/${f.dataset.resource}/offer`, { method: "POST", body: { request_id: Number(f.dataset.request), quantity: q } }); toast("Offer sent. Quantity is now reserved."); route();
    } else if (f.dataset.form === "assign") {
      const v = $("select", f).value; if (!v) return toast("Choose a volunteer first", true);
      await api(`/allocations/${f.dataset.id}/assign-volunteer`, { method: "POST", body: { volunteer_id: Number(v) } }); toast("Volunteer assigned"); route();
    }
  } catch (ex) { fail(ex.message); }
});
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- boot
async function boot() {
  if (!state.token) return renderAuth();
  try { if (!state.me) state.me = await api("/auth/me"); } catch { return renderAuth(); }
  await loadNotes(); await route();
}
setInterval(() => { if (state.me) loadNotes(); }, 30000);
boot();
