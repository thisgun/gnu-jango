import { existsSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const deployRoot = join(nextRoot, '.deploy');
const packageScript = join(scriptDir, 'package-live-deploy.mjs');
const archiveName = 'nextjs25-live.tar.gz';
const archiveChecksumName = `${archiveName}.sha256`;
const archiveManifestName = 'nextjs25-live.archive.json';
const archivePath = join(deployRoot, archiveName);
const archiveChecksumPath = join(deployRoot, archiveChecksumName);
const archiveManifestPath = join(deployRoot, archiveManifestName);

const help = `
Usage:
  LIVE_DEPLOY_HOST=host LIVE_DEPLOY_WEB_ROOT=/var/www/gnuboard npm run deploy:live:ssh

Required:
  LIVE_DEPLOY_HOST            SSH host for the live server.
  LIVE_DEPLOY_WEB_ROOT        Live Gnuboard document root on the server.

Common options:
  LIVE_DEPLOY_USER            SSH user. Optional when LIVE_DEPLOY_HOST already includes user@.
  LIVE_DEPLOY_PORT            SSH port. Default: 22.
  LIVE_DEPLOY_SSH_KEY         SSH private key path.
  LIVE_DEPLOY_SSH_CONNECT_TIMEOUT
                              SSH connect timeout in seconds. Default: 10.
  LIVE_DEPLOY_REMOTE_DIR      Remote staging directory. Default: /tmp/g5-nextjs25-live-deploy.
  LIVE_DEPLOY_APPLY=1         Actually install files, activate theme, and run server verify.
                              Without this, upload/extract/checksum still runs, then install/theme are dry-run.
  LIVE_DEPLOY_CONFIRM_APPLY   Required with LIVE_DEPLOY_APPLY=1 and root apply mode.
                              Set to the theme name, normally nextjs25.
  LIVE_DEPLOY_THEME_ONLY=1    Install theme files with the SSH user and skip nginx changes.
                              Theme activation defaults to off in this mode.
  LIVE_DEPLOY_WEB_ROOT_ONLY=1 Install theme and API files with the SSH user and skip
                              root/nginx changes. Useful while sudo/root is pending.
  LIVE_DEPLOY_ACTIVATE_THEME  Override theme activation. Defaults to 1 only for full apply mode.
  LIVE_DEPLOY_SUDO            Sudo command. Default: sudo. Set to empty/none/off when not needed.
  LIVE_DEPLOY_ROOT_TARGET     Optional SSH target for root helper commands after upload.
                              Example: root@example.com. Defaults to the deploy SSH target.
  LIVE_DEPLOY_ROOT_SUDO       Sudo command for root helper target. Defaults to LIVE_DEPLOY_SUDO,
                              or no sudo when LIVE_DEPLOY_ROOT_TARGET starts with root@.
  LIVE_DEPLOY_NGINX_SNIPPETS_DIR
                              Nginx snippets dir. Default: /etc/nginx/snippets.
  LIVE_DEPLOY_NGINX_CONF      Nginx main config. Default: /etc/nginx/nginx.conf.
  LIVE_DEPLOY_NGINX_SITE_CONF nextjs.thisgun.net site config path.
  LIVE_DEPLOY_PHP_BIN         PHP CLI command/path used by theme activation and verify.
  LIVE_DEPLOY_PHP_WEB_ROOT    WEB_ROOT as seen by PHP when different from the shell path.
  LIVE_DEPLOY_SKIP_PACKAGE=1  Reuse the existing local archive instead of regenerating it.
  LIVE_DEPLOY_SKIP_NGINX_PLAN=1
  LIVE_DEPLOY_SKIP_NGINX_INSTALL=1
  LIVE_DEPLOY_SKIP_NGINX_TEST=1
  LIVE_DEPLOY_SKIP_NGINX_RELOAD=1
  LIVE_DEPLOY_SKIP_NGINX_DUMP=1
  LIVE_DEPLOY_NGINX_TEST_COMMAND
                              Override server nginx syntax test command.
  LIVE_DEPLOY_NGINX_DUMP_COMMAND
                              Override server nginx loaded-config dump command.
  LIVE_DEPLOY_SKIP_API_INSTALL=1
                              Leave the live web-root api directory untouched.
  LIVE_DEPLOY_SKIP_PHP_THEME_CHECK=1
  LIVE_DEPLOY_SKIP_APPLY_PREFLIGHT=1
                              Skip the apply-mode root helper dry-run preflight.
  LIVE_DEPLOY_SKIP_SUDO_PREFLIGHT=1
                              Skip the non-interactive sudo/root preflight.
  LIVE_DEPLOY_ROOT_APPLY=0  Use the older split SERVER-INSTALL.sh flow instead
                            of SERVER-ROOT-APPLY.sh.

The default is intentionally safe: it uploads and extracts the archive, verifies
checksums, prints SERVER-ROOT-COMMANDS.sh status, then runs
SERVER-ROOT-COMMANDS.sh dry-run. Set LIVE_DEPLOY_APPLY=1 and
LIVE_DEPLOY_CONFIRM_APPLY=nextjs25 only when the SSH user has root/sudo access
and the dry-run output looks correct. Apply mode uses SERVER-ROOT-COMMANDS.sh
apply-and-verify through the configured root helper target and sudo command.
When sudo is enabled, server helpers are executed through sudo env so WEB_ROOT
and the nginx/PHP options are passed to the root shell.
`;

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log(help.trim());
  process.exit(0);
}

