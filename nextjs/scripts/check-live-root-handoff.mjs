import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const deployRoot = join(nextRoot, '.deploy');
const archiveName = 'nextjs25-live.tar.gz';
const archiveManifestName = 'nextjs25-live.archive.json';
const archivePath = join(deployRoot, archiveName);
const archiveChecksumPath = join(deployRoot, `${archiveName}.sha256`);
const archiveManifestPath = join(deployRoot, archiveManifestName);
const rootPatchFiles = [
  'common.php',
  'plugin/social/includes/functions.php',
  'extend/dday.extend.php',
  'extend/nextjs25-social.extend.php',
];
const packageImpactingPrefixes = [
  'api/',
  'docs/nginx/',
  'nextjs/public/',
  'nextjs/src/',
  'theme/nextjs25/',
];
const packageImpactingFiles = new Set([
  'nextjs/.env.production.example',
  'nextjs/components.json',
  'nextjs/next.config.ts',
  'nextjs/package-lock.json',
  'nextjs/package.json',
  'nextjs/postcss.config.mjs',
  'nextjs/scripts/build-next.mjs',
  'nextjs/scripts/inject-sw-version.mjs',
  'nextjs/scripts/package-live-deploy.mjs',
  'nextjs/scripts/sync-static-theme.mjs',
  'nextjs/scripts/write-apache-static-headers.mjs',
  'nextjs/tsconfig.json',
  ...rootPatchFiles,
]);

function env(name, fallback = '') {
  const value = process.env[name];
  return value === undefined || value === '' ? fallback : value;
}

