<#
.SYNOPSIS
  Keeps the NINFA API, web app and worker running on the Windows pilot PC.

.DESCRIPTION
  One Windows Task Scheduler task ("NINFA Pilot Runtime") runs `ninfa-runtime.ps1 run`, a small
  supervisor that:
    - waits for PostgreSQL, then starts the API, the worker and the web app (in that order);
    - restarts any of them that exits, after a delay that doubles while it keeps failing
      (5 s, 10 s, 20 s ... capped at 120 s; a run of 2 minutes or more resets it);
    - never starts a duplicate: one supervisor at a time (named mutex), and a port or a worker
      that is already there and was NOT started by the supervisor is reported, never replaced;
    - writes one log file pair per process under <runtime>\logs and its own state (PIDs) to
      <runtime>\state.json.
  <runtime> is %LOCALAPPDATA%\NINFA\runtime (override: NINFA_RUNTIME_DIR). Nothing is written to
  %TEMP% or to the repository.

  It supervises the checkout it was installed from. It changes no business logic, no scheduler and
  no database setting: it only starts the same three commands that `npm run dev:api`,
  `npm run dev:worker` and `npm run dev:web` start, and restarts them if they die.

.PARAMETER Command
  install    copy this script to <runtime>\bin and register the task, then start it.
             Default trigger: at user logon (no administrator needed).
             -Startup: at Windows start, whether anyone is logged on or not (needs administrator:
             Windows shows a confirmation prompt).
  uninstall  stop everything and remove the task. Logs are kept unless -PurgeLogs.
  start      start the supervisor (through the task).
  stop       stop the supervisor and the three processes it started.
  restart    stop + start; or restart one process: restart api | web | worker.
  status     what is running, PIDs, restarts, health, log locations. Exit code 0 = all up.
  run        the supervisor itself (what the task runs; not meant to be typed).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 install
  powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 status
  powershell -ExecutionPolicy Bypass -File scripts\windows\ninfa-runtime.ps1 restart api
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'start', 'stop', 'restart', 'status', 'run')]
    [string]$Command = 'status',

    [Parameter(Position = 1)]
    [ValidateSet('all', 'api', 'web', 'worker')]
    [string]$Component = 'all',

    # install: the checkout to supervise (default: the checkout this script lives in)
    [string]$RepoRoot,
    # install: start at Windows boot instead of at logon (needs administrator)
    [switch]$Startup,
    # uninstall: also delete the logs
    [switch]$PurgeLogs
)

$ErrorActionPreference = 'Stop'

# ---- policy ----------------------------------------------------------------------------------------
$TaskName = 'NINFA Pilot Runtime'
$MutexName = 'Global\NINFA-Pilot-Runtime'
$BackoffStartSeconds = 5     # first restart after a failure
$BackoffMaxSeconds = 120     # cap: never hammer, never give up
$StableAfterSeconds = 120    # a run this long counts as healthy and clears the failure count
$LoopSeconds = 2
$StateRefreshSeconds = 15
$DbWaitSeconds = 180
$StartSpacingSeconds = 3
$KeepAliveMinutes = 5        # Windows tries to start the task this often (ignored while it runs)
$ArchiveKeep = 30            # archived logs kept per process
$SupervisorLogMaxBytes = 5MB

# ---- locations -------------------------------------------------------------------------------------
function Resolve-RuntimeDir {
    if ($env:NINFA_RUNTIME_DIR) { return $env:NINFA_RUNTIME_DIR }
    # Run from the installed copy (<runtime>\bin\ninfa-runtime.ps1): the runtime folder is its parent,
    # which does not depend on %LOCALAPPDATA% being set (a task that runs while nobody is logged on).
    $parent = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -eq 'bin' -and (Test-Path -LiteralPath (Join-Path $parent 'config.json'))) {
        return $parent
    }
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set: set NINFA_RUNTIME_DIR.' }
    return (Join-Path $env:LOCALAPPDATA 'NINFA\runtime')
}

$RuntimeDir = Resolve-RuntimeDir
$BinDir = Join-Path $RuntimeDir 'bin'
$LogDir = Join-Path $RuntimeDir 'logs'
$ArchiveDir = Join-Path $LogDir 'archive'
$ConfigFile = Join-Path $RuntimeDir 'config.json'
$StateFile = Join-Path $RuntimeDir 'state.json'
$StopFlagFile = Join-Path $RuntimeDir 'stopped.flag'
$InstalledScript = Join-Path $BinDir 'ninfa-runtime.ps1'
$SupervisorLog = Join-Path $LogDir 'supervisor.log'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# ---- small helpers ---------------------------------------------------------------------------------
function New-RuntimeDirectories {
    foreach ($dir in @($RuntimeDir, $BinDir, $LogDir, $ArchiveDir)) {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }
}

