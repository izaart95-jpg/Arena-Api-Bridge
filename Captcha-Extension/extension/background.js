/**
 * background.js — Arena reCAPTCHA Harvester
 * Service worker. All logic lives here.
 */

// ─── Config defaults ──────────────────────────────────────────────────────────

const DEFAULT_CONFIG = {
  SERVER_PORT: 5000,
  FIVE_GAIN:   false,
  EVAL_ID:     "",
  TUNING:      true,
  HARD_TUNING: false,
};

const HARD_TUNING_KEEP = new Set([
  "arena-auth-prod-v1.0",
  "arena-auth-prod-v1.1",
  "__cf_bm",
  "cf_clearance",
]);

// Per-tab state: { status, activeHarvester, tokenCount }
const tabState = {};

// ─── Config helpers ───────────────────────────────────────────────────────────

function getConfig() {
  return new Promise(resolve => {
    chrome.storage.local.get("harvester_config", data => {
      resolve(Object.assign({}, DEFAULT_CONFIG, data.harvester_config || {}));
    });
  });
}

function saveConfig(cfg) {
  return new Promise(resolve => chrome.storage.local.set({ harvester_config: cfg }, resolve));
}

// ─── Core injection helper ────────────────────────────────────────────────────
// Injects a JS string into the MAIN world of a tab.
// We use the (code => eval(code)) pattern to avoid MV3 function-serialization
// issues where closures and referenced outer functions are lost.

function runInTab(tabId, jsString) {
  return chrome.scripting.executeScript({
    target: { tabId, allFrames: false },
    world:  "MAIN",
    func:   (code) => { (0, eval)(code); },
    args:   [jsString],
  });
}

// ─── Script builders ─────────────────────────────────────────────────────────

function getBlockerScript() {
  return `(function() {
  if (window.__POSTHOG_CAPTURE_READY__) return;
  window.__POSTHOG_CAPTURE_READY__ = true;
  var _orig = window.fetch;
  window.fetch = function() {
    var args = Array.prototype.slice.call(arguments);
    var options = args[1] || {};
    if (options.body && typeof options.body === 'string') {
      try {
        var body = JSON.parse(options.body);
        var deepClean = function(obj) {
          if (!obj || typeof obj !== 'object') return obj;
          if (Array.isArray(obj)) return obj.map(deepClean);
          var out = {};
          for (var k in obj) {
            if (k === 'forceLowRecaptchaScore') { console.log('REMOVED forceLowRecaptchaScore'); continue; }
            out[k] = deepClean(obj[k]);
          }
          return out;
        };
        args[1] = Object.assign({}, options, { body: JSON.stringify(deepClean(body)) });
      } catch(e) {}
    }
    return _orig.apply(this, args);
  };
  console.log('[harvester] Blocker installed');
})();`;
}