function quote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function shellAssignments(values) {
  return Object.entries(values)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${quote(value)}`)
    .join(' ');
}

function sha256(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function readExpectedArchiveSha() {
  if (!existsSync(archiveChecksumPath)) {
    return '';
  }

  const [hash] = readFileSync(archiveChecksumPath, 'utf8').trim().split(/\s+/);
  return hash || '';
}

function readJsonFile(path, label) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    fail(`Could not read ${label}: ${error.message}`);
  }
}

function parseRemoteJson(result, label) {
  if (!result.ok) {
    return { ok: false, detail: result.stderr.trim() || `exit ${result.status}` };
  }

  try {
    return { ok: true, value: JSON.parse(result.stdout) };
  } catch (error) {
    return { ok: false, detail: `${label} is not valid JSON: ${error.message}` };
  }
}

function missingTokens(output, tokens) {
  return tokens.filter((token) => !output.includes(token));
}

function manifestDetail(manifest) {
  return `${manifest.gitCommit || 'unknown'} ${manifest.generatedAt || 'unknown'}`;
}

function sourceSnapshotDetail(manifest) {
  const snapshot = manifest?.sourceSnapshot;
  if (!snapshot) {
    return 'sourceSnapshot=(missing)';
  }

  return `sourceSnapshot=${snapshot.digest || 'unknown'} (${snapshot.fileCount || 'unknown'} file(s))`;
}

function sourceSnapshotsMatch(left, right) {
  const leftSnapshot = left?.sourceSnapshot;
  const rightSnapshot = right?.sourceSnapshot;

  return Boolean(
    leftSnapshot &&
      rightSnapshot &&
      leftSnapshot.version === rightSnapshot.version &&
      leftSnapshot.algorithm === rightSnapshot.algorithm &&
      leftSnapshot.digest === rightSnapshot.digest &&
      leftSnapshot.fileCount === rightSnapshot.fileCount
  );
}

function fail(message) {
  console.error(`[check-live-root-handoff] ${message}`);
  process.exit(1);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  return {
    ok: !result.error && result.status === 0,
    status: result.status,
    error: result.error,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function git(args) {
  return run('git', args);
}

function normalizeRepoPath(path) {
  return String(path || '').trim().replaceAll('\\', '/');
}

function repoAbsolutePath(repoPath) {
  return join(repoRoot, ...repoPath.split('/').filter(Boolean));
}

function isPackageImpactingFile(file) {
  return packageImpactingFiles.has(file) || packageImpactingPrefixes.some((prefix) => file.startsWith(prefix));
}

function isExcludedSourceSnapshotPath(file) {
  if (!file.startsWith('api/')) {
    return false;
  }

  return file.split('/').some((part) => part === '.env' || part.startsWith('.env.'));
}

function collectSourceSnapshotFiles(dir) {
  const files = [];

  if (!existsSync(dir)) {
    return files;
  }

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const entryPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectSourceSnapshotFiles(entryPath));
      continue;
    }

    if (entry.isFile()) {
      const file = normalizeRepoPath(relative(repoRoot, entryPath));
      if (!isExcludedSourceSnapshotPath(file)) {
        files.push(file);
      }
    }
  }

  return files;
}

function createSourceSnapshot() {
  const sourceFiles = new Set();

  for (const prefix of packageImpactingPrefixes) {
    for (const file of collectSourceSnapshotFiles(repoAbsolutePath(prefix))) {
      sourceFiles.add(file);
    }
  }

  for (const file of packageImpactingFiles) {
    if (!isExcludedSourceSnapshotPath(file) && existsSync(repoAbsolutePath(file))) {
      sourceFiles.add(file);
    }
  }

  const files = Array.from(sourceFiles).sort((a, b) => a.localeCompare(b));
  const digest = createHash('sha256');

  for (const file of files) {
    digest.update(`${sha256(repoAbsolutePath(file))}  ${file}\n`, 'utf8');
  }

  return {
    version: 1,
    algorithm: 'sha256',
    digest: digest.digest('hex'),
    fileCount: files.length,
  };
}

function parseGitStatusPorcelainZ(output) {
  const records = output.split('\0');
  const files = [];

  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    if (!record) {
      continue;
    }

    const status = record.slice(0, 2);
    const file = normalizeRepoPath(record.slice(3));
    if (file) {
      files.push(file);
    }

    if (status.includes('R') || status.includes('C')) {
      index += 1;
      const originalFile = normalizeRepoPath(records[index] || '');
      if (originalFile) {
        files.push(originalFile);
      }
    }
  }

  return Array.from(new Set(files)).sort((a, b) => a.localeCompare(b));
}

function packageImpactingDirtyFiles() {
  const status = git(['status', '--porcelain=v1', '-z', '--untracked-files=all']);
  if (!status.ok) {
    return { ok: false, detail: status.stderr.trim() || `git status failed with ${status.status}` };
  }

  return {
    ok: true,
    files: parseGitStatusPorcelainZ(status.stdout).filter(isPackageImpactingFile),
  };
}

function packageImpactingChangesSince(commit) {
  if (!commit) {
    return { ok: false, detail: 'archive manifest has no gitCommit' };
  }

  const commitProbe = git(['cat-file', '-e', `${commit}^{commit}`]);
  if (!commitProbe.ok) {
    return { ok: false, detail: `git commit not found locally: ${commit}` };
  }

  const diff = git(['diff', '--name-only', `${commit}..HEAD`]);
  if (!diff.ok) {
    return { ok: false, detail: diff.stderr.trim() || `git diff failed with ${diff.status}` };
  }

  const changedFiles = diff.stdout
    .split(/\r?\n/)
    .map(normalizeRepoPath)
    .filter(Boolean);
  const impactingFiles = changedFiles.filter(isPackageImpactingFile);

  return {
    ok: true,
    changedFiles,
    impactingFiles,
  };
}

const host = env('LIVE_DEPLOY_HOST', 'nextjs.thisgun.net');
const user = env('LIVE_DEPLOY_USER');
const port = env('LIVE_DEPLOY_PORT', '22');
const sshKey = env('LIVE_DEPLOY_SSH_KEY');
const hostWithoutUser = host.includes('@') ? host.split('@').pop() : host;
const rootSshTarget = env('LIVE_DEPLOY_ROOT_TARGET', `root@${hostWithoutUser}`);
const remoteDir = env('LIVE_DEPLOY_REMOTE_DIR', '/tmp/g5-nextjs25-live-deploy');
const packageDir = env(
  'LIVE_DEPLOY_PACKAGE_DIR',
  `${remoteDir.replace(/\/+$/, '')}/nextjs25-live`
);
const webRoot = env('LIVE_DEPLOY_WEB_ROOT', '/home/nextjs/www/study-gnuboard');
const nginxConf = env('LIVE_DEPLOY_NGINX_CONF', '/etc/nginx/nginx.conf');
const nginxSiteConf = env(
  'LIVE_DEPLOY_NGINX_SITE_CONF',
  '/etc/nginx/sites-enabled/nextjs.thisgun.net'
);
const nginxSnippetsDir = env('LIVE_DEPLOY_NGINX_SNIPPETS_DIR', '/etc/nginx/snippets');
const nginxDumpCommand = env('LIVE_DEPLOY_NGINX_DUMP_COMMAND', 'sudo -n /usr/sbin/nginx -T');
const ignoreSourceDrift = env('LIVE_ROOT_HANDOFF_IGNORE_SOURCE_DRIFT') === '1';
const liveOnly = env('LIVE_ROOT_HANDOFF_LIVE_ONLY') === '1';
const skipRootApplyDryRun = env('LIVE_ROOT_HANDOFF_SKIP_ROOT_DRY_RUN') === '1';
const sshTarget = user && !host.includes('@') ? `${user}@${host}` : host;
const sshBaseArgs = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-p', port];

if (sshKey) {
  sshBaseArgs.push('-i', sshKey);
}

function remote(command) {
  return run('ssh', [...sshBaseArgs, sshTarget, `bash -lc ${quote(command)}`]);
}

function remoteAs(target, command) {
  return run('ssh', [...sshBaseArgs, target, `bash -lc ${quote(command)}`]);
}

function parseIncludeStatus(output) {
  const rows = [];
  let inStatusBlock = false;

  for (const line of output.split(/\r?\n/)) {
    if (line.trim() === 'Current include status:') {
      inStatusBlock = true;
      continue;
    }

    if (inStatusBlock && (line.trim() === '' || line.startsWith('Copy snippets as root:'))) {
      break;
    }

    if (!inStatusBlock) {
      continue;
    }

    const match = line.match(/^\s{2}(.+?)\s{2,}(.+?)\s*$/);
    if (match) {
      rows.push({ check: match[1].trim(), status: match[2].trim() });
    }
  }

  return rows;
}

function webRootChecksumCommand(packagePrefix, targetPrefix) {
  return [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      WEB_ROOT: webRoot,
      PACKAGE_PREFIX: packagePrefix,
      TARGET_PREFIX: targetPrefix,
    })} php <<'PHP'
<?php
$webRoot = rtrim((string) getenv('WEB_ROOT'), '/');
$packagePrefix = (string) getenv('PACKAGE_PREFIX');
$targetPrefix = (string) getenv('TARGET_PREFIX');
$checksumFile = __DIR__ . '/CHECKSUMS.sha256';

if ($webRoot === '' || $packagePrefix === '' || $targetPrefix === '') {
    fwrite(STDERR, "missing checksum environment\\n");
    exit(1);
}

if (!is_file($checksumFile)) {
    fwrite(STDERR, "missing CHECKSUMS.sha256\\n");
    exit(1);
}

$checked = 0;
$handle = fopen($checksumFile, 'rb');
if (!$handle) {
    fwrite(STDERR, "could not open CHECKSUMS.sha256\\n");
    exit(1);
}

while (($line = fgets($handle)) !== false) {
    $line = trim($line);
    if ($line === '' || !preg_match('/^([a-f0-9]{64})\\s+(.+)$/', $line, $match)) {
        continue;
    }

    $expected = $match[1];
    $packagePath = str_replace('\\\\', '/', $match[2]);
    if (strpos($packagePath, $packagePrefix) !== 0) {
        continue;
    }

    $relative = substr($packagePath, strlen($packagePrefix));
    $target = $webRoot . '/' . $targetPrefix . $relative;

    if (!is_file($target)) {
        fwrite(STDERR, "missing live file: {$target}\\n");
        exit(1);
    }

    $actual = hash_file('sha256', $target);
    if ($actual !== $expected) {
        fwrite(STDERR, "checksum mismatch: {$target}\\nexpected {$expected}\\nactual   {$actual}\\n");
        exit(1);
    }

    $checked++;
}

fclose($handle);

if ($checked === 0) {
    fwrite(STDERR, "no checksum entries matched {$packagePrefix}\\n");
    exit(1);
}

echo $checked . PHP_EOL;
PHP`,
  ].join(' && ');
}

