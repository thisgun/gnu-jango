import { randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import {
  cpSync,
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  symlinkSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveThemeSourceName } from './theme-pair.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const THEME_SOURCE = resolveThemeSourceName();
const OTHER_THEME_SOURCES = existsSync(join(ROOT, 'themes'))
  ? readdirSync(join(ROOT, 'themes')).filter((name) => name !== THEME_SOURCE && name !== 'default')
  : [];
const BUILD_LOCK_PATH = join(ROOT, '.g5-next-build.lock');
const STATIC_BUILD_WORKSPACE_NAME = '.g5-next-theme-build-workspace';
const DYNAMIC_PARAMS_RE = /export const dynamicParams = (true|false);/g;
const SERVER_RUNTIME_ONLY_RE = /@g5-server-runtime-only/;
const require = createRequire(import.meta.url);
const { loadEnvConfig } = require('@next/env');

loadEnvConfig(ROOT, false);

const runtimeArgument = process.argv.slice(2).find((argument) => argument.startsWith('--runtime='));
const requestedRuntime = runtimeArgument?.slice('--runtime='.length);
const nextBuildArguments = process.argv
  .slice(2)
  .filter((argument) => !argument.startsWith('--runtime='));

if (runtimeArgument && !['server', 'static'].includes(requestedRuntime)) {
  throw new Error(`Unsupported G5_NEXT_RUNTIME override: ${requestedRuntime}`);
}

const SERVER_RUNTIME = requestedRuntime
  ? requestedRuntime === 'server'
  : process.env.G5_NEXT_RUNTIME === 'server';
const DESIRED_DYNAMIC_PARAMS = SERVER_RUNTIME ? 'true' : 'false';
const NEXT_DIST_DIR =
  process.env.G5_NEXT_DIST_DIR?.trim() ||
  (SERVER_RUNTIME ? '.next' : '.next-theme-build');
const BUILD_ENV = {
  ...process.env,
  G5_NEXT_DIST_DIR: NEXT_DIST_DIR,
  G5_NEXT_RUNTIME: SERVER_RUNTIME ? 'server' : 'static',
  // The static build runs in a sibling workspace whose node_modules is a link back into ROOT.
  // Turbopack (the default builder since Next 16) refuses links that leave its root, so the root
  // is widened to the folder that holds both. Server builds run in place and keep the default.
  ...(SERVER_RUNTIME ? {} : { G5_TURBOPACK_ROOT: process.env.G5_TURBOPACK_ROOT || dirname(ROOT) }),
};
const EXCLUDED_BUILD_ENTRIES = new Set([
  '.deploy',
  '.git',
  '.g5-next-build.lock',
  '.next',
  '.next-server-build',
  '.next-theme-build',
  'node_modules',
  'out',
  'playwright-report',
  'test-results',
]);

function collectRouteFiles(dir) {
  const files = [];

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectRouteFiles(fullPath));
      continue;
    }

    if (!/\.(ts|tsx)$/.test(entry.name)) continue;

    const content = readFileSync(fullPath, 'utf8');
    if (DYNAMIC_PARAMS_RE.test(content)) {
      files.push(fullPath);
    }
    DYNAMIC_PARAMS_RE.lastIndex = 0;
  }

  return files;
}

function collectServerRuntimeOnlyFiles(dir) {
  const files = [];

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectServerRuntimeOnlyFiles(fullPath));
      continue;
    }

    if (!['middleware.ts', 'proxy.ts', 'route.ts', 'route.tsx'].includes(entry.name)) continue;

    const content = readFileSync(fullPath, 'utf8');
    if (SERVER_RUNTIME_ONLY_RE.test(content)) {
      files.push(fullPath);
    }
  }

  return files;
}

function nextBin(projectRoot) {
  return join(projectRoot, 'node_modules', 'next', 'dist', 'bin', 'next');
}

