// content/gemini.js
// Hardened version — mirrors chatgpt.js defensive pattern
(function () {
  let lastCount = 0;
  let isContextValid = true;

  // ── Context guard (same pattern as chatgpt.js) ──────────────────────────
  function checkContext() {
    try {
      return chrome.runtime && chrome.runtime.id !== undefined;
    } catch {
      return false;
    }
  }

  function countMessages() {
    if (!isContextValid) return;

    try {
      // ── Gemini uses <user-query> custom elements ─────────────────────────
      // Fallback selectors in case Gemini updates their DOM
      const msgs =
        document.querySelectorAll("user-query").length > 0
          ? document.querySelectorAll("user-query")
          : document.querySelectorAll('[data-turn-role="user"]'); // fallback

      if (msgs.length > lastCount) {
        const diff = msgs.length - lastCount;
        lastCount = msgs.length;

        for (let i = 0; i < diff; i++) {
          if (!checkContext()) {
            isContextValid = false;
            observer.disconnect();
            console.log("[Cognitive] Gemini: Extension context invalidated");
            return;
          }

          chrome.runtime
            .sendMessage({ type: "MESSAGE_SENT", platform: "Gemini", features: window.__cognitivePromptFeatures?.(msgs[msgs.length - diff + i]?.innerText) })
            .catch((err) => {
              if (
                err?.message?.includes("Extension context invalidated") ||
                err?.message?.includes("Could not establish connection")
              ) {
                isContextValid = false;
                observer.disconnect();
                console.log(
                  "[Cognitive] Gemini: Extension reloaded — stopping observer"
                );
              }
            });
        }
      }
    } catch (e) {
      isContextValid = false;
      observer.disconnect();
      console.log("[Cognitive] Gemini: Error in countMessages:", e.message);
    }
  }

  const observer = new MutationObserver(() => {
    if (!isContextValid) {
      observer.disconnect();
      return;
    }
    try {
      countMessages();
    } catch (e) {
      isContextValid = false;
      observer.disconnect();
    }
  });

  // ── Start ─────────────────────────────────────────────────────────────────
  if (checkContext()) {
    observer.observe(document.body, { childList: true, subtree: true });
    countMessages(); // Check existing messages on load

    chrome.runtime
      .sendMessage({ type: "CONTENT_SCRIPT_READY", platform: "Gemini" })
      .catch(() => {}); // Silently ignore if background not ready yet
  } else {
    console.log("[Cognitive] Gemini: Cannot start — extension context invalid");
  }
})();