function Write-Log {
    param([string]$Level, [string]$Message, [string]$Source = 'supervisor')
    $stamp = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffzzz')
    $line = '{0} {1,-5} [{2}] {3}' -f $stamp, $Level, $Source, $Message
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        try { [IO.File]::AppendAllText($SupervisorLog, $line + "`n", $Utf8NoBom); return } catch { Start-Sleep -Milliseconds 100 }
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Save-JsonFile {
    param([string]$Path, $Object)
    $tmp = $Path + '.tmp'
    [IO.File]::WriteAllText($tmp, ($Object | ConvertTo-Json -Depth 8), $Utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function ConvertFrom-IsoDate {
    param([string]$Text)
    return [datetime]::Parse($Text, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
}

# `stop` leaves a flag so that the keep-alive trigger does not undo it. It lasts until `start`, or
# until the next Windows boot (a reboot always brings NINFA back: a lost day cannot be recovered).
function Test-StopFlagActive {
    if (-not (Test-Path -LiteralPath $StopFlagFile)) { return $false }
    $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    if ((Get-Item -LiteralPath $StopFlagFile).LastWriteTime -gt $boot) { return $true }
    Remove-Item -LiteralPath $StopFlagFile -Force -ErrorAction SilentlyContinue
    return $false
}

function Test-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-Node {
    $found = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $default = 'C:\Program Files\nodejs\node.exe'
    if (Test-Path -LiteralPath $default) { return $default }
    throw 'node.exe was not found (looked on PATH and in C:\Program Files\nodejs).'
}

function Get-EnvFileValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in [IO.File]::ReadLines($Path)) {
        $text = $line.Trim()
        if ($text.Length -eq 0 -or $text.StartsWith('#')) { continue }
        $eq = $text.IndexOf('=')
        if ($eq -lt 1) { continue }
        if ($text.Substring(0, $eq).Trim() -eq $Key) { return $text.Substring($eq + 1).Trim().Trim('"').Trim("'") }
    }
    return $null
}

# The process environment wins over .env, exactly as apps/web/scripts/run-next.mjs and the API do.
function Get-Setting {
    param([string]$Root, [string]$Key, $Default = $null)
    $fromProcess = [Environment]::GetEnvironmentVariable($Key, 'Process')
    if ($fromProcess) { return $fromProcess }
    $fromFile = Get-EnvFileValue (Join-Path $Root '.env') $Key
    if ($null -ne $fromFile -and $fromFile -ne '') { return $fromFile }
    return $Default
}

function Get-RepoSettings {
    param([string]$Root)
    $settings = @{ RepoRoot = $Root }
    $settings.ApiHost = [string](Get-Setting $Root 'API_HOST' '127.0.0.1')
    $settings.ApiPort = [int](Get-Setting $Root 'API_PORT' 8000)
    $settings.WebHost = [string](Get-Setting $Root 'WEB_HOST' '127.0.0.1')
    $settings.WebPort = [int](Get-Setting $Root 'WEB_PORT' 3100)
    $settings.AppEnv = [string](Get-Setting $Root 'APP_ENV' 'development')
    $settings.CookieConfigured = ($null -ne (Get-Setting $Root 'SESSION_COOKIE_SECURE' $null))
    $settings.DbHost = '127.0.0.1'
    $settings.DbPort = 5432
    $url = [string](Get-Setting $Root 'DATABASE_URL' '')
    if ($url -match '.*@(?<h>[^@:/]+)(:(?<p>\d+))?/') {
        $settings.DbHost = $Matches['h']
        if ($Matches['p']) { $settings.DbPort = [int]$Matches['p'] }
    }
    return $settings
}

function ConvertTo-ProbeHost {
    param([string]$HostName)
    if ($HostName -eq '0.0.0.0' -or $HostName -eq '::') { return '127.0.0.1' }
    return $HostName
}

function Test-TcpPort {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 700)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch { return $false } finally { $client.Close() }
}

function Get-HttpStatus {
    param([string]$Url, [int]$TimeoutSec = 10)
    try { return [int](Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec).StatusCode }
    catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return 0
    }
}

# ---- processes: identity is PID + start time, never a name or a command-line pattern -----------------
function Test-ProcessIdentity {
    param($ProcessId, $StartIso)
    if (-not $ProcessId -or -not $StartIso) { return $false }
    $process = Get-Process -Id ([int]$ProcessId) -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    try { return ([math]::Abs(($process.StartTime - (ConvertFrom-IsoDate $StartIso)).TotalSeconds) -lt 2) } catch { return $false }
}