const checks = [];

function addCheck(name, status, detail) {
  checks.push({ check: name, status, detail });
}

console.log(`[check-live-root-handoff] target=${sshTarget}`);
console.log(`[check-live-root-handoff] package=${packageDir}`);
console.log(`[check-live-root-handoff] webRoot=${webRoot}`);
console.log(`[check-live-root-handoff] liveOnly=${liveOnly ? 'yes' : 'no'}`);

let localArchiveSha = '';
let localArchiveManifest = null;
let sourceSnapshotMatches = false;

if (liveOnly) {
  addCheck('local archive comparison', 'warn', 'skipped by LIVE_ROOT_HANDOFF_LIVE_ONLY=1');
} else {
  if (!existsSync(archivePath)) {
    fail(
      `Missing local archive ${relative(repoRoot, archivePath).replaceAll('\\', '/')}; run npm run package:live`
    );
  }

  if (!existsSync(archiveChecksumPath)) {
    fail(
      `Missing local archive checksum ${relative(repoRoot, archiveChecksumPath).replaceAll('\\', '/')}; run npm run package:live`
    );
  }

  if (!existsSync(archiveManifestPath)) {
    fail(
      `Missing local archive manifest ${relative(repoRoot, archiveManifestPath).replaceAll('\\', '/')}; run npm run package:live`
    );
  }

  const expectedArchiveSha = readExpectedArchiveSha();
  localArchiveSha = sha256(archivePath);
  localArchiveManifest = readJsonFile(archiveManifestPath, 'local archive manifest');
  addCheck(
    'local archive checksum',
    localArchiveSha === expectedArchiveSha ? 'ok' : 'fail',
    localArchiveSha
  );
  addCheck(
    'local archive manifest',
    localArchiveManifest.archive === archiveName && localArchiveManifest.sha256 === localArchiveSha
      ? 'ok'
      : 'fail',
    manifestDetail(localArchiveManifest)
  );

  const currentSourceSnapshot = createSourceSnapshot();
  const archiveSourceSnapshot = localArchiveManifest.sourceSnapshot;
  const currentSourceSnapshotManifest = { sourceSnapshot: currentSourceSnapshot };
  sourceSnapshotMatches = sourceSnapshotsMatch(localArchiveManifest, currentSourceSnapshotManifest);
  addCheck(
    'package source snapshot',
    archiveSourceSnapshot ? (sourceSnapshotMatches ? 'ok' : ignoreSourceDrift ? 'warn' : 'fail') : 'warn',
    archiveSourceSnapshot
      ? sourceSnapshotMatches
        ? `${currentSourceSnapshot.digest} (${currentSourceSnapshot.fileCount} file(s))`
        : `run npm run build:theme && npm run package:live; archive ${
            archiveSourceSnapshot.digest || 'unknown'
          }/${archiveSourceSnapshot.fileCount || 'unknown'} file(s), current ${
            currentSourceSnapshot.digest
          }/${currentSourceSnapshot.fileCount} file(s)`
      : 'archive manifest has no sourceSnapshot; run npm run package:live with the updated packager'
  );

  const dirtySourceState = packageImpactingDirtyFiles();
  addCheck(
    'package source dirty state',
    dirtySourceState.ok ? (dirtySourceState.files.length === 0 ? 'ok' : 'warn') : 'warn',
    dirtySourceState.ok
      ? dirtySourceState.files.length === 0
        ? 'package-impacting working tree is clean'
        : `${dirtySourceState.files.length} package-impacting dirty file(s); source snapshot ${
            sourceSnapshotMatches ? 'matches archive' : 'differs from archive'
          }; ${dirtySourceState.files.slice(0, 5).join(', ')}`
      : dirtySourceState.detail
  );

  const packageDrift = packageImpactingChangesSince(localArchiveManifest.gitCommit);
  addCheck(
    'package source drift',
    packageDrift.ok && packageDrift.impactingFiles.length === 0
      ? 'ok'
      : ignoreSourceDrift
        ? 'warn'
        : 'fail',
    packageDrift.ok
      ? packageDrift.impactingFiles.length > 0
        ? `run npm run build:theme && npm run package:live; changed ${packageDrift.impactingFiles
            .slice(0, 3)
            .join(', ')}`
        : packageDrift.changedFiles.length === 0
        ? 'archive commit matches HEAD'
        : `non-package changes since archive: ${packageDrift.changedFiles.length}`
      : packageDrift.detail
  );
}

