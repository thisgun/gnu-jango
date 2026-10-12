<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit("CLI only.\n");
}

$root = dirname(__DIR__);
$script = basename((string) ($_SERVER['SCRIPT_FILENAME'] ?? ''));
$args = array_slice($argv ?? [], 1);

function smoke_should_delegate_to_legacy(): bool
{
    $target = strtolower((string) getenv('GNUBOARD5_SMOKE_TARGET'));
    if ($target === 'django') {
        return false;
    }
    if ($target === 'php' || $target === 'legacy') {
        return true;
    }

    $expectedApi = (string) getenv('LOCAL_EXPECTED_API_URL');
    if ($expectedApi !== '' && strpos($expectedApi, '127.0.0.9') === false) {
        return false;
    }

    $appUrl = (string) getenv('LOCAL_APP_URL');
    if ($appUrl !== '' && strpos($appUrl, '127.0.0.20') === false) {
        return false;
    }

    return true;
}

function smoke_run_process(array $command, string $cwd): int
{
    $escaped = array_map('escapeshellarg', $command);
    $process = proc_open(
        implode(' ', $escaped),
        [
            1 => ['pipe', 'w'],
            2 => ['pipe', 'w'],
        ],
        $pipes,
        $cwd
    );

    if (!is_resource($process)) {
        fwrite(STDERR, json_encode(['success' => false, 'message' => 'failed to start smoke helper']) . PHP_EOL);
        return 1;
    }

    $stdout = stream_get_contents($pipes[1]);
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[1]);
    fclose($pipes[2]);
    $exitCode = proc_close($process);

    $stdout = preg_replace('/^Active code page:\s*65001\s*\R?/m', '', (string) $stdout);
    if ($stdout !== '') {
        echo $stdout;
    }
    if ($stderr !== '') {
        fwrite(STDERR, $stderr);
    }

    return (int) $exitCode;
}

$legacyRoot = getenv('GNUBOARD5_SMOKE_SCRIPT_ROOT') ?: 'C:\\xampp824\\www\\gnuboard5_3';
$legacyScript = $legacyRoot . DIRECTORY_SEPARATOR . 'scripts' . DIRECTORY_SEPARATOR . $script;
if (
    smoke_should_delegate_to_legacy()
    && is_file($legacyScript)
    && realpath($legacyScript) !== realpath((string) ($_SERVER['SCRIPT_FILENAME'] ?? ''))
) {
    exit(smoke_run_process(array_merge([PHP_BINARY, $legacyScript], $args), $legacyRoot));
}

$python = getenv('PYTHON');
if (!$python) {
    $candidate = $root . DIRECTORY_SEPARATOR . '.venv314' . DIRECTORY_SEPARATOR . 'Scripts' . DIRECTORY_SEPARATOR . 'python.exe';
    $python = is_file($candidate) ? $candidate : 'python';
}

$djangoArgs = [];
$extraArgs = [];
foreach ($args as $arg) {
    if (in_array($arg, ['--json', '--admin', '--force'], true)) {
        $djangoArgs[] = $arg;
    } else {
        $extraArgs[] = $arg;
    }
}
$command = array_merge(
    [$python, $root . DIRECTORY_SEPARATOR . 'manage.py', 'nextjs_smoke', '--script=' . $script],
    $djangoArgs,
    $extraArgs ? ['--'] : [],
    $extraArgs
);
exit(smoke_run_process($command, $root));