# Stops a process we started and everything it started (the venv python and `node run-next.mjs`
# are launchers: the real server is a child). Children are found by parent PID + creation time,
# so they are found even after the launcher is gone. Returns how many processes were stopped.
function Stop-ProcessTree {
    param([int]$RootPid, [datetime]$RootStart)
    $root = Get-Process -Id $RootPid -ErrorAction SilentlyContinue
    $rootAlive = $false
    if ($root) {
        try { if ([math]::Abs(($root.StartTime - $RootStart).TotalSeconds) -ge 2) { return 0 } } catch { return 0 }  # PID reused by a stranger
        $rootAlive = $true
    }
    $table = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, CreationDate)
    $ids = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([pscustomobject]@{ Id = $RootPid; Start = $RootStart })
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($row in $table) {
            if ($null -eq $row.CreationDate) { continue }
            if ([int]$row.ParentProcessId -eq $current.Id -and $row.CreationDate -ge $current.Start.AddSeconds(-2) -and -not $ids.Contains([int]$row.ProcessId)) {
                $ids.Add([int]$row.ProcessId)
                $queue.Enqueue([pscustomobject]@{ Id = [int]$row.ProcessId; Start = [datetime]$row.CreationDate })
            }
        }
    }
    $stopped = 0
    for ($i = $ids.Count - 1; $i -ge 0; $i--) {
        try { Stop-Process -Id $ids[$i] -Force -ErrorAction Stop; $stopped++ } catch { }
    }
    if ($rootAlive) { try { Stop-Process -Id $RootPid -Force -ErrorAction Stop; $stopped++ } catch { } }
    return $stopped
}

function Get-TreeSummary {
    param([int]$RootPid, [datetime]$RootStart)
    $table = @(Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, CreationDate)
    $found = @()
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([pscustomobject]@{ Id = $RootPid; Start = $RootStart })
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($row in $table) {
            if ($null -eq $row.CreationDate) { continue }
            if ([int]$row.ParentProcessId -eq $current.Id -and $row.CreationDate -ge $current.Start.AddSeconds(-2)) {
                $found += [pscustomobject]@{ Pid = [int]$row.ProcessId; Name = $row.Name }
                $queue.Enqueue([pscustomobject]@{ Id = [int]$row.ProcessId; Start = [datetime]$row.CreationDate })
            }
        }
    }
    return $found
}

# ---- logs ------------------------------------------------------------------------------------------
function Move-LogToArchive {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if ((Get-Item -LiteralPath $Path).Length -eq 0) { Remove-Item -LiteralPath $Path -Force; return }
    $base = [IO.Path]::GetFileNameWithoutExtension($Path)
    $target = Join-Path $ArchiveDir ('{0}-{1}.log' -f $base, (Get-Date).ToString('yyyyMMdd-HHmmss'))
    Move-Item -LiteralPath $Path -Destination $target -Force
    Get-ChildItem -LiteralPath $ArchiveDir -Filter ($base + '-*.log') |
        Sort-Object LastWriteTime -Descending | Select-Object -Skip $ArchiveKeep |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Get-LogTail {
    param([string]$Path, [int]$Lines)
    try {
        if (Test-Path -LiteralPath $Path) { return ((Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction Stop) -join ' | ') }
    } catch { }
    return ''
}

function Limit-Text {
    param([string]$Text, [int]$Max = 700)
    if ($Text.Length -le $Max) { return $Text }
    return $Text.Substring($Text.Length - $Max)
}

# ---- the three components --------------------------------------------------------------------------
function New-Components {
    param($Settings)
    $root = $Settings.RepoRoot
    $venvPython = Join-Path $root '.venv\Scripts\python.exe'
    $runNext = Join-Path $root 'apps\web\scripts\run-next.mjs'
    $node = Resolve-Node
    $apiHost = ConvertTo-ProbeHost $Settings.ApiHost
    $webHost = ConvertTo-ProbeHost $Settings.WebHost

    # A plain-HTTP loopback dev server needs the session cookie without the Secure flag, or the
    # browser drops it (docs/development/local-development.md). Only for the API, only when the
    # operator has not decided it (environment or .env), and never when APP_ENV is production.
    $apiEnv = @{ PYTHONUNBUFFERED = '1' }
    if (-not $Settings.CookieConfigured -and $Settings.AppEnv -ne 'production') { $apiEnv['SESSION_COOKIE_SECURE'] = 'false' }

    $list = @(
        @{ Name = 'api'; Exe = $venvPython; Args = '-m app'; Env = $apiEnv; ProbeHost = $apiHost; Port = $Settings.ApiPort; Url = ('http://{0}:{1}/api/v1/health' -f $apiHost, $Settings.ApiPort) },
        @{ Name = 'worker'; Exe = $venvPython; Args = '-m worker run'; Env = @{ PYTHONUNBUFFERED = '1' }; ProbeHost = ''; Port = 0; Url = '' },
        @{ Name = 'web'; Exe = $node; Args = ('"{0}" dev' -f $runNext); Env = @{}; ProbeHost = $webHost; Port = $Settings.WebPort; Url = ('http://{0}:{1}/' -f $webHost, $Settings.WebPort) }
    )
    $index = 0
    foreach ($c in $list) {
        $c.Proc = $null
        $c.LauncherStart = [datetime]::MinValue
        $c.StartedAt = $null
        $c.State = 'waiting'
        $c.Message = ''
        $c.Starts = 0
        $c.Restarts = 0
        $c.Failures = 0
        $c.LastExitCode = $null
        $c.LastExitAt = $null
        $c.ManualRestart = $false
        $c.NextStartAt = (Get-Date).AddSeconds($index * $StartSpacingSeconds)
        $index++
    }
    return $list
}

# Something that serves this component already exists and is not ours: starting a second one
# would either crash on the port or run two workers. Report it, do not kill it.
function Find-ForeignInstance {
    param($C)
    if ($C.Port -gt 0) {
        if (Test-TcpPort $C.ProbeHost $C.Port) { return ('port {0} already answers and was not started by this supervisor' -f $C.Port) }
        return $null
    }
    $others = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
            $_.CommandLine -and $_.CommandLine.IndexOf($C.Exe, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine.Contains('-m worker run')
        })
    if ($others.Count -gt 0) { return ('a worker of this checkout is already running (pid {0}) and was not started by this supervisor' -f $others[0].ProcessId) }
    return $null
}