const connect = remote('true');
addCheck('ssh batch connection', connect.ok ? 'ok' : 'fail', connect.ok ? 'connected' : connect.stderr.trim());

if (!connect.ok) {
  console.table(checks);
  fail('SSH connection failed; cannot verify live handoff readiness');
}

const sudoProbe = remote('sudo -n true');
addCheck(
  'passwordless sudo',
  sudoProbe.ok ? 'ok' : 'warn',
  sudoProbe.ok ? 'available' : (sudoProbe.stderr || sudoProbe.stdout).trim() || 'not available'
);

const loadedConfigTokens = [
  'g5-nextjs25-security-map.conf',
  'g5-nextjs25-theme-locations.conf',
  'g5-nextjs25-api-security-headers.conf',
  'location = /theme/nextjs25/route.php',
  'location = /api/index.php',
];
const nginxDumpProbe = remote(
  [
    `dump="$(${nginxDumpCommand} 2>&1)" || { printf '%s\\n' "$dump" >&2; exit 1; }`,
    ...loadedConfigTokens.map(
      (token) =>
        `printf '%s' "$dump" | grep -Fq ${quote(token)} || { printf '%s\\n' ${quote(
          `missing token: ${token}`
        )} >&2; exit 1; }`
    ),
  ].join(' && ')
);
addCheck(
  'nginx loaded config dump',
  nginxDumpProbe.ok ? 'ok' : 'warn',
  nginxDumpProbe.ok
    ? `${loadedConfigTokens.length} token(s) present`
    : (nginxDumpProbe.stderr || nginxDumpProbe.stdout).trim() || `${nginxDumpCommand} not available`
);

