import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const staticExportDir = 'out';
const outDir = join(nextRoot, staticExportDir);
const templateDir = join(repoRoot, 'gnu_jango', 'templates', 'theme', 'nextjs_default');
const staticDir = join(repoRoot, 'gnu_jango', 'templates', 'theme_static', 'nextjs_default');
const compatibilityManifestName = '.g5-static-compat.json';
const compatibilityManifestPath = join(staticDir, compatibilityManifestName);

function fail(message, details = []) {
  console.error(`[check-static-theme-sync] ${message}`);
  for (const detail of details.slice(0, 40)) {
    console.error(`  - ${detail}`);
  }
  if (details.length > 40) {
    console.error(`  ... and ${details.length - 40} more`);
  }
  process.exit(1);
}

function listFiles(root) {
  if (!existsSync(root)) {
    fail(`Missing directory: ${root}`);
  }

  const files = [];
  const stack = [''];
  while (stack.length > 0) {
    const current = stack.pop();
    const absolute = join(root, current);
    for (const entry of readdirSync(absolute)) {
      const relPath = current ? join(current, entry) : entry;
      const entryPath = join(root, relPath);
      const stat = statSync(entryPath);
      if (stat.isDirectory()) {
        stack.push(relPath);
      } else if (stat.isFile()) {
        files.push(relPath.replaceAll('\\', '/'));
      }
    }
  }

  return files.sort();
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function targetForOutFile(file) {
  return file.startsWith('_next/') || file.startsWith('assets/') ? staticDir : templateDir;
}

const outFiles = listFiles(outDir);
const templateFiles = listFiles(templateDir);
const staticFiles = listFiles(staticDir);
const themeFiles = [
  ...templateFiles.map((file) => ({ root: templateDir, file })),
  ...staticFiles.map((file) => ({ root: staticDir, file })),
];
const outSet = new Set(outFiles);
const themeSet = new Set(
  themeFiles
    .filter((item) => !(item.root === staticDir && item.file === compatibilityManifestName))
    .map((item) => item.file)
);
const staticSet = new Set(staticFiles);

let compatibilityEntries = [];
const compatibilityProblems = [];
if (existsSync(compatibilityManifestPath)) {
  try {
    const manifest = JSON.parse(readFileSync(compatibilityManifestPath, 'utf8'));
    if (manifest.version !== 1 || !Array.isArray(manifest.files)) {
      compatibilityProblems.push(`${compatibilityManifestName} has an unsupported format`);
    } else {
      compatibilityEntries = manifest.files;
    }
  } catch (error) {
    compatibilityProblems.push(`${compatibilityManifestName} is invalid JSON: ${error.message}`);
  }
}

const compatibilityPaths = new Set();
for (const entry of compatibilityEntries) {
  const file = entry?.path;
  if (
    typeof file !== 'string' ||
    !file.startsWith('_next/static/') ||
    file.includes('..') ||
    file.includes('\\')
  ) {
    compatibilityProblems.push(`invalid legacy asset path in ${compatibilityManifestName}: ${String(file)}`);
    continue;
  }
  if (compatibilityPaths.has(file)) {
    compatibilityProblems.push(`duplicate legacy asset path: ${file}`);
    continue;
  }
  compatibilityPaths.add(file);
  if (!staticSet.has(file)) {
    compatibilityProblems.push(`legacy asset missing from static theme: ${file}`);
  }
  if (outSet.has(file)) {
    compatibilityProblems.push(`legacy asset overlaps current export: ${file}`);
  }
  if (typeof entry.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(entry.sha256)) {
    compatibilityProblems.push(`legacy asset has no valid SHA-256 in ${compatibilityManifestName}: ${file}`);
  } else if (staticSet.has(file) && sha256(join(staticDir, file)) !== entry.sha256) {
    compatibilityProblems.push(`legacy asset content differs from ${compatibilityManifestName}: ${file}`);
  }
}

const missing = outFiles.filter((file) => !themeSet.has(file));
const extra = themeFiles
  .filter((item) => !(item.root === staticDir && item.file === compatibilityManifestName))
  .filter((item) => !outSet.has(item.file))
  .map((item) => item.file);
const unexpectedExtra = extra.filter((file) => !compatibilityPaths.has(file));
const changed = outFiles.filter((file) => {
  if (!themeSet.has(file)) return false;
  return sha256(join(outDir, file)) !== sha256(join(targetForOutFile(file), file));
});

const problems = [
  ...compatibilityProblems,
  ...missing.map((file) => `missing in theme: ${file}`),
  ...unexpectedExtra.map((file) => `extra in theme without compatibility manifest: ${file}`),
  ...[...compatibilityPaths].filter((file) => !extra.includes(file)).map((file) => `legacy manifest entry is not an extra asset: ${file}`),
  ...changed.map((file) => `content differs: ${file}`),
];

if (problems.length > 0) {
  fail(
    `${relative(repoRoot, templateDir)} and ${relative(repoRoot, staticDir)} are not synced with ${relative(repoRoot, outDir)}. Run npm run build:theme.`,
    problems
  );
}

console.log(
  `[check-static-theme-sync] ${relative(repoRoot, templateDir)} + ${relative(repoRoot, staticDir)} match ${relative(repoRoot, outDir)} (${outFiles.length} current files, ${compatibilityPaths.size} retained legacy assets)`
);
