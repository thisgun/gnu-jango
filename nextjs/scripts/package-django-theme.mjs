import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveThemeName } from './theme-pair.mjs';

const THEME_NAME = resolveThemeName();

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const deployRoot = join(nextRoot, '.deploy');
const packageName = 'nextjs-default-theme';
const packageRoot = join(deployRoot, packageName);
const archiveName = `${packageName}.tar.gz`;
const archivePath = join(deployRoot, archiveName);
const archiveChecksumPath = `${archivePath}.sha256`;
const templateSource = join(repoRoot, 'gnu_jango', 'templates', 'theme', THEME_NAME);
const assetSource = join(repoRoot, 'gnu_jango', 'templates', 'theme_static', THEME_NAME);
const deploymentGuideSource = join(repoRoot, 'docs', '04-deploy', 'nextjs-default-theme.md');
const uploadRoot = join(packageRoot, 'upload');
const manifestName = 'MANIFEST.json';
const checksumName = 'CHECKSUMS.sha256';
const rmRetryOptions = { force: true, maxRetries: 10, retryDelay: 200 };

function fail(message) {
  console.error(`[package-django-theme] ${message}`);
  process.exit(1);
}

function collectFiles(root, current = root) {
  const files = [];

  for (const entry of readdirSync(current, { withFileTypes: true })) {
    const absolutePath = join(current, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectFiles(root, absolutePath));
    } else if (entry.isFile()) {
      files.push({
        absolutePath,
        relativePath: relative(root, absolutePath).replaceAll('\\', '/'),
      });
    }
  }

  return files.sort((left, right) => left.relativePath.localeCompare(right.relativePath));
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function safePackageTarget() {
  const resolvedRoot = resolve(deployRoot);
  const resolvedTarget = resolve(packageRoot);
  if (resolvedTarget === resolvedRoot || !resolvedTarget.startsWith(`${resolvedRoot}${sep}`)) {
    fail(`Refusing to clear package path outside ${resolvedRoot}`);
  }
}

if (!existsSync(templateSource) || !existsSync(assetSource)) {
  fail('Theme output directories are missing. Run `npm run build:theme` first.');
}

safePackageTarget();
mkdirSync(deployRoot, { recursive: true });
rmSync(packageRoot, { recursive: true, ...rmRetryOptions });

const templateTarget = join(uploadRoot, 'theme', THEME_NAME);
const assetTarget = join(uploadRoot, 'theme_static', THEME_NAME);
mkdirSync(dirname(templateTarget), { recursive: true });
mkdirSync(dirname(assetTarget), { recursive: true });
cpSync(templateSource, templateTarget, { recursive: true, errorOnExist: true });
cpSync(assetSource, assetTarget, { recursive: true, errorOnExist: true });
copyFileSync(deploymentGuideSource, join(packageRoot, 'DEPLOYMENT.md'));

const payloadFiles = collectFiles(uploadRoot).map(({ absolutePath, relativePath }) => ({
  path: `upload/${relativePath}`,
  size: readFileSync(absolutePath).length,
  sha256: sha256(absolutePath),
}));

let sourceCommit = 'unknown';
let sourceDirty = null;
try {
  sourceCommit = execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  sourceDirty = Boolean(execFileSync('git', ['status', '--porcelain'], {
    cwd: repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim());
} catch {
  // The archive remains usable when created from a source snapshot without Git metadata.
}

const manifest = {
  schemaVersion: 1,
  theme: THEME_NAME,
  generatedAt: new Date().toISOString(),
  sourceCommit,
  sourceDirty,
  templateTarget: `TEMPLATES_DIR/theme/${THEME_NAME}`,
  staticAssetTarget: `TEMPLATES_DIR/theme_static/${THEME_NAME}`,
  fileCount: payloadFiles.length,
  files: payloadFiles,
};
writeFileSync(join(packageRoot, manifestName), `${JSON.stringify(manifest, null, 2)}\n`);

const checksumFiles = collectFiles(packageRoot).filter(({ relativePath }) => relativePath !== checksumName);
const checksumText = checksumFiles
  .map(({ absolutePath, relativePath }) => `${sha256(absolutePath)}  ${relativePath}`)
  .join('\n');
writeFileSync(join(packageRoot, checksumName), `${checksumText}\n`);

rmSync(archivePath, rmRetryOptions);
rmSync(archiveChecksumPath, rmRetryOptions);
try {
  const compressionOptions = process.platform === 'win32'
    ? ['--options', 'gzip:compression-level=1']
    : [];
  execFileSync('tar', [...compressionOptions, '-czf', archivePath, '-C', deployRoot, packageName], {
    cwd: nextRoot,
    stdio: 'inherit',
  });
} catch (error) {
  fail(`Could not create ${archiveName} with tar: ${error.message}`);
}

const archiveListing = execFileSync('tar', ['-tzf', archivePath], {
  cwd: nextRoot,
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'inherit'],
});
for (const requiredPath of [
  `${packageName}/DEPLOYMENT.md`,
  `${packageName}/MANIFEST.json`,
  `${packageName}/CHECKSUMS.sha256`,
  `${packageName}/upload/theme/${THEME_NAME}/index.html`,
  `${packageName}/upload/theme_static/${THEME_NAME}/_next/static`,
]) {
  if (!archiveListing.split(/\r?\n/).some((entry) => entry === requiredPath || entry.startsWith(`${requiredPath}/`))) {
    fail(`Archive is missing required path: ${requiredPath}`);
  }
}

writeFileSync(archiveChecksumPath, `${sha256(archivePath)}  ${archiveName}\n`);
console.log(`[package-django-theme] Packaged ${payloadFiles.length} theme files from commit ${sourceCommit}`);
console.log(`[package-django-theme] Directory: ${packageRoot}`);
console.log(`[package-django-theme] Archive: ${archivePath}`);
console.log(`[package-django-theme] Checksum: ${archiveChecksumPath}`);
