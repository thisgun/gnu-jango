import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = process.cwd();
const SRC_DIR = join(ROOT, "src");
const API_DIR = join(ROOT, "..", "api");
const MAX_LINES = Number(process.env.MAX_SOURCE_FILE_LINES || 2500);
const WARN_LINES = Number(process.env.WARN_SOURCE_FILE_LINES || 1500);
const MAX_PHP_LINES = Number(process.env.MAX_PHP_FILE_LINES || 4000);
const WARN_PHP_LINES = Number(process.env.WARN_PHP_FILE_LINES || 1500);
const EXTENSIONS = new Set([".ts", ".tsx"]);
const PHP_EXTENSIONS = new Set([".php"]);

function extensionOf(filePath) {
  const match = filePath.match(/\.[^.]+$/);
  return match ? match[0] : "";
}

function walk(dir, extensions = EXTENSIONS) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(fullPath, extensions));
      continue;
    }
    // *.gen.ts is generated (src/types/api.gen.ts from the OpenAPI schema), not hand-maintained.
    if (entry.isFile() && extensions.has(extensionOf(entry.name)) && !entry.name.endsWith(".gen.ts")) {
      files.push(fullPath);
    }
  }

  return files;
}

function lineCount(filePath) {
  const content = readFileSync(filePath, "utf8");
  if (!content) return 0;
  return content.split(/\r?\n/).length;
}

const oversized = [];
const warnings = [];

function inspectFiles({ dir, extensions, maxLines, warnLines }) {
  if (!statSync(dir).isDirectory()) return;

  for (const file of walk(dir, extensions)) {
    const stat = statSync(file);
    if (!stat.isFile()) continue;

    const lines = lineCount(file);
    const item = {
      file: relative(ROOT, file).replace(/\\/g, "/"),
      lines,
    };

    if (Number.isFinite(maxLines) && maxLines > 0 && lines > maxLines) {
      oversized.push(item);
    } else if (Number.isFinite(warnLines) && warnLines > 0 && lines > warnLines) {
      warnings.push(item);
    }
  }
}

inspectFiles({
  dir: SRC_DIR,
  extensions: EXTENSIONS,
  maxLines: MAX_LINES,
  warnLines: WARN_LINES,
});

inspectFiles({
  dir: API_DIR,
  extensions: PHP_EXTENSIONS,
  maxLines: MAX_PHP_LINES,
  warnLines: WARN_PHP_LINES,
});

for (const item of warnings.sort((a, b) => b.lines - a.lines)) {
  console.warn(`[check-source-file-size] warning ${item.file}: ${item.lines} lines`);
}

if (oversized.length > 0) {
  for (const item of oversized.sort((a, b) => b.lines - a.lines)) {
    console.error(`[check-source-file-size] too large ${item.file}: ${item.lines} lines`);
  }
  console.error(`[check-source-file-size] TS/TSX limit is ${MAX_LINES} lines; PHP limit is ${MAX_PHP_LINES} lines. Split the file or raise the matching limit intentionally.`);
  process.exit(1);
}

console.log("[check-source-file-size] ok");
