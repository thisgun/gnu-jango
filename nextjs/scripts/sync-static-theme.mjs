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

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const staticExportDir = 'out';
const outDir = join(nextRoot, staticExportDir);
const templateDir = join(repoRoot, 'gnu_jango', 'templates', 'theme', 'nextjs_default');
const staticDir = join(repoRoot, 'gnu_jango', 'templates', 'theme_static', 'nextjs_default');
const compatibilityManifestName = '.g5-static-compat.json';

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

const currentOutFiles = new Set(listFiles(outDir));
const previousStaticAssets = listFiles(staticDir).filter(
  (file) => file.startsWith('_next/static/') && !currentOutFiles.has(file)
);
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
}));
writeFileSync(
  join(staticDir, compatibilityManifestName),
  `${JSON.stringify({ version: 1, files: compatibilityFiles }, null, 2)}\n`
);
rmSync(compatibilityStageDir, { recursive: true, force: true });

console.log(`[sync-static-theme] Synced templates ${outDir} -> ${templateDir}`);
console.log(`[sync-static-theme] Synced static assets ${outDir} -> ${staticDir}`);
console.log(`[sync-static-theme] Preserved ${compatibilityFiles.length} previous hashed assets for already-open pages`);
