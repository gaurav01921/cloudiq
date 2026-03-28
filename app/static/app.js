const totalCost = document.getElementById("totalCost");
const totalCostLabel = document.getElementById("totalCostLabel");
const forecastCost = document.getElementById("forecastCost");
const forecastCostLabel = document.getElementById("forecastCostLabel");
const forecastCostBadge = document.getElementById("forecastCostBadge");
const anomalyCount = document.getElementById("anomalyCount");
const recommendationCount = document.getElementById("recommendationCount");
const potentialSavings = document.getElementById("potentialSavings");
const lastSync = document.getElementById("lastSync");
const costSource = document.getElementById("costSource");
const costSourceBadge = document.getElementById("costSourceBadge");
const anomalySeverityBadge = document.getElementById("anomalySeverityBadge");
const anomalyReadiness = document.getElementById("anomalyReadiness");
const anomalyStatusMessage = document.getElementById("anomalyStatusMessage");
const anomalyGraphMeta = document.getElementById("anomalyGraphMeta");
const anomalyGraph = document.getElementById("anomalyGraph");
const syncTimeline = document.getElementById("syncTimeline");
const anomaliesContainer = document.getElementById("anomalies");
const recommendationsContainer = document.getElementById("recommendations");
const recentActivity = document.getElementById("recentActivity");
const consoleEl = document.getElementById("console");
const syncResult = document.getElementById("syncResult");
const syncButton = document.getElementById("syncButton");
const refreshButton = document.getElementById("refreshButton");
const logoutButton = document.getElementById("logoutButton");
const sessionInfo = document.getElementById("sessionInfo");
const roleLabel = document.getElementById("roleLabel");
const environmentLabel = document.getElementById("environmentLabel");
const dateRangeLabel = document.getElementById("dateRangeLabel");
const dataModeSelect = document.getElementById("dataModeSelect");
const dataModeStatus = document.getElementById("dataModeStatus");
const userManagement = document.getElementById("userManagement");
const userAdminHint = document.getElementById("userAdminHint");
const navItems = Array.from(document.querySelectorAll(".nav-item[href^='#']"));

let currentUser = null;
let dataModeDirty = false;
let latestAuditLogs = [];
let visibleAuditCount = 12;

function log(message, payload) {
  const timestamp = new Date().toLocaleTimeString();
  const line = payload ? `${timestamp} ${message}\n${JSON.stringify(payload, null, 2)}` : `${timestamp} ${message}`;
  consoleEl.textContent = `${line}\n\n${consoleEl.textContent}`.trim();
}

function money(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value || 0);
}

function compactMoney(value) {
  return money(value).replace(".00", "");
}

function timeLabel(value) {
  if (!value) {
    return "No sync has run yet.";
  }
  return `Last sync: ${new Date(value).toLocaleString()}`;
}

function billedSpendLabel(summary) {
  if (summary.billing_signal_status === "actual_billing_available") {
    return "Actual billed spend from live cloud billing data.";
  }
  if (summary.billing_signal_status === "billing_zero_or_credit_only") {
    return "Live billing rows are present, but billed spend is still zero or credit-covered.";
  }
  return "Waiting for real billing rows from the connected cloud account.";
}

function costSourceBadgeLabel(summary) {
  if (summary.billing_signal_status === "actual_billing_available") {
    return "Verified";
  }
  if (summary.billing_signal_status === "billing_zero_or_credit_only") {
    return "Zero Spend";
  }
  return "Warming Up";
}

function forecastValueLabel(summary) {
  if (summary.has_actual_billing_data) {
    return "Forecasted EOM";
  }
  return "Run Rate";
}

function forecastBadgeLabel(summary) {
  return summary.has_actual_billing_data ? "Projected" : "Estimated";
}

function forecastCopy(summary) {
  const syncText = timeLabel(summary.last_sync_at);
  if (summary.has_actual_billing_data) {
    return `Projected from current billed trend. ${syncText}`;
  }
  if (summary.billing_signal_status === "billing_zero_or_credit_only") {
    return `Current monthly run rate from live resource inventory. ${syncText}`;
  }
  return `Inventory estimate until billing data arrives. ${syncText}`;
}

function dataModeLabel(dataMode) {
  return `Data mode: ${dataMode}`;
}

function environmentText(dataMode) {
  if (dataMode === "demo") {
    return "Demo Scenario";
  }
  if (dataMode === "hybrid") {
    return "Hybrid Control Plane";
  }
  return "Production (AWS/GCP)";
}