function getV2Script(tabId, serverPort) {
  return `(function() {
  if (typeof window.__INTERCOM_SHUTDOWN__ === 'function') window.__INTERCOM_SHUTDOWN__();

  var SERVER_URL = 'http://localhost:${serverPort}/api';
  var V2_SITEKEY = '6Ld7ePYrAAAAAB34ovoFoDau1fqCJ6IyOjFEQaMn';
  var TAB_ID = ${tabId};
  var v2Count = 0, currentTimeoutId = null, panelCreated = false, widgetCounter = 0, invisibleErrors = 0;

  function randInt(min, max) {
    var arr = new Uint32Array(1); crypto.getRandomValues(arr);
    return min + (arr[0] / (0xFFFFFFFF + 1)) * (max - min);
  }

  function sendToken(token, mode) {
    v2Count++; invisibleErrors = 0; updateCount();
    if (panelCreated) updateStatus('Token #' + v2Count + ' captured! Sending...');
    return fetch(SERVER_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: token, version: 'v2', action: mode === 'invisible' ? 'invisible_auto' : 'checkbox_challenge',
        harvest_number: v2Count, source_url: window.location.href, tab_id: TAB_ID, _reload_after: true })
    }).then(function(r) { return r.json(); }).then(function(data) {
      console.log('[v2-' + mode + ' #' + v2Count + '] Stored. Total: ' + data.total_count);
      if (panelCreated) updateStatus('Token #' + v2Count + ' stored! Reloading...');
    }).catch(function(err) { console.error('[v2-' + mode + '] Store failed:', err); });
  }

  function harvestInvisible() {
    var g = window.grecaptcha && window.grecaptcha.enterprise;
    if (!g || typeof g.render !== 'function') { currentTimeoutId = setTimeout(harvestInvisible, 2000); return; }
    widgetCounter++;
    var el = document.createElement('div');
    el.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;overflow:hidden;';
    document.body.appendChild(el);
    var settled = false;
    var timer = setTimeout(function() { if (!settled) { settled = true; el.remove(); handleInvFail(); } }, 60000);
    try {
      var wid = g.render(el, {
        sitekey: V2_SITEKEY, size: 'invisible',
        callback: function(token) {
          if (settled) return; settled = true; clearTimeout(timer); el.remove();
          sendToken(token, 'invisible').then(function() { currentTimeoutId = setTimeout(harvestInvisible, randInt(80, 100) * 1000); });
        },
        'error-callback': function() { if (settled) return; settled = true; clearTimeout(timer); el.remove(); handleInvFail(); }
      });
      if (typeof g.execute === 'function') g.execute(wid);
    } catch(e) { el.remove(); handleInvFail(); }
  }

  function handleInvFail() {
    invisibleErrors++;
    currentTimeoutId = setTimeout(harvestInvisible, Math.min(15 * Math.pow(1.5, invisibleErrors - 1), 300) * 1000);
  }

  function updateStatus(msg) { var el = document.getElementById('__ph_widget_status__'); if (el) el.textContent = msg; }
  function updateCount()     { var el = document.getElementById('__ph_widget_count__');  if (el) el.textContent = v2Count + ' token' + (v2Count !== 1 ? 's' : ''); }

  function createPanel() {
    if (panelCreated) return; panelCreated = true;
    if (document.getElementById('__ph_widget_container__')) return;
    var panel = document.createElement('div');
    panel.id = '__ph_widget_container__';
    panel.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;background:#1a1a2e;border:2px solid #16213e;border-radius:12px;padding:12px 16px;box-shadow:0 4px 20px rgba(0,0,0,0.4);font-family:system-ui,sans-serif;min-width:320px;';
    panel.innerHTML = '<div style="color:#e0e0e0;font-size:13px;margin-bottom:8px;font-weight:600;">v2 Harvester <span id="__ph_widget_count__" style="color:#4ade80;float:right;">0 tokens</span></div><div id="__ph_widget_status__" style="color:#9ca3af;font-size:11px;margin-bottom:10px;">Click the checkbox to harvest</div><div id="__ph_widget_body__" style="display:flex;justify-content:center;"></div><div id="__ph_widget_dismiss__" style="color:#6b7280;font-size:11px;margin-top:8px;cursor:pointer;text-align:center;">x stop</div>';
    panel.querySelector('#__ph_widget_dismiss__').addEventListener('click', function() { window.__INTERCOM_SHUTDOWN__(); });
    document.body.appendChild(panel);
  }

  function renderCheckbox() {
    var g = window.grecaptcha && window.grecaptcha.enterprise;
    if (!g || typeof g.render !== 'function') { setTimeout(renderCheckbox, 1000); return; }
    var panel = document.getElementById('__ph_widget_container__'); if (!panel) return;
    var old = document.getElementById('__ph_widget_body__'); if (old) old.remove();
    var container = document.createElement('div');
    container.id = '__ph_widget_body__'; container.style.cssText = 'display:flex;justify-content:center;';
    panel.insertBefore(container, panel.lastElementChild);
    updateStatus('Click the checkbox to harvest a v2 token');
    var expTimer = setTimeout(function() { updateStatus('Expired. Re-rendering...'); renderCheckbox(); }, 60000);
    try {
      g.render(container, {
        sitekey: V2_SITEKEY,
        callback: function(token) { clearTimeout(expTimer); sendToken(token, 'checkbox'); },
        'error-callback':   function() { clearTimeout(expTimer); updateStatus('Failed. Retry in 5s...');   setTimeout(renderCheckbox, 5000); },
        'expired-callback': function() { clearTimeout(expTimer); updateStatus('Expired. Retry in 3s...');  setTimeout(renderCheckbox, 3000); },
        theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light'
      });
    } catch(e) { clearTimeout(expTimer); updateStatus('Error: ' + e.message + '. Retry in 10s...'); setTimeout(renderCheckbox, 10000); }
  }

  window.__INTERCOM_SHUTDOWN__ = function() {
    if (currentTimeoutId) { clearTimeout(currentTimeoutId); currentTimeoutId = null; }
    var panel = document.getElementById('__ph_widget_container__'); if (panel) panel.remove();
    panelCreated = false; console.log('[v2] Stopped. Tokens: ' + v2Count);
  };

  console.log('[v2] Harvester starting');
  createPanel();
  if (window.grecaptcha && window.grecaptcha.enterprise && window.grecaptcha.enterprise.ready) {
    window.grecaptcha.enterprise.ready(renderCheckbox);
  } else { renderCheckbox(); }
})();`;
}

