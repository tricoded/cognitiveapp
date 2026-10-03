// background.js — Service Worker
// Handles: tab tracking, idle detection, session logging, nudge notifications

import { COGNITIVE_CONFIG } from "./config.js";

// ── PERSISTENT LOGGING (survives DevTools close) ─────────────────────────────

const MAX_LOG_ENTRIES = 100;

function addPersistentLog(message) {
  const timestamp = new Date().toISOString();
  const entry = `[${timestamp}] ${message}`;
  
  chrome.storage.local.get(["cognitive_logs"], (r) => {
    let logs = r.cognitive_logs || [];
    logs.push(entry);
    if (logs.length > MAX_LOG_ENTRIES) {
      logs = logs.slice(-MAX_LOG_ENTRIES); // Keep only last 100
    }
    chrome.storage.local.set({ cognitive_logs: logs });
  });
  
  // Also log to console for real-time viewing
  console.log(message);
}

// Replace console.log calls in your code with addPersistentLog()

let activeSessions = {};

// ── Platform detection ────────────────────────────────────────────────────────

function getPlatform(url) {
  try {
    const hostname = new URL(url).hostname.replace("www.", "");
    for (const [key, val] of Object.entries(COGNITIVE_CONFIG.PLATFORMS)) {
      if (hostname.includes(key)) return { hostname, ...val };
    }
  } catch (_) {}
  return null;
}

// ── Storage helpers ───────────────────────────────────────────────────────────

async function getApiBase() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["apiBase"], (res) => {
      resolve(res.apiBase || COGNITIVE_CONFIG.API_BASE_DEFAULT);
    });
  });
}

async function getDailyBudgetMins() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(["dailyBudgetMins"], (res) => {
      resolve(res.dailyBudgetMins || 120);
    });
  });
}

async function getTodayTotalMins() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["todayDate", "todayTotalMins"], (res) => {
      const today = new Date().toISOString().slice(0, 10);
      if (res.todayDate !== today) {
        chrome.storage.local.set({ todayDate: today, todayTotalMins: 0 });
        resolve(0);
      } else {
        resolve(res.todayTotalMins || 0);
      }
    });
  });
}

async function addTodayMins(mins) {
  const current = await getTodayTotalMins();
  const newTotal = current + mins;
  const today = new Date().toISOString().slice(0, 10);
  chrome.storage.local.set({ todayDate: today, todayTotalMins: newTotal });
  return newTotal;
}

function qualityFromCount(messageCount) {
  if (messageCount === 0) return "passive";
  if (messageCount < 3)  return "passive";
  return "active";
}

async function saveActiveSessions() {
  return chrome.storage.local.set({ activeSessions });
}

async function loadActiveSessions() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["activeSessions"], (res) => {
      activeSessions = res.activeSessions || {};
      resolve(activeSessions);
    });
  });
}

loadActiveSessions().then(() => {
  addPersistentLog(`[Cognitive] Restored ${Object.keys(activeSessions).length} active session(s) from storage`);
});

saveActiveSessions()

// ── Create a new session object ───────────────────────────────────────────────

function createSession(tabId, platform) {
  return {
    tabId,
    hostname:     platform.hostname,
    platformName: platform.name,
    category:     platform.category,
    startTime:    Date.now(),
    activeMs:     0,
    lastTick:     Date.now(),
    messageCount: 0,
    idleSince:    null,
    logged:       false,
    sessionId:    "s" + Math.random().toString(16).slice(2, 12),
    delegationCount: 0,
    reaskCount:      0,
    msgTimes:        [],   // timestamps only, for msgs_last_5min
  };
}

async function logSession(session) {
  // ✅ FIX: Changed from 1 minute to 10 seconds (gives users time to load page)
  const durationMins = Math.round(session.activeMs / 60000);
  if (durationMins < 0.2) {  // 0.2 min = 12 seconds
    addPersistentLog(`[Cognitive] Skipping session for ${session.platformName} — duration too short (${Math.round(session.activeMs / 1000)}s)`);
    return;
  }

  const apiBase = await getApiBase();
  const payload = {
    tool_name:     session.platformName,
    category:      session.category,
    duration_mins: Math.max(1, durationMins),  // ✅ Always send at least 1 min to backend
    quality:       qualityFromCount(session.messageCount),
    notes:         `Auto-tracked · ${session.messageCount} message(s)`,
  };

  addPersistentLog(`[Cognitive] 📤 Logging session to ${apiBase}/ai-usage/ | duration: ${Math.round(session.activeMs / 1000)}s (${durationMins}m)`);

  try {
    const res = await fetch(`${apiBase}/ai-usage/`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });

    if (!res.ok) {
      const errText = await res.text();
      addPersistentLog(`[Cognitive] ❌ Failed to log session: HTTP ${res.status} | ${errText}`);
      saveFailedSession(payload);
    } else {
      addPersistentLog(`[Cognitive] ✅ Session logged successfully`);
    }
  } catch (err) {
    addPersistentLog(`[Cognitive] 🌐 Network error logging session: ${err.message}`);
    saveFailedSession(payload);
  }

  const newTotal = await addTodayMins(Math.max(1, durationMins));
  await checkNudge(newTotal);
}