function createStaticBuildWorkspace() {
  const workspace = join(dirname(ROOT), STATIC_BUILD_WORKSPACE_NAME);
  removeGeneratedPath(workspace, STATIC_BUILD_WORKSPACE_NAME, dirname(ROOT));
  mkdirSync(workspace);
  const projectRoot = join(workspace, 'nextjs');

  cpSync(ROOT, projectRoot, {
    recursive: true,
    filter(sourcePath) {
      const relativePath = relative(ROOT, sourcePath);
      if (!relativePath) return true;

      const pathParts = relativePath.split(sep);
      if (EXCLUDED_BUILD_ENTRIES.has(pathParts[0])) return false;
      // Tailwind scans every file of the project, so another theme's classes would end up in this
      // theme's CSS. Only the selected theme source goes into the build workspace.
      if (pathParts[0] === 'themes' && pathParts.length > 1 && pathParts[1] !== THEME_SOURCE) return false;
      // Specs named tests/<theme>-*.spec.ts import that theme's source, which is not in this workspace.
      if (pathParts[0] === 'tests' && pathParts.length > 1 && OTHER_THEME_SOURCES.some((name) => pathParts[1].startsWith(`${name}-`))) return false;
      if (pathParts[0].startsWith('.next-local-smoke-')) return false;
      if (pathParts.length === 1 && pathParts[0].startsWith('.env')) return false;
      return true;
    },
  });

  // tsconfig.json points "@g5-theme/*" at the default theme (for the editor and `tsc`); the build
  // workspace only holds the selected theme, so the type check there has to look in that folder.
  const workspaceTsconfig = join(projectRoot, 'tsconfig.json');
  if (THEME_SOURCE !== 'default' && existsSync(workspaceTsconfig)) {
    writeFileSync(
      workspaceTsconfig,
      readFileSync(workspaceTsconfig, 'utf8').replace('./themes/default/*', `./themes/${THEME_SOURCE}/*`)
    );
  }

  // A theme's own public files (icons, og image, ...) replace the app's.
  const themePublic = join(ROOT, 'themes', THEME_SOURCE, 'public');
  if (existsSync(themePublic)) cpSync(themePublic, join(projectRoot, 'public'), { recursive: true });

  symlinkSync(
    join(ROOT, 'node_modules'),
    join(projectRoot, 'node_modules'),
    process.platform === 'win32' ? 'junction' : 'dir'
  );

  return { projectRoot, workspace };
}

function removeGeneratedPath(path, expectedPrefix, expectedParent = ROOT) {
  const absolutePath = resolve(path);
  if (dirname(absolutePath) !== resolve(expectedParent) || !basename(absolutePath).startsWith(expectedPrefix)) {
    throw new Error(`Refusing to remove a path outside the generated output area: ${absolutePath}`);
  }

  if (!existsSync(absolutePath)) return;
  if (lstatSync(absolutePath).isSymbolicLink()) {
    throw new Error(`Refusing to remove a generated output symlink: ${absolutePath}`);
  }

  rmSync(absolutePath, { recursive: true, force: true });
}

function publishStaticExport(sourceRoot) {
  const exportRoot = resolve(sourceRoot, NEXT_DIST_DIR);
  if (!exportRoot.startsWith(`${resolve(sourceRoot)}${sep}`)) {
    throw new Error(`Static export directory must stay inside the build workspace: ${exportRoot}`);
  }
  const exportPage = join(exportRoot, 'index.html');
  if (!existsSync(exportPage)) {
    throw new Error(`Static export is missing its index page: ${exportPage}`);
  }

  const destination = join(ROOT, 'out');
  const staging = join(ROOT, `.out-theme-build-${randomUUID()}`);
  const backup = join(ROOT, `.out-theme-backup-${randomUUID()}`);
  const expectedParent = resolve(ROOT);

  for (const path of [destination, staging, backup]) {
    if (dirname(resolve(path)) !== expectedParent) {
      throw new Error(`Refusing to replace an output outside the Next.js project: ${path}`);
    }
  }

  if (existsSync(destination)) {
    const destinationStat = lstatSync(destination);
    if (!destinationStat.isDirectory() || destinationStat.isSymbolicLink()) {
      throw new Error(`Expected a normal generated output directory: ${destination}`);
    }
  }

  try {
    cpSync(exportRoot, staging, { recursive: true });
    if (existsSync(destination)) renameSync(destination, backup);

    try {
      renameSync(staging, destination);
    } catch (error) {
      if (error?.code !== 'EPERM' || existsSync(destination)) {
        if (existsSync(backup) && !existsSync(destination)) renameSync(backup, destination);
        throw error;
      }

      try {
        cpSync(staging, destination, { recursive: true });
        if (!existsSync(join(destination, 'index.html'))) {
          throw new Error(`Static export copy is missing its index page: ${destination}`);
        }
        console.warn('[build-next] Directory rename was denied; copied the staged export instead.');
      } catch (copyError) {
        if (existsSync(destination)) removeGeneratedPath(destination, 'out');
        if (existsSync(backup) && !existsSync(destination)) renameSync(backup, destination);
        throw copyError;
      }
    }

    removeGeneratedPath(backup, '.out-theme-backup-');
    console.log(`[build-next] Published static export to ${destination}`);
  } finally {
    removeGeneratedPath(staging, '.out-theme-build-');
    if (existsSync(backup) && existsSync(destination)) {
      removeGeneratedPath(backup, '.out-theme-backup-');
    }
  }
}