function getV3Script(tabId, serverPort) {
  return `(function() {
  if (typeof window.__RUDDERSTACK_FLUSH__ === 'function') window.__RUDDERSTACK_FLUSH__();

  var SERVER_URL = 'http://localhost:${serverPort}/api';
  var SITE_KEY   = '6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I';
  var ACTION     = 'chat_submit';
  var TAB_ID     = ${tabId};
  var tokenCount = 0, currentTimeoutId = null;

  function randInterval() {
    var arr = new Uint32Array(1); crypto.getRandomValues(arr);
    return 12 + (arr[0] / (0xFFFFFFFF + 1)) * 6;
  }

  function harvest() {
    if (!window.grecaptcha || !window.grecaptcha.enterprise) { currentTimeoutId = setTimeout(harvest, 2000); return; }
    grecaptcha.enterprise.ready(function() {
      grecaptcha.enterprise.execute(SITE_KEY, { action: ACTION }).then(function(token) {
        tokenCount++;
        console.log('[v3 #' + tokenCount + '] Token generated (' + token.length + ' chars)');
        return fetch(SERVER_URL, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token: token, version: 'v3', action: ACTION,
            harvest_number: tokenCount, source_url: window.location.href, tab_id: TAB_ID, _reload_after: true })
        }).then(function(r) { return r.json(); }).then(function(data) {
          console.log('[v3 #' + tokenCount + '] Stored. Total: ' + data.total_count);
          window.__STRIPE_DEVICE_ID__ = token;
          scheduleNext();
        });
      }).catch(function(err) { console.error('[v3] Error:', err); scheduleNext(); });
    });
  }

  function scheduleNext() {
    var next = randInterval();
    console.log('[v3] Next harvest in ' + next.toFixed(2) + 's');
    currentTimeoutId = setTimeout(harvest, next * 1000);
  }

  window.__RUDDERSTACK_FLUSH__ = function() {
    if (currentTimeoutId) { clearTimeout(currentTimeoutId); currentTimeoutId = null; }
    console.log('[v3] Stopped. Total: ' + tokenCount);
  };

  console.log('[v3] Harvester starting');
  harvest();
})();`;
}

function getInvisibleScript(serverPort) {
  return `(function() {
  var SERVER_URL = 'http://localhost:${serverPort}/api';
  var SITE_KEY   = '6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I';
  function loadScript() {
    return new Promise(function(res, rej) {
      if (document.querySelector('script[src*="recaptcha/enterprise.js"]')) { res(); return; }
      var s = document.createElement('script');
      s.src = 'https://www.google.com/recaptcha/enterprise.js?render=' + SITE_KEY;
      s.async = true; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
  }
  function waitFor() {
    return new Promise(function(res, rej) {
      var t = Date.now();
      (function check() {
        if (window.grecaptcha && window.grecaptcha.enterprise && window.grecaptcha.enterprise.render) { res(); return; }
        if (Date.now() - t > 30000) { rej(new Error('Timeout')); return; }
        setTimeout(check, 100);
      })();
    });
  }
  (async function() {
    try {
      if (!window.grecaptcha || !window.grecaptcha.enterprise) await loadScript();
      await waitFor();
      var g = window.grecaptcha.enterprise;
      var el = document.createElement('div');
      el.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;';
      document.body.appendChild(el);
      var settled = false, done = function(fn, v) { if (settled) return; settled = true; fn(v); };
      var token = await new Promise(function(res, rej) {
        var t = setTimeout(function() { done(rej, 'TIMEOUT'); }, 60000);
        var wid = g.render(el, {
          sitekey: SITE_KEY, size: 'invisible',
          callback: function(tok) { clearTimeout(t); done(res, tok); },
          'error-callback': function() { clearTimeout(t); done(rej, 'ERROR'); }
        });
        if (typeof g.execute === 'function') g.execute(wid);
      });
      el.remove();
      await fetch(SERVER_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token, version: 'v2_ondemand', action: 'manual_trigger', source_url: window.location.href }) });
      console.log('[invisible] Token stored');
    } catch(e) { console.error('[invisible] Failed:', e); }
  })();
})();`;
}

