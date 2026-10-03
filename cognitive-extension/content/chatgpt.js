// content/chatgpt.js
(function () {
  let lastMessageCount = 0;
  let isContextValid = true;

  // Check if extension context is still valid
  function checkContext() {
    try {
      return chrome.runtime && chrome.runtime.id !== undefined;
    } catch {
      return false;
    }
  }

  function countMessages() {
    // Stop if context is invalidated
    if (!isContextValid) return;

    try {
      const msgs = document.querySelectorAll('[data-message-author-role="user"]');

      if (msgs.length > lastMessageCount) {
        const newCount = msgs.length - lastMessageCount;
        lastMessageCount = msgs.length;

        for (let i = 0; i < newCount; i++) {
          // Check context before sending message
          if (!checkContext()) {
            isContextValid = false;
            observer.disconnect();
            console.log(
              "[Cognitive] Extension context invalidated - stopping observer"
            );
            return;
          }

          chrome.runtime
            .sendMessage({ type: "MESSAGE_SENT", platform: "ChatGPT", features: window.__cognitivePromptFeatures?.(msgs[msgs.length - newCount + i]?.innerText) })
            .catch((error) => {
              // Extension context invalidated — stop observing
              if (
                error.message &&
                error.message.includes("Extension context invalidated")
              ) {
                isContextValid = false;
                observer.disconnect();
                console.log(
                  "[Cognitive] Extension reloaded - content script stopped"
                );
              }
            });
        }
      }
    } catch (e) {
      // Extension reloaded mid-session — gracefully stop
      isContextValid = false;
      observer.disconnect();
      console.log("[Cognitive] Error in countMessages:", e.message);
    }
  }

  const observer = new MutationObserver(() => {
    if (!isContextValid) {
      observer.disconnect();
      return;
    }
    try {
      countMessages();
    } catch (error) {
      isContextValid = false;
      observer.disconnect();
      console.log("[Cognitive] Observer error:", error.message);
    }
  });

  // Start observing
  if (checkContext()) {
    observer.observe(document.body, { childList: true, subtree: true });
    countMessages();
  } else {
    console.log("[Cognitive] Cannot start - extension context invalid");
  }
})();