const totalCost = document.getElementById("totalCost");
const anomalyCount = document.getElementById("anomalyCount");
const recommendationCount = document.getElementById("recommendationCount");
const potentialSavings = document.getElementById("potentialSavings");
const lastSync = document.getElementById("lastSync");
const costSource = document.getElementById("costSource");
const anomalyReadiness = document.getElementById("anomalyReadiness");
const anomalyStatusMessage = document.getElementById("anomalyStatusMessage");
const anomalyGraph = document.getElementById("anomalyGraph");
const anomaliesContainer = document.getElementById("anomalies");
const recommendationsContainer = document.getElementById("recommendations");
const consoleEl = document.getElementById("console");
const syncResult = document.getElementById("syncResult");
const syncButton = document.getElementById("syncButton");
const refreshButton = document.getElementById("refreshButton");
const logoutButton = document.getElementById("logoutButton");
const sessionInfo = document.getElementById("sessionInfo");
const userManagement = document.getElementById("userManagement");
const userAdminHint = document.getElementById("userAdminHint");

let currentUser = null;

function log(message, payload) {
  const timestamp = new Date().toLocaleTimeString();
  const line = payload ? `${timestamp} ${message}\n${JSON.stringify(payload, null, 2)}` : `${timestamp} ${message}`;
  consoleEl.textContent = `${line}\n\n${consoleEl.textContent}`.trim();
}

function money(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value || 0);
}

function timeLabel(value) {
  if (!value) {
    return "No sync has run yet";
  }
  return `Last sync signal: ${new Date(value).toLocaleString()}`;
}

function costSourceLabel(source) {
  return source === "actual_billing"
    ? "Cost source: actual AWS/GCP billing data"
    : "Cost source: live estimated pricing from current resource inventory";
}

function anomalyReadinessLabel(readiness, observedDays, minDaysRequired) {
  if (readiness === "ready") {
    return `Detector ready - ${observedDays}/${minDaysRequired} billing days`;
  }
  if (readiness === "warming_up") {
    return `Detector warming up - ${observedDays}/${minDaysRequired} billing days`;
  }
  return `Detector waiting - ${observedDays}/${minDaysRequired} billing days`;
}

async function getJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (response.status === 401) {
    window.location.href = "/auth/login";
    throw new Error("Authentication required.");
  }
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json();
}

async function requireSession() {
  currentUser = await getJson("/auth/me");
  sessionInfo.textContent = `${currentUser.full_name} - ${currentUser.role}`;
  const canOperate = currentUser.role === "operator" || currentUser.role === "admin";
  syncButton.disabled = !canOperate;
  recommendationsContainer.dataset.canOperate = String(canOperate);
}

function renderAnomalies(items) {
  if (!items.length) {
    anomaliesContainer.className = "stack-list empty-state";
    anomaliesContainer.textContent = "No anomalies detected in the current data window.";
    return;
  }
  anomaliesContainer.className = "stack-list";
  anomaliesContainer.innerHTML = items.map((item) => `
    <article class="item-card">
      <div class="item-topline">
        <div>
          <h3 class="item-title">${item.scope_key}</h3>
          <p class="item-meta">
            Observed ${money(item.observed_cost)} vs expected ${money(item.expected_cost)} on ${item.usage_date}
          </p>
        </div>
        <span class="badge badge-danger">score ${(item.anomaly_score * 100).toFixed(0)}</span>
      </div>
    </article>
  `).join("");
}

function renderAnomalyGraph(status) {
  anomalyReadiness.textContent = anomalyReadinessLabel(
    status.readiness,
    status.observed_days,
    status.min_days_required,
  );
  anomalyStatusMessage.textContent = status.status_message;

  if (!status.points.length) {
    anomalyGraph.className = "graph empty-graph";
    anomalyGraph.textContent = "No billing-history points yet. Cost Explorer is still warming up.";
    return;
  }

  const maxCost = Math.max(...status.points.map((point) => point.total_cost), 0.01);
  anomalyGraph.className = "graph";
  anomalyGraph.innerHTML = status.points.map((point) => {
    const height = Math.max((point.total_cost / maxCost) * 120, 8);
    const label = new Date(point.usage_date).toLocaleDateString("en-US", { month: "short", day: "numeric" });
    return `
      <div class="graph-bar-wrap" title="${label}: ${money(point.total_cost)} across ${point.record_count} records">
        <div class="graph-value">${money(point.total_cost)}</div>
        <div class="graph-bar" style="height:${height}px"></div>
        <div class="graph-label">${label}</div>
      </div>
    `;
  }).join("");
}

