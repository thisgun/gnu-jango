import { spawn, spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const action = process.argv[2];
const args = process.argv.slice(3);
const distDir = process.env.G5_NEXT_DIST_DIR?.trim() || '.next-server-build';
const env = {
  ...process.env,
  G5_NEXT_RUNTIME: 'server',
  G5_NEXT_DIST_DIR: distDir,
};

if (!['build', 'start'].includes(action)) {
  console.error('Usage: node scripts/server-runtime.mjs <build|start> [...next args]');
  process.exit(2);
}

const command =
  action === 'build'
    ? [resolve(root, 'scripts/build-next.mjs'), '--runtime=server', ...args]
    : [resolve(root, 'node_modules/next/dist/bin/next'), 'start', ...args];

if (action === 'build') {
  const result = spawnSync(process.execPath, command, {
    cwd: root,
    env,
    shell: false,
    stdio: 'inherit',
  });

  if (result.error) console.error(`[server-runtime] ${result.error.message}`);
  process.exitCode = result.status ?? 1;
} else {
  const child = spawn(process.execPath, command, {
    cwd: root,
    env,
    shell: false,
    stdio: 'inherit',
  });

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => {
      if (child.exitCode === null) child.kill(signal);
    });
  }

  child.on('error', (error) => {
    console.error(`[server-runtime] ${error.message}`);
    process.exitCode = 1;
  });
  child.on('exit', (code, signal) => {
    process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 1);
  });
}