const originals = new Map();
const hiddenServerOnlyRoutes = [];
let buildLockFd = null;
let buildLockOwned = false;
let buildRoot = ROOT;
let buildWorkspace = null;

function acquireBuildLock() {
  try {
    buildLockFd = openSync(BUILD_LOCK_PATH, 'wx');
    buildLockOwned = true;
    writeFileSync(
      buildLockFd,
      JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() }, null, 2)
    );
  } catch (error) {
    if (buildLockFd !== null) {
      releaseBuildLock();
    }

    if (error?.code === 'EEXIST') {
      throw new Error(
        `Build lock exists at ${BUILD_LOCK_PATH}. Another build may be running; remove it only after confirming no build is active.`
      );
    }
    throw error;
  }
}

function releaseBuildLock() {
  if (buildLockFd !== null) {
    closeSync(buildLockFd);
    buildLockFd = null;
  }

  if (buildLockOwned && existsSync(BUILD_LOCK_PATH)) {
    unlinkSync(BUILD_LOCK_PATH);
  }
  buildLockOwned = false;
}

try {
  acquireBuildLock();

  if (!SERVER_RUNTIME) {
    const workspace = createStaticBuildWorkspace();
    buildWorkspace = workspace.workspace;
    buildRoot = workspace.projectRoot;
  }

  if (!SERVER_RUNTIME) {
    for (const file of collectServerRuntimeOnlyFiles(join(buildRoot, 'src'))) {
      const disabledPath = `${file}.g5-static-disabled`;
      if (existsSync(disabledPath)) {
        throw new Error(`Refusing to hide server-only route because ${disabledPath} already exists`);
      }
      renameSync(file, disabledPath);
      hiddenServerOnlyRoutes.push([disabledPath, file]);
    }
  }

  for (const file of collectRouteFiles(join(buildRoot, 'src', 'app'))) {
    const original = readFileSync(file, 'utf8');
    const updated = original.replace(DYNAMIC_PARAMS_RE, `export const dynamicParams = ${DESIRED_DYNAMIC_PARAMS};`);

    if (updated !== original) {
      originals.set(file, original);
      writeFileSync(file, updated);
    }
    DYNAMIC_PARAMS_RE.lastIndex = 0;
  }

  console.log(
    `[build-next] G5_NEXT_RUNTIME=${SERVER_RUNTIME ? 'server' : 'static'}; dynamicParams=${DESIRED_DYNAMIC_PARAMS}${SERVER_RUNTIME ? '' : '; isolated workspace'}`
  );

  const result = spawnSync(process.execPath, [nextBin(buildRoot), 'build', ...nextBuildArguments], {
    cwd: buildRoot,
    env: BUILD_ENV,
    shell: false,
    stdio: 'inherit',
  });

  if (result.error) {
    console.error(`[build-next] ${result.error.message}`);
  }

  process.exitCode = result.status ?? 1;

  if (!result.error && result.status === 0) {
    for (const script of ['inject-sw-version.mjs', 'write-apache-static-headers.mjs']) {
      const postbuild = spawnSync(process.execPath, [join(buildRoot, 'scripts', script)], {
        cwd: buildRoot,
        env: BUILD_ENV,
        shell: false,
        stdio: 'inherit',
      });

      if (postbuild.error) {
        console.error(`[build-next] ${postbuild.error.message}`);
      }

      if (postbuild.status !== 0) {
        process.exitCode = postbuild.status ?? 1;
        break;
      }
    }

    if (!SERVER_RUNTIME && process.exitCode === 0) {
      publishStaticExport(buildRoot);
    }
  }
} finally {
  try {
    for (const [disabledPath, file] of hiddenServerOnlyRoutes.reverse()) {
      if (existsSync(disabledPath)) {
        renameSync(disabledPath, file);
      }
    }

    for (const [file, content] of originals) {
      writeFileSync(file, content);
    }
  } finally {
    try {
      releaseBuildLock();
    } finally {
      if (buildWorkspace) {
        const absoluteWorkspace = resolve(buildWorkspace);
        if (dirname(absoluteWorkspace) !== resolve(dirname(ROOT)) || basename(absoluteWorkspace) !== STATIC_BUILD_WORKSPACE_NAME) {
          throw new Error(`Refusing to remove a build workspace outside the repository workspace: ${absoluteWorkspace}`);
        }
        rmSync(absoluteWorkspace, { recursive: true, force: true });
      }
    }
  }
}