function providerLabel(provider) {
  return {
    aws: "AWS",
    gcp: "GCP",
    demo: "Demo",
  }[provider] || provider.toUpperCase();
}

function anomalySeverityLabel(count) {
  if (count >= 3) {
    return "Critical";
  }
  if (count >= 1) {
    return "Active";
  }
  return "Stable";
}

function recommendationState(item) {
  const result = item.execution_result || {};
  if (item.executed) {
    return { label: "Executed", badgeClass: "badge-teal" };
  }
  if (result.dry_run && result.authorized) {
    return { label: "Dry Run Ready", badgeClass: "badge-info" };
  }
  if (result.skipped) {
    return { label: "Blocked", badgeClass: "badge-warning" };
  }
  if (item.approved) {
    return { label: "Approved", badgeClass: "badge-neutral" };
  }
  return { label: "Pending", badgeClass: "badge-danger" };
}

function anomalyReadinessLabel(readiness, observedDays, minDaysRequired) {
  if (readiness === "ready") {
    return `ML anomaly detection is ready with ${observedDays} billing days in the baseline window.`;
  }
  if (readiness === "warming_up") {
    return `The detector is warming up with ${observedDays}/${minDaysRequired} billing days collected.`;
  }
  if (readiness === "waiting_for_cost_signal") {
    return "Billing rows are arriving, but there is still no real spend signal for anomaly training.";
  }
  return `Waiting for billing history: ${observedDays}/${minDaysRequired} baseline days available.`;
}

function timelineModeLabel(mode) {
  if (mode === "demo_preset") {
    return "Demo preset timeline";
  }
  if (mode === "hybrid_timeline") {
    return "Hybrid timeline";
  }
  return "Live billing timeline";
}

