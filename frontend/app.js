const API_BASE = window.REVSHIELD_API_BASE || "https://revshield-ai-go39.onrender.com/";

let token = localStorage.getItem("revshield_token") || null;
let businessName = localStorage.getItem("revshield_business") || "";

// ---------- API helper ----------
async function api(path, { method = "GET", body = null, isForm = false } = {}) {
  const headers = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!isForm && body) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : null,
  });

  if (res.status === 401) {
    logout();
    throw new Error("Session expired. Please log in again.");
  }
  if (!res.ok) {
    let detail = "Request failed";
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : null;
}

// ---------- AUTH ----------
const authScreen = document.getElementById("auth-screen");
const appRoot = document.getElementById("app");

function showApp() {
  authScreen.classList.add("hidden");
  appRoot.classList.remove("hidden");
  document.getElementById("business-name").textContent = businessName;
  loadView("dashboard");
}

function showAuth() {
  appRoot.classList.add("hidden");
  authScreen.classList.remove("hidden");
}

function logout() {
  token = null;
  businessName = "";
  localStorage.removeItem("revshield_token");
  localStorage.removeItem("revshield_business");
  showAuth();
}

document.querySelectorAll(".auth-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".auth-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const target = tab.dataset.tab;
    document.getElementById("login-form").classList.toggle("hidden", target !== "login");
    document.getElementById("signup-form").classList.toggle("hidden", target !== "signup");
  });
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: {
        email: document.getElementById("login-email").value,
        password: document.getElementById("login-password").value,
      },
    });
    token = data.access_token;
    businessName = data.business_name;
    localStorage.setItem("revshield_token", token);
    localStorage.setItem("revshield_business", businessName);
    showApp();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById("signup-error");
  errorEl.textContent = "";
  try {
    const data = await api("/auth/signup", {
      method: "POST",
      body: {
        business_name: document.getElementById("signup-business").value,
        email: document.getElementById("signup-email").value,
        password: document.getElementById("signup-password").value,
      },
    });
    token = data.access_token;
    businessName = data.business_name;
    localStorage.setItem("revshield_token", token);
    localStorage.setItem("revshield_business", businessName);
    showApp();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("logout-btn").addEventListener("click", logout);

// ---------- NAVBAR ----------
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => loadView(btn.dataset.view));
});

function loadView(view) {
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  document.getElementById(`view-${view}`).classList.remove("hidden");

  if (view !== "dashboard") stopDashboardPolling();

  if (view === "dashboard") loadDashboard();
  else if (view === "data") loadDataView();
  else if (view === "risk") loadRiskView();
  else if (view === "recovery") loadRecoveryView();
  else if (view === "offers") loadOffersView();
  else if (view === "assistant") loadAssistantView();
}

function fmtMoney(n) {
  return "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function fmtPct(n) {
  return Math.round((n || 0) * 100) + "%";
}

// ---------- DASHBOARD ----------
let dashboardPollTimer = null;

async function loadDashboard() {
  await refreshDashboardOnce();
  // Keep the dashboard alive: re-pull metrics/queue/feed every few seconds
  // while the merchant is looking at it, so uploads and approvals show up
  // without a manual refresh.
  if (dashboardPollTimer) clearInterval(dashboardPollTimer);
  dashboardPollTimer = setInterval(refreshDashboardOnce, 5000);
}

function stopDashboardPolling() {
  if (dashboardPollTimer) {
    clearInterval(dashboardPollTimer);
    dashboardPollTimer = null;
  }
}

async function refreshDashboardOnce() {
  try {
    const d = await api("/dashboard");
    document.getElementById("m-revenue").textContent = fmtMoney(d.revenue_today);
    document.getElementById("m-risk").textContent = fmtMoney(d.revenue_at_risk);
    document.getElementById("m-recoverable").textContent = fmtMoney(d.recoverable_revenue);
    document.getElementById("m-growth").textContent = fmtMoney(d.growth_opportunity);
    document.getElementById("m-risky-count").textContent = d.risky_transactions;
    document.getElementById("m-incidents-count").textContent = d.payment_incidents;

    const list = document.getElementById("ai-priorities-list");
    list.innerHTML = "";
    d.ai_priorities.forEach((p) => {
      const li = document.createElement("li");
      li.textContent = p;
      list.appendChild(li);
    });
  } catch (err) {
    console.error(err);
  }

  await loadRecoveryQueueWidget();
  await loadActivityFeed();
}