function recommendationButtons(item) {
  const canOperate = currentUser && (currentUser.role === "operator" || currentUser.role === "admin");
  if (!canOperate) {
    return "";
  }
  return `
    <div class="item-actions">
      <button class="button button-secondary button-small" data-action="approve" data-id="${item.id}">
        Approve + Dry Run
      </button>
      <button class="button button-primary button-small" data-action="execute" data-id="${item.id}">
        Force Execute
      </button>
    </div>
  `;
}

function renderRecommendations(items) {
  if (!items.length) {
    recommendationsContainer.className = "stack-list empty-state";
    recommendationsContainer.textContent = "No optimization candidates yet.";
    return;
  }
  recommendationsContainer.className = "stack-list";
  recommendationsContainer.innerHTML = items.map((item) => `
    <article class="item-card">
      <div class="item-topline">
        <div>
          <h3 class="item-title">${item.description}</h3>
          <p class="item-meta">
            ${item.provider.toUpperCase()} - ${item.recommendation_type} - saves ${money(item.estimated_monthly_savings)}/mo
          </p>
        </div>
        <span class="badge ${item.executed ? "badge-teal" : item.approved ? "badge-neutral" : "badge-danger"}">
          ${item.executed ? "Executed" : item.approved ? "Approved" : "Pending"}
        </span>
      </div>
      ${recommendationButtons(item)}
    </article>
  `).join("");
}

function userCard(user) {
  return `
    <article class="item-card">
      <div class="item-topline">
        <div>
          <h3 class="item-title">${user.full_name}</h3>
          <p class="item-meta">${user.email} - ${user.role} - ${user.is_active ? "active" : "inactive"}</p>
        </div>
      </div>
    </article>
  `;
}

function inviteCard(invite) {
  return `
    <article class="item-card">
      <div class="item-topline">
        <div>
          <h3 class="item-title">${invite.full_name}</h3>
          <p class="item-meta">${invite.email} - ${invite.role} - ${invite.status}</p>
        </div>
      </div>
      <p class="item-meta">Invite link: <a href="${invite.invite_link}" target="_blank" rel="noreferrer">${invite.invite_link}</a></p>
    </article>
  `;
}

function auditCard(entry) {
  return `
    <article class="item-card">
      <div class="item-topline">
        <div>
          <h3 class="item-title">${entry.action}</h3>
          <p class="item-meta">${entry.actor_email || "system"} - ${entry.outcome} - ${new Date(entry.created_at).toLocaleString()}</p>
        </div>
      </div>
      <p class="item-meta">${entry.target_type || "system"} ${entry.target_id || ""}</p>
    </article>
  `;
}

