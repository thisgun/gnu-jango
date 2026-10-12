import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, "..");
const files = {
  globals: resolve(nextRoot, "src/app/globals.css"),
  tokens: resolve(nextRoot, "src/app/solune-theme.tokens.css"),
  shell: resolve(nextRoot, "src/app/solune-theme.shell.css"),
  home: resolve(nextRoot, "src/app/page.tsx"),
};

const checks = [];
const failures = [];

function assertIncludes(content, token, label) {
  if (content.includes(token)) {
    checks.push({ check: label, status: "ok" });
  } else {
    failures.push({ check: label, status: "fail", detail: "missing " + token });
  }
}

const globals = readFileSync(files.globals, "utf8");
const tokens = readFileSync(files.tokens, "utf8");
const shell = readFileSync(files.shell, "utf8");
const home = readFileSync(files.home, "utf8");

assertIncludes(globals, '@plugin "daisyui"', "DaisyUI plugin is enabled");
assertIncludes(globals, "themes: gnu-default --default, gnu-dark --prefersdark", "light and dark themes are registered");
assertIncludes(globals, 'name: "gnu-default"', "default Gnuboard theme is defined");
assertIncludes(globals, 'name: "gnu-dark"', "dark Gnuboard theme is defined");
assertIncludes(tokens, "--solune-primary: #3159b7;", "Solune primary blue token exists");
assertIncludes(tokens, "--solune-page: #f5f7fa;", "Solune page surface token exists");
assertIncludes(tokens, "--solune-surface: #ffffff;", "Solune card surface token exists");
assertIncludes(tokens, "--solune-border: #d9e0ea;", "Solune border token exists");
assertIncludes(tokens, "--solune-shell: 80rem;", "Solune shell width token exists");
assertIncludes(tokens, ":root[data-solune-theme=\"dark\"]", "Solune dark theme overrides exist");
assertIncludes(shell, ".solune-shell", "shared responsive shell is defined");
assertIncludes(shell, ".solune-root", "theme page root is defined");
assertIncludes(shell, "@media (min-width: 1024px)", "shell has a desktop breakpoint");
assertIncludes(home, "ReferenceHomeClient", "home page uses the current reference implementation");

console.table([...checks, ...failures]);
if (failures.length > 0) {
  console.error("[check-design-system] " + failures.length + " current theme invariant(s) failed");
  process.exit(1);
}

console.log("[check-design-system] Current DaisyUI and Solune theme invariants passed");