function env(name, fallback = '') {
  const value = process.env[name];
  return value === undefined || value === '' ? fallback : value;
}

function envAllowEmpty(name, fallback = '') {
  const value = process.env[name];
  return value === undefined ? fallback : value;
}

function fail(message) {
  console.error(`[deploy-live-ssh] ${message}`);
  process.exit(1);
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

function helperCommand(command, envValues = {}, commandSudoPrefix = sudoPrefix) {
  const assignments = shellAssignments(envValues);

  if (commandSudoPrefix) {
    return [commandSudoPrefix, 'env', assignments, command].filter(Boolean).join(' ');
  }

  return [assignments, command].filter(Boolean).join(' ');
}

function rootProbeCommand(commandSudoPrefix = sudoPrefix) {
  if (!commandSudoPrefix) {
    return 'test "$(id -u)" = "0"';
  }

  if (commandSudoPrefix === 'sudo') {
    return 'sudo -n env true';
  }

  return `${commandSudoPrefix} env true`;
}

function run(command, args, options = {}) {
  const printable = [command, ...args].join(' ');
  console.log(`[deploy-live-ssh] ${printable}`);

  const result = spawnSync(command, args, {
    cwd: options.cwd || nextRoot,
    shell: false,
    stdio: 'inherit',
  });

  if (result.error) {
    fail(`${command} failed to start: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail(`${command} exited with ${result.status}`);
  }
}

function runOptional(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || nextRoot,
    shell: false,
    stdio: options.stdio || 'ignore',
  });

  return !result.error && result.status === 0;
}

function requireFile(path, label) {
  if (!existsSync(path)) {
    fail(`Missing ${label}: ${path}`);
  }
}

function sshBaseArgs() {
  const args = ['-o', 'BatchMode=yes', '-o', `ConnectTimeout=${sshConnectTimeout}`];
  if (sshKey) {
    args.push('-i', sshKey);
  }
  args.push('-p', sshPort);
  return args;
}

function scpBaseArgs() {
  const args = ['-o', 'BatchMode=yes', '-o', `ConnectTimeout=${sshConnectTimeout}`];
  if (sshKey) {
    args.push('-i', sshKey);
  }
  args.push('-P', sshPort);
  return args;
}

function remoteExec(command, target = sshTarget) {
  run('ssh', [...sshBaseArgs(), target, `bash -lc ${quote(command)}`], { cwd: repoRoot });
}

function upload(localPath, remotePath) {
  run('scp', [...scpBaseArgs(), localPath, `${sshTarget}:${remotePath}`], { cwd: repoRoot });
}

const liveHost = env('LIVE_DEPLOY_HOST');
const liveUser = env('LIVE_DEPLOY_USER');
const liveWebRoot = env('LIVE_DEPLOY_WEB_ROOT');
const sshPort = env('LIVE_DEPLOY_PORT', '22');
const sshKey = env('LIVE_DEPLOY_SSH_KEY');
const sshConnectTimeout = env('LIVE_DEPLOY_SSH_CONNECT_TIMEOUT', '10');
const remoteDir = env('LIVE_DEPLOY_REMOTE_DIR', '/tmp/g5-nextjs25-live-deploy');
const sudoCommand = envAllowEmpty('LIVE_DEPLOY_SUDO', 'sudo');
const apply = env('LIVE_DEPLOY_APPLY') === '1';
const themeOnly = env('LIVE_DEPLOY_THEME_ONLY') === '1';
const webRootOnly = env('LIVE_DEPLOY_WEB_ROOT_ONLY') === '1';

if (!liveHost) {
  fail(`LIVE_DEPLOY_HOST is required.\n\n${help.trim()}`);
}

if (!liveWebRoot) {
  fail(`LIVE_DEPLOY_WEB_ROOT is required.\n\n${help.trim()}`);
}

if (!runOptional('ssh', ['-V'])) {
  fail('ssh command is required.');
}

const sshTarget = liveUser && !liveHost.includes('@') ? `${liveUser}@${liveHost}` : liveHost;
const installDryRun = apply ? '0' : '1';
const webRootScoped = themeOnly || webRootOnly;
const activateApply = env('LIVE_DEPLOY_ACTIVATE_THEME', themeOnly ? '0' : apply ? '1' : '0');
const runServerVerify = env('LIVE_DEPLOY_RUN_VERIFY', apply && !themeOnly ? '1' : '0');
const skipNginxReload = env('LIVE_DEPLOY_SKIP_NGINX_RELOAD', apply && !webRootScoped ? '0' : '1');
const skipNginxTest = env('LIVE_DEPLOY_SKIP_NGINX_TEST', webRootScoped ? '1' : '0');
const skipNginxDump = env('LIVE_DEPLOY_SKIP_NGINX_DUMP', webRootScoped ? '1' : '0');
const nginxTestCommand = env('LIVE_DEPLOY_NGINX_TEST_COMMAND');
const nginxDumpCommand = env('LIVE_DEPLOY_NGINX_DUMP_COMMAND');
const skipNginxPlan = env('LIVE_DEPLOY_SKIP_NGINX_PLAN', webRootScoped ? '1' : '0');
const skipNginxInstall = env('LIVE_DEPLOY_SKIP_NGINX_INSTALL', webRootScoped ? '1' : '0');
const skipApiInstall = env('LIVE_DEPLOY_SKIP_API_INSTALL', themeOnly ? '1' : '0');
const skipPhpThemeCheck = env('LIVE_DEPLOY_SKIP_PHP_THEME_CHECK', '0');
const skipApplyPreflight = env('LIVE_DEPLOY_SKIP_APPLY_PREFLIGHT', '0');
const skipSudoPreflight = env('LIVE_DEPLOY_SKIP_SUDO_PREFLIGHT', webRootScoped ? '1' : '0');
const useRootApply = webRootScoped ? false : env('LIVE_DEPLOY_ROOT_APPLY', '1') !== '0';
const nginxSnippetsDir = env('LIVE_DEPLOY_NGINX_SNIPPETS_DIR', '/etc/nginx/snippets');
const nginxConf = env('LIVE_DEPLOY_NGINX_CONF', '/etc/nginx/nginx.conf');
const nginxSiteConf = env('LIVE_DEPLOY_NGINX_SITE_CONF', '/etc/nginx/sites-enabled/nextjs.thisgun.net');
const phpBin = env('LIVE_DEPLOY_PHP_BIN');
const phpWebRoot = env('LIVE_DEPLOY_PHP_WEB_ROOT');
const theme = env('LIVE_DEPLOY_THEME', 'nextjs25');
const confirmApply = env('LIVE_DEPLOY_CONFIRM_APPLY');
const sudoValue = sudoCommand.trim();
const sudoDisabled = ['0', 'false', 'none', 'no', 'off'].includes(sudoValue.toLowerCase());
const sudoPrefix = sudoDisabled ? '' : sudoValue;
const rootSshTarget = env('LIVE_DEPLOY_ROOT_TARGET', sshTarget);
const rootSudoCommand = envAllowEmpty(
  'LIVE_DEPLOY_ROOT_SUDO',
  rootSshTarget !== sshTarget && rootSshTarget.startsWith('root@') ? '' : sudoCommand,
);
const rootSudoValue = rootSudoCommand.trim();
const rootSudoDisabled = ['0', 'false', 'none', 'no', 'off'].includes(rootSudoValue.toLowerCase());
const rootSudoPrefix = rootSudoDisabled ? '' : rootSudoValue;
const helperTarget = webRootScoped ? sshTarget : rootSshTarget;
const helperSudoPrefix = webRootOnly ? '' : themeOnly ? sudoPrefix : rootSudoPrefix;
const effectiveHelperSudoPrefix = apply ? helperSudoPrefix : '';

if (apply && useRootApply && confirmApply !== theme) {
  fail(`LIVE_DEPLOY_CONFIRM_APPLY must be set to ${theme} when LIVE_DEPLOY_APPLY=1.`);
}

if (apply && skipSudoPreflight !== '1') {
  console.log('[deploy-live-ssh] preflight root/sudo access');
  remoteExec(rootProbeCommand(helperSudoPrefix), helperTarget);
}

if (env('LIVE_DEPLOY_SKIP_PACKAGE') !== '1') {
  run('node', [packageScript], { cwd: nextRoot });
}

requireFile(archivePath, 'live deploy archive');
requireFile(archiveChecksumPath, 'live deploy archive checksum');
requireFile(archiveManifestPath, 'live deploy archive manifest');

const archiveSize = statSync(archivePath).size;
console.log(
  `[deploy-live-ssh] archive ${relative(repoRoot, archivePath).replaceAll('\\', '/')} (${archiveSize} bytes)`,
);
console.log(`[deploy-live-ssh] target ${sshTarget}:${remoteDir}`);
if (!webRootScoped) {
  console.log(`[deploy-live-ssh] root helper target ${helperTarget}`);
  console.log(`[deploy-live-ssh] root helper sudo ${effectiveHelperSudoPrefix || '(none)'}`);
}
const modePrefix = webRootOnly ? 'web-root-only ' : themeOnly ? 'theme-only ' : '';
console.log(`[deploy-live-ssh] mode ${modePrefix}${apply ? 'apply' : 'dry-run'}`);

remoteExec(`mkdir -p ${quote(remoteDir)}`);
upload(archivePath, `${remoteDir}/${archiveName}`);
upload(archiveChecksumPath, `${remoteDir}/${archiveChecksumName}`);
upload(archiveManifestPath, `${remoteDir}/${archiveManifestName}`);

remoteExec(
  [
    `cd ${quote(remoteDir)}`,
    `sha256sum -c ${quote(archiveChecksumName)}`,
    [
      'if [ -e nextjs25-live ]; then',
      'if rm -rf nextjs25-live 2>/tmp/g5-nextjs25-deploy-rm.err; then',
      ':;',
      'else',
      'stale_dir="nextjs25-live.stale.$(date +%Y%m%d-%H%M%S).$$";',
      'mv nextjs25-live "$stale_dir";',
      'printf "[deploy-live-ssh] preserved previous package at %s\\n" "$stale_dir";',
      'fi;',
      'fi',
    ].join(' '),
    `tar -xzf ${quote(archiveName)}`,
    'cd nextjs25-live',
    'sha256sum -c CHECKSUMS.sha256',
  ].join(' && '),
);

const baseServerEnv = {
  WEB_ROOT: liveWebRoot,
  NGINX_SNIPPETS_DIR: nginxSnippetsDir,
  PHP_BIN: phpBin,
  PHP_WEB_ROOT: phpWebRoot,
};
const rootApplyEnv = {
  ...baseServerEnv,
  NGINX_CONF: nginxConf,
  SITE_CONF: nginxSiteConf,
  NGINX_SNIPPETS_DIR: nginxSnippetsDir,
  THEME: theme,
  DRY_RUN: installDryRun,
  SKIP_NGINX_PLAN: skipNginxPlan,
  SKIP_NGINX_INSTALL: skipNginxInstall,
  SKIP_NGINX_TEST: skipNginxTest,
  SKIP_NGINX_RELOAD: skipNginxReload,
  SKIP_NGINX_DUMP: skipNginxDump,
  NGINX_TEST_COMMAND: nginxTestCommand,
  NGINX_DUMP_COMMAND: nginxDumpCommand,
  SKIP_API_INSTALL: skipApiInstall,
  SKIP_PHP_THEME_CHECK: skipPhpThemeCheck,
  RUN_VERIFY: runServerVerify,
};

if (useRootApply) {
  console.log('[deploy-live-ssh] root status preflight');
  remoteExec(
    [
      `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
      helperCommand('bash SERVER-ROOT-COMMANDS.sh status', {
        WEB_ROOT: liveWebRoot,
        NGINX_CONF: nginxConf,
        SITE_CONF: nginxSiteConf,
        NGINX_SNIPPETS_DIR: nginxSnippetsDir,
        THEME: theme,
        PHP_BIN: phpBin,
        PHP_WEB_ROOT: phpWebRoot,
      }, ''),
    ].join(' && '),
    helperTarget,
  );
}

if (apply && useRootApply && skipApplyPreflight !== '1') {
  console.log('[deploy-live-ssh] preflight SERVER-ROOT-COMMANDS.sh dry-run');
  remoteExec(
    [
      `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
      helperCommand('bash SERVER-ROOT-COMMANDS.sh dry-run', {
        ...rootApplyEnv,
        SKIP_NGINX_RELOAD: '1',
        ACTIVATE_THEME: '0',
        RUN_VERIFY: '0',
      }, effectiveHelperSudoPrefix),
    ].join(' && '),
    helperTarget,
  );
}

if (useRootApply) {
  const rootCommand = apply
    ? 'bash SERVER-ROOT-COMMANDS.sh apply-and-verify'
    : 'bash SERVER-ROOT-COMMANDS.sh dry-run';
  const rootCommandEnv = apply
    ? {
        ...rootApplyEnv,
        CONFIRM_APPLY: confirmApply,
      }
    : {
        ...rootApplyEnv,
        SKIP_NGINX_RELOAD: '1',
        ACTIVATE_THEME: '0',
        RUN_VERIFY: '0',
      };

  remoteExec(
    [
      `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
      helperCommand(rootCommand, rootCommandEnv, effectiveHelperSudoPrefix),
    ].join(' && '),
    helperTarget,
  );

  if (!apply) {
    console.log('[deploy-live-ssh] root apply dry-run complete; set LIVE_DEPLOY_APPLY=1 when root/sudo access is available.');
  }
} else {
  if (skipNginxPlan !== '1') {
    remoteExec(
      [
        `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
        `${shellAssignments({
          NGINX_CONF: nginxConf,
          SITE_CONF: nginxSiteConf,
          NGINX_SNIPPETS_DIR: nginxSnippetsDir,
          WRITE_SITE_SNIPPET: '1',
        })} bash SERVER-NGINX-PLAN.sh`,
      ].join(' && '),
      helperTarget,
    );
  }

  remoteExec(
    [
      `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
      helperCommand('bash SERVER-INSTALL.sh', {
        ...baseServerEnv,
        DRY_RUN: installDryRun,
        SKIP_NGINX_INSTALL: skipNginxInstall,
        SKIP_API_INSTALL: skipApiInstall,
        SKIP_NGINX_TEST: skipNginxTest,
        NGINX_TEST_COMMAND: nginxTestCommand,
        SKIP_NGINX_RELOAD: skipNginxReload,
      }, effectiveHelperSudoPrefix),
    ].join(' && '),
    helperTarget,
  );

  remoteExec(
    [
      `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
      helperCommand('bash SERVER-ACTIVATE-THEME.sh', {
        WEB_ROOT: liveWebRoot,
        PHP_BIN: phpBin,
        PHP_WEB_ROOT: phpWebRoot,
        THEME: theme,
        APPLY: activateApply,
      }, effectiveHelperSudoPrefix),
    ].join(' && '),
    helperTarget,
  );

  if (apply && runServerVerify === '1') {
    remoteExec(
      [
        `cd ${quote(`${remoteDir}/nextjs25-live`)}`,
        helperCommand('bash SERVER-VERIFY.sh', {
          ...baseServerEnv,
          SKIP_NGINX_TEST: skipNginxTest,
          SKIP_NGINX_DUMP: skipNginxDump,
          NGINX_TEST_COMMAND: nginxTestCommand,
          NGINX_DUMP_COMMAND: nginxDumpCommand,
          SKIP_PHP_THEME_CHECK: skipPhpThemeCheck,
        }, effectiveHelperSudoPrefix),
      ].join(' && '),
      helperTarget,
    );
  } else if (apply) {
    console.log(`[deploy-live-ssh] server verify skipped because LIVE_DEPLOY_RUN_VERIFY=${runServerVerify}.`);
  } else {
    console.log('[deploy-live-ssh] dry-run complete; server verify is skipped until LIVE_DEPLOY_APPLY=1.');
  }
}

console.log('[deploy-live-ssh] done');