// ─── HARD_TUNING helpers ──────────────────────────────────────────────────────

async function hardTuningCycleCookies() {
  try {
    const all = await chrome.cookies.getAll({ domain: "arena.ai" });
    const saved = all.filter(c => HARD_TUNING_KEEP.has(c.name));
    console.log("[bg][HARD_TUNING] Saving:", saved.map(c => c.name).join(", ") || "none");
    for (const c of all) {
      const url = `http${c.secure ? "s" : ""}://${c.domain.replace(/^\./, "")}${c.path}`;
      await chrome.cookies.remove({ url, name: c.name }).catch(() => {});
    }
    console.log("[bg][HARD_TUNING] Wiped", all.length, "cookies");
    return saved;
  } catch (e) {
    console.error("[bg][HARD_TUNING] wipe error:", e);
    return [];
  }
}

async function restoreCookies(saved) {
  for (const c of saved) {
    try {
      const url = `https://${c.domain.replace(/^\./, "")}${c.path}`;
      await chrome.cookies.set({
        url, name: c.name, value: c.value, domain: c.domain, path: c.path,
        secure: c.secure, httpOnly: c.httpOnly,
        sameSite: (c.sameSite || "lax").toLowerCase(),
        ...(c.expirationDate ? { expirationDate: c.expirationDate } : {}),
      });
    } catch (e) { console.warn("[bg][HARD_TUNING] restore failed:", c.name, e.message); }
  }
  console.log("[bg][HARD_TUNING] Restored", saved.length, "cookies");
}

// ─── TUNING: reload tab after token ──────────────────────────────────────────

async function reloadTabAfterToken(tabId, version) {
  const cfg   = await getConfig();
  const state = tabState[tabId];
  if (!state || !state.activeHarvester) {
    console.log("[bg] Tab", tabId, "harvester stopped — skip reload");
    return;
  }

  state.status = "reloading";
  broadcastStateUpdate();

  let savedCookies = [];
  if (cfg.HARD_TUNING) savedCookies = await hardTuningCycleCookies();

  const targetUrl = (cfg.FIVE_GAIN && cfg.EVAL_ID)
    ? `https://arena.ai/c/${cfg.EVAL_ID}`
    : "https://arena.ai";

  const onCompleted = (details) => {
    if (details.tabId !== tabId || details.frameId !== 0) return;
    chrome.webNavigation.onCompleted.removeListener(onCompleted);

    (async () => {
      if (cfg.HARD_TUNING && savedCookies.length > 0) {
        await restoreCookies(savedCookies);
        await new Promise(r => setTimeout(r, 400));
      }

      try { await runInTab(tabId, getBlockerScript()); } catch(e) { console.warn("[bg] Blocker error:", e.message); }

      const s = tabState[tabId];
      if (!s || !s.activeHarvester) {
        if (s) s.status = "idle";
        broadcastStateUpdate();
        return;
      }

      const harvType = s.activeHarvester;
      try {
        const script = harvType === "v2" ? getV2Script(tabId, cfg.SERVER_PORT) : getV3Script(tabId, cfg.SERVER_PORT);
        await runInTab(tabId, script);
        s.status = harvType === "v2" ? "harvesting_v2" : "harvesting_v3";
        console.log("[bg] Tab", tabId, "✅", harvType, "re-injected after reload");
      } catch (e) {
        console.error("[bg] Re-inject error:", e.message);
        s.status = "idle";
      }
      broadcastStateUpdate();
    })();
  };

  chrome.webNavigation.onCompleted.addListener(onCompleted);

  try {
    if (!cfg.FIVE_GAIN || !cfg.EVAL_ID) {
      await chrome.tabs.reload(tabId, { bypassCache: cfg.HARD_TUNING });
    } else {
      await chrome.tabs.update(tabId, { url: targetUrl });
    }
  } catch (err) {
    console.error("[bg] Reload error:", err.message);
    if (tabState[tabId]) tabState[tabId].status = "idle";
    chrome.webNavigation.onCompleted.removeListener(onCompleted);
    broadcastStateUpdate();
  }
}