// One-click recovery queue right on the dashboard: approve/skip is the only
// merchant action; the AI (backend) contacts the customer and records the
// outcome itself.
async function loadRecoveryQueueWidget() {
  const wrap = document.getElementById("recovery-queue");
  if (!wrap) return;
  try {
    const offers = await api("/offers?merchant_status=pending");
    const resolved = await api("/offers");
    wrap.innerHTML = "";

    if (!offers.length) {
      const recentlyResolved = resolved
        .filter((o) => o.merchant_status !== "pending")
        .slice(0, 3);
      if (!recentlyResolved.length) {
        wrap.innerHTML = '<p class="empty-note">No recovery candidates right now. Upload transaction/order data to find some.</p>';
        return;
      }
      recentlyResolved.forEach((o) => wrap.appendChild(renderRecoveryCard(o, true)));
      return;
    }

    offers.slice(0, 6).forEach((o) => wrap.appendChild(renderRecoveryCard(o, false)));
  } catch (err) {
    console.error(err);
  }
}

function renderRecoveryCard(o, resolvedOnly) {
  const div = document.createElement("div");
  div.className = "rq-card";
  div.innerHTML = `
    <div class="rq-top"><span>Offer #${o.id}</span><span>${fmtMoney(o.estimated_cost)} cost</span></div>
    <div class="rq-sub">${o.discount_percent}% off drafted by AI</div>
    <div class="rq-offer">${o.message}</div>
  `;

  if (resolvedOnly || o.merchant_status !== "pending") {
    const status = document.createElement("div");
    const label =
      o.customer_status === "accepted" ? "✅ Customer accepted — recovered"
      : o.customer_status === "declined" ? "— Customer declined"
      : o.merchant_status === "rejected" ? "Skipped"
      : "Processing…";
    const cls = o.customer_status === "accepted" ? "accepted" : "declined";
    status.className = "rq-status " + cls;
    status.textContent = label;
    div.appendChild(status);
    return div;
  }

  const actions = document.createElement("div");
  actions.className = "rq-actions";
  const approveBtn = document.createElement("button");
  approveBtn.className = "approve";
  approveBtn.textContent = "Approve";
  approveBtn.addEventListener("click", async () => {
    approveBtn.disabled = true;
    approveBtn.textContent = "AI is handling it…";
    try {
      await api(`/offers/${o.id}/decision`, { method: "PUT", body: { action: "approve" } });
      await refreshDashboardOnce();
    } catch (err) {
      alert(err.message);
    }
  });
  const skipBtn = document.createElement("button");
  skipBtn.textContent = "Skip";
  skipBtn.addEventListener("click", async () => {
    skipBtn.disabled = true;
    try {
      await api(`/offers/${o.id}/decision`, { method: "PUT", body: { action: "reject" } });
      await refreshDashboardOnce();
    } catch (err) {
      alert(err.message);
    }
  });
  actions.appendChild(approveBtn);
  actions.appendChild(skipBtn);
  div.appendChild(actions);
  return div;
}

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso + "Z").getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return mins + "m ago";
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + "h ago";
  return Math.floor(hrs / 24) + "d ago";
}

async function loadActivityFeed() {
  const wrap = document.getElementById("activity-feed");
  if (!wrap) return;
  try {
    const events = await api("/dashboard/activity");
    wrap.innerHTML = "";
    if (!events.length) {
      wrap.innerHTML = '<p class="empty-note">Nothing yet — upload data to see the AI start working.</p>';
    } else {
      events.forEach((e) => {
        const div = document.createElement("div");
        div.className = "activity-item " + e.type;
        div.innerHTML = `<span class="a-time"></span><span></span>`;
        div.querySelector(".a-time").textContent = timeAgo(e.time);
        div.querySelectorAll("span")[1].textContent = e.text;
        wrap.appendChild(div);
      });
    }
    document.getElementById("activity-updated").textContent =
      "Updated " + new Date().toLocaleTimeString();
  } catch (err) {
    console.error(err);
  }
}

// ---------- DATA ----------
function loadDataView() {
  document.getElementById("upload-date").valueAsDate = new Date();
  document.getElementById("autopsy-date") && (document.getElementById("autopsy-date").valueAsDate = new Date());
  loadUploadsHistory();
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const type = document.getElementById("upload-type").value;
  const date = document.getElementById("upload-date").value;
  const fileInput = document.getElementById("upload-file");
  const resultEl = document.getElementById("upload-result");

  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  resultEl.classList.remove("hidden");
  resultEl.textContent = "Uploading and running AI analysis...";

  try {
    const qs = new URLSearchParams({ data_type: type, upload_date: date });
    const data = await api(`/data/upload?${qs.toString()}`, { method: "POST", body: formData, isForm: true });
    resultEl.textContent =
      `Done. Ingested ${data.transactions_ingested || data.orders_ingested || data.customers_ingested} rows for ${data.upload_date}.` +
      (data.analysis_triggered ? ` AI analysis ran — ${data.anomalies_detected} anomalies detected. Jumping to Dashboard…` : "");
    loadUploadsHistory();
    fileInput.value = "";
    if (data.analysis_triggered) {
      setTimeout(() => loadView("dashboard"), 900);
    }
  } catch (err) {
    resultEl.textContent = "Error: " + err.message;
  }
});