function Start-Component {
    param($C, $Settings)
    $out = Join-Path $LogDir ($C.Name + '.out.log')
    $err = Join-Path $LogDir ($C.Name + '.err.log')
    Move-LogToArchive $out
    Move-LogToArchive $err
    $saved = @{}
    foreach ($key in @($C.Env.Keys)) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $C.Env[$key], 'Process')
    }
    try {
        $process = Start-Process -FilePath $C.Exe -ArgumentList $C.Args -WorkingDirectory $Settings.RepoRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        $null = $process.Handle    # keep the handle: ExitCode is readable after the process has gone
    } finally {
        foreach ($key in @($saved.Keys)) { [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process') }
    }
    if ($C.Starts -gt 0) { $C.Restarts++ }
    $C.Starts++
    $C.Proc = $process
    $C.LauncherStart = $process.StartTime
    $C.StartedAt = Get-Date
    $C.State = 'running'
    $C.Message = ''
    Write-Log INFO ('{0} started: launcher pid {1} (start #{2}); logs {0}.out.log / {0}.err.log' -f $C.Name, $process.Id, $C.Starts)
}

function Update-Component {
    param($C, $Settings)
    $flag = Join-Path $RuntimeDir ('restart-{0}.flag' -f $C.Name)
    if (Test-Path -LiteralPath $flag) {
        Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
        $C.ManualRestart = $true
        Write-Log INFO ('{0}: restart requested by an operator' -f $C.Name)
        if (-not $C.Proc) { $C.Failures = 0; $C.NextStartAt = Get-Date }
    }

    if ($C.Proc) {
        if (-not $C.Proc.HasExited) { $C.State = 'running'; return }
        $code = $C.Proc.ExitCode
        $ran = (Get-Date) - $C.StartedAt
        $tail = Limit-Text ((Get-LogTail (Join-Path $LogDir ($C.Name + '.err.log')) 4) + ' || ' + (Get-LogTail (Join-Path $LogDir ($C.Name + '.out.log')) 2))
        Write-Log WARN ('{0} exited: launcher pid {1}, exit code {2}, ran {3}s. Last log lines: {4}' -f $C.Name, $C.Proc.Id, $code, [int]$ran.TotalSeconds, $tail)
        $left = Stop-ProcessTree -RootPid $C.Proc.Id -RootStart $C.LauncherStart
        if ($left -gt 0) { Write-Log WARN ('{0}: stopped {1} leftover process(es) of the exited launcher, so no duplicate can start' -f $C.Name, $left) }
        $C.LastExitCode = $code
        $C.LastExitAt = Get-Date
        $C.Proc = $null
        if ($C.ManualRestart -or $ran.TotalSeconds -ge $StableAfterSeconds) { $C.Failures = 0 }
        if ($C.ManualRestart) {
            $delay = 0
            $C.ManualRestart = $false
        } else {
            $delay = [math]::Min($BackoffStartSeconds * [math]::Pow(2, $C.Failures), $BackoffMaxSeconds)
            $C.Failures++
        }
        $C.NextStartAt = (Get-Date).AddSeconds($delay)
        $C.State = 'backoff'
        Write-Log INFO ('{0}: restart in {1}s' -f $C.Name, [int]$delay)
        return
    }

    if ((Get-Date) -lt $C.NextStartAt) { return }
    $foreign = Find-ForeignInstance $C
    if ($foreign) {
        if ($C.Message -ne $foreign) { Write-Log WARN ('{0}: NOT started: {1}; checking again every 30s' -f $C.Name, $foreign) }
        $C.State = 'blocked'
        $C.Message = $foreign
        $C.NextStartAt = (Get-Date).AddSeconds(30)
        return
    }
    $C.ManualRestart = $false
    try {
        Start-Component $C $Settings
    } catch {
        # A failed start (for example a log file still held open) backs off like any other failure.
        $delay = [math]::Min($BackoffStartSeconds * [math]::Pow(2, $C.Failures), $BackoffMaxSeconds)
        $C.Failures++
        $C.NextStartAt = (Get-Date).AddSeconds($delay)
        $C.State = 'backoff'
        $C.Message = 'start failed: ' + $_.Exception.Message
        Write-Log ERROR ('{0}: could not start: {1}; trying again in {2}s' -f $C.Name, $_.Exception.Message, [int]$delay)
    }
}

function Save-SupervisorState {
    param($Components, $Settings, [datetime]$StartedAt)
    $comp = [ordered]@{}
    foreach ($c in $Components) {
        $comp[$c.Name] = [ordered]@{
            state = $c.State
            message = $c.Message
            launcherPid = $(if ($c.Proc) { $c.Proc.Id } else { $null })
            launcherStart = $(if ($c.Proc) { $c.LauncherStart.ToString('o') } else { $null })
            startedAt = $(if ($c.StartedAt) { $c.StartedAt.ToString('o') } else { $null })
            starts = $c.Starts
            restarts = $c.Restarts
            consecutiveFailures = $c.Failures
            lastExitCode = $c.LastExitCode
            lastExitAt = $(if ($c.LastExitAt) { $c.LastExitAt.ToString('o') } else { $null })
            nextStartAt = $(if ($c.State -eq 'backoff' -or $c.State -eq 'blocked' -or $c.State -eq 'waiting') { $c.NextStartAt.ToString('o') } else { $null })
        }
    }
    $self = Get-Process -Id $PID
    Save-JsonFile $StateFile ([ordered]@{
            supervisor = [ordered]@{
                pid = $PID
                start = $self.StartTime.ToString('o')
                startedAt = $StartedAt.ToString('o')
                updatedAt = (Get-Date).ToString('o')
            }
            repoRoot = $Settings.RepoRoot
            components = $comp
        })
}

function Remove-LeftoversFromPreviousRun {
    $old = Read-JsonFile $StateFile
    if (-not $old -or -not $old.components) { return }
    foreach ($name in @($old.components.PSObject.Properties.Name)) {
        $c = $old.components.$name
        if ($c.launcherPid -and $c.launcherStart) {
            $stopped = Stop-ProcessTree -RootPid ([int]$c.launcherPid) -RootStart (ConvertFrom-IsoDate $c.launcherStart)
            if ($stopped -gt 0) { Write-Log WARN ('{0}: stopped {1} leftover process(es) of a previous supervisor run' -f $name, $stopped) }
        }
    }
}

function Wait-ForDatabase {
    param($Settings)
    $deadline = (Get-Date).AddSeconds($DbWaitSeconds)
    $announced = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort $Settings.DbHost $Settings.DbPort 1000) {
            Write-Log INFO ('PostgreSQL answers on {0}:{1}' -f $Settings.DbHost, $Settings.DbPort)
            return
        }
        if (-not $announced) { Write-Log INFO ('waiting for PostgreSQL on {0}:{1}' -f $Settings.DbHost, $Settings.DbPort); $announced = $true }
        Start-Sleep -Seconds 3
    }
    Write-Log WARN ('PostgreSQL did not answer within {0}s: starting anyway, every process retries by itself' -f $DbWaitSeconds)
}