function shortDate(value) {
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function longDate(value) {
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function monthDateRangeLabel(points) {
  if (!points || !points.length) {
    const now = new Date();
    return now.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }
  const first = points[0].usage_date;
  const last = points[points.length - 1].usage_date;
  return `${longDate(first)} - ${longDate(last)}`;
}

function buildLinePath(points, width, height, padding) {
  const maxCost = Math.max(...points.map((point) => point.total_cost), 0.01);
  const innerWidth = width - (padding * 2);
  const innerHeight = height - (padding * 2);
  const step = points.length > 1 ? innerWidth / (points.length - 1) : 0;

  const mapped = points.map((point, index) => {
    const x = padding + (step * index);
    const y = padding + (innerHeight - ((point.total_cost / maxCost) * innerHeight));
    return { ...point, x, y };
  });

  const line = mapped.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const area = `${line} L ${mapped[mapped.length - 1].x} ${height - padding} L ${mapped[0].x} ${height - padding} Z`;
  return { mapped, line, area, maxCost };
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
  sessionInfo.textContent = `${currentUser.full_name}\n${currentUser.email}`;
  roleLabel.textContent = `${currentUser.full_name} - ${currentUser.role}`;
  const canOperate = currentUser.role === "operator" || currentUser.role === "admin";
  syncButton.disabled = !canOperate;
  dataModeSelect.disabled = !canOperate;
  recommendationsContainer.dataset.canOperate = String(canOperate);
}

async function loadDataMode() {
  const result = await getJson("/data-mode");
  dataModeSelect.value = result.data_mode;
  dataModeSelect.dataset.currentMode = result.data_mode;
  dataModeStatus.textContent = dataModeLabel(result.data_mode);
  environmentLabel.textContent = environmentText(result.data_mode);
}

async function updateDataMode() {
  const selectedMode = dataModeSelect.value;
  const previousMode = dataModeSelect.dataset.currentMode || selectedMode;
  dataModeSelect.disabled = true;
  dataModeStatus.textContent = `Switching to ${selectedMode}...`;
  try {
    const result = await getJson("/data-mode", {
      method: "PUT",
      body: JSON.stringify({ data_mode: selectedMode }),
    });
    dataModeSelect.value = result.data_mode;
    dataModeSelect.dataset.currentMode = result.data_mode;
    environmentLabel.textContent = environmentText(result.data_mode);
    dataModeDirty = true;
    dataModeStatus.textContent = `${dataModeLabel(result.data_mode)}. Syncing fresh ${result.data_mode} data...`;
    log("Data mode updated.", result);
    await runSync({ reason: "mode_switch", quiet: true });
  } catch (error) {
    dataModeSelect.value = previousMode;
    dataModeSelect.dataset.currentMode = previousMode;
    environmentLabel.textContent = environmentText(previousMode);
    dataModeStatus.textContent = `Data mode update failed: ${error.message}`;
    log("Data mode update failed.", { error: error.message });
  } finally {
    dataModeSelect.disabled = !(currentUser && (currentUser.role === "operator" || currentUser.role === "admin"));
  }
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
          <p class="item-meta">Observed ${money(item.observed_cost)} vs expected ${money(item.expected_cost)} on ${item.usage_date}</p>
        </div>
        <span class="badge badge-danger">Score ${(item.anomaly_score * 100).toFixed(0)}</span>
      </div>
    </article>
  `).join("");
}

function renderAnomalyGraph(status, anomalyItems = []) {
  anomalyReadiness.textContent = anomalyReadinessLabel(
    status.readiness,
    status.signal_days,
    status.min_days_required,
  );
  anomalyStatusMessage.textContent = status.status_message;
  dateRangeLabel.textContent = monthDateRangeLabel(status.points);

  if (!status.points.length) {
    anomalyGraph.className = "graph empty-graph";
    anomalyGraphMeta.className = "graph-meta";
    anomalyGraphMeta.innerHTML = "";
    renderSyncTimeline(status.sync_markers);
    anomalyGraph.textContent = "No billing-history points yet. Cost Explorer is still warming up.";
    return;
  }

  const width = 1280;
  const height = 460;
  const padding = 44;
  const { mapped, line, area, maxCost } = buildLinePath(status.points, width, height, padding);
  const anomalyDates = new Set(anomalyItems.map((item) => item.usage_date));
  const latestPoint = mapped[mapped.length - 1];
  const highestPoint = mapped.reduce((best, point) => (point.total_cost > best.total_cost ? point : best), mapped[0]);
  const interval = Math.max(1, Math.floor(mapped.length / 6));
  const tickIndexes = Array.from(new Set(mapped.map((_, index) => index).filter((index) => {
    return index === 0 || index === mapped.length - 1 || index % interval === 0;
  })));
  const yTicks = 4;
  const anomalyPointCount = mapped.filter((point) => anomalyDates.has(point.usage_date)).length;
  const latestVisiblePoints = mapped.slice(-Math.min(mapped.length, 10));
  const latestRangeMin = Math.min(...latestVisiblePoints.map((point) => point.total_cost));
  const latestRangeMax = Math.max(...latestVisiblePoints.map((point) => point.total_cost));
  const chartMode = status.timeline_mode === "demo_preset" ? "scenario preview" : "live timeline";

  anomalyGraphMeta.className = "graph-meta";
  anomalyGraphMeta.innerHTML = `
    <div class="graph-stat">
      <span class="graph-stat-label">Latest</span>
      <strong>${compactMoney(latestPoint.total_cost)}</strong>
      <span>${shortDate(latestPoint.usage_date)}</span>
    </div>
    <div class="graph-stat">
      <span class="graph-stat-label">Peak Day</span>
      <strong>${compactMoney(highestPoint.total_cost)}</strong>
      <span>${shortDate(highestPoint.usage_date)}</span>
    </div>
    <div class="graph-stat">
      <span class="graph-stat-label">Window</span>
      <strong>${mapped.length} days</strong>
      <span>${compactMoney(maxCost)} max</span>
    </div>
    <div class="graph-stat">
      <span class="graph-stat-label">Timeline</span>
      <strong>${timelineModeLabel(status.timeline_mode)}</strong>
      <span>${status.points[0].point_source.toUpperCase()} source</span>
    </div>
    <div class="graph-stat">
      <span class="graph-stat-label">Recent range</span>
      <strong>${compactMoney(latestRangeMin)} - ${compactMoney(latestRangeMax)}</strong>
      <span>${chartMode}</span>
    </div>
  `;

  anomalyGraph.className = "graph graph-line";
  anomalyGraph.innerHTML = `
    <svg class="trend-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-label="Billing trend">
      <defs>
        <linearGradient id="anomalyAreaFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="rgba(108, 99, 255, 0.28)"></stop>
          <stop offset="100%" stop-color="rgba(108, 99, 255, 0.02)"></stop>
        </linearGradient>
      </defs>
      ${anomalyItems.map((item) => {
        const point = mapped.find((entry) => entry.usage_date === item.usage_date);
        if (!point) {
          return "";
        }
        return `<rect x="${Math.max(point.x - 9, padding)}" y="${padding}" width="18" height="${height - (padding * 2)}" class="trend-anomaly-band"></rect>`;
      }).join("")}
      ${Array.from({ length: yTicks }, (_, index) => {
        const ratio = index / (yTicks - 1);
        const y = padding + ((height - (padding * 2)) * ratio);
        return `<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" class="trend-grid"></line>`;
      }).join("")}
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" class="trend-axis"></line>
      <path d="${area}" class="trend-area"></path>
      <path d="${line}" class="trend-line"></path>
      ${mapped.map((point) => `
        <g class="trend-point-group">
          ${anomalyDates.has(point.usage_date)
            ? `<circle cx="${point.x}" cy="${point.y}" r="5.5" class="trend-point-anomaly"></circle>`
            : ""}
          ${point.usage_date === latestPoint.usage_date
            ? `<circle cx="${point.x}" cy="${point.y}" r="4" class="trend-point-latest"></circle>`
            : ""}
          <title>${shortDate(point.usage_date)}: ${money(point.total_cost)} across ${point.record_count} records</title>
        </g>
      `).join("")}
      ${anomalyItems.map((item) => {
        const point = mapped.find((entry) => entry.usage_date === item.usage_date);
        if (!point) {
          return "";
        }
        return `
          <g class="trend-callout">
            <line x1="${point.x}" y1="${point.y - 12}" x2="${point.x}" y2="${point.y - 34}" class="trend-callout-line"></line>
            <rect x="${point.x - 36}" y="${point.y - 54}" width="72" height="22" rx="11" class="trend-callout-pill"></rect>
            <text x="${point.x}" y="${point.y - 39}" text-anchor="middle" class="trend-callout-text">${compactMoney(item.observed_cost)}</text>
          </g>
        `;
      }).join("")}
      ${Array.from({ length: yTicks }, (_, index) => {
        const value = maxCost - ((maxCost / (yTicks - 1)) * index);
        const y = padding + ((height - (padding * 2)) * (index / (yTicks - 1)));
        return `<text x="0" y="${y + 4}" text-anchor="start" class="trend-y-tick">${compactMoney(value)}</text>`;
      }).join("")}
      ${tickIndexes.map((index) => `
        <text x="${mapped[index].x}" y="${height - 2}" text-anchor="middle" class="trend-tick">${shortDate(mapped[index].usage_date)}</text>
      `).join("")}
    </svg>
  `;
  renderSyncTimeline(status.sync_markers);
}

function renderSyncTimeline(markers) {
  if (!markers || !markers.length) {
    syncTimeline.className = "sync-timeline empty-state";
    syncTimeline.textContent = "No recent sync markers yet.";
    return;
  }
  syncTimeline.className = "sync-timeline";
  syncTimeline.innerHTML = markers.map((marker) => `
    <div class="sync-chip">
      <strong>${new Date(marker.started_at).toLocaleTimeString()}</strong>
      <span>${marker.status} - ${marker.records_ingested} records</span>
      <span>${marker.anomalies_detected} anomalies</span>
    </div>
  `).join("");
}

function recommendationButtons(item) {
  const canOperate = currentUser && (currentUser.role === "operator" || currentUser.role === "admin");
  if (!canOperate) {
    return "";
  }
  if (item.executed) {
    return `
      <div class="item-actions">
        <button class="button button-secondary button-small" disabled>Completed</button>
      </div>
    `;
  }
  const readyForExecution = Boolean(item.execution_result && item.execution_result.dry_run && item.execution_result.authorized);
  const approveLabel = readyForExecution ? "Re-Run Dry Run" : "Approve + Dry Run";
  const executeDisabled = item.provider !== "demo" && !readyForExecution;
  return `
    <div class="item-actions">
      <button class="button button-secondary button-small" data-action="approve" data-id="${item.id}">
        ${approveLabel}
      </button>
      <button class="button button-primary button-small" data-action="execute" data-id="${item.id}" ${executeDisabled ? "disabled" : ""}>
        Execute Now
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
          <p class="item-meta">${providerLabel(item.provider)} - ${item.recommendation_type} - saves ${money(item.estimated_monthly_savings)}/mo</p>
        </div>
        <span class="badge ${recommendationState(item).badgeClass}">${recommendationState(item).label}</span>
      </div>
      ${item.execution_result?.reason ? `<p class="item-meta">${item.execution_result.reason}</p>` : ""}
      ${recommendationButtons(item)}
    </article>
  `).join("");
}

function renderRecentActivity(entries) {
  if (!entries.length) {
    recentActivity.className = "activity-stream empty-state";
    recentActivity.textContent = "Recent activity will appear here.";
    return;
  }
  recentActivity.className = "activity-stream";
  recentActivity.innerHTML = entries.map((entry) => `
    <article class="activity-item">
      <h3 class="activity-title">${entry.action}</h3>
      <div class="activity-copy">Target: ${entry.target_type || "system"} ${entry.target_id || ""}</div>
      <div class="activity-time">${entry.actor_email || "system"} - ${entry.outcome} - ${new Date(entry.created_at).toLocaleString()}</div>
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
    <article class="item-card audit-row">
      <div class="item-topline audit-row-topline">
        <div>
          <h3 class="item-title">${entry.action}</h3>
          <p class="item-meta">${entry.actor_email || "system"} - ${entry.target_type || "system"} ${entry.target_id || ""}</p>
        </div>
        <div class="audit-row-meta">
          <span class="badge ${entry.outcome === "success" ? "badge-teal" : "badge-warning"}">${entry.outcome}</span>
          <span class="audit-row-time">${new Date(entry.created_at).toLocaleString()}</span>
        </div>
      </div>
    </article>
  `;
}

function buildAuditQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      query.set(key, String(value).trim());
    }
  });
  return query.toString();
}

async function fetchAuditLogs(filters = {}) {
  const query = buildAuditQuery(filters);
  const path = query ? `/auth/audit-logs?${query}` : "/auth/audit-logs";
  return getJson(path);
}

function renderAuditList() {
  const auditList = document.getElementById("auditLogList");
  const auditCount = document.getElementById("auditCount");
  const auditLoadMore = document.getElementById("auditLoadMore");
  if (!auditList) {
    return;
  }
  if (auditCount) {
    auditCount.textContent = `${latestAuditLogs.length} events loaded`;
  }
  auditList.innerHTML = latestAuditLogs.length
    ? latestAuditLogs.slice(0, visibleAuditCount).map(auditCard).join("")
    : '<div class="empty-state">No audit events match the current filters.</div>';
  if (auditLoadMore) {
    auditLoadMore.hidden = latestAuditLogs.length <= visibleAuditCount;
    auditLoadMore.textContent = `Load more (${Math.max(latestAuditLogs.length - visibleAuditCount, 0)} remaining)`;
  }
}

async function refreshAuditSection(filters = {}) {
  visibleAuditCount = 12;
  latestAuditLogs = await fetchAuditLogs(filters);
  renderRecentActivity(latestAuditLogs.slice(0, 8));
  renderAuditList();
}

function updateActiveNavigation() {
  const trackedSections = [
    { sectionId: "dashboardSection", element: document.getElementById("dashboardSection") },
    { sectionId: "radarSection", element: document.getElementById("radarSection") },
    { sectionId: "optimizationSection", element: document.getElementById("optimizationSection") },
    { sectionId: "governanceSection", element: document.getElementById("governanceSection") },
  ].filter((entry) => entry.element);

  const offset = 180;
  let activeSectionId = "dashboardSection";

  trackedSections.forEach((entry) => {
    if (entry.element.getBoundingClientRect().top - offset <= 0) {
      activeSectionId = entry.sectionId;
    }
  });

  navItems.forEach((item) => item.classList.remove("nav-item-active"));
  const activeItem = navItems.find((item) => item.dataset.section === activeSectionId);
  if (activeItem) {
    activeItem.classList.add("nav-item-active");
  }
}

async function loadUsers() {
  if (!currentUser || currentUser.role !== "admin") {
    userAdminHint.textContent = "Admin tools hidden";
    userManagement.className = "admin-grid empty-state";
    userManagement.textContent = "User management is available to admins only.";
    renderRecentActivity([]);
    return;
  }

  userAdminHint.textContent = "Admin access enabled";
  const [users, invites, logs] = await Promise.all([
    getJson("/auth/users"),
    getJson("/auth/invites"),
    getJson("/auth/audit-logs"),
  ]);

  latestAuditLogs = logs;
  renderRecentActivity(logs.slice(0, 8));
  userManagement.className = "admin-grid";
  userManagement.innerHTML = `
    <div class="split-panel">
      <section class="item-card">
        <h3 class="item-title">Invite User</h3>
        <form id="inviteForm" class="admin-form">
          <label class="field field-dark"><span>Full Name</span><input id="inviteName" required></label>
          <label class="field field-dark"><span>Email</span><input id="inviteEmail" type="email" required></label>
          <label class="field field-dark">
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
      <div class="audit-summary">
        <span id="auditCount">${logs.length} events loaded</span>
        <span>Scrollable log view</span>
      </div>
      <div class="audit-toolbar">
        <label class="field field-dark">
          <span>Search</span>
          <input id="auditQuery" placeholder="action, actor, target">
        </label>
        <label class="field field-dark">
          <span>Action</span>
          <input id="auditAction" placeholder="ops.sync">
        </label>
        <label class="field field-dark">
          <span>Outcome</span>
          <select id="auditOutcome">
            <option value="">all</option>
            <option value="success">success</option>
            <option value="failure">failure</option>
          </select>
        </label>
        <label class="field field-dark">
          <span>Actor</span>
          <input id="auditActorEmail" placeholder="admin@example.com">
        </label>
      </div>
      <div class="audit-actions">
        <button id="auditApplyFilters" class="button button-secondary button-small" type="button">Apply Filters</button>
        <button id="auditResetFilters" class="button button-ghost button-small" type="button">Reset</button>
        <label class="field field-dark field-inline">
          <span>Purge Older Than Days</span>
          <input id="auditPurgeDays" type="number" min="0" placeholder="30">
        </label>
        <button id="auditPurgeButton" class="button button-secondary button-small" type="button">Purge Matching Logs</button>
      </div>
      <div id="auditStatus" class="auth-status">Use filters to narrow audit events or purge retained history safely.</div>
      <div id="auditLogList" class="audit-log-list">${logs.length ? logs.map(auditCard).join("") : '<div class="empty-state">No audit events yet.</div>'}</div>
      <button id="auditLoadMore" class="button button-ghost button-small" type="button" ${logs.length <= visibleAuditCount ? "hidden" : ""}>Load more</button>
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

  const auditStatus = document.getElementById("auditStatus");
  const auditQuery = document.getElementById("auditQuery");
  const auditAction = document.getElementById("auditAction");
  const auditOutcome = document.getElementById("auditOutcome");
  const auditActorEmail = document.getElementById("auditActorEmail");
  const auditPurgeDays = document.getElementById("auditPurgeDays");

  const currentAuditFilters = () => ({
    query: auditQuery.value,
    action: auditAction.value,
    outcome: auditOutcome.value,
    actor_email: auditActorEmail.value,
    limit: 200,
  });

  document.getElementById("auditApplyFilters").addEventListener("click", async () => {
    auditStatus.className = "auth-status auth-status-pending";
    auditStatus.textContent = "Loading filtered audit log...";
    try {
      await refreshAuditSection(currentAuditFilters());
      auditStatus.className = "auth-status auth-status-success";
      auditStatus.textContent = `Loaded ${latestAuditLogs.length} audit events.`;
    } catch (error) {
      auditStatus.className = "auth-status auth-status-error";
      auditStatus.textContent = `Audit log filter failed: ${error.message}`;
    }
  });

  document.getElementById("auditResetFilters").addEventListener("click", async () => {
    auditQuery.value = "";
    auditAction.value = "";
    auditOutcome.value = "";
    auditActorEmail.value = "";
    auditPurgeDays.value = "";
    auditStatus.className = "auth-status auth-status-pending";
    auditStatus.textContent = "Reloading latest audit log...";
    try {
      await refreshAuditSection({ limit: 200 });
      auditStatus.className = "auth-status auth-status-success";
      auditStatus.textContent = "Audit filters cleared.";
    } catch (error) {
      auditStatus.className = "auth-status auth-status-error";
      auditStatus.textContent = `Audit reset failed: ${error.message}`;
    }
  });

  document.getElementById("auditPurgeButton").addEventListener("click", async () => {
    const purgeDaysValue = auditPurgeDays.value.trim();
    const payload = {
      older_than_days: purgeDaysValue ? Number(purgeDaysValue) : null,
      query: auditQuery.value || null,
      action: auditAction.value || null,
      outcome: auditOutcome.value || null,
      actor_email: auditActorEmail.value || null,
    };
    auditStatus.className = "auth-status auth-status-pending";
    auditStatus.textContent = "Purging matching audit logs...";
    try {
      const result = await getJson("/auth/audit-logs", {
        method: "DELETE",
        body: JSON.stringify(payload),
      });
      await refreshAuditSection({ limit: 200 });
      auditStatus.className = "auth-status auth-status-success";
      auditStatus.textContent = `Purged ${result.deleted_count} audit events.`;
      log("Audit log purge completed.", result);
    } catch (error) {
      auditStatus.className = "auth-status auth-status-error";
      auditStatus.textContent = `Audit purge failed: ${error.message}`;
      log("Audit log purge failed.", { error: error.message });
    }
  });

  document.getElementById("auditLoadMore").addEventListener("click", () => {
    visibleAuditCount += 12;
    renderAuditList();
  });

  renderAuditList();
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
    totalCostLabel.textContent = "MTD Spend";
    forecastCostLabel.textContent = forecastValueLabel(dashboardSummary);
    forecastCostBadge.textContent = forecastBadgeLabel(dashboardSummary);
    forecastCost.textContent = money(dashboardSummary.projected_end_of_month_cost);
    anomalyCount.textContent = String(dashboardSummary.anomaly_count);
    recommendationCount.textContent = String(dashboardSummary.recommendation_count);
    potentialSavings.textContent = `${money(dashboardSummary.estimated_monthly_savings)}/mo`;
    lastSync.textContent = forecastCopy(dashboardSummary);
    costSource.textContent = billedSpendLabel(dashboardSummary);
    costSourceBadge.textContent = costSourceBadgeLabel(dashboardSummary);
    anomalySeverityBadge.textContent = anomalySeverityLabel(dashboardSummary.anomaly_count);
    environmentLabel.textContent = environmentText(dashboardSummary.data_mode);
    dataModeSelect.value = dashboardSummary.data_mode;
    dataModeSelect.dataset.currentMode = dashboardSummary.data_mode;
    dataModeStatus.textContent = dataModeDirty
      ? `${dataModeLabel(dashboardSummary.data_mode)}. Refresh pending sync.`
      : dataModeLabel(dashboardSummary.data_mode);

    renderAnomalyGraph(anomalyStatus, anomalyItems);
    renderAnomalies(anomalyItems);
    renderRecommendations(recommendationItems);
    await loadUsers();
    log("Dashboard refreshed.");
  } catch (error) {
    syncResult.textContent = `Failed to load dashboard: ${error.message}`;
    log("Dashboard load failed.", { error: error.message });
  }
}

async function runSync(options = {}) {
  const { reason = "manual", quiet = false } = options;
  syncButton.disabled = true;
  refreshButton.disabled = true;
  dataModeSelect.disabled = true;
  syncResult.textContent = reason === "mode_switch"
    ? `Syncing ${dataModeSelect.value} data...`
    : "Running live sync...";
  try {
    const result = await getJson("/sync", { method: "POST" });
    syncResult.textContent = `Sync complete: ${result.ingested_cost_records} cost records, ${result.anomalies_detected} anomalies, ${result.recommendations_generated} recommendations.`;
    dataModeDirty = false;
    if (!quiet) {
      log("Live sync completed.", result);
    } else {
      log("Mode change sync completed.", result);
    }
    await loadDashboard();
  } catch (error) {
    syncResult.textContent = `Sync failed: ${error.message}`;
    log(reason === "mode_switch" ? "Mode change sync failed." : "Live sync failed.", { error: error.message });
  } finally {
    const canOperate = currentUser && (currentUser.role === "operator" || currentUser.role === "admin");
    syncButton.disabled = !canOperate;
    refreshButton.disabled = false;
    dataModeSelect.disabled = !canOperate;
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
refreshButton.addEventListener("click", async () => {
  const canOperate = currentUser && (currentUser.role === "operator" || currentUser.role === "admin");
  if (canOperate) {
    await runSync({ reason: "refresh" });
    return;
  }
  await loadDashboard();
});
logoutButton.addEventListener("click", logout);
dataModeSelect.addEventListener("change", updateDataMode);

recommendationsContainer.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const id = target.dataset.id;
  const action = target.dataset.action;
  if (!id || !action || target.hasAttribute("disabled")) {
    return;
  }
  runOptimization(id, action);
});

window.addEventListener("scroll", updateActiveNavigation, { passive: true });

(async function bootstrap() {
  await requireSession();
  await loadDataMode();
  await loadDashboard();
  updateActiveNavigation();
})();
