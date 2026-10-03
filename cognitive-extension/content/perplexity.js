// content/perplexity.js
(function () {
  let lastCount = 0;

  function countSearches() {
    try {
      const results = document.querySelectorAll(".prose");
      if (results.length > lastCount) {
        const diff = results.length - lastCount;
        lastCount = results.length;
        for (let i = 0; i < diff; i++) {
          chrome.runtime.sendMessage({ type: "MESSAGE_SENT", platform: "Perplexity" })
            .catch(() => observer.disconnect());
        }
      }
    } catch (_) {
      observer.disconnect();
    }
  }

  const observer = new MutationObserver(() => {
    try { countSearches(); } catch (_) { observer.disconnect(); }
  });

  observer.observe(document.body, { childList: true, subtree: true });
  countSearches();
})();