# ---- run: the supervisor ---------------------------------------------------------------------------
function Invoke-Supervisor {
    New-RuntimeDirectories
    if (Test-StopFlagActive) { return 0 }    # stopped by an operator: the keep-alive trigger must not undo it
    if ((Test-Path -LiteralPath $SupervisorLog) -and (Get-Item -LiteralPath $SupervisorLog).Length -gt $SupervisorLogMaxBytes) {
        Move-LogToArchive $SupervisorLog
    }
    $mutex = New-Object System.Threading.Mutex($false, $MutexName)
    $owned = $false
    try { $owned = $mutex.WaitOne(0) }
    catch {
        if ($_.Exception -is [System.Threading.AbandonedMutexException] -or $_.Exception.InnerException -is [System.Threading.AbandonedMutexException]) { $owned = $true }
        else { throw }
    }
    if (-not $owned) {
        $other = Read-JsonFile $StateFile
        $otherPid = if ($other -and $other.supervisor) { $other.supervisor.pid } else { 'unknown' }
        Write-Log WARN ('another supervisor is already running (pid {0}): this one exits, nothing is started twice' -f $otherPid)
        return 0
    }

    try {
        $config = Read-JsonFile $ConfigFile
        if (-not $config -or -not $config.repoRoot) { throw "no config at ${ConfigFile}: run 'install' first" }
        $settings = Get-RepoSettings ([string]$config.repoRoot)
        Write-Log INFO ('supervisor started: pid {0}, checkout {1}, PowerShell {2}' -f $PID, $settings.RepoRoot, $PSVersionTable.PSVersion)
        Remove-LeftoversFromPreviousRun
        $components = New-Components $settings
        Wait-ForDatabase $settings
        $startedAt = Get-Date
        $lastSave = [datetime]::MinValue
        $lastDigest = ''
        try {
            while ($true) {
                foreach ($c in $components) {
                    try { Update-Component $c $settings }
                    catch {
                        Write-Log ERROR ('{0}: supervision error: {1}' -f $c.Name, $_.Exception.Message)
                        if (-not $c.Proc) { $c.NextStartAt = (Get-Date).AddSeconds(10) }    # never a tight error loop
                    }
                }
                $digest = (($components | ForEach-Object { '{0}:{1}:{2}' -f $_.Name, $_.State, $(if ($_.Proc) { $_.Proc.Id } else { 0 }) }) -join ';')
                if ($digest -ne $lastDigest -or ((Get-Date) - $lastSave).TotalSeconds -ge $StateRefreshSeconds) {
                    try { Save-SupervisorState $components $settings $startedAt } catch { Write-Log ERROR ('cannot save state: ' + $_.Exception.Message) }
                    $lastDigest = $digest
                    $lastSave = Get-Date
                }
                Start-Sleep -Seconds $LoopSeconds
            }
        } finally {
            Write-Log INFO 'supervisor stopping: stopping the processes it started'
            foreach ($c in $components) {
                if ($c.Proc) { $null = Stop-ProcessTree -RootPid $c.Proc.Id -RootStart $c.LauncherStart }
            }
            Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
        }
    } finally {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}

# ---- control commands ------------------------------------------------------------------------------
function Get-InstalledTask {
    return (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)
}

function Get-LiveState {
    $state = Read-JsonFile $StateFile
    if ($state -and $state.supervisor -and (Test-ProcessIdentity $state.supervisor.pid $state.supervisor.start)) { return $state }
    return $null
}

function Resolve-RepoRoot {
    if ($RepoRoot) { return [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\') }
    if ((Split-Path -Leaf $PSScriptRoot) -eq 'windows' -and (Split-Path -Leaf (Split-Path -Parent $PSScriptRoot)) -eq 'scripts') {
        return [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')).TrimEnd('\')
    }
    $config = Read-JsonFile $ConfigFile
    if ($config -and $config.repoRoot) { return [string]$config.repoRoot }
    throw 'Cannot tell which checkout to supervise: pass -RepoRoot <path to the NINFA checkout>.'
}

function Assert-RepoRoot {
    param([string]$Root)
    $required = @('.venv\Scripts\python.exe', 'apps\web\scripts\run-next.mjs', '.env')
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $relative))) { throw "Not a ready NINFA checkout: $Root\$relative is missing." }
    }
}