function saveFailedSession(payload) {
  chrome.storage.local.get(["failedSessions"], (r) => {
    const failed = r.failedSessions || [];
    failed.push({ ...payload, failedAt: Date.now() });
    chrome.storage.local.set({ failedSessions: failed });
    console.log(`[Cognitive] 💾 Saved to retry queue (${failed.length} pending)`);
  });
}

// ── Nudge ─────────────────────────────────────────────────────────────────────

async function checkNudge(totalMins) {
  const today = new Date().toISOString().slice(0, 10);
  const result = await new Promise((r) =>
    chrome.storage.local.get(["nudgeFiredDate"], r)
  );
  if (result.nudgeFiredDate === today) return;

  if (totalMins >= COGNITIVE_CONFIG.NUDGE_THRESHOLD_MINS) {
    chrome.notifications.create("cognitive_nudge", {
      type:     "basic",
      iconUrl:  "icons/icon96.png",
      message:  `You've spent ${totalMins} minutes on AI tools today. Take a moment to reflect — is this working for you?`,
      buttons:  [{ title: "Open Dashboard" }, { title: "Dismiss" }],
      priority: 2,
    });
    chrome.storage.local.set({ nudgeFiredDate: today });
  }
}

chrome.notifications.onButtonClicked.addListener((notifId, btnIdx) => {
  if (notifId === "cognitive_nudge" && btnIdx === 0) {
    chrome.storage.sync.get(["appUrl"], (res) => {
      chrome.tabs.create({ url: res.appUrl || "http://localhost:8501" });
    });
  }
});

// ── Retry failed sessions ─────────────────────────────────────────────────────

async function retryFailedSessions() {
  chrome.storage.local.get(["failedSessions"], async (r) => {
    const failed = r.failedSessions || [];
    if (failed.length === 0) return;

    console.log(`[Cognitive] ♻️ Retrying ${failed.length} failed session(s)...`);
    const apiBase    = await getApiBase();
    const retrying   = [...failed];
    const stillFailed = [];

    for (const payload of retrying) {
      try {
        const res = await fetch(`${apiBase}/ai-usage/`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(payload),
        });
        if (!res.ok) {
          stillFailed.push(payload);
        } else {
          console.log("[Cognitive] ♻️ Retry succeeded:", payload.tool_name);
        }
      } catch (_) {
        stillFailed.push(payload);
      }
    }

    chrome.storage.local.set({ failedSessions: stillFailed });
  });
}

// ── Tab event listeners ───────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const now = Date.now();

  for (const [id, session] of Object.entries(activeSessions)) {
    if (parseInt(id) !== tabId && session.lastTick) {
      session.activeMs += now - session.lastTick;
      session.lastTick = null;
    }
  }

  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab?.url) return;

  const platform = getPlatform(tab.url);
  if (!platform) return;

  if (!activeSessions[tabId]) {
    activeSessions[tabId] = createSession(tabId, platform);
    addPersistentLog(`[Cognitive] 🟢 New session: ${platform.name} (tab ${tabId})`);
  } else {
    activeSessions[tabId].lastTick = now;
    addPersistentLog(`[Cognitive] ▶️ Resumed session: ${platform.name} (tab ${tabId})`);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const session = activeSessions[tabId];
  if (!session) {
    addPersistentLog(`[Cognitive] ⚠️ Tab ${tabId} closed — no tracked session found`);
    return;
  }

  const now = Date.now();
  if (session.lastTick) {
    session.activeMs += now - session.lastTick;
    session.lastTick = null;
  }

  addPersistentLog(`[Cognitive] 🔴 Tab closed: ${session.platformName} — logging session`);
  logSession({ ...session });
  delete activeSessions[tabId];
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url) {
    const session  = activeSessions[tabId];
    const platform = getPlatform(changeInfo.url);

    if (session && !platform) {
      // Navigated away from a tracked platform
      addPersistentLog(`[Cognitive] 🔄 Navigated away from ${session.platformName} — logging`);      logSession(session);
      delete activeSessions[tabId];
    } else if (!session && platform) {
      // Navigated TO a tracked platform
      activeSessions[tabId] = createSession(tabId, platform);
      addPersistentLog(`[Cognitive] 🟢 New session via navigation: ${platform.name}`);
    } else if (session && platform && session.platformName !== platform.name) {
      // Switched between platforms (e.g., ChatGPT → Gemini in same tab)
      addPersistentLog(`[Cognitive] 🔄 Platform switch: ${session.platformName} → ${platform.name}`);
      logSession(session);
      activeSessions[tabId] = createSession(tabId, platform);
    }
  }
});

