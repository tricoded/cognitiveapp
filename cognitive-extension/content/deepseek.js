// cognitive-extension/content/deepseek.js
console.log("[Cognitive] ✅ DeepSeek content script loaded");

let lastMessageCount = 0;

const STRATEGIES = [
  // Strategy 1: Hash-like class starting with 'fbb'
  () => document.querySelectorAll('div[class^="fbb"]'),
  
  // Strategy 2: Any div with 8-char hex class
  () => document.querySelectorAll('div[class*="737a4"]'),
  
  // Strategy 3: Fallback to main content divs
  () => document.querySelectorAll('main div[class]'),
];

function detectMessages() {
  let allMessages = [];
  
  for (let i = 0; i < STRATEGIES.length; i++) {
    try {
      const found = STRATEGIES[i]();
      if (found && found.length > 0) {
        // Filter out non-message divs (length check)
        allMessages = Array.from(found).filter(el => 
          el.textContent.trim().length > 5
        );
        
        if (allMessages.length > 0) {
          console.log(`[Cognitive] ✅ Strategy ${i + 1} found ${allMessages.length} messages`);
          console.log(`[Cognitive] 📝 First: "${allMessages[0].textContent.slice(0, 50)}..."`);
          break;
        }
      }
    } catch (err) {
      console.warn(`[Cognitive] ⚠️ Strategy ${i + 1} failed:`, err);
    }
  }

  if (allMessages.length === 0) {
    console.log("[Cognitive] ⚠️ No messages found");
    return;
  }

  const userMessages = allMessages.filter((_, idx) => idx % 2 === 0);
  const currentCount = userMessages.length;

  console.log(`[Cognitive] 📊 Total: ${allMessages.length}, User: ${currentCount}, Last: ${lastMessageCount}`);

  if (currentCount > lastMessageCount) {
    console.log(`[Cognitive] 💬 NEW MESSAGE! Sending MESSAGE_SENT...`);
    chrome.runtime.sendMessage({ type: "MESSAGE_SENT", platform: "DeepSeek", features: window.__cognitivePromptFeatures?.(userMessages[currentCount - 1]?.textContent) }, (res) => {
      if (chrome.runtime.lastError) {
        console.error("[Cognitive] ❌", chrome.runtime.lastError.message);
      } else {
        console.log("[Cognitive] ✅ Acknowledged:", res);
      }
    });
    lastMessageCount = currentCount;
  }
}

function init() {
  console.log("[Cognitive] 🚀 DeepSeek initializing...");
  setTimeout(detectMessages, 2000);
  setInterval(detectMessages, 2000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