function Register-RuntimeTask {
    $me = '{0}\{1}' -f $env:USERDOMAIN, $env:USERNAME
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $argument = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" run' -f $InstalledScript
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $argument -WorkingDirectory $RuntimeDir
    if ($Startup) {
        $start = New-ScheduledTaskTrigger -AtStartup
        $start.Delay = 'PT30S'
        $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType S4U -RunLevel Limited
    } else {
        $start = New-ScheduledTaskTrigger -AtLogOn -User $me
        $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    }
    # Keep-alive: every few minutes Windows tries to start the task. While the supervisor runs that is
    # ignored (MultipleInstances IgnoreNew); if the supervisor itself was killed or crashed, this brings
    # it back, and it cleans up whatever it left running. (Measured: the task's own "restart on failure"
    # setting does NOT restart a killed process, so it is not relied upon.)
    $keepAlive = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $KeepAliveMinutes)
    # No run-time limit (the default would end the task after 72 h).
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    # -Force replaces an existing task in one step: a failed registration leaves the old task untouched.
    $null = Register-ScheduledTask -TaskName $TaskName -Force -Action $action -Trigger @($start, $keepAlive) -Settings $settings -Principal $principal `
        -Description 'Keeps the NINFA API, web app and worker running (supervisor: restarts them if they exit). Remove with: ninfa-runtime.ps1 uninstall'
}

function Invoke-Stop {
    if (Test-Path -LiteralPath $RuntimeDir) {
        [IO.File]::WriteAllText($StopFlagFile, (Get-Date).ToString('o'), $Utf8NoBom)    # first, so the keep-alive cannot race the stop
    }
    $task = Get-InstalledTask
    if ($task -and $task.State -eq 'Running') {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Log INFO 'stop: the task was stopped' 'control'
    }
    $state = Read-JsonFile $StateFile
    if ($state) {
        # A supervisor started by hand (not through the task), found by its recorded identity.
        if ($state.supervisor -and (Test-ProcessIdentity $state.supervisor.pid $state.supervisor.start)) {
            Stop-Process -Id ([int]$state.supervisor.pid) -Force -ErrorAction SilentlyContinue
            Write-Log INFO ('stop: supervisor pid {0} stopped' -f $state.supervisor.pid) 'control'
        }
        # Whatever it left running, by recorded PID + start time.
        if ($state.components) {
            foreach ($name in @($state.components.PSObject.Properties.Name)) {
                $c = $state.components.$name
                if ($c.launcherPid -and $c.launcherStart) {
                    $stopped = Stop-ProcessTree -RootPid ([int]$c.launcherPid) -RootStart (ConvertFrom-IsoDate $c.launcherStart)
                    if ($stopped -gt 0) { Write-Log INFO ('stop: {0}: {1} process(es) stopped' -f $name, $stopped) 'control' }
                }
            }
        }
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Start {
    if (-not (Get-InstalledTask)) { throw "The task '$TaskName' is not installed: run 'ninfa-runtime.ps1 install' first." }
    Remove-Item -LiteralPath $StopFlagFile -Force -ErrorAction SilentlyContinue
    if (Get-LiveState) { Write-Host 'The supervisor is already running (nothing was started twice).'; Show-Status | Out-Null; return }
    Start-ScheduledTask -TaskName $TaskName
    Write-Log INFO 'start: task started' 'control'
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        $state = Get-LiveState
        if ($state -and @($state.components.PSObject.Properties | Where-Object { $_.Value.state -ne 'running' }).Count -eq 0) { break }
        Start-Sleep -Seconds 2
    }
    $null = Show-Status
}

function Invoke-RestartComponent {
    param([string]$Name)
    $state = Get-LiveState
    if (-not $state) { throw "The supervisor is not running: use 'start' (or 'restart' without a name)." }
    $before = $state.components.$Name.launcherPid
    # The flag first: the supervisor then restarts at once, without counting this as a failure.
    [IO.File]::WriteAllText((Join-Path $RuntimeDir ('restart-{0}.flag' -f $Name)), (Get-Date).ToString('o'), $Utf8NoBom)
    $c = $state.components.$Name
    if ($c.launcherPid -and $c.launcherStart) {
        $null = Stop-ProcessTree -RootPid ([int]$c.launcherPid) -RootStart (ConvertFrom-IsoDate $c.launcherStart)
    }
    Write-Log INFO ('restart {0}: requested (launcher pid was {1})' -f $Name, $before) 'control'
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $now = (Read-JsonFile $StateFile).components.$Name
        if ($now.state -eq 'running' -and $now.launcherPid -and $now.launcherPid -ne $before) { break }
    }
    $null = Show-Status
}

function Show-Status {
    $ok = $true
    Write-Host ('NINFA pilot runtime   runtime folder: {0}' -f $RuntimeDir)
    $task = Get-InstalledTask
    if (-not $task) {
        Write-Host ("Task:        NOT INSTALLED ('{0}')" -f $TaskName)
        $ok = $false
    } else {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        $triggers = if ($task.Triggers.Count -gt 0) { (@($task.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace '^MSFT_Task', '' -replace 'Trigger$', '' }) -join ' + ') } else { 'none' }
        $result = [uint32]$info.LastTaskResult
        $resultText = switch ($result) {
            0 { 'ok' }
            267009 { 'running' }
            2147946720 { 'keep-alive ignored because it is already running (normal)' }
            4294967295 { 'ended by a stop or a kill' }
            default { '0x{0:X}' -f $result }
        }
        Write-Host ('Task:        {0}   state={1}   triggers={2}   runs as {3} ({4})   last result: {5}' -f $TaskName, $task.State, $triggers, $task.Principal.UserId, $task.Principal.LogonType, $resultText)
    }
    $state = Get-LiveState
    if (-not $state) {
        if (Test-StopFlagActive) { Write-Host 'Supervisor:  STOPPED BY AN OPERATOR (on purpose: run start, or reboot Windows, to resume)' }
        else { Write-Host 'Supervisor:  NOT RUNNING' }
        $ok = $false
    } else {
        $age = [int]((Get-Date) - (ConvertFrom-IsoDate $state.supervisor.updatedAt)).TotalSeconds
        Write-Host ('Supervisor:  running, pid {0}, since {1}, state updated {2}s ago{3}' -f $state.supervisor.pid, (ConvertFrom-IsoDate $state.supervisor.startedAt).ToString('yyyy-MM-dd HH:mm:ss'), $age, $(if ($age -gt 60) { '  <-- STALE' } else { '' }))
        Write-Host ('Checkout:    {0}' -f $state.repoRoot)
        $settings = Get-RepoSettings ([string]$state.repoRoot)
        foreach ($name in @('api', 'worker', 'web')) {
            $c = $state.components.$name
            $line = '  {0,-7} {1,-8}' -f $name, $c.state
            if ($c.launcherPid -and (Test-ProcessIdentity $c.launcherPid $c.launcherStart)) {
                $tree = @(Get-TreeSummary ([int]$c.launcherPid) (ConvertFrom-IsoDate $c.launcherStart) | Where-Object { $_.Name -ne 'conhost.exe' })
                $children = ($tree | ForEach-Object { '{0} {1}' -f $_.Pid, ($_.Name -replace '\.exe$', '') }) -join ', '
                $up = [int]((Get-Date) - (ConvertFrom-IsoDate $c.startedAt)).TotalSeconds
                $line += ' launcher {0}; server {1}   up {2}s   restarts {3}' -f $c.launcherPid, $children, $up, $c.restarts
            } else {
                $line += ' (no live process)   restarts {0}' -f $c.restarts
                $ok = $false
            }
            if ($null -ne $c.lastExitCode) { $line += '   last exit code {0} at {1}' -f $c.lastExitCode, (ConvertFrom-IsoDate $c.lastExitAt).ToString('HH:mm:ss') }
            if ($c.message) { $line += '   NOTE: ' + $c.message }
            if ($c.state -ne 'running') { $ok = $false }
            Write-Host $line
        }
        $apiHost = ConvertTo-ProbeHost $settings.ApiHost
        $webHost = ConvertTo-ProbeHost $settings.WebHost
        $api = Get-HttpStatus ('http://{0}:{1}/api/v1/health' -f $apiHost, $settings.ApiPort) 8
        $web = Get-HttpStatus ('http://{0}:{1}/' -f $webHost, $settings.WebPort) 30
        Write-Host ('Health:      api /api/v1/health -> {0}    web / -> {1}    worker: process only (heartbeat is in the database)' -f $api, $web)
        if ($api -ne 200 -or $web -ne 200) { $ok = $false }
        if ((Test-Path -LiteralPath $InstalledScript) -and (Test-Path -LiteralPath (Join-Path $settings.RepoRoot 'scripts\windows\ninfa-runtime.ps1'))) {
            if ((Get-FileHash -LiteralPath $InstalledScript).Hash -ne (Get-FileHash -LiteralPath (Join-Path $settings.RepoRoot 'scripts\windows\ninfa-runtime.ps1')).Hash) {
                Write-Host 'Note:        the installed supervisor differs from the checkout copy: run install again to update it.'
            }
        }
    }
    Write-Host ('Logs:        {0}   (supervisor.log, api|worker|web .out.log / .err.log; older runs in logs\archive)' -f $LogDir)
    return $ok
}

function Invoke-Install {
    $root = Resolve-RepoRoot
    Assert-RepoRoot $root
    $null = Resolve-Node
    if ($Startup -and -not (Test-Admin)) {
        Write-Host 'Startup mode needs administrator rights: Windows will now ask for your confirmation.'
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" install -Startup -RepoRoot "{1}"' -f $PSCommandPath, $root
        $elevated = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        if ($elevated.ExitCode -ne 0) { throw "The elevated install failed (exit code $($elevated.ExitCode)); see $SupervisorLog." }
        $null = Show-Status
        return
    }
    New-RuntimeDirectories
    if ($PSCommandPath -ne $InstalledScript) { Copy-Item -LiteralPath $PSCommandPath -Destination $InstalledScript -Force }
    Save-JsonFile $ConfigFile ([ordered]@{
            repoRoot = $root
            trigger = $(if ($Startup) { 'startup' } else { 'logon' })
            installedAt = (Get-Date).ToString('o')
        })
    # Register first: if it fails, nothing running is touched. Only then replace the running supervisor.
    Register-RuntimeTask
    Write-Log INFO ('install: task registered, trigger={0}, checkout={1}' -f $(if ($Startup) { 'startup' } else { 'logon' }), $root) 'control'
    Write-Host ('Installed. Trigger: {0}. Supervised checkout: {1}' -f $(if ($Startup) { 'Windows start (runs whether anyone is logged on or not)' } else { 'user logon' }), $root)
    Invoke-Stop
    Invoke-Start
}

function Invoke-Uninstall {
    Invoke-Stop
    if (Get-InstalledTask) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Task '$TaskName' removed."
    } else {
        Write-Host "Task '$TaskName' was not installed."
    }
    Write-Log INFO 'uninstall: task removed' 'control'
    foreach ($path in @($ConfigFile, $StateFile, $StopFlagFile, $InstalledScript, $BinDir)) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
    if ($PurgeLogs) { Remove-Item -LiteralPath $RuntimeDir -Recurse -Force -ErrorAction SilentlyContinue; Write-Host "Runtime folder deleted: $RuntimeDir" }
    else { Write-Host "Logs kept in $LogDir (use -PurgeLogs to delete them)." }
}

# ---- dispatch --------------------------------------------------------------------------------------
switch ($Command) {
    'run' {
        try {
            $result = @(Invoke-Supervisor)
        } catch {
            # The supervisor runs hidden: whatever stops it must end up in its log. The keep-alive trigger tries again.
            if (Test-Path -LiteralPath $LogDir) { Write-Log ERROR ('supervisor stopped by an error: {0}' -f $_.Exception.Message) }
            exit 1
        }
        exit $(if ($result.Count -gt 0) { [int]$result[-1] } else { 0 })
    }
    'install' { Invoke-Install }
    'uninstall' { Invoke-Uninstall }
    'start' { Invoke-Start }
    'stop' {
        Invoke-Stop
        Write-Host 'Stopped: supervisor and the processes it started.'
    }
    'restart' {
        if ($Component -eq 'all') { Invoke-Stop; Invoke-Start } else { Invoke-RestartComponent $Component }
    }
    'status' { if (-not (Show-Status)) { exit 1 } }
}