// ── CRITICAL FIX: Handle CONTENT_SCRIPT_READY ────────────────────────────────
// This fires when a content script loads on a page, ensuring the session
// is registered even if the tab was already open before the extension loaded.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // ── Session registration from content script ──────────────────────────────
  if (msg.type === "CONTENT_SCRIPT_READY") {
    const tabId = sender.tab?.id;
    const url   = sender.tab?.url;

    if (!tabId || !url) {
      sendResponse({ ok: false, reason: "no tab info" });
      return true;
    }

    const platform = getPlatform(url);
    if (!platform) {
      sendResponse({ ok: false, reason: "not a tracked platform" });
      return true;
    }

    // Only create session if one doesn't already exist
    if (!activeSessions[tabId]) {
      activeSessions[tabId] = createSession(tabId, platform);
      addPersistentLog(`[Cognitive] 🟢 Session registered via content script: ${platform.name} (tab ${tabId})`);
    }

    sendResponse({ ok: true, platform: platform.name });
    return true;
  }

  // ── Message count ─────────────────────────────────────────────────────────
  if (msg.type === "MESSAGE_SENT") {
    const tabId = sender.tab?.id;
    if (tabId && activeSessions[tabId]) {
      activeSessions[tabId].messageCount += 1;
      recordPromptFeatures(activeSessions[tabId], msg.features);
      addPersistentLog(`[Cognitive] 💬 ${activeSessions[tabId].platformName} message count: ${activeSessions[tabId].messageCount}`);
    } else if (tabId) {
      // Session missing — try to create it from tab URL
      const url = sender.tab?.url;
      if (url) {
        const platform = getPlatform(url);
        if (platform) {
          activeSessions[tabId] = createSession(tabId, platform);
          activeSessions[tabId].messageCount = 1;
          addPersistentLog(`[Cognitive] 🟡 Late session created for ${platform.name} via MESSAGE_SENT`);
        }
      }
    }
    sendResponse({ ok: true });
    return true;
  }

  // ── Get all active sessions (for popup) ──────────────────────────────────
  if (msg.type === "GET_SESSIONS") {
    const sessions = Object.values(activeSessions).map((s) => ({
      tabId:        s.tabId,
      platformName: s.platformName,
      category:     s.category,
      activeMs:     s.activeMs,
      messageCount: s.messageCount,
      startTime:    s.startTime,
      isActive:     s.lastTick !== null,
    }));
    sendResponse({ sessions });
    return true;
  }

  // ── Today's total usage ───────────────────────────────────────────────────
  if (msg.type === "GET_TODAY_TOTAL") {
    getTodayTotalMins().then((total) => {
      getDailyBudgetMins().then((budget) => {
        sendResponse({ total, budget });
      });
    });
    return true;
  }

  // ── Force log all sessions (called before opening dashboard) ─────────────
  if (msg.type === "FORCE_LOG_ALL") {
    const sessions = Object.values(activeSessions).map((s) => ({ ...s }));
    Promise.all(sessions.map((s) => logSession(s))).then(async () => {
      activeSessions = {};
      await saveActiveSessions();
      sendResponse({ ok: true });
    });
    return true;
  }
});

// ── Prompt-level events + real-time decisions ───────────────────────────────
// Only on-device features arrive here (see content/prompt_features.js);
// prompt text never reaches the background worker or the API.

const EVENT_QUEUE_MAX = 2000;

async function getDeviceId() {
  const r = await chrome.storage.local.get(["deviceId"]);
  if (r.deviceId) return r.deviceId;
  const id = "d" + crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  await chrome.storage.local.set({ deviceId: id });
  return id;
}

function recordPromptFeatures(session, features) {
  session.msgTimes = (session.msgTimes || []).filter((t) => Date.now() - t < 5 * 60 * 1000);
  session.msgTimes.push(Date.now());
  if (!features) return;
  if (features.prompt_kind === "delegation") session.delegationCount = (session.delegationCount || 0) + 1;
  if (features.is_reask) session.reaskCount = (session.reaskCount || 0) + 1;
  const event = {
    ...features,
    platform:    session.platformName,
    session_id:  session.sessionId,
    app_version: chrome.runtime.getManifest().version,
  };
  chrome.storage.local.get(["eventQueue"], (r) => {
    const q = (r.eventQueue || []).concat([event]).slice(-EVENT_QUEUE_MAX);
    chrome.storage.local.set({ eventQueue: q });
  });
}

