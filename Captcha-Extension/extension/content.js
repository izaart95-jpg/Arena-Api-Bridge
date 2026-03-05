/**
 * content.js — Arena reCAPTCHA Harvester
 * =======================================
 * Injected into every arena.ai page at document_idle.
 *
 * Responsibilities:
 *   - Install the fetch blocker (removes forceLowRecaptchaScore) immediately
 *   - Provide a message bridge so the page's injected harvester scripts can
 *     communicate with the background service worker via chrome.runtime
 *
 * Note: Content scripts run in an isolated world — they can't directly reach
 * window.grecaptcha. The actual harvester JS (injectV2Harvester / injectV3Harvester)
 * is injected into the MAIN world by the background via chrome.scripting.executeScript.
 * This file just handles the relay layer.
 */

// ─── Install fetch blocker in MAIN world via classic script injection ─────────
// Content scripts can't override window.fetch directly in the page context,
// so we create a <script> element to run in the MAIN world.

function installBlockerViaScript() {
  if (document.getElementById("__arena_blocker_script__")) return;
  const s = document.createElement("script");
  s.id = "__arena_blocker_script__";
  s.textContent = `
    (function() {
      if (window.__ARENA_BLOCKER_INSTALLED__) return;
      window.__ARENA_BLOCKER_INSTALLED__ = true;
      const _origFetch = window.fetch;
      window.fetch = function(...args) {
        let [url, options = {}] = args;
        if (options.body && typeof options.body === 'string') {
          try {
            const body = JSON.parse(options.body);
            const deepClean = (obj) => {
              if (!obj || typeof obj !== 'object') return obj;
              if (Array.isArray(obj)) return obj.map(deepClean);
              const out = {};
              for (const [k, v] of Object.entries(obj)) {
                if (k === 'forceLowRecaptchaScore') { console.log('🚫 REMOVED forceLowRecaptchaScore'); continue; }
                out[k] = deepClean(v);
              }
              return out;
            };
            options = { ...options, body: JSON.stringify(deepClean(body)) };
            args[1] = options;
          } catch(_) {}
        }
        return _origFetch.apply(this, args);
      };
      console.log('[content] ✅ Arena Blocker installed');
    })();
  `;
  (document.head || document.documentElement).appendChild(s);
  s.remove(); // clean up DOM after execution
}

installBlockerViaScript();

// ─── Listen for messages from background → forward page-visible notifications ─
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "STATE_UPDATE") {
    // Could dispatch a custom event to the page if needed in future
  }
});

console.log("[content] Arena Harvester content script loaded on", window.location.href);