const rootSshProbe = remoteAs(rootSshTarget, 'test "$(id -u)" = "0"');
addCheck(
  'root ssh',
  rootSshProbe.ok ? 'ok' : 'warn',
  rootSshProbe.ok
    ? rootSshTarget
    : (rootSshProbe.stderr || rootSshProbe.stdout).trim() || `${rootSshTarget} not available`
);

const remoteArchive = remote(
  `[ -f ${quote(`${remoteDir.replace(/\/+$/, '')}/${archiveName}`)} ] && sha256sum ${quote(
    `${remoteDir.replace(/\/+$/, '')}/${archiveName}`
  )} | awk '{print $1}'`
);
const remoteArchiveSha = remoteArchive.stdout.trim();
addCheck(
  'remote archive checksum',
  remoteArchive.ok && (liveOnly ? remoteArchiveSha.length > 0 : remoteArchiveSha === localArchiveSha) ? 'ok' : 'fail',
  remoteArchiveSha || remoteArchive.stderr.trim()
);

const remoteArchiveManifest = parseRemoteJson(
  remote(
    `[ -f ${quote(`${remoteDir.replace(/\/+$/, '')}/${archiveManifestName}`)} ] && cat ${quote(
      `${remoteDir.replace(/\/+$/, '')}/${archiveManifestName}`
    )}`
  ),
  'remote archive manifest'
);
addCheck(
  'remote archive manifest',
  remoteArchiveManifest.ok &&
    (liveOnly
      ? remoteArchiveManifest.value.archive === archiveName &&
        remoteArchiveManifest.value.sha256 === remoteArchiveSha
      : remoteArchiveManifest.value.sha256 === localArchiveManifest.sha256 &&
        remoteArchiveManifest.value.gitCommit === localArchiveManifest.gitCommit &&
        remoteArchiveManifest.value.generatedAt === localArchiveManifest.generatedAt &&
        sourceSnapshotsMatch(remoteArchiveManifest.value, localArchiveManifest))
      ? 'ok'
      : 'fail',
  remoteArchiveManifest.ok
    ? `${manifestDetail(remoteArchiveManifest.value)} ${sourceSnapshotDetail(remoteArchiveManifest.value)}`
    : remoteArchiveManifest.detail
);

const packageProbe = remote(
  [
    `test -d ${quote(packageDir)}`,
    `test -f ${quote(`${packageDir}/SERVER-ROOT-APPLY.sh`)}`,
    `test -f ${quote(`${packageDir}/SERVER-ROOT-COMMANDS.sh`)}`,
    `test -f ${quote(`${packageDir}/SERVER-NGINX-PLAN.sh`)}`,
    `test -f ${quote(`${packageDir}/CHECKSUMS.sha256`)}`,
  ].join(' && ')
);
addCheck(
  'remote package files',
  packageProbe.ok ? 'ok' : 'fail',
  packageProbe.ok ? 'present' : packageProbe.stderr.trim()
);

