// config.js
// Configuration constants for Cognitive AI Tracker

const COGNITIVE_CONFIG = {
  // API Settings
  API_BASE_DEFAULT: "http://localhost:8000",
  
  // Idle detection threshold (in seconds)
  IDLE_THRESHOLD_SECS: 30,
  
  // Nudge notification threshold (in minutes)
  NUDGE_THRESHOLD_MINS: 90,
  
  // Supported AI platforms
  PLATFORMS: {
    "chatgpt.com": {
      name: "ChatGPT",
      category: "AI Chat"
    },
    "app.chatly.ai": {
      name: "Claude",
      category: "AI Chat"
    },
    "chatlyai.app": {
      name: "Claude",
      category: "AI Chat"
    },
    "chatly.ai": {
      name: "Claude",
      category: "AI Chat"
    },
    "gemini.google.com": {
      name: "Gemini",
      category: "AI Chat"
    },
    "deepseek.com": {
      name: "DeepSeek",
      category: "AI Search"
    },
    "perplexity.ai": {
      name: "Perplexity",
      category: "AI Search"
    },
    "copilot.microsoft.com": {
      name: "Copilot",
      category: "AI Assistant"
    }
  }
};

// Export for ES6 modules
export { COGNITIVE_CONFIG };