async function loadUsers() {
  if (!currentUser || currentUser.role !== "admin") {
    userAdminHint.textContent = "Admin tools hidden";
    userManagement.className = "admin-grid empty-state";
    userManagement.textContent = "User management is available to admins only.";
    return;
  }
  userAdminHint.textContent = "Admin access enabled";
  const [users, invites, logs] = await Promise.all([
    getJson("/auth/users"),
    getJson("/auth/invites"),
    getJson("/auth/audit-logs"),
  ]);
  userManagement.className = "admin-grid";
  userManagement.innerHTML = `
    <div class="split-panel">
      <section class="item-card">
        <h3 class="item-title">Invite User</h3>
        <form id="inviteForm" class="admin-form">
          <label class="field"><span>Full Name</span><input id="inviteName" required></label>
          <label class="field"><span>Email</span><input id="inviteEmail" type="email" required></label>
          <label class="field">
            <span>Role</span>
            <select id="inviteRole">
              <option value="viewer">viewer</option>
              <option value="operator">operator</option>
              <option value="admin">admin</option>
            </select>
          </label>
          <button class="button button-primary" type="submit">Create Invite</button>
        </form>
        <div id="inviteStatus" class="auth-status">Invite links are redeemable from the accept page.</div>
      </section>
      <section class="item-card">
        <h3 class="item-title">Current Users</h3>
        <div class="stack-list">${users.map(userCard).join("")}</div>
      </section>
    </div>
    <section class="item-card">
      <h3 class="item-title">Pending And Recent Invites</h3>
      <div class="stack-list">${invites.length ? invites.map(inviteCard).join("") : '<div class="empty-state">No invites yet.</div>'}</div>
    </section>
    <section class="item-card">
      <h3 class="item-title">Audit Log</h3>
      <div class="stack-list">${logs.length ? logs.map(auditCard).join("") : '<div class="empty-state">No audit events yet.</div>'}</div>
    </section>
  `;
  const inviteForm = document.getElementById("inviteForm");
  inviteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      full_name: document.getElementById("inviteName").value,
      email: document.getElementById("inviteEmail").value,
      role: document.getElementById("inviteRole").value,
      expires_in_days: 7,
    };
    const inviteStatus = document.getElementById("inviteStatus");
    inviteStatus.className = "auth-status auth-status-pending";
    inviteStatus.textContent = "Creating invite...";
    try {
      const invite = await getJson("/auth/invites", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      inviteStatus.className = "auth-status auth-status-success";
      inviteStatus.textContent = `Invite created for ${invite.email}.`;
      await loadUsers();
    } catch (error) {
      inviteStatus.className = "auth-status auth-status-error";
      inviteStatus.textContent = `Invite failed: ${error.message}`;
    }
  });
}

async function loadDashboard() {
  try {
    const [anomalyStatus, dashboardSummary, anomalyItems, recommendationItems] = await Promise.all([
      getJson("/anomaly-status"),
      getJson("/summary"),
      getJson("/anomalies"),
      getJson("/recommendations"),
    ]);
    totalCost.textContent = money(dashboardSummary.total_cost);
    anomalyCount.textContent = String(dashboardSummary.anomaly_count);
    recommendationCount.textContent = String(dashboardSummary.recommendation_count);
    potentialSavings.textContent = `${money(dashboardSummary.estimated_monthly_savings)}/mo`;
    lastSync.textContent = timeLabel(dashboardSummary.last_sync_at);
    costSource.textContent = costSourceLabel(dashboardSummary.cost_source);
    renderAnomalyGraph(anomalyStatus);
    renderAnomalies(anomalyItems);
    renderRecommendations(recommendationItems);
    await loadUsers();
    log("Dashboard refreshed.");
  } catch (error) {
    syncResult.textContent = `Failed to load dashboard: ${error.message}`;
    log("Dashboard load failed.", { error: error.message });
  }
}

async function runSync() {
  syncButton.disabled = true;
  syncResult.textContent = "Running live sync...";
  try {
    const result = await getJson("/sync", { method: "POST" });
    syncResult.textContent = `Sync complete: ${result.ingested_cost_records} cost records, ${result.anomalies_detected} anomalies, ${result.recommendations_generated} recommendations.`;
    log("Live sync completed.", result);
    await loadDashboard();
  } catch (error) {
    syncResult.textContent = `Sync failed: ${error.message}`;
    log("Live sync failed.", { error: error.message });
  } finally {
    syncButton.disabled = false;
  }
}

async function runOptimization(id, mode) {
  try {
    const payload = {
      recommendation_ids: [Number(id)],
      auto_approve: mode === "approve",
      force_execute: mode === "execute",
    };
    const result = await getJson("/optimize", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    log(`Optimization ${mode} completed.`, result);
    await loadDashboard();
  } catch (error) {
    log(`Optimization ${mode} failed.`, { error: error.message });
  }
}

async function logout() {
  await getJson("/auth/logout", { method: "POST" });
  window.location.href = "/auth/login";
}

syncButton.addEventListener("click", runSync);
refreshButton.addEventListener("click", loadDashboard);
logoutButton.addEventListener("click", logout);

recommendationsContainer.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const id = target.dataset.id;
  const action = target.dataset.action;
  if (!id || !action) {
    return;
  }
  runOptimization(id, action);
});

(async function bootstrap() {
  await requireSession();
  await loadDashboard();
})();
