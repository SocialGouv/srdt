// Shared by index.html and accord.html. Asks for the password, derives the key once and
// decrypts the files written by crypto_site.py: iv (12 bytes) + AES-256-GCM(gzip(data)),
// key = PBKDF2-HMAC-SHA256(password, salt, iterations) from manifest.json.
(function (root) {
  "use strict";
  const STORE = "acco-site-key-v1";
  const subtle = (root.crypto || globalThis.crypto).subtle;

  const fromHex = s => Uint8Array.from(s.match(/../g) || [], b => parseInt(b, 16));
  const toB64 = bytes => btoa(String.fromCharCode(...bytes));
  const fromB64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

  async function deriveKey(password, saltHex, iterations) {
    const base = await subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
    const bits = await subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: fromHex(saltHex), iterations }, base, 256);
    return new Uint8Array(bits);
  }

  const importKey = raw => subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);

  async function decryptBlob(key, buffer) {
    const bytes = new Uint8Array(buffer);
    const plain = await subtle.decrypt({ name: "AES-GCM", iv: bytes.slice(0, 12) }, key, bytes.slice(12));
    return new Response(new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
  }

  // ---- browser only: the manifest, the password prompt, the session key ----
  let manifestPromise = null;
  let keyPromise = null;

  function manifest() {
    if (!manifestPromise) {
      manifestPromise = fetch("manifest.json").then(r => {
        if (!r.ok) throw new Error("manifest.json : " + r.status);
        return r.json();
      });
    }
    return manifestPromise;
  }

  function remembered(m) {
    try {
      const [salt, key] = (sessionStorage.getItem(STORE) || "").split(":");
      return salt === m.salt && key ? fromB64(key) : null;
    } catch (e) { return null; }
  }
  function remember(m, raw) { try { sessionStorage.setItem(STORE, m.salt + ":" + toB64(raw)); } catch (e) {} }
  function forget() { try { sessionStorage.removeItem(STORE); } catch (e) {} keyPromise = null; }

  const STYLE = ".gate{position:fixed;inset:0;z-index:10;display:flex;flex-direction:column;align-items:center;justify-content:center;" +
    "gap:12px;padding:16px;background:var(--bg,#f6f4ef);color:var(--fg,#1f2421);font:15px/1.5 system-ui,sans-serif;text-align:center}" +
    ".gate h1{margin:0;font-size:20px}.gate p{margin:0}.gate input,.gate button{font:inherit;padding:8px 12px;border-radius:6px;" +
    "border:1px solid var(--line,#ddd8cc);background:var(--panel,#fffdf8);color:inherit;max-width:100%}.gate input{width:20em}" +
    ".gate button{cursor:pointer;background:var(--accent,#b4491f);color:#fff;border-color:transparent}.gate .error{min-height:1.5em;color:var(--accent,#b4491f)}";

  function prompt(m, failed) {
    return new Promise(resolve => {
      const style = document.createElement("style");
      style.textContent = STYLE;
      document.head.append(style);
      const box = document.createElement("form");
      box.className = "gate";
      box.innerHTML = '<h1>Accès protégé</h1><p>Ces pages sont chiffrées : saisissez le mot de passe.</p>' +
        '<input type="password" name="password" autocomplete="current-password" aria-label="Mot de passe" required>' +
        '<button type="submit">Ouvrir</button><p class="error" role="alert"></p>';
      const error = box.querySelector(".error"), input = box.querySelector("input"), button = box.querySelector("button");
      if (failed) error.textContent = "Mot de passe incorrect.";
      box.addEventListener("submit", async e => {
        e.preventDefault();
        button.disabled = true; error.textContent = "Déverrouillage…";
        const raw = await deriveKey(input.value, m.salt, m.iterations);
        box.remove();
        resolve(raw);
      });
      document.body.append(box);
      input.focus();
    });
  }

  async function unlock(m, failed) {
    if (!keyPromise) {
      keyPromise = (async () => {
        let raw = failed ? null : remembered(m);
        if (!raw) { raw = await prompt(m, failed); remember(m, raw); }
        return importKey(raw);
      })();
    }
    return keyPromise;
  }

  // the text of a published file, decrypted when the site is encrypted
  async function text(path) {
    const m = await manifest();
    const res = await fetch(path);
    if (!res.ok) throw new Error(path + " : " + res.status);
    if (!m.encrypted) return res.text();
    const buffer = await res.arrayBuffer();
    for (let failed = false; ; failed = true) {
      const key = await unlock(m, failed);
      try { return await decryptBlob(key, buffer); } catch (e) { forget(); }
    }
  }

  const Gate = { text, manifest, deriveKey, importKey, decryptBlob };
  if (typeof module !== "undefined" && module.exports) module.exports = Gate;
  else root.Gate = Gate;
})(typeof window !== "undefined" ? window : globalThis);