const packageManifest = parseRemoteJson(
  remote(`[ -f ${quote(`${packageDir}/manifest.json`)} ] && cat ${quote(`${packageDir}/manifest.json`)}`),
  'remote package manifest'
);
addCheck(
  'remote package manifest',
  packageManifest.ok &&
    (liveOnly
      ? true
      : packageManifest.value.gitCommit === localArchiveManifest.gitCommit &&
        packageManifest.value.generatedAt === localArchiveManifest.generatedAt &&
        sourceSnapshotsMatch(packageManifest.value, localArchiveManifest)) &&
    Array.isArray(packageManifest.value.serverScripts) &&
    packageManifest.value.serverScripts.includes('SERVER-ROOT-COMMANDS.sh')
    ? 'ok'
    : 'fail',
  packageManifest.ok
    ? `${manifestDetail(packageManifest.value)} ${sourceSnapshotDetail(packageManifest.value)}`
    : packageManifest.detail
);

const rootWrapperCommand = remote(
  [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      WEB_ROOT: webRoot,
      NGINX_CONF: nginxConf,
      SITE_CONF: nginxSiteConf,
      NGINX_SNIPPETS_DIR: nginxSnippetsDir,
    })} bash SERVER-ROOT-COMMANDS.sh print-dry-run`,
  ].join(' && ')
);
const rootWrapperMissingTokens = rootWrapperCommand.ok
  ? missingTokens(rootWrapperCommand.stdout, [
      `cd ${packageDir}`,
      'sudo env',
      `WEB_ROOT=${webRoot}`,
      `NGINX_CONF=${nginxConf}`,
      `SITE_CONF=${nginxSiteConf}`,
      `NGINX_SNIPPETS_DIR=${nginxSnippetsDir}`,
      'THEME=nextjs25',
      'DRY_RUN=1',
      'SKIP_NGINX_RELOAD=1',
      'ACTIVATE_THEME=0',
      'RUN_VERIFY=0',
      'bash SERVER-ROOT-APPLY.sh',
    ])
  : [];
addCheck(
  'root wrapper command',
  rootWrapperCommand.ok && rootWrapperMissingTokens.length === 0 ? 'ok' : 'fail',
  rootWrapperCommand.ok
    ? rootWrapperMissingTokens.length === 0
      ? 'dry-run command'
      : `missing token(s): ${rootWrapperMissingTokens.slice(0, 3).join(', ')}`
    : (rootWrapperCommand.stderr || rootWrapperCommand.stdout).trim() || `exit ${rootWrapperCommand.status}`
);

const rootWrapperStatus = remote(
  [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      WEB_ROOT: webRoot,
      NGINX_CONF: nginxConf,
      SITE_CONF: nginxSiteConf,
      NGINX_SNIPPETS_DIR: nginxSnippetsDir,
    })} bash SERVER-ROOT-COMMANDS.sh status`,
  ].join(' && ')
);
const rootWrapperStatusMissingTokens = rootWrapperStatus.ok
  ? missingTokens(rootWrapperStatus.stdout, [
      '[server-root-commands] mode: status',
      'Current include status:',
      '[server-activate-theme] current theme:',
      '[server-activate-theme] target theme: nextjs25',
    ])
  : [];
addCheck(
  'root wrapper status',
  rootWrapperStatus.ok && rootWrapperStatusMissingTokens.length === 0 ? 'ok' : 'fail',
  rootWrapperStatus.ok
    ? rootWrapperStatusMissingTokens.length === 0
      ? 'status command'
      : `missing token(s): ${rootWrapperStatusMissingTokens.slice(0, 3).join(', ')}`
    : (rootWrapperStatus.stderr || rootWrapperStatus.stdout).trim() || `exit ${rootWrapperStatus.status}`
);

