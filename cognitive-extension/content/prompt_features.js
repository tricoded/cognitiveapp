// content/prompt_features.js
// On-device prompt feature extraction. Loaded before every platform script.
//
// PRIVACY: the prompt text is only ever read here, in the page, and reduced to
// a handful of numbers/booleans. The text itself is never stored and never
// sent anywhere. Only the returned feature object leaves the page.

(function () {
  const DELEGATION = /\b(write|generate|make|create|draft|fix|rewrite|summari[sz]e|translate|do|give me|build|code)\b/i;
  const LEARNING = /\b(why|how does|how do|explain|understand|what is|what's the difference|teach|intuition|compare|help me learn)\b/i;
  const CODE = /```|\b(def|function|class|import|return|const|let|var|SELECT|#include)\b|[{};]\s*$/m;

  // Cheap similarity for "is this a re-ask of the previous prompt?":
  // Jaccard over word 3-shingles. Only the shingle *hashes* of the previous
  // prompt are kept in memory, not its text.
  function shingleHashes(text) {
    const words = text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);
    const out = new Set();
    for (let i = 0; i + 2 < words.length; i++) {
      const s = words[i] + " " + words[i + 1] + " " + words[i + 2];
      let h = 2166136261;
      for (let j = 0; j < s.length; j++) h = Math.imul(h ^ s.charCodeAt(j), 16777619);
      out.add(h >>> 0);
    }
    if (out.size === 0 && words.length) out.add(words.join(" ").length);
    return out;
  }

  function jaccard(a, b) {
    if (!a.size || !b.size) return 0;
    let inter = 0;
    for (const x of a) if (b.has(x)) inter++;
    return inter / (a.size + b.size - inter);
  }

  let prevShingles = new Set();

  function randomId(prefix) {
    const b = new Uint8Array(8);
    crypto.getRandomValues(b);
    return prefix + Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  }

  window.__cognitivePromptFeatures = function (text) {
    const t = (text || "").trim();
    const sh = shingleHashes(t);
    const reask = jaccard(sh, prevShingles) >= 0.5;
    prevShingles = sh;
    const learning = LEARNING.test(t);
    return {
      event_id: randomId("e"),
      client_ts: new Date().toISOString(),
      tz_offset: -Math.round(new Date().getTimezoneOffset() / 60),
      msg_len: t.length,
      has_code: CODE.test(t),
      is_question: /\?\s*$/.test(t) || learning,
      is_reask: reask,
      prompt_kind: learning ? "learning" : DELEGATION.test(t) ? "delegation" : "learning",
    };
  };
})();