async function flushEvents() {
  const { eventQueue = [] } = await chrome.storage.local.get(["eventQueue"]);
  if (eventQueue.length === 0) return;
  const batch = eventQueue.slice(0, 500);
  const deviceId = await getDeviceId();
  try {
    const res = await fetch(`${await getApiBase()}/ai-usage/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(batch.map((e) => ({ ...e, device_id: deviceId }))),
    });
    if (res.ok) {
      // Server dedups on event_id, so a retry after a lost response is safe.
      const sent = new Set(batch.map((e) => e.event_id));
      const { eventQueue: latest = [] } = await chrome.storage.local.get(["eventQueue"]);
      await chrome.storage.local.set({ eventQueue: latest.filter((e) => !sent.has(e.event_id)) });
    }
  } catch (_) { /* offline: keep queue, retry next tick */ }
}

async function requestDecision(session) {
  const n = session.messageCount || 0;
  const payload = {
    platform:          session.platformName,
    session_minutes:   session.activeMs / 60000,
    msgs_in_session:   n,
    msgs_last_5min:    (session.msgTimes || []).filter((t) => Date.now() - t < 5 * 60 * 1000).length,
    delegation_share:  n ? (session.delegationCount || 0) / n : 0,
    reask_share:       n ? (session.reaskCount || 0) / n : 0,
    local_hour:        new Date().getHours(),
    today_total_mins:  await getTodayTotalMins(),
    daily_budget_mins: await getDailyBudgetMins(),
  };
  try {
    const res = await fetch(`${await getApiBase()}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return;
    const d = await res.json();
    if (d.action !== "allow" && d.message) {
      chrome.notifications.create(`cognitive_decision_${d.decision_id}`, {
        type:     "basic",
        iconUrl:  "icons/icon96.png",
        title:    d.action === "cool_down" ? "Time for a cool-down" : "Cognitive check-in",
        message:  d.message,
        buttons:  [{ title: "Open Dashboard" }, { title: "Dismiss" }],
        priority: d.action === "soft_nudge" ? 1 : 2,
      });
      addPersistentLog(`[Cognitive] 🧭 Decision ${d.action} (${d.reasons.join(",")}) variant=${d.variant}`);
    }
  } catch (_) { /* API offline: fail open (allow) */ }
}

chrome.notifications.onButtonClicked.addListener((notifId, btnIdx) => {
  if (notifId.startsWith("cognitive_decision_") && btnIdx === 0) {
    chrome.storage.sync.get(["appUrl"], (res) => {
      chrome.tabs.create({ url: res.appUrl || "http://localhost:8501" });
    });
  }
});

// ── Tick (every 30 seconds) ───────────────────────────────────────────────────

chrome.alarms.create("tick", { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "tick") return;

  const now      = Date.now();
  const idleMs   = COGNITIVE_CONFIG.IDLE_THRESHOLD_SECS * 1000;

  chrome.idle.queryState(COGNITIVE_CONFIG.IDLE_THRESHOLD_SECS, (state) => {
    for (const [tabId, session] of Object.entries(activeSessions)) {
      if (!session.lastTick) continue;

      const elapsed = now - session.lastTick;

      if (state === "idle" || state === "locked") {
        if (!session.idleSince) session.idleSince = now;
      } else {
        if (session.idleSince) {
          const idleDuration = now - session.idleSince;
          if (idleDuration > idleMs) {
            // Was idle too long — reset tick without counting time
            session.lastTick  = now;
            session.idleSince = null;
            continue;
          }
          session.idleSince = null;
        }

        session.activeMs += elapsed;
        session.lastTick  = now;

        // Auto-log every 30 minutes of active time
        if (session.activeMs >= 30 * 60 * 1000) {
          addPersistentLog(`[Cognitive] ⏰ 30min reached for ${session.platformName} — auto-logging`);
          logSession({ ...session });
          session.activeMs  = 0;
          session.startTime = now;
        }
      }
    }
  });

  retryFailedSessions();
  flushEvents();

  // Ask the decision engine about each active session, at most once a minute.
  for (const session of Object.values(activeSessions)) {
    if (!session.lastTick) continue;
    if (session.lastDecisionAt && now - session.lastDecisionAt < 60 * 1000) continue;
    session.lastDecisionAt = now;
    requestDecision(session);
  }
});