const rootWrapperVerifyCommand = remote(
  [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      WEB_ROOT: webRoot,
      NGINX_SNIPPETS_DIR: nginxSnippetsDir,
    })} bash SERVER-ROOT-COMMANDS.sh print-verify`,
  ].join(' && ')
);
const rootWrapperVerifyMissingTokens = rootWrapperVerifyCommand.ok
  ? missingTokens(rootWrapperVerifyCommand.stdout, [
      `cd ${packageDir}`,
      'sudo env',
      `WEB_ROOT=${webRoot}`,
      `NGINX_SNIPPETS_DIR=${nginxSnippetsDir}`,
      'PHP_BIN=php',
      'bash SERVER-ROOT-COMMANDS.sh verify',
    ])
  : [];
addCheck(
  'root wrapper verify command',
  rootWrapperVerifyCommand.ok && rootWrapperVerifyMissingTokens.length === 0 ? 'ok' : 'fail',
  rootWrapperVerifyCommand.ok
    ? rootWrapperVerifyMissingTokens.length === 0
      ? 'verify command'
      : `missing token(s): ${rootWrapperVerifyMissingTokens.slice(0, 3).join(', ')}`
    : (rootWrapperVerifyCommand.stderr || rootWrapperVerifyCommand.stdout).trim() ||
        `exit ${rootWrapperVerifyCommand.status}`
);

const rootWrapperApplyVerifyCommand = remote(
  [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      WEB_ROOT: webRoot,
      NGINX_CONF: nginxConf,
      SITE_CONF: nginxSiteConf,
      NGINX_SNIPPETS_DIR: nginxSnippetsDir,
    })} bash SERVER-ROOT-COMMANDS.sh print-apply-and-verify`,
  ].join(' && ')
);
const rootWrapperApplyVerifyMissingTokens = rootWrapperApplyVerifyCommand.ok
  ? missingTokens(rootWrapperApplyVerifyCommand.stdout, [
      `cd ${packageDir}`,
      'sudo env',
      `WEB_ROOT=${webRoot}`,
      `NGINX_CONF=${nginxConf}`,
      `SITE_CONF=${nginxSiteConf}`,
      `NGINX_SNIPPETS_DIR=${nginxSnippetsDir}`,
      'THEME=nextjs25',
      'CONFIRM_APPLY=nextjs25',
      'PHP_BIN=php',
      'bash SERVER-ROOT-COMMANDS.sh apply-and-verify',
    ])
  : [];
addCheck(
  'root wrapper apply+verify command',
  rootWrapperApplyVerifyCommand.ok && rootWrapperApplyVerifyMissingTokens.length === 0
    ? 'ok'
    : 'fail',
  rootWrapperApplyVerifyCommand.ok
    ? rootWrapperApplyVerifyMissingTokens.length === 0
      ? 'apply-and-verify command'
      : `missing token(s): ${rootWrapperApplyVerifyMissingTokens.slice(0, 3).join(', ')}`
    : (rootWrapperApplyVerifyCommand.stderr || rootWrapperApplyVerifyCommand.stdout).trim() ||
        `exit ${rootWrapperApplyVerifyCommand.status}`
);

const checksumProbe = remote(
  `cd ${quote(packageDir)} && sha256sum -c CHECKSUMS.sha256 >/tmp/g5-nextjs25-root-handoff-checksums.out`
);
addCheck(
  'remote package checksums',
  checksumProbe.ok ? 'ok' : 'fail',
  checksumProbe.ok ? 'passed' : 'failed; see /tmp/g5-nextjs25-root-handoff-checksums.out'
);

const themeProbe = remote(
  [
    `test -d ${quote(`${webRoot}/theme/nextjs25`)}`,
    `test -f ${quote(`${webRoot}/theme/nextjs25/route.php`)}`,
    `test -f ${quote(`${webRoot}/theme/nextjs25/bridge/app-shell.php`)}`,
    `test -f ${quote(`${webRoot}/theme/nextjs25/app/index.html`)}`,
  ].join(' && ')
);
addCheck('live theme files', themeProbe.ok ? 'ok' : 'fail', themeProbe.ok ? 'present' : themeProbe.stderr.trim());

const themeChecksumProbe = remote(
  webRootChecksumCommand('upload/theme/nextjs25/', 'theme/nextjs25/')
);
addCheck(
  'live theme checksums',
  themeChecksumProbe.ok ? 'ok' : 'fail',
  themeChecksumProbe.ok
    ? `${themeChecksumProbe.stdout.trim()} file(s)`
    : (themeChecksumProbe.stderr || themeChecksumProbe.stdout).trim() || `exit ${themeChecksumProbe.status}`
);

const apiProbe = remote(
  [
    `test -f ${quote(`${webRoot}/api/index.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/settings.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/shop/router.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/shop/products.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/shop/reviews.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/shop/policy.php`)}`,
    `test -f ${quote(`${webRoot}/api/v1/shop/shipping.php`)}`,
  ].join(' && ')
);
addCheck('live API files', apiProbe.ok ? 'ok' : 'fail', apiProbe.ok ? 'present' : apiProbe.stderr.trim());

const apiChecksumProbe = remote(webRootChecksumCommand('upload/api/', 'api/'));
addCheck(
  'live API checksums',
  apiChecksumProbe.ok ? 'ok' : 'fail',
  apiChecksumProbe.ok
    ? `${apiChecksumProbe.stdout.trim()} file(s)`
    : (apiChecksumProbe.stderr || apiChecksumProbe.stdout).trim() || `exit ${apiChecksumProbe.status}`
);

