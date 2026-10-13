import { spawn } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));

const actionScripts = [
  'check:local-auth-actions',
  'check:local-user-actions',
  'check:local-shop-actions',
  'check:local-order-actions',
  'check:local-shop-content-actions',
  'check:local-address-actions',
  'check:local-memo-actions',
  'check:local-member-actions',
  'check:local-notification-actions',
  'check:local-scrap-actions',
  'check:local-coupon-actions',
  'check:local-qa-actions',
  'check:local-personalpay-actions',
  'check:local-point-actions',
  'check:local-poll-actions',
  'check:local-post-reaction-actions',
];

const maxRetries = Number.parseInt(process.env.LOCAL_ACTION_CHECK_RETRIES || '1', 10);

function actionFileToScript(file) {
  return file.replace(/^check-local-/, 'check:local-').replace(/\.mjs$/, '');
}

function validateActionScriptList() {
  const discoveredFiles = readdirSync(scriptDir).filter((file) =>
    /^check-local-.+-actions\.mjs$/.test(file)
  );
  const discoveredScripts = discoveredFiles
    .map(actionFileToScript)
    .sort();
  const configuredScripts = [...actionScripts].sort();
  const configuredSet = new Set(configuredScripts);
  const discoveredSet = new Set(discoveredScripts);

  const unlisted = discoveredScripts.filter((script) => !configuredSet.has(script));
  const missingFiles = configuredScripts.filter((script) => !discoveredSet.has(script));

  if (unlisted.length === 0 && missingFiles.length === 0) {
    return;
  }

  if (unlisted.length > 0) {
    console.error(`[check-local-actions] Unlisted action check scripts: ${unlisted.join(', ')}`);
  }

  if (missingFiles.length > 0) {
    console.error(`[check-local-actions] Missing action check files: ${missingFiles.join(', ')}`);
  }

  process.exit(1);
}

validateActionScriptList();

function retryCount() {
  return Number.isFinite(maxRetries) && maxRetries > 0 ? maxRetries : 0;
}

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

for (const script of actionScripts) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await runScript(script);
      break;
    } catch (error) {
      if (attempt >= retryCount()) {
        throw error;
      }
      console.warn(
        `[check-local-actions] ${script} failed; retrying (${attempt + 1}/${retryCount()})`
      );
    }
  }
}

console.log('\n[check-local-actions] all local action checks passed');
