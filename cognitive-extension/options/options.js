// options.js

function load() {
  chrome.storage.sync.get(["apiBase", "appUrl", "dailyBudgetMins"], (res) => {
    document.getElementById("apiBase").value    = res.apiBase        || "http://localhost:8000";
    document.getElementById("appUrl").value     = res.appUrl         || "http://localhost:8501";
    document.getElementById("budgetMins").value = res.dailyBudgetMins || 120;
  });
}

document.getElementById("save").addEventListener("click", () => {
  const apiBase        = document.getElementById("apiBase").value.trim();
  const appUrl         = document.getElementById("appUrl").value.trim();
  const dailyBudgetMins = parseInt(document.getElementById("budgetMins").value, 10) || 120;

  chrome.storage.sync.set({ apiBase, appUrl, dailyBudgetMins }, () => {
    const msg = document.getElementById("savedMsg");
    msg.style.display = "inline";
    setTimeout(() => (msg.style.display = "none"), 2500);
  });
});

load();