const nginxPlan = remote(
  [
    `cd ${quote(packageDir)}`,
    `${shellAssignments({
      NGINX_CONF: nginxConf,
      SITE_CONF: nginxSiteConf,
      NGINX_SNIPPETS_DIR: nginxSnippetsDir,
      WRITE_SITE_SNIPPET: '0',
    })} bash SERVER-NGINX-PLAN.sh`,
  ].join(' && ')
);

if (!nginxPlan.ok) {
  addCheck('nginx include plan', 'fail', nginxPlan.stderr.trim() || `exit ${nginxPlan.status}`);
} else {
  addCheck('nginx include plan', 'ok', 'parsed');
}

let rootApplyDryRun = null;
if (skipRootApplyDryRun) {
  addCheck('root apply dry-run', 'warn', 'skipped by LIVE_ROOT_HANDOFF_SKIP_ROOT_DRY_RUN=1');
} else {
  rootApplyDryRun = remote(
    [
      `cd ${quote(packageDir)}`,
      `${shellAssignments({
        WEB_ROOT: webRoot,
        NGINX_CONF: nginxConf,
        SITE_CONF: nginxSiteConf,
        NGINX_SNIPPETS_DIR: nginxSnippetsDir,
        SKIP_NGINX_RELOAD: '1',
        ACTIVATE_THEME: '0',
        RUN_VERIFY: '0',
      })} bash SERVER-ROOT-COMMANDS.sh dry-run`,
    ].join(' && ')
  );

  addCheck(
    'root apply dry-run',
    rootApplyDryRun.ok && rootApplyDryRun.stdout.includes('Root apply flow finished.')
      ? 'ok'
      : 'fail',
    rootApplyDryRun.ok
      ? 'finished'
      : (rootApplyDryRun.stderr || rootApplyDryRun.stdout).trim() || `exit ${rootApplyDryRun.status}`
  );
}

console.table(checks);

const failedChecks = checks.filter((check) => check.status === 'fail');

if (failedChecks.length > 0) {
  fail(`${failedChecks.length} handoff readiness check(s) failed`);
}

const statusRows = nginxPlan.ok ? parseIncludeStatus(nginxPlan.stdout) : [];
if (statusRows.length === 0) {
  fail('Could not parse nginx include status from SERVER-NGINX-PLAN.sh output');
}

console.log('\n[check-live-root-handoff] nginx include status');
console.table(statusRows);

const missingRows = statusRows.filter((row) => row.status !== 'present');
if (missingRows.length === 0) {
  console.log('[check-live-root-handoff] root nginx handoff is no longer pending');
  process.exit(0);
}

console.log(
  `[check-live-root-handoff] ${missingRows.length} root nginx include item(s) still need sudo/root apply`
);
const rootCommandEnv = shellAssignments({
  WEB_ROOT: webRoot,
  NGINX_CONF: nginxConf,
  SITE_CONF: nginxSiteConf,
  NGINX_SNIPPETS_DIR: nginxSnippetsDir,
});
console.log('\nRun on the live server as root or a sudo-capable user:');
console.log(`cd ${packageDir}`);
console.log(`bash SERVER-ROOT-COMMANDS.sh status`);
console.log(`sudo env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh dry-run`);
console.log(`sudo env ${rootCommandEnv} CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify`);
console.log('\nOr apply and verify as separate commands:');
console.log(`sudo env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh apply`);
console.log(`sudo env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh verify`);
if (rootSshProbe.ok) {
  console.log('\nOr run from this machine through root SSH:');
  console.log(
    `ssh ${rootSshTarget} ${quote(
      `cd ${packageDir} && env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh status`
    )}`
  );
  console.log(
    `ssh ${rootSshTarget} ${quote(
      `cd ${packageDir} && env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh dry-run`
    )}`
  );
  console.log(
    `ssh ${rootSshTarget} ${quote(
      `cd ${packageDir} && env ${rootCommandEnv} CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify`
    )}`
  );
}
console.log('\nRaw helper equivalent:');
console.log(`sudo env ${rootCommandEnv} DRY_RUN=1 bash SERVER-ROOT-APPLY.sh`);
console.log(`sudo env ${rootCommandEnv} DRY_RUN=0 bash SERVER-ROOT-APPLY.sh`);
console.log('\nThen verify locally:');
console.log('npm run check:release:live:nginx');
