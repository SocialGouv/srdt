// Loads the generate prompts from the web TypeScript sources, without a build step:
// each file is transpiled with the web's own `typescript` package and evaluated with
// its imports stubbed (they are either other prompt files or type-only imports).
//
//   node scripts/web_prompts.mjs export <out.json>
//       Writes the instruction templates and the sha256 of their source files.
//   node scripts/web_prompts.mjs render <cases.json>
//       Prints the system prompt the web would build for each case (used by the
//       parity test of answer_eval/prompt.py). A case is
//       {text, idcc, idcc_name, fiches, code, idcc_chunks}, chunks being
//       {content, metadata: {id, source, url, title}}.

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const EVAL_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO_DIR = resolve(EVAL_DIR, "..");
const WEB_SRC = join(REPO_DIR, "web", "src");
const require = createRequire(join(REPO_DIR, "web", "package.json"));
const ts = require("typescript");

// The web enum values the prompt builders read (`web/src/constants.ts`).
const CONSTANTS_STUB = { Collection: { JUDILIBRE: "judilibre" } };
const CONFIG = "v2.0"; // web: Config.V2_0, the only prompt config

const SOURCES = {
  shared: "prompts/shared.ts",
  generate: "prompts/generate.ts",
  builders: "modules/api/prompt-builders.ts",
};

const cache = new Map();

function load(relPath) {
  if (cache.has(relPath)) return cache.get(relPath);
  const source = readFileSync(join(WEB_SRC, relPath), "utf-8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: relPath,
  });
  const module = { exports: {} };
  const localRequire = (spec) => {
    if (spec === "./shared") return load(SOURCES.shared);
    if (spec === "@/constants") return CONSTANTS_STUB;
    if (spec.endsWith("/types")) return {}; // type-only imports
    throw new Error(`${relPath}: unexpected import ${spec}`);
  };
  new Function("require", "module", "exports", outputText)(
    localRequire,
    module,
    module.exports,
  );
  cache.set(relPath, module.exports);
  return module.exports;
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function exportTemplates(outPath) {
  const { GENERATE_INSTRUCTIONS } = load(SOURCES.generate);
  const sources = {};
  for (const rel of [SOURCES.shared, SOURCES.generate, SOURCES.builders]) {
    const path = join(WEB_SRC, rel);
    sources[relative(REPO_DIR, path)] = sha256(path);
  }
  const out = {
    config: CONFIG,
    generate_instruction: GENERATE_INSTRUCTIONS.generate_instruction,
    generate_instruction_idcc: GENERATE_INSTRUCTIONS.generate_instruction_idcc,
    sources,
  };
  writeFileSync(outPath, JSON.stringify(out, null, 2) + "\n", "utf-8");
}

// Same steps as `getGenerateData` in web/src/modules/api/process.ts.
function render(cases) {
  const { GENERATE_INSTRUCTIONS } = load(SOURCES.generate);
  const { createKnowledgeBaseContent } = load(SOURCES.builders);
  return cases.map((c) => {
    const kb = createKnowledgeBaseContent(
      c.fiches,
      c.code,
      c.idcc ? c.idcc_chunks : undefined,
      [],
    );
    const idcc = c.idcc;
    const template = idcc
      ? GENERATE_INSTRUCTIONS.generate_instruction_idcc
          .replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`,
          )
          .replace(/\$\{IDCC_NAME\}/g, c.idcc_name || "")
          .replace(/\$\{IDCC_NUMBER\}/g, idcc || "")
      : GENERATE_INSTRUCTIONS.generate_instruction;
    return template + "\n\n" + kb;
  });
}

const [command, path] = process.argv.slice(2);
if (command === "export" && path) {
  exportTemplates(path);
} else if (command === "render" && path) {
  const cases = JSON.parse(readFileSync(path, "utf-8"));
  process.stdout.write(JSON.stringify(render(cases)));
} else {
  console.error("usage: web_prompts.mjs export <out.json> | render <cases.json>");
  process.exit(2);
}