async function loadUploadsHistory() {
  try {
    const rows = await api("/data/uploads");
    const tbody = document.querySelector("#uploads-table tbody");
    tbody.innerHTML = "";
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.upload_date}</td>
        <td>${r.transactions_count}</td>
        <td>${r.orders_count}</td>
        <td>${r.customers_count}</td>
        <td>${r.success_rate != null ? fmtPct(r.success_rate) : "—"}</td>
        <td>${r.revenue != null ? fmtMoney(r.revenue) : "—"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// ---------- RISK & INCIDENTS ----------
async function loadRiskView() {
  try {
    const incidents = await api("/risk/incidents?status=open");
    const list = document.getElementById("incidents-list");
    list.innerHTML = "";
    if (!incidents.length) {
      list.innerHTML = '<li class="incident-item" style="border-left-color:var(--ok)">No open incidents. 👍</li>';
    }
    incidents.forEach((inc) => {
      const li = document.createElement("li");
      li.className = "incident-item";
      li.innerHTML = `
        <span class="incident-type">${inc.incident_type.replace(/_/g, " ")}</span>
        ${inc.description}
        <div class="incident-actions">
          <button class="btn-secondary" data-resolve="${inc.id}">Mark resolved</button>
        </div>
      `;
      list.appendChild(li);
    });
    list.querySelectorAll("[data-resolve]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api(`/risk/incidents/${btn.dataset.resolve}/resolve`, { method: "PUT" });
        loadRiskView();
        loadDashboard();
      });
    });
  } catch (err) {
    console.error(err);
  }

  try {
    const txns = await api("/risk/transactions?limit=25");
    const tbody = document.querySelector("#risk-table tbody");
    tbody.innerHTML = "";
    txns.forEach((t) => {
      const badgeClass = t.risk_score >= 65 ? "risk-high" : t.risk_score >= 35 ? "risk-med" : "risk-low";
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${t.external_id}</td>
        <td>${fmtMoney(t.amount)}</td>
        <td>${t.payment_method}</td>
        <td>${t.status.replace(/_/g, " ")}</td>
        <td><span class="badge ${badgeClass}">${t.risk_score.toFixed(0)}</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

document.getElementById("autopsy-btn").addEventListener("click", async () => {
  const date = document.getElementById("autopsy-date").value;
  const resultEl = document.getElementById("autopsy-result");
  resultEl.classList.remove("hidden");
  resultEl.textContent = "Analyzing...";
  try {
    const data = await api(`/risk/autopsy?upload_date=${date}`);
    resultEl.textContent = data.explanation;
  } catch (err) {
    resultEl.textContent = "Error: " + err.message;
  }
});

// ---------- RECOVERY ----------
async function loadRecoveryView() {
  try {
    const budget = await api("/recovery/budget");
    document.getElementById("budget-input").value = budget.total_budget;
    const pct = budget.total_budget > 0 ? Math.min((budget.used / budget.total_budget) * 100, 100) : 0;
    document.getElementById("budget-fill").style.width = pct + "%";
    document.getElementById("budget-text").textContent =
      `${fmtMoney(budget.used)} used of ${fmtMoney(budget.total_budget)} (${budget.candidates_selected} candidates selected)`;
  } catch (err) {
    console.error(err);
  }

  try {
    const rows = await api("/recovery/candidates");
    const tbody = document.querySelector("#recovery-table tbody");
    tbody.innerHTML = "";
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${r.priority_rank ?? "—"}</td>
        <td>${r.reason.replace(/_/g, " ")}</td>
        <td>${fmtMoney(r.customer_value)}</td>
        <td>${fmtPct(r.recovery_probability)}</td>
        <td>${r.recommended_action}</td>
        <td>${r.status}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

document.getElementById("budget-save-btn").addEventListener("click", async () => {
  const amount = parseFloat(document.getElementById("budget-input").value);
  if (isNaN(amount) || amount < 0) return;
  await api(`/recovery/budget?amount=${amount}`, { method: "PUT" });
  loadRecoveryView();
});

document.getElementById("whatif-btn").addEventListener("click", async () => {
  const discount = parseFloat(document.getElementById("whatif-discount").value) || 0;
  const resultEl = document.getElementById("whatif-result");
  resultEl.classList.remove("hidden");
  resultEl.innerHTML = "<div class='wf-explain'>Simulating...</div>";
  try {
    const data = await api("/recovery/what-if", { method: "POST", body: { discount_percent: discount } });
    resultEl.innerHTML = `
      <div class="wf-stat"><div class="wf-label">Expected recovery (no offer)</div><div class="wf-value">${fmtMoney(data.no_offer_expected_recovery)}</div></div>
      <div class="wf-stat"><div class="wf-label">Expected recovery (with offer)</div><div class="wf-value">${fmtMoney(data.offer_expected_recovery)}</div></div>
      <div class="wf-stat"><div class="wf-label">Offer cost</div><div class="wf-value">${fmtMoney(data.offer_cost)}</div></div>
      <div class="wf-explain"><strong>Expected net benefit: ${fmtMoney(data.expected_net_benefit)}</strong><br/>${data.explanation}</div>
    `;
  } catch (err) {
    resultEl.innerHTML = `<div class="wf-explain">Error: ${err.message}</div>`;
  }
});

// ---------- OFFERS ----------
async function loadOffersView() {
  try {
    const offers = await api("/offers");
    const wrap = document.getElementById("offers-list");
    wrap.innerHTML = "";
    if (!offers.length) {
      wrap.innerHTML = '<p class="subtitle">No offers drafted yet — upload transaction/order data to generate recovery offers.</p>';
      return;
    }
    offers.forEach((o) => {
      const card = document.createElement("div");
      card.className = "offer-card";
      const canDecide = o.merchant_status === "pending";
      const outcomeText =
        o.customer_status === "accepted" ? "✅ Customer accepted — recovered"
        : o.customer_status === "declined" ? "Customer declined"
        : o.merchant_status === "rejected" ? "You skipped this one"
        : "Customer response: pending";

      card.innerHTML = `
        <div class="offer-top">
          <span class="offer-discount">${o.discount_percent}% off</span>
          <span class="status-pill ${o.merchant_status}">${o.merchant_status}</span>
        </div>
        <p class="offer-message">${o.message}</p>
        <p class="offer-meta">Estimated cost: ${fmtMoney(o.estimated_cost)} · ${outcomeText}</p>
        <div class="offer-actions">
          ${canDecide ? `
            <button class="btn-approve" data-approve="${o.id}">Approve — let AI handle it</button>
            <button class="btn-edit" data-edit="${o.id}">Edit</button>
            <button class="btn-reject" data-reject="${o.id}">Reject</button>
          ` : ""}
        </div>
      `;
      wrap.appendChild(card);
    });

    wrap.querySelectorAll("[data-approve]").forEach((btn) =>
      btn.addEventListener("click", () => decideOffer(btn.dataset.approve, "approve"))
    );
    wrap.querySelectorAll("[data-reject]").forEach((btn) =>
      btn.addEventListener("click", () => decideOffer(btn.dataset.reject, "reject"))
    );
    wrap.querySelectorAll("[data-edit]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const discount = prompt("New discount %:");
        const message = prompt("New customer message:");
        if (discount == null && message == null) return;
        decideOffer(btn.dataset.edit, "edit", { discount_percent: discount ? parseFloat(discount) : null, message });
      })
    );
  } catch (err) {
    console.error(err);
  }
}

async function decideOffer(id, action, extra = {}) {
  try {
    await api(`/offers/${id}/decision`, { method: "PUT", body: { action, ...extra } });
    loadOffersView();
  } catch (err) {
    alert(err.message);
  }
}

async function customerRespond(id, accepted) {
  try {
    await api(`/offers/${id}/customer-response?accepted=${accepted}`, { method: "PUT" });
    loadOffersView();
    loadDashboard();
  } catch (err) {
    alert(err.message);
  }
}

// ---------- ASSISTANT ----------
async function loadAssistantView() {
  const messagesEl = document.getElementById("chat-messages");
  messagesEl.innerHTML = "";
  try {
    const history = await api("/assistant/history");
    history.forEach((m) => appendChatMessage(m.role, m.content));
  } catch (err) {
    console.error(err);
  }
  if (!messagesEl.children.length) {
    appendChatMessage("assistant", "Hi, I'm RevShield's assistant. Ask me about today's risk, revenue, or recovery status.");
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendChatMessage(role, content) {
  const messagesEl = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.textContent = content;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const question = input.value.trim();
  if (!question) return;
  appendChatMessage("user", question);
  input.value = "";
  appendChatMessage("assistant", "Thinking...");
  try {
    const data = await api("/assistant/ask", { method: "POST", body: { question } });
    const messagesEl = document.getElementById("chat-messages");
    messagesEl.lastChild.textContent = data.answer;
  } catch (err) {
    const messagesEl = document.getElementById("chat-messages");
    messagesEl.lastChild.textContent = "Error: " + err.message;
  }
});

// ---------- BOOT ----------
if (token) showApp();
else showAuth();
