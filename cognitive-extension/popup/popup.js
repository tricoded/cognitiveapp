// popup/popup.js — Clean version, no openTracker reference

const STREAMLIT_FALLBACK = "http://localhost:8501";

// ── Elements — all fetched safely ────────────────────────────────────────────
const statusDot        = document.getElementById("statusDot");
const budgetValue      = document.getElementById("budgetValue");
const barFill          = document.getElementById("barFill");
const budgetLeft       = document.getElementById("budgetLeft");
const budgetPct        = document.getElementById("budgetPct");
const sessionsList     = document.getElementById("sessionsList");
const refreshBtn       = document.getElementById("refreshBtn");
const lastUpdated      = document.getElementById("lastUpdated");
const overBudgetBanner = document.getElementById("overBudgetBanner");
const openDashboard    = document.getElementById("openDashboard");
const openOptions      = document.getElementById("openOptions");
// ✅ openTracker is COMPLETELY REMOVED — was causing script crash

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatMs(ms) {
  const totalSec = Math.floor(ms / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  if (mins === 0) return `${secs}s`;
  return `${mins}m ${secs}s`;
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function platformIcon(name) {
  const icons = {
    ChatGPT:    "🤖",
    Claude:     "🧠",
    Gemini:     "♊",
    DeepSeek:   "🔍",
    Perplexity: "🔮",
    Copilot:    "💡",
  };
  return icons[name] || "🤖";
}

// ── Render sessions ───────────────────────────────────────────────────────────

function renderSessions(sessions) {
  if (!sessionsList) return;

  if (!sessions || sessions.length === 0) {
    sessionsList.innerHTML = `
      <div class="empty">
        <div class="empty-icon">😴</div>
        <div>No AI tools open right now</div>
        <div style="font-size:9px; margin-top:4px; color:var(--muted);">
          Open ChatGPT, Gemini, or Claude to start tracking
        </div>
      </div>`;
    if (statusDot) statusDot.className = "status-dot";
    return;
  }

  const activeSessions = sessions.filter((s) => s.isActive);
  if (statusDot) {
    statusDot.className =
      activeSessions.length > 0 ? "status-dot active" : "status-dot";
  }

  sessionsList.innerHTML = sessions
    .map((session) => {
      const icon     = platformIcon(session.platformName);
      const timeStr  = formatMs(session.activeMs);
      const isActive = session.isActive;
      const category = session.category || "AI Tool";

      return `
        <div class="session-card ${isActive ? "active-tab" : ""}">
          <div>
            <div class="session-name">${icon} ${session.platformName}</div>
            <div class="badges">
              <span class="cat-badge">${category}</span>
              <span class="msg-badge">
                💬 ${session.messageCount} msg${session.messageCount !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
          <div style="text-align:right;">
            <div class="session-time">${timeStr}</div>
            ${
              isActive
                ? `<div style="font-size:9px; color:var(--accent2); margin-top:2px;">● LIVE</div>`
                : `<div style="font-size:9px; color:var(--muted); margin-top:2px;">paused</div>`
            }
          </div>
        </div>`;
    })
    .join("");
}

// ── Render budget ─────────────────────────────────────────────────────────────

function renderBudget(totalMins, budgetMins) {
  if (!budgetValue || !barFill || !budgetPct || !budgetLeft) return;

  const pct       = Math.min((totalMins / budgetMins) * 100, 100);
  const remaining = budgetMins - totalMins;
  const over      = totalMins > budgetMins;

  budgetValue.innerHTML = `${totalMins}<span> / ${budgetMins}min</span>`;

  barFill.style.width      = `${pct}%`;
  barFill.style.background = over
    ? "var(--danger)"
    : pct >= 80
    ? "var(--warn)"
    : "var(--accent2)";

  budgetPct.textContent  = `${pct.toFixed(0)}%`;
  budgetLeft.textContent = over
    ? `⚠️ ${Math.abs(remaining)}min over budget`
    : `${remaining}min remaining`;
  budgetLeft.style.color = over
    ? "var(--danger)"
    : pct >= 80
    ? "var(--warn)"
    : "var(--muted)";

  if (statusDot) {
    if (over) {
      statusDot.classList.add("danger");
      statusDot.classList.remove("warn");
    } else if (pct >= 80) {
      statusDot.classList.add("warn");
      statusDot.classList.remove("danger");
    }
  }

  if (overBudgetBanner) {
    overBudgetBanner.classList.toggle("visible", over);
  }
}

// ── Main refresh ──────────────────────────────────────────────────────────────

async function refresh() {
  if (refreshBtn) refreshBtn.classList.add("spinning");

  try {
    // 1. Sessions from background service worker
    const sessionRes = await chrome.runtime.sendMessage({ type: "GET_SESSIONS" });
    renderSessions(sessionRes?.sessions || []);

    // 2. Today's budget from background
    const todayRes = await chrome.runtime.sendMessage({ type: "GET_TODAY_TOTAL" });
    renderBudget(todayRes?.total ?? 0, todayRes?.budget ?? 120);

    if (lastUpdated) lastUpdated.textContent = `Updated ${formatTime(new Date())}`;
  } catch (err) {
    console.error("[Popup] Refresh error:", err);
    if (sessionsList) {
      sessionsList.innerHTML = `
        <div class="empty">
          <div>⚠️ Extension error — try reloading</div>
        </div>`;
    }
    if (lastUpdated) lastUpdated.textContent = "Update failed";
  }

  setTimeout(() => {
    if (refreshBtn) refreshBtn.classList.remove("spinning");
  }, 500);
}

// ── Button events — all guarded with ?. ──────────────────────────────────────

openDashboard?.addEventListener("click", async () => {
  // Force-log all sessions before opening dashboard so data is fresh
  try {
    await chrome.runtime.sendMessage({ type: "FORCE_LOG_ALL" });
    await new Promise((r) => setTimeout(r, 600)); // wait for POST to complete
  } catch (_) {}

  const res = await chrome.storage.sync.get(["appUrl"]);
  chrome.tabs.create({ url: res.appUrl || STREAMLIT_FALLBACK });
  window.close();
});

openOptions?.addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
  window.close();
});

refreshBtn?.addEventListener("click", () => refresh());

// ── Auto-refresh every 5s while popup open ────────────────────────────────────
refresh();
const interval = setInterval(refresh, 5000);
window.addEventListener("unload", () => clearInterval(interval));
