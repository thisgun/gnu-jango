import { createHash } from 'node:crypto';
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveThemeName } from './theme-pair.mjs';

const THEME_NAME = resolveThemeName();

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const staticExportDir = 'out';
const outDir = join(nextRoot, staticExportDir);
const templateDir = join(repoRoot, 'gnu_jango', 'templates', 'theme', THEME_NAME);
const staticDir = join(repoRoot, 'gnu_jango', 'templates', 'theme_static', THEME_NAME);
const compatibilityManifestName = '.g5-static-compat.json';
// Hashed assets of earlier builds are kept so pages opened before a deploy keep working, but only for the
// last few builds; older ones are dropped so the theme does not grow forever.
const keepBuilds = Math.max(1, Number.parseInt(process.env.G5_STATIC_KEEP_BUILDS ?? '2', 10) || 2);

function listFiles(root) {
  if (!existsSync(root)) return [];

  const files = [];
  const stack = [''];
  while (stack.length > 0) {
    const current = stack.pop();
    const absolute = join(root, current);
    for (const entry of readdirSync(absolute, { withFileTypes: true })) {
      const relPath = current ? join(current, entry.name) : entry.name;
      if (entry.isDirectory()) {
        stack.push(relPath);
      } else if (entry.isFile()) {
        files.push(relPath.replaceAll('\\', '/'));
      }
    }
  }

  return files.sort();
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

if (!existsSync(outDir)) {
  console.error(`[sync-static-theme] Missing ${staticExportDir}. Run npm run build first.`);
  process.exit(1);
}

function readManifest() {
  try {
    const manifest = JSON.parse(readFileSync(join(staticDir, compatibilityManifestName), 'utf8'));
    const retiredAt = new Map(
      (Array.isArray(manifest.files) ? manifest.files : [])
        .filter((entry) => typeof entry?.path === 'string')
        .map((entry) => [entry.path, Number.isInteger(entry.retiredAt) ? entry.retiredAt : 0])
    );
    return { generation: Number.isInteger(manifest.generation) ? manifest.generation : 0, retiredAt };
  } catch {
    return { generation: 0, retiredAt: new Map() };
  }
}

const previousManifest = readManifest();
const generation = previousManifest.generation + 1;
const currentOutFiles = new Set(listFiles(outDir));
const retiredAtByPath = new Map();
let droppedCount = 0;
for (const file of listFiles(staticDir)) {
  if (!file.startsWith('_next/static/') || currentOutFiles.has(file)) continue;
  // a file the previous build still served retires now; one already retired keeps its build number
  const retiredAt = previousManifest.retiredAt.get(file) ?? generation;
  if (generation - retiredAt >= keepBuilds) {
    droppedCount += 1;
    continue;
  }
  retiredAtByPath.set(file, retiredAt);
}
const previousStaticAssets = [...retiredAtByPath.keys()];
const compatibilityStageDir = mkdtempSync(join(tmpdir(), 'g5-nextjs-static-compat-'));

for (const file of previousStaticAssets) {
  const stagedFile = join(compatibilityStageDir, file);
  mkdirSync(dirname(stagedFile), { recursive: true });
  copyFileSync(join(staticDir, file), stagedFile);
}

mkdirSync(templateDir, { recursive: true });
mkdirSync(staticDir, { recursive: true });
rmSync(templateDir, { recursive: true, force: true });
rmSync(staticDir, { recursive: true, force: true });
mkdirSync(templateDir, { recursive: true });
mkdirSync(staticDir, { recursive: true });

for (const entry of readdirSync(outDir, { withFileTypes: true })) {
  const source = join(outDir, entry.name);
  const targetRoot = entry.name === '_next' || entry.name === 'assets' ? staticDir : templateDir;
  cpSync(source, join(targetRoot, entry.name), { recursive: true });
}

for (const file of previousStaticAssets) {
  const targetFile = join(staticDir, file);
  mkdirSync(dirname(targetFile), { recursive: true });
  copyFileSync(join(compatibilityStageDir, file), targetFile);
}

const compatibilityFiles = previousStaticAssets.map((path) => ({
  path,
  sha256: sha256(join(staticDir, path)),
  retiredAt: retiredAtByPath.get(path),
}));
writeFileSync(
  join(staticDir, compatibilityManifestName),
  `${JSON.stringify({ version: 2, generation, keepBuilds, files: compatibilityFiles }, null, 2)}\n`
);
rmSync(compatibilityStageDir, { recursive: true, force: true });

console.log(`[sync-static-theme] Synced templates ${outDir} -> ${templateDir}`);
console.log(`[sync-static-theme] Synced static assets ${outDir} -> ${staticDir}`);
console.log(
  `[sync-static-theme] Build ${generation}: kept ${compatibilityFiles.length} hashed assets of the last ${keepBuilds} build(s) for already-open pages, dropped ${droppedCount} older ones`
);
