// cognitive-extension/content/claude.js
(function () {
  console.log("[Cognitive] ✅ Claude content script loaded");

  let lastMessageCount = 0;
  let isInitialized = false;

  function getUserMessages() {
    const selectors = [
      '[data-testid*="user"]',
      '[class*="user"]',
      '[data-message-author="human"]',
      '[data-role="user"]',
      'div[data-is-streaming="false"]'
    ];

    for (const selector of selectors) {
      try {
        const nodes = document.querySelectorAll(selector);
        const filtered = Array.from(nodes).filter(
          (el) => el.textContent && el.textContent.trim().length > 0
        );
        if (filtered.length > 0) {
          console.log(`[Cognitive] Claude selector matched: ${selector} -> ${filtered.length}`);
          return filtered;
        }
      } catch (err) {
        console.warn(`[Cognitive] Selector failed: ${selector}`, err);
      }
    }

    return [];
  }

  function detectMessages() {
    const userMessages = getUserMessages();
    const currentCount = userMessages.length;

    console.log(`[Cognitive] Claude user messages: ${currentCount}, last: ${lastMessageCount}`);

    if (!isInitialized) {
      lastMessageCount = currentCount;
      isInitialized = true;
      console.log(`[Cognitive] Claude baseline set to ${currentCount}`);
      return;
    }

    if (currentCount > lastMessageCount) {
      const newCount = currentCount - lastMessageCount;

      for (let i = 0; i < newCount; i++) {
        chrome.runtime.sendMessage({
          type: "MESSAGE_SENT",
          platform: "Claude",
          features: window.__cognitivePromptFeatures?.(userMessages[currentCount - newCount + i]?.textContent)
        }, (res) => {
          if (chrome.runtime.lastError) {
            console.error("[Cognitive] Claude send error:", chrome.runtime.lastError.message);
          } else {
            console.log("[Cognitive] Claude MESSAGE_SENT acknowledged:", res);
          }
        });
      }

      lastMessageCount = currentCount;
    }
  }

  const observer = new MutationObserver(() => {
    detectMessages();
  });

  function init() {
    console.log("[Cognitive] 🚀 Claude initializing...");

    setTimeout(() => {
      detectMessages();
      observer.observe(document.body, { childList: true, subtree: true });
    }, 2500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();