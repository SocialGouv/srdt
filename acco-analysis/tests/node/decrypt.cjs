// Decrypts a file written by crypto_site.py with the real pages/gate.js.
// usage: node decrypt.cjs <file> <password> <salt hex> <iterations>
const fs = require("fs");
const path = require("path");
const Gate = require(path.join(__dirname, "../../src/acco_analysis/pages/gate.js"));

(async () => {
  const [file, password, salt, iterations] = process.argv.slice(2);
  const raw = await Gate.deriveKey(password, salt, Number(iterations));
  const key = await Gate.importKey(raw);
  const text = await Gate.decryptBlob(key, fs.readFileSync(file));
  process.stdout.write(text);
})().catch(e => { console.error(e.name || e.message); process.exit(1); });
