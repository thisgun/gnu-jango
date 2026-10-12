import { spawnSync } from 'node:child_process';

const args = new Set(process.argv.slice(2));
const supportedArgs = new Set(['--require-applied']);

for (const arg of args) {
  if (!supportedArgs.has(arg)) {
    console.error(`[check-live-nginx-plan] Unknown argument: ${arg}`);
    console.error('[check-live-nginx-plan] Supported arguments: --require-applied');
    process.exit(1);
  }
}

const requireApplied =
  args.has('--require-applied') || process.env.LIVE_NGINX_PLAN_REQUIRE_APPLIED === '1';

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

function fail(message) {
  console.error(`[check-live-nginx-plan] ${message}`);
  process.exit(1);
}

const host = env('LIVE_DEPLOY_HOST', 'nextjs.thisgun.net');
const user = env('LIVE_DEPLOY_USER');
const port = env('LIVE_DEPLOY_PORT', '22');
const sshKey = env('LIVE_DEPLOY_SSH_KEY');
const remoteDir = env('LIVE_DEPLOY_REMOTE_DIR', '/tmp/g5-nextjs25-live-deploy');
const packageDir = env('LIVE_DEPLOY_PACKAGE_DIR', `${remoteDir.replace(/\/+$/, '')}/nextjs25-live`);
const nginxConf = env('LIVE_DEPLOY_NGINX_CONF', '/etc/nginx/nginx.conf');
const nginxSiteConf = env(
  'LIVE_DEPLOY_NGINX_SITE_CONF',
  '/etc/nginx/sites-enabled/nextjs.thisgun.net'
);
const nginxSnippetsDir = env('LIVE_DEPLOY_NGINX_SNIPPETS_DIR', '/etc/nginx/snippets');

const sshTarget = user && !host.includes('@') ? `${user}@${host}` : host;
const sshArgs = ['-p', port];
if (sshKey) {
  sshArgs.push('-i', sshKey);
}

const assignments = shellAssignments({
  NGINX_CONF: nginxConf,
  SITE_CONF: nginxSiteConf,
  NGINX_SNIPPETS_DIR: nginxSnippetsDir,
  WRITE_SITE_SNIPPET: '0',
});
const remoteCommand = `cd ${quote(packageDir)} && ${assignments} bash SERVER-NGINX-PLAN.sh`;

console.log(`[check-live-nginx-plan] target=${sshTarget}`);
console.log(`[check-live-nginx-plan] package=${packageDir}`);

const result = spawnSync('ssh', [...sshArgs, sshTarget, remoteCommand], {
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
});

if (result.error) {
  fail(`ssh failed to start: ${result.error.message}`);
}

if (result.status !== 0) {
  process.stdout.write(result.stdout || '');
  process.stderr.write(result.stderr || '');
  fail(`SERVER-NGINX-PLAN.sh failed with exit code ${result.status}`);
}

const output = result.stdout || '';
const statusRows = [];
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
    statusRows.push({ check: match[1].trim(), status: match[2].trim() });
  }
}

if (statusRows.length === 0) {
  process.stdout.write(output);
  fail('Could not parse include status from SERVER-NGINX-PLAN.sh output');
}

console.table(statusRows);

const incompleteRows = statusRows.filter((row) => row.status !== 'present');
if (incompleteRows.length === 0) {
  console.log('[check-live-nginx-plan] nginx include status is fully applied');
  process.exit(0);
}

console.warn(
  `[check-live-nginx-plan] ${incompleteRows.length} nginx include item(s) are not applied`
);
const rootCommandEnv = shellAssignments({
  WEB_ROOT: env('LIVE_DEPLOY_WEB_ROOT', '/home/nextjs/www/study-gnuboard'),
  NGINX_CONF: nginxConf,
  SITE_CONF: nginxSiteConf,
  NGINX_SNIPPETS_DIR: nginxSnippetsDir,
});
console.warn(
  [
    '[check-live-nginx-plan] next root steps:',
    `  cd ${packageDir}`,
    '  bash SERVER-ROOT-COMMANDS.sh status',
    `  sudo env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh dry-run`,
    `  sudo env ${rootCommandEnv} CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify`,
  ].join('\n')
);

if (requireApplied) {
  process.exit(1);
}