// ─── Broadcast ────────────────────────────────────────────────────────────────

function broadcastStateUpdate() {
  chrome.runtime.sendMessage({ type: "STATE_UPDATE" }).catch(() => {});
}

// ─── Message handler ──────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    let cfg;
    try { cfg = await getConfig(); } catch(e) { cfg = Object.assign({}, DEFAULT_CONFIG); }

    try {
      switch (msg.type) {

        case "GET_STATE": {
          const tabs = await chrome.tabs.query({ url: "https://arena.ai/*" });
          sendResponse({
            ok: true,
            tabs: tabs.map(t => ({
              tabId: t.id,
              title: t.title || ("Tab " + t.id),
              url:   t.url || "",
              ...(tabState[t.id] || { status: "idle", activeHarvester: null, tokenCount: 0 }),
            })),
            config: cfg,
          });
          break;
        }

        case "SAVE_CONFIG": {
          if (msg.config.HARD_TUNING && !msg.config.TUNING) {
            sendResponse({ ok: false, error: "HARD_TUNING requires TUNING=true" });
            break;
          }
          await saveConfig(Object.assign({}, cfg, msg.config));
          sendResponse({ ok: true });
          break;
        }

        case "V2_START": {
          const { tabId } = msg;
          if (!tabState[tabId]) tabState[tabId] = { status: "idle", activeHarvester: null, tokenCount: 0 };
          try {
            await runInTab(tabId, getBlockerScript());
            await runInTab(tabId, getV2Script(tabId, cfg.SERVER_PORT));
            tabState[tabId].activeHarvester = "v2";
            tabState[tabId].status = "harvesting_v2";
            sendResponse({ ok: true });
          } catch (e) {
            console.error("[bg] V2_START error:", e);
            sendResponse({ ok: false, error: e.message });
          }
          broadcastStateUpdate();
          break;
        }

        case "V2_STOP": {
          const { tabId } = msg;
          if (tabState[tabId]) { tabState[tabId].activeHarvester = null; tabState[tabId].status = "idle"; }
          try { await runInTab(tabId, "if(typeof window.__INTERCOM_SHUTDOWN__==='function')window.__INTERCOM_SHUTDOWN__();"); } catch(_) {}
          sendResponse({ ok: true });
          broadcastStateUpdate();
          break;
        }

        case "V3_START": {
          const { tabId } = msg;
          if (!tabState[tabId]) tabState[tabId] = { status: "idle", activeHarvester: null, tokenCount: 0 };
          try {
            await runInTab(tabId, getBlockerScript());
            await runInTab(tabId, getV3Script(tabId, cfg.SERVER_PORT));
            tabState[tabId].activeHarvester = "v3";
            tabState[tabId].status = "harvesting_v3";
            sendResponse({ ok: true });
          } catch (e) {
            console.error("[bg] V3_START error:", e);
            sendResponse({ ok: false, error: e.message });
          }
          broadcastStateUpdate();
          break;
        }

        case "V3_STOP": {
          const { tabId } = msg;
          if (tabState[tabId]) { tabState[tabId].activeHarvester = null; tabState[tabId].status = "idle"; }
          try { await runInTab(tabId, "if(typeof window.__RUDDERSTACK_FLUSH__==='function')window.__RUDDERSTACK_FLUSH__();"); } catch(_) {}
          sendResponse({ ok: true });
          broadcastStateUpdate();
          break;
        }

        case "INVISIBLE_RUN": {
          const { tabId } = msg;
          try {
            await runInTab(tabId, getInvisibleScript(cfg.SERVER_PORT));
            sendResponse({ ok: true });
          } catch (e) {
            sendResponse({ ok: false, error: e.message });
          }
          break;
        }

        default:
          sendResponse({ ok: false, error: "Unknown message: " + msg.type });
      }
    } catch (e) {
      console.error("[bg] Unhandled error:", e);
      sendResponse({ ok: false, error: e.message });
    }
  })();
  return true; // keep async channel open
});

// ─── Tab close cleanup ────────────────────────────────────────────────────────

chrome.tabs.onRemoved.addListener(tabId => { delete tabState[tabId]; });

console.log("[bg] Arena Harvester service worker ready.");
