import { spawn } from 'node:child_process';

const args = new Set(process.argv.slice(2));
const supportedArgs = new Set([
  '--continue-on-failure',
  '--require-nginx',
  '--skip-browser',
  '--skip-mobile',
]);

for (const arg of args) {
  if (!supportedArgs.has(arg)) {
    console.error(`[check-release-live] Unknown argument: ${arg}`);
    console.error(
      '[check-release-live] Supported arguments: --continue-on-failure, --require-nginx, --skip-browser, --skip-mobile'
    );
    process.exit(1);
  }
}

const continueOnFailure =
  args.has('--continue-on-failure') || process.env.LIVE_RELEASE_CONTINUE_ON_FAILURE === '1';
const requireNginx = args.has('--require-nginx') || process.env.LIVE_RELEASE_REQUIRE_NGINX === '1';
const skipBrowser = args.has('--skip-browser');
const skipMobile = args.has('--skip-mobile');
const maxRetries = Number.parseInt(process.env.LIVE_RELEASE_CHECK_RETRIES || '1', 10);

const releaseScripts = [
  'check',
  'check:live-root-handoff',
  requireNginx ? 'check:live-nginx-plan:required' : 'check:live-nginx-plan',
  'check:live-deployment',
  'check:live-legacy-admin',
  'check:live-social-redirects',
  'check:live-youngcart-legacy-routes',
  'check:live-youngcart-core-flow',
  'check:live-migration-sample',
  'check:live-youngcart-order-flow',
  'check:live-rsc-payloads',
  'check:live-runtime',
  ...(!skipBrowser ? ['check:live-browser'] : []),
  ...(!skipBrowser && !skipMobile ? ['check:live-browser:mobile'] : []),
];

function runScript(script) {
  return new Promise((resolve, reject) => {
    console.log(`\n>>> npm run ${script}`);
    const child = spawn('npm', ['run', script], {
      stdio: 'inherit',
      shell: process.platform === 'win32',
    });

    child.on('error', reject);
    child.on('exit', (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }

      const reason = signal ? `signal ${signal}` : `exit code ${code}`;
      reject(new Error(`${script} failed with ${reason}`));
    });
  });
}

function retryCount() {
  return Number.isFinite(maxRetries) && maxRetries > 0 ? maxRetries : 0;
}

console.log(
  `[check-release-live] nginx=${requireNginx ? 'required' : 'advisory'} browser=${
    skipBrowser ? 'no' : 'yes'
  } mobile=${
    skipBrowser || skipMobile ? 'no' : 'yes'
  } continueOnFailure=${continueOnFailure ? 'yes' : 'no'}`
);

const failures = [];

for (const script of releaseScripts) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await runScript(script);
      break;
    } catch (error) {
      if (attempt >= retryCount()) {
        if (!continueOnFailure) {
          throw error;
        }

        failures.push({ script, error: error.message });
        console.error(`[check-release-live] ${script} failed; continuing because --continue-on-failure is set`);
        break;
      }
      console.warn(
        `[check-release-live] ${script} failed; retrying (${attempt + 1}/${retryCount()})`
      );
    }
  }
}

if (failures.length > 0) {
  console.error(`\n[check-release-live] ${failures.length} sub-check(s) failed`);
  console.table(failures);
  process.exit(1);
}

console.log('\n[check-release-live] live release gate passed');
