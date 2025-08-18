# 🔬 MCI 재난 시뮬레이션 자동화 시스템 Complete v5.0
# 작성자: 류연우 - 적대적 재난 에이전트 생성을 활용한 복합재난 대응기술개발
# 수정: 1) weighted=False 반영, 2) UI 개선 및 정리, 3) 진행상황 표시 개선, 4) 완전한 버전

param(
    [string]$ProjectPath = "",
    [switch]$SkipConfirmation
)



# UTF-8 BOM CSV Export
function Export-CsvUtf8Bom {
    param(
        [Parameter(Mandatory=$true)] $Data,
        [Parameter(Mandatory=$true)] [string] $Path
    )
    try {
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            $Data | Export-Csv -Path $Path -NoTypeInformation -Encoding utf8BOM
        } else {
            $tmp = [System.IO.Path]::GetTempFileName()
            $Data | Export-Csv -Path $tmp -NoTypeInformation -Encoding UTF8
            $bytes = [System.IO.File]::ReadAllBytes($tmp)
            $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
            if (-not $hasBom) {
                $bom = [byte[]](0xEF,0xBB,0xBF)
                $bytes = $bom + $bytes
            }
            [System.IO.File]::WriteAllBytes($Path, $bytes)
            Remove-Item $tmp -Force
        }
    } catch {
        Write-Host "❌ Export-CsvUtf8Bom 실패: $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

# YAML parser for summary (regex-based, \r?\n compliant)
function Parse-Yaml-ForSummary {
    param([string]$YamlPath)
    $text = Get-Content -Raw $YamlPath

    $patAmb = '(?ms)^\s*ambulance:\s*(?:#.*)?\r?\n(?<b>(?:^[ \t]{2,}.*(?:\r?\n|$))+)' 
    $patUav = '(?ms)^\s*uav:\s*(?:#.*)?\r?\n(?<b>(?:^[ \t]{2,}.*(?:\r?\n|$))+)' 
    $patSim = '(?ms)^\s*simulator:\s*(?:#.*)?\r?\n(?<b>(?:^[ \t]{2,}.*(?:\r?\n|$))+)' 
    $patHos = '(?ms)^\s*hospital:\s*(?:#.*)?\r?\n(?<b>(?:^[ \t]{2,}.*(?:\r?\n|$))+)' 
    $patRun = '(?ms)^\s*run_setting:\s*(?:#.*)?\r?\n(?<b>(?:^[ \t]{2,}.*(?:\r?\n|$))+)' 

    $ambV=$null; $ambH=$null
    $mAmb = [regex]::Match($text, $patAmb)
    if ($mAmb.Success) {
        $b = $mAmb.Groups['b'].Value
        if ($b -match '(?m)^\s*velocity:\s*([0-9.]+)')      { $ambV = [double]$matches[1] }
        if ($b -match '(?m)^\s*handover_time:\s*([0-9]+)')  { $ambH = [int]$matches[1] }
    }
    $uavV=$null; $uavH=$null
    $mUav = [regex]::Match($text, $patUav)
    if ($mUav.Success) {
        $b = $mUav.Groups['b'].Value
        if ($b -match '(?m)^\s*velocity:\s*([0-9.]+)')      { $uavV = [double]$matches[1] }
        if ($b -match '(?m)^\s*handover_time:\s*([0-9]+)')  { $uavH = [int]$matches[1] }
    }
    $totS=$null; $seed=$null
    $mSim = [regex]::Match($text, $patSim)
    if ($mSim.Success) {
        $b = $mSim.Groups['b'].Value
        if ($b -match '(?m)^\s*totalSamples:\s*([0-9]+)') { $totS = [int]$matches[1] }
        if ($b -match '(?m)^\s*random_seed:\s*([0-9]+)')  { $seed = [int]$matches[1] }
    }
    $maxCoeff=$null
    $mHos = [regex]::Match($text, $patHos)
    if ($mHos.Success) {
        $b = $mHos.Groups['b'].Value
        if ($b -match '(?m)^\s*max_send_coeff\s*:\s*\[?\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]?') {
            $maxCoeff = "$($matches[1]),$($matches[2])"
        }
    }
    $outPath=$null
    $mRun = [regex]::Match($text, $patRun)
    if ($mRun.Success) {
        $b = $mRun.Groups['b'].Value
        if ($b -match '(?m)^\s*output_path\s*:\s*["'']?(.+?)["'']?\s*$') {
            $outPath = $matches[1].Trim()
        }
    }

    $coord = (Split-Path -Leaf (Split-Path -Parent $YamlPath))
    if ($coord -match '^\(([0-9\.\-]+),([0-9\.\-]+)\)$') {
        $lat = $matches[1]; $lon = $matches[2]
    } else {
        $lat = $null; $lon = $null
    }

    [PSCustomObject]@{
        '실험ID'              = (Split-Path -Leaf (Split-Path -Parent (Split-Path -Parent $YamlPath)))
        '순번'                = ""
        '좌표'                = $coord
        '위도'                = $lat
        '경도'                = $lon
        '주소'                = ""
        '모드'                = "재사용"
        '상태'                = "실행"
        'YAML'                = $YamlPath
        '로그'                = ""
        'ambulance.velocity'  = $ambV
        'ambulance.handover'  = $ambH
        'uav.velocity'        = $uavV
        'uav.handover'        = $uavH
        'sim.totalSamples'    = $totS
        'sim.random_seed'     = $seed
        'hospital.max_send_coeff' = $maxCoeff
        'run.output_path'     = $outPath
        '시작시각'            = ""
        '종료시각'            = ""
        '소요(초)'            = ""
        'DiffFromDefaults'    = ""
    }
}

function Update-SummaryRowTimes {
    param([pscustomobject]$Row, [datetime]$StartTime, [datetime]$EndTime, [string]$LogPath)
    $Row.'시작시각' = $StartTime.ToString('yyyy-MM-dd HH:mm:ss')
    $Row.'종료시각' = $EndTime.ToString('yyyy-MM-dd HH:mm:ss')
    $Row.'소요(초)' = [Math]::Round(($EndTime - $StartTime).TotalSeconds, 3)
    $Row.'로그'     = $LogPath
    return $Row
}

# Read existing summary headers if possible to align schema
function Get-PreferredSummaryHeaders {
    param([string]$ExpDir)
    $candidates = Get-ChildItem -Path $ExpDir -File -Filter '*_summary.csv' | Sort-Object LastWriteTime -Descending
    if ($candidates.Count -gt 0) {
        try {
            $firstLine = (Get-Content -Path $candidates[0].FullName -TotalCount 1 -Encoding UTF8)
            if (-not $firstLine) { $firstLine = (Get-Content -Path $candidates[0].FullName -TotalCount 1) }
            $firstLine = $firstLine.TrimStart("ufeff")  # strip BOM if present
            $headers = $firstLine.Trim().Trim('"').Split('","')
            if ($headers.Count -gt 0) { return $headers }
        } catch {}
    }
    return @('실험ID','순번','좌표','위도','경도','주소','모드','상태','YAML','로그','ambulance.velocity','ambulance.handover','uav.velocity','uav.handover','sim.totalSamples','sim.random_seed','hospital.max_send_coeff','run.output_path','시작시각','종료시각','소요(초)','DiffFromDefaults')
}

function New-RowWithOrder {
    param([pscustomobject]$Row, [string[]]$Headers)
    $ordered = [ordered]@{}
    foreach ($h in $Headers) {
        if ($Row.PSObject.Properties.Name -contains $h) {
            $ordered[$h] = $Row.$h
        } else {
            $ordered[$h] = $null
        }
    }
    return [PSCustomObject]$ordered
}

# Override: Invoke-LocalEditRerun (재사용 모드 전용, 즉시 실행)
if (Get-Command Invoke-LocalEditRerun -ErrorAction SilentlyContinue) {
    Remove-Item function:Invoke-LocalEditRerun -ErrorAction SilentlyContinue
}
function Invoke-LocalEditRerun {
    param([string]$ProjectPath)
    $ScenariosRoot = Join-Path $ProjectPath 'scenarios'
    if (-not (Test-Path $ScenariosRoot)) { throw "유효한 경로가 아닙니다. ($ScenariosRoot)" }

    # 실험 선택
    $expDirs = Get-ChildItem -Path $ScenariosRoot -Directory -Filter 'exp_*' | Sort-Object Name
    if ($expDirs.Count -eq 0) { throw "선택 가능한 실험ID가 없습니다." }
    Write-Host ""
    Write-Host "📁 선택 가능한 실험ID:"
    for ($i=0; $i -lt $expDirs.Count; $i++) {
        Write-Host "  [$i] $($expDirs[$i].FullName)"
    }
    Write-Host "  [A] 전체 선택"
    $sel = Read-Host "번호(쉼표로 다중선택) 또는 A"
    $selectedExp = @()
    if ($sel -match '^[Aa]$') { $selectedExp = $expDirs } else {
        foreach ($tok in $sel.Split(',', [System.StringSplitOptions]::RemoveEmptyEntries)) {
            [void][int]::TryParse($tok.Trim(), [ref]$idx)
            if ($idx -ge 0 -and $idx -lt $expDirs.Count) { $selectedExp += $expDirs[$idx] }
        }
    }
    if ($selectedExp.Count -eq 0) { throw "선택이 올바르지 않습니다." }

    # Python exe 추정
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue)?.Source
    $mci = Join-Path $env:USERPROFILE 'anaconda3\envs\MCI\python.exe'
    if (Test-Path $mci) { $PythonExe = $mci }
    $MainPy = Join-Path $ProjectPath 'main.py'

    foreach ($exp in $selectedExp) {
        # 좌표 폴더 선택
        $coordDirs = Get-ChildItem -Path $exp.FullName -Directory | Where-Object { $_.Name -match '^\([0-9\.\-]+,[0-9\.\-]+\)$' } | Sort-Object Name
        if ($coordDirs.Count -eq 0) { Write-Host "⚠️ 좌표 폴더가 없습니다. $($exp.FullName)"; continue }
        Write-Host ""
        Write-Host "📌 선택 가능한 좌표 폴더:"
        for ($i=0; $i -lt $coordDirs.Count; $i++) {
            Write-Host "  [$i] $($coordDirs[$i].Parent.BaseName) | $($coordDirs[$i].Name)"
        }
        Write-Host "  [A] 전체 선택"
        $sel2 = Read-Host "번호(쉼표로 다중선택) 또는 A"
        $selectedCoords = @()
        if ($sel2 -match '^[Aa]$') { $selectedCoords = $coordDirs } else {
            foreach ($tok in $sel2.Split(',', [System.StringSplitOptions]::RemoveEmptyEntries)) {
                [void][int]::TryParse($tok.Trim(), [ref]$idx2)
                if ($idx2 -ge 0 -and $idx2 -lt $coordDirs.Count) { $selectedCoords += $coordDirs[$idx2] }
            }
        }
        if ($selectedCoords.Count -eq 0) { throw "선택이 올바르지 않습니다." }

        $summaryPath = Join-Path $exp.FullName ("{0}_summary.csv" -f $exp.Name)
        Write-Host ""
        Write-Host "🧭 재사용 실행 - 원본 실험: $($exp.Name) (요약: $summaryPath)"

        $rows = @()
        $headers = Get-PreferredSummaryHeaders -ExpDir $exp.FullName
        $n = 0

        foreach ($coordDir in $selectedCoords) {
            $n++
            $coordName = $coordDir.Name
            $yaml = Get-ChildItem -Path $coordDir.FullName -File -Filter 'config_*.yaml' | Sort-Object Name | Select-Object -First 1
            if (-not $yaml) { Write-Host "⚠️ YAML 없음: $($coordDir.FullName)"; continue }
            $YamlPath = $yaml.FullName
            Write-Host "🚀 실행: $coordName | YAML: $YamlPath"

            $row = Parse-Yaml-ForSummary -YamlPath $YamlPath
            $row.'순번' = $n

            $logDir = Join-Path $ProjectPath 'experiment_logs'
            if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
            $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
            $logName = "{0}_{1}.log" -f $coordName, $ts
            $logPath = Join-Path $logDir $logName

            $start = Get-Date
            try {
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName  = $PythonExe
                $psi.Arguments = "`"$MainPy`" --config_path `"$YamlPath`""
                $psi.RedirectStandardOutput = $true
                $psi.RedirectStandardError  = $true
                $psi.UseShellExecute = $false
                $psi.CreateNoWindow = $true
                $proc = [System.Diagnostics.Process]::Start($psi)
                $stdout = $proc.StandardOutput.ReadToEnd()
                $stderr = $proc.StandardError.ReadToEnd()
                $proc.WaitForExit()
                $out = $stdout + "`r`n" + $stderr
                [System.IO.File]::WriteAllText($logPath, $out, [System.Text.Encoding]::UTF8)
                if ($proc.ExitCode -ne 0) {
                    Write-Host "⚠️ 실패 (ExitCode=$($proc.ExitCode)) $YamlPath"
                    $row.'상태' = "실패"
                } else {
                    Write-Host "✅ 완료 $YamlPath"
                    $row.'상태' = "성공"
                }
            } catch {
                [System.IO.File]::WriteAllText($logPath, $_.Exception.ToString(), [System.Text.Encoding]::UTF8)
                Write-Host "❌ 실패(예외): $($YamlPath) → $($_.Exception.Message)"
                $row.'상태' = "예외"
            }
            $end = Get-Date
            $row = Update-SummaryRowTimes -Row $row -StartTime $start -EndTime $end -LogPath $logPath
            $rows += (New-RowWithOrder -Row $row -Headers $headers)
        }

        if ($rows.Count -gt 0) {
            Export-CsvUtf8Bom -Data $rows -Path $summaryPath
            Write-Host "📝 재사용 요약 저장 $summaryPath"
        } else {
            Write-Host "⚠️ 요약 저장 건 없음"
        }
    }
}

# ====== [Injected by ChatGPT v5.0 patch] END ======

# UTF-8 인코딩 설정 강화
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
chcp 65001 | Out-Null

# 색상 테마 정의
$Colors = @{
    Header = 'Cyan'
    Success = 'Green' 
    Warning = 'Yellow'
    Error = 'Red'
    Info = 'White'
    Debug = 'DarkGray'
    Highlight = 'Magenta'
    Progress = 'Blue'
    Accent = 'DarkCyan'
    Box = 'DarkYellow'
}

# 전역 변수
$script:AvailableSidos = @()
$script:SimulationConfigs = @()
$script:GlobalParams = @{}



# ==================== 유틸리티 함수 ====================

function Write-StyledHeader {
    param([string]$Text, [string]$Color = 'Cyan')
    
    Write-Host ""
    Write-Host "┌────────────────────────────────────────────────────────────────────────┐" -ForegroundColor $Color
    Write-Host " $Text " -ForegroundColor $Color
    Write-Host "└────────────────────────────────────────────────────────────────────────┘" -ForegroundColor $Color
    Write-Host ""
}

function Write-StatusLine {
    param(
        [string]$Icon,
        [string]$Message,
        [string]$Color = 'White',
        [string]$Detail = "",
        [switch]$NoNewline
    )
    
    if ($Detail) {
        Write-Host "$Icon $Message" -ForegroundColor $Color -NoNewline
        Write-Host " $Detail" -ForegroundColor 'DarkGray' -NoNewline:$NoNewline
    } else {
        Write-Host "$Icon $Message" -ForegroundColor $Color -NoNewline:$NoNewline
    }
    
    if (-not $NoNewline) { Write-Host "" }
}

function Show-ProgressBar {
    param(
        [int]$Current,
        [int]$Total,
        [string]$Activity,
        [TimeSpan]$Elapsed = $null,
        [bool]$ShowETA = $true
    )
    
    $percent = [math]::Round(($Current / $Total) * 100, 1)
    $barLength = 40
    $filled = [math]::Floor($barLength * ($Current / $Total))
    $empty = $barLength - $filled
    
    $bar = "█" * $filled + "░" * $empty
    
    # ETA 계산
    $etaText = ""
    if ($ShowETA -and $Elapsed -and $Current -gt 0) {
        $avgTimePerItem = $Elapsed.TotalSeconds / $Current
        $remainingItems = $Total - $Current
        $remainingSeconds = $avgTimePerItem * $remainingItems
        $eta = [TimeSpan]::FromSeconds($remainingSeconds)
        $etaText = " | ETA: $($eta.ToString('mm\:ss'))"
    }
    
    Write-Host "`r  $bar $percent% - $Activity$etaText" -NoNewline -ForegroundColor $Colors.Progress
}

function Write-InfoBox {
    param(
        [string]$Title,
        [string[]]$Content,
        [string]$BorderColor = 'DarkGray',
        [int]$Width = 60
    )
    
    Write-Host ""
    Write-Host "  $Title" -ForegroundColor $BorderColor
    Write-Host "  " + ("─" * ($Title.Length + 2)) -ForegroundColor $BorderColor
    
    foreach ($line in $Content) {
        Write-Host "  $line" -ForegroundColor $Colors.Info
    }
    Write-Host ""
}




# ==================== 로그 관리 함수 ====================

function Save-ExperimentLog {
    param(
        [PSCustomObject]$Config,
        [hashtable]$GlobalParams,
        [string]$ConfigPath,
        [string]$Status,
        [int]$ExitCode = 0,
        [string]$Output = ""
    )
    
    $logDir = "experiment_logs"
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    
    # 좌표 정보 추출
    $coordText = switch ($Config.Mode) {
        "korea_random" { "대한민국_전국완전랜덤" }
        "sido" { $Config.SidoName }
        "manual" { "($($Config.Latitude),$($Config.Longitude))" }
    }
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logFileName = "${coordText}_${timestamp}.log"
    $logPath = Join-Path $logDir $logFileName
    
    $logContent = @"
=== EXECUTION LOG ===
Coordinate: $coordText
Config Path: $ConfigPath
Start Time: $(Get-Date -Format 'MM/dd/yyyy HH:mm:ss')
Exit Code: $ExitCode
Status: $Status

=== DETAILED OUTPUT ===
$Output

=== END ===
"@
    
    $logContent | Out-File -FilePath $logPath -Encoding UTF8BOM
    
    Write-Host "📄 실험 로그 저장: $logPath" -ForegroundColor $Colors.Debug
    return $logPath
}

function Show-ExperimentLogs {
    param([hashtable]$GlobalParams)
    
    $logDir = "experiment_logs"
    if (Test-Path $logDir) {
        $logFiles = Get-ChildItem -Path $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending
        
        if ($logFiles.Count -gt 0) {
            Write-Host ""
            Write-Host "📂 실험 로그 파일들:" -ForegroundColor $Colors.Info
            foreach ($logFile in $logFiles) {
                Write-Host "  • $($logFile.Name)" -ForegroundColor $Colors.Debug
            }
        }
    }
}

# ==================== 1단계: 필수 설정 ====================

function Get-ProjectPath {
    Write-StyledHeader "📁 프로젝트 경로 설정" $Colors.Header
    
    $defaultPath = Get-Location
    Write-Host "현재 디렉토리: $defaultPath" -ForegroundColor $Colors.Info
    Write-Host ""
    Write-Host "프로젝트 경로를 입력하세요 (Enter = 현재 디렉토리):" -ForegroundColor $Colors.Info
    $userValue = Read-Host "경로"
    
    if ([string]::IsNullOrWhiteSpace($userValue)) {
        $selectedPath = $defaultPath
    } else {
        if (Test-Path $userValue) {
            $selectedPath = $userValue
        } else {
            Write-StatusLine "❌" "유효하지 않은 경로" $Colors.Error $userValue
            Write-Host "기본 경로를 사용합니다." -ForegroundColor $Colors.Warning
            $selectedPath = $defaultPath
        }
    }
    
    $selectedPath = [System.IO.Path]::GetFullPath($selectedPath)
    Write-StatusLine "✅" "프로젝트 경로 설정" $Colors.Success $selectedPath
    return $selectedPath
}

function Initialize-CondaEnvironment {
    Write-Host "🔍 Conda 환경 초기화 확인 중..." -ForegroundColor Cyan
    
    # 1. conda 명령어 존재 확인
    try {
        $condaPath = Get-Command conda -ErrorAction Stop
        Write-Host "✅ conda 명령어 발견: $($condaPath.Source)" -ForegroundColor Green
    } catch {
        Write-Host "❌ conda 명령어를 찾을 수 없습니다." -ForegroundColor Red
        Write-Host "   Anaconda/Miniconda가 설치되어 있는지 확인하세요." -ForegroundColor Yellow
        return $false
    }
    
    # 2. PowerShell conda hook 확인
    try {
        # conda info 실행해서 활성 환경 확인
        $condaInfo = & conda info --json 2>$null | ConvertFrom-Json
        $activeEnv = $condaInfo.active_prefix
        
        if ($activeEnv -and $activeEnv -ne $condaInfo.conda_prefix) {
            Write-Host "✅ Conda 환경이 이미 활성화됨: $(Split-Path $activeEnv -Leaf)" -ForegroundColor Green
            return $true
        } else {
            Write-Host "⚠️ 기본 환경이 활성화됨. PowerShell hook 초기화 필요" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "⚠️ conda info 실행 실패. PowerShell hook 초기화 필요" -ForegroundColor Yellow
    }
    
    # 3. PowerShell용 conda 초기화 시도
    try {
        Write-Host "🔧 PowerShell conda hook 초기화 중..." -ForegroundColor Cyan
        
        # conda hook을 현재 세션에 로드
        $condaHookPath = & conda info --base 2>$null
        if ($condaHookPath) {
            $hookScript = Join-Path $condaHookPath "shell\condabin\conda-hook.ps1"
            if (Test-Path $hookScript) {
                . $hookScript
                Write-Host "✅ PowerShell conda hook 로드 완료" -ForegroundColor Green
                return $true
            }
        }
        
        # 대안: conda init powershell 실행
        Write-Host "🔄 conda init powershell 실행 중..." -ForegroundColor Cyan
        & conda init powershell 2>$null
        
        # PowerShell 프로필 재로드 시도
        if (Test-Path $PROFILE) {
            . $PROFILE
            Write-Host "✅ PowerShell 프로필 재로드 완료" -ForegroundColor Green
        }
        
        return $true
        
    } catch {
        Write-Host "❌ PowerShell conda 초기화 실패: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "   CMD 방식을 사용합니다." -ForegroundColor Yellow
        return $false
    }
}

function Get-CondaEnvironment {
    Write-StyledHeader "🐍 Conda 환경 탐지" $Colors.Header
    
    # Conda 초기화 먼저 수행
    $condaInitialized = Initialize-CondaEnvironment
    
    try {
        $envList = & conda env list 2>&1
        $envs = @()
        
        foreach ($line in $envList) {
            if ($line -match "^([^\s#]+)\s+") {
                $envName = $matches[1]
                if ($envName -ne "base" -and $envName -ne "") {
                    $envs += $envName
                }
            }
        }
        
        if ($envs -contains "MCI") {
            Write-StatusLine "✅" "MCI 환경 발견" $Colors.Success
            $useDefault = Read-Host "MCI 환경을 사용하시겠습니까? [Y/N]"
            if ($useDefault -eq 'Y' -or $useDefault -eq 'y') {
                # Y 선택 시 - 이 부분은 잘 작동함
                if ($condaInitialized) {
                    try {
                        & conda activate MCI
                        $pythonPath = & python -c "import sys; print(sys.executable)" 2>$null
                        if ($pythonPath -like "*MCI*") {
                            Write-StatusLine "✅" "MCI 환경 활성화 확인" $Colors.Success $pythonPath
                        } else {
                            Write-StatusLine "⚠️" "PowerShell 활성화 실패, CMD 방식 사용" $Colors.Warning
                        }
                    } catch {
                        Write-StatusLine "⚠️" "PowerShell 활성화 실패, CMD 방식 사용" $Colors.Warning
                    }
                }
                return "MCI"
            }
        }
        
        # ⭐⭐⭐ N 선택 후 목록에서 선택하는 부분 - 여기가 문제! ⭐⭐⭐
        Write-Host "사용 가능한 Conda 환경:" -ForegroundColor $Colors.Info
        for ($i = 0; $i -lt $envs.Count; $i++) {
            Write-Host "  [$($i+1)] $($envs[$i])" -ForegroundColor $Colors.Highlight
        }
        
        $choice = Read-Host "환경 번호 선택 (1-$($envs.Count))"
        $selectedEnv = $envs[[int]$choice - 1]
        
        # ⭐⭐⭐ 여기에 활성화 코드 추가! ⭐⭐⭐
        if ($condaInitialized) {
            try {
                Write-Host "🔄 $selectedEnv 환경 활성화 중..." -ForegroundColor $Colors.Info
                & conda activate $selectedEnv
                Start-Sleep -Seconds 1  # 활성화 대기
                
                $pythonPath = & python -c "import sys; print(sys.executable)" 2>$null
                if ($pythonPath -like "*$selectedEnv*") {
                    Write-StatusLine "✅" "$selectedEnv 환경 활성화 확인" $Colors.Success $pythonPath
                } else {
                    Write-StatusLine "⚠️" "PowerShell 활성화 실패, CMD 방식 사용" $Colors.Warning
                }
            } catch {
                Write-StatusLine "⚠️" "PowerShell 활성화 실패, CMD 방식 사용" $Colors.Warning
            }
        }
        
        Write-StatusLine "✅" "Conda 환경 선택" $Colors.Success $selectedEnv
        return $selectedEnv
        
    } catch {
        Write-StatusLine "⚠️" "Conda 환경 자동 탐지 실패" $Colors.Warning
        $manualEnv = Read-Host "Conda 환경명을 직접 입력하세요"
        return $manualEnv
    }
}

function Get-NaverAPIKeys {
    Write-StyledHeader "🔑 Naver API 키 설정" $Colors.Header
    
    $envClientId = $env:NAVER_CLIENT_ID
    $envClientSecret = $env:NAVER_CLIENT_SECRET
    
    if ($envClientId -and $envClientSecret) {
        Write-Host "환경 변수에서 API 키 발견:" -ForegroundColor $Colors.Info
        Write-Host "  Client ID: $($envClientId.Substring(0,4))..." -ForegroundColor $Colors.Debug
        Write-Host "  Client Secret: $($envClientSecret.Substring(0,4))..." -ForegroundColor $Colors.Debug
        
        $useEnv = Read-Host "이 키를 사용하시겠습니까? [Y/N]"
        if ($useEnv -eq 'Y' -or $useEnv -eq 'y') {
            return @{
                ClientId = $envClientId
                ClientSecret = $envClientSecret
            }
        }
    }
    
    Write-Host "Naver Cloud Platform API 키를 입력하세요:" -ForegroundColor $Colors.Info
    Write-Host "(https://console.ncloud.com/maps/application)" -ForegroundColor $Colors.Debug
    
    $clientId = Read-Host "  Client ID"
    $clientSecret = Read-Host "  Client Secret"
    
    $saveEnv = Read-Host "이 키를 환경 변수에 저장하시겠습니까? [Y/N]"
    if ($saveEnv -eq 'Y' -or $saveEnv -eq 'y') {
        [System.Environment]::SetEnvironmentVariable('NAVER_CLIENT_ID', $clientId, 'User')
        [System.Environment]::SetEnvironmentVariable('NAVER_CLIENT_SECRET', $clientSecret, 'User')
        Write-StatusLine "✅" "API 키가 환경 변수에 저장되었습니다" $Colors.Success
    }
    
    return @{
        ClientId = $clientId
        ClientSecret = $clientSecret
    }
}

function Test-Prerequisites {
    param([string]$ProjectPath)
    
    Write-StatusLine "🔍" "필수 요구사항 검사 중..." $Colors.Info
    
    $issues = @()
    
    # Python 확인
    try {
        $pythonVersion = & python --version 2>&1
        Write-StatusLine "✅" "Python 확인" $Colors.Success $pythonVersion
    } catch {
        $issues += "Python이 설치되어 있지 않습니다"
    }
    
    # Conda 확인
    try {
        $condaVersion = & conda --version 2>&1
        Write-StatusLine "✅" "Conda 확인" $Colors.Success $condaVersion
    } catch {
        $issues += "Conda가 설치되어 있지 않습니다"
    }
    
    # 필수 파일 확인
    $requiredFiles = @(
        "event_info.json",
        "main.py",
        "random_coordinate_generator.py",
        "make_csv_yaml_dynamic.py",
        "EntityManager.py",
        "EventManager.py",
        "ScenarioManager.py",
        "RuleManager.py",
        "MCIEnvironment_gymnasium.py"
    )
    
    $dataFiles = @(
        "scenarios\안전센터와 소방서.csv",
        "scenarios\엑셀 결합 데이터.xlsx",
        "scenarios\ctprvn.shp"
    )
    
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path (Join-Path $ProjectPath $file))) {
            $issues += "필수 파일이 없습니다: $file"
        }
    }
    
    foreach ($file in $dataFiles) {
        if (-not (Test-Path (Join-Path $ProjectPath $file))) {
            $issues += "데이터 파일이 없습니다: $file"
        }
    }
    
    return $issues
}

# ==================== 패키지 설치 함수 ====================

function Install-PythonPackages {
    param([string]$CondaEnv)
    
    Write-StyledHeader "📦 Python 패키지 확인" $Colors.Header
    
    # 필수 패키지 목록
    $requiredPackages = @(
        "pandas",
        "numpy", 
        "requests",
        "haversine",
        "pyyaml",
        "geopandas",
        "shapely",
        "gymnasium",
        "scipy",
        "openpyxl"
    )
    
    # 1단계: conda 환경 활성화 상태 확인
    Write-StatusLine "🔍" "Conda 환경 상태 확인 중..." $Colors.Info
    
    try {
        # 현재 활성화된 conda 환경 확인
        $condaInfo = & conda info --json 2>$null | ConvertFrom-Json
        $activeEnv = $condaInfo.active_prefix
        $basePath = $condaInfo.conda_prefix
        
        if ($activeEnv -and $activeEnv -ne $basePath) {
            $activeEnvName = Split-Path $activeEnv -Leaf
            Write-StatusLine "✅" "활성 환경 확인" $Colors.Success "($activeEnvName)"
            
            # MCI 환경이 활성화되어 있는지 확인
            if ($activeEnvName -eq $CondaEnv) {
                Write-StatusLine "✅" "$CondaEnv 환경이 올바르게 활성화됨" $Colors.Success
            } else {
                Write-StatusLine "❌" "잘못된 환경이 활성화됨" $Colors.Error "현재: $activeEnvName, 필요: $CondaEnv"
                Write-Host ""
                Write-Host "🔧 해결 방법:" -ForegroundColor $Colors.Warning
                Write-Host "  1. PowerShell을 종료합니다" -ForegroundColor $Colors.Warning
                Write-Host "  2. 새 PowerShell을 열어서 다음 명령어를 실행:" -ForegroundColor $Colors.Warning
                Write-Host "     conda activate $CondaEnv" -ForegroundColor $Colors.Highlight
                Write-Host "  3. 다시 이 스크립트를 실행하세요" -ForegroundColor $Colors.Warning
                Write-Host ""
                Read-Host "Enter 키를 눌러 종료하세요"
                exit 1
            }
        } else {
            Write-StatusLine "❌" "conda 환경이 활성화되지 않음" $Colors.Error "현재: base 환경"
            Write-Host ""
            Write-Host "🔧 해결 방법:" -ForegroundColor $Colors.Warning
            Write-Host "  1. PowerShell을 종료합니다" -ForegroundColor $Colors.Warning
            Write-Host "  2. 새 PowerShell을 열어서 다음 명령어를 실행:" -ForegroundColor $Colors.Warning
            Write-Host "     conda activate $CondaEnv" -ForegroundColor $Colors.Highlight
            Write-Host "  3. 다시 이 스크립트를 실행하세요" -ForegroundColor $Colors.Warning
            Write-Host ""
            Read-Host "Enter 키를 눌러 종료하세요"
            exit 1
        }
        
    } catch {
        Write-StatusLine "❌" "conda 환경 상태 확인 실패" $Colors.Error $_.Exception.Message
        Write-Host ""
        Write-Host "🔧 해결 방법:" -ForegroundColor $Colors.Warning
        Write-Host "  conda가 제대로 설치되어 있는지 확인하세요" -ForegroundColor $Colors.Warning
        Write-Host ""
        Read-Host "Enter 키를 눌러 종료하세요"
        exit 1
    }
    
    # 2단계: pip list로 설치된 패키지 확인
    Write-StatusLine "🔍" "설치된 패키지 확인 중..." $Colors.Info
    
    try {
        $pipList = & pip list 2>$null
        $installedPackages = @()
        $missingPackages = @()
        
        foreach ($pkg in $requiredPackages) {
            $packageLine = $pipList | Where-Object { $_ -match "^$pkg\s+" } | Select-Object -First 1
            
            if ($packageLine) {
                $parts = $packageLine -split '\s+'
                $version = $parts[1]
                $installedPackages += @{Name = $pkg; Version = $version}
                Write-StatusLine "✅" "$pkg" $Colors.Success "$version"
            } else {
                $missingPackages += $pkg
                Write-StatusLine "❌" "$pkg" $Colors.Error "미설치"
            }
        }
        
    } catch {
        Write-StatusLine "❌" "pip list 실행 실패" $Colors.Error $_.Exception.Message
        Write-Host ""
        Write-Host "🔧 해결 방법:" -ForegroundColor $Colors.Warning
        Write-Host "  pip가 제대로 설치되어 있는지 확인하세요" -ForegroundColor $Colors.Warning
        Write-Host ""
        Read-Host "Enter 키를 눌러 종료하세요"
        exit 1
    }
    
    # 3단계: 결과 요약
    Write-Host ""
    Write-Host "📊 패키지 설치 상태 요약" -ForegroundColor $Colors.Info
    Write-Host "  ──────────────────────" -ForegroundColor $Colors.Info
    Write-Host "  ✅ 설치됨: $($installedPackages.Count)개" -ForegroundColor $Colors.Success
    Write-Host "  ❌ 미설치: $($missingPackages.Count)개" -ForegroundColor $Colors.Error
    Write-Host ""
    
    # 4단계: 누락된 패키지 처리
    if ($missingPackages.Count -eq 0) {
        Write-StatusLine "🎉" "모든 필수 패키지가 설치되어 있습니다!" $Colors.Success
        return
    }
    
    Write-Host "❌ 다음 패키지들이 누락되었습니다:" -ForegroundColor $Colors.Error
    foreach ($pkg in $missingPackages) {
        Write-Host "  • $pkg" -ForegroundColor $Colors.Error
    }
    Write-Host ""
    
    Write-Host "🔧 설치 방법:" -ForegroundColor $Colors.Info
    Write-Host "  현재 ($CondaEnv) 환경에서 다음 명령어들을 실행하세요:" -ForegroundColor $Colors.Info
    Write-Host ""
    
    foreach ($pkg in $missingPackages) {
        Write-Host "  pip install $pkg" -ForegroundColor $Colors.Highlight
    }
    
    Write-Host ""
    Write-Host "또는 한 번에 설치:" -ForegroundColor $Colors.Info
    $allMissing = $missingPackages -join " "
    Write-Host "  pip install $allMissing" -ForegroundColor $Colors.Highlight
    Write-Host ""
    
    # 5단계: 사용자 선택
    Write-Host "다음 중 선택하세요:" -ForegroundColor $Colors.Info
    Write-Host "  [1] 지금 설치하기 (자동)" -ForegroundColor $Colors.Highlight
    Write-Host "  [2] 수동으로 설치하기 (위 명령어 복사해서 사용)" -ForegroundColor $Colors.Highlight  
    Write-Host "  [3] 나중에 설치하기 (계속 진행)" -ForegroundColor $Colors.Highlight
    Write-Host ""
    
    do {
        $choice = Read-Host "선택 [1/2/3]"
    } while ($choice -notin @('1', '2', '3'))
    
    switch ($choice) {
        "1" {
            Write-StatusLine "🚀" "자동 설치 시작..." $Colors.Progress
            Write-Host ""
            
            $successCount = 0
            $failCount = 0
            
            foreach ($pkg in $missingPackages) {
                try {
                    Write-Host "  📦 $pkg 설치 중..." -ForegroundColor $Colors.Info
                    $result = & pip install $pkg 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-StatusLine "✅" "$pkg 설치 완료" $Colors.Success
                        $successCount++
                    } else {
                        Write-StatusLine "❌" "$pkg 설치 실패" $Colors.Error
                        Write-Host "     오류: $result" -ForegroundColor $Colors.Error
                        $failCount++
                    }
                } catch {
                    Write-StatusLine "❌" "$pkg 설치 예외" $Colors.Error $_.Exception.Message
                    $failCount++
                }
                
                Start-Sleep -Milliseconds 500
            }
            
            Write-Host ""
            Write-StatusLine "📊" "설치 완료" $Colors.Info "성공: $successCountᄀ개, 실패: $failCountᄀ개"
            
            if ($failCount -eq 0) {
                Write-StatusLine "🎉" "모든 패키지 설치 완료!" $Colors.Success
            } else {
                Write-StatusLine "⚠️" "일부 패키지 설치 실패" $Colors.Warning "수동 설치 필요"
            }
        }
        
        "2" {
            Write-StatusLine "📋" "수동 설치 모드" $Colors.Info
            Write-Host ""
            Write-Host "다음 명령어를 복사해서 실행하세요:" -ForegroundColor $Colors.Info
            Write-Host ""
            Write-Host "pip install $allMissing" -ForegroundColor $Colors.Highlight
            Write-Host ""
            Read-Host "설치 완료 후 Enter 키를 누르세요"
        }
        
        "3" {
            Write-StatusLine "⚠️" "패키지 설치 건너뛰기" $Colors.Warning
            Write-Host ""
            Write-Host "⚠️ 누락된 패키지로 인해 시뮬레이션이 실패할 수 있습니다." -ForegroundColor $Colors.Warning
            Write-Host "   나중에 위의 명령어로 설치하세요." -ForegroundColor $Colors.Warning
        }
    }
    
    Write-Host ""
    Write-Host "💡 팁: 앞으로는 ($CondaEnv) 환경에서만 pip install을 사용하세요!" -ForegroundColor $Colors.Info
}

# ==================== 나머지 함수들 ====================
function Set-YamlMaxSendCoeff {
    param(
        [Parameter(Mandatory=$true)][string]$ConfigPath,
        [Parameter(Mandatory=$true)][string]$CoeffInput
    )

    if ([string]::IsNullOrWhiteSpace($CoeffInput)) {
        return   # 미입력이면 기본값 유지
    }
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Write-Host "⚠️ YAML 경로가 유효하지 않습니다: $ConfigPath" -ForegroundColor Yellow
        return
    }
    if ($CoeffInput -notmatch '^\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*$') {
        Write-Host "⚠️ 형식은 'a,b' 여야 합니다. 예: 1.1,1" -ForegroundColor Yellow
        return
    }
    $a = $matches[1]; $b = $matches[2]

    $text = Get-Content -Raw -LiteralPath $ConfigPath -Encoding UTF8

    # 1차: 기존 라인 교체 (어디에 있어도 교체)
    $patched = $text -replace '(?m)^( *max_send_coeff:\s*)\[[^\]]+\]', "`$1[$a, $b]"

    if ($patched -eq $text) {
        # 2차: hospital: 블록 바로 아래에 삽입
        $lines = $text -split "`r?`n"
        $idx = [Array]::FindIndex($lines, [Predicate[string]]{ param($l) $l.Trim() -eq 'hospital:' })
        if ($idx -ge 0) {
            $hospIndent = ($lines[$idx] -replace '^( *)hospital:.*$','$1')
            $indent = "$hospIndent  "
            $lines = $lines[0..$idx] + @("$indent" + "max_send_coeff: [$a, $b]") + $lines[($idx+1)..($lines.Length-1)]
            $patched = ($lines -join "`r`n")
        } else {
            # 3차: 최후수단 - 파일 맨 끝에 블록 추가
            $patched = $text + "`r`n" + "hospital:`r`n  max_send_coeff: [$a, $b]"
        }
    }

    Set-Content -LiteralPath $ConfigPath -Value $patched -Encoding UTF8
    Write-Host "🔧 max_send_coeff → [$a, $b] 적용됨: $ConfigPath" -ForegroundColor Green

    # 확인 출력
    $line = (Select-String -Path $ConfigPath -Pattern '^\s*max_send_coeff:' -SimpleMatch | Select-Object -First 1).Line
    if ($line) { Write-Host "   → $line" -ForegroundColor DarkGray }
}

function Get-SimulationCount {


Write-StyledHeader "🎯 시뮬레이션 개수 설정" $Colors.Header

    
    
    do {
        Write-Host "생성할 시뮬레이션 개수를 입력하세요 (1-10):" -ForegroundColor $Colors.Info
        $count = Read-Host "개수"
        try {
            $simCount = [int]$count
            if ($simCount -ge 1 -and $simCount -le 10) {
                break
            } else {
                Write-Host "❌ 1-10 사이의 숫자를 입력해주세요." -ForegroundColor $Colors.Error
            }
        } catch {
            Write-Host "❌ 올바른 숫자를 입력해주세요." -ForegroundColor $Colors.Error
        }
    } while ($true)
    
    Write-StatusLine "✅" "시뮬레이션 개수" $Colors.Success "$simCount 개"
    return $simCount
}

function Get-GlobalParameters {
    Write-StyledHeader "🌍 전역 파라미터 설정" $Colors.Header
    
    $experimentId = "exp_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    Write-StatusLine "📖" "실험 ID" $Colors.Info $experimentId
    
    # 출력 경로 설정
    $outputPath = "./results/$experimentId"
    Write-StatusLine "📂" "출력 경로" $Colors.Info $outputPath
    
    return @{
        ExperimentId = $experimentId
        OutputPath = $outputPath
        Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    }
}

function Get-DefaultParameters {
    return @{
        incident_size = 30
        amb_size = 30
        uav_size = 3
        amb_velocity = 40
        uav_velocity = 80
        total_samples = 10
        random_seed = 0
    }
}

function Show-DefaultParameters {
    param([hashtable]$Params)
    
    Write-StyledHeader "📋 디폴트 파라미터 설정" $Colors.Header
    
    Write-Host "  기본 설정" -ForegroundColor $Colors.Accent
    Write-Host "  ──────────" -ForegroundColor $Colors.Accent
    Write-Host "  환자 수: $($Params.incident_size)명" -ForegroundColor $Colors.Info
    Write-Host "  구급차 수: $($Params.amb_size)대" -ForegroundColor $Colors.Info
    Write-Host "  UAV 수: $($Params.uav_size)대" -ForegroundColor $Colors.Info
    Write-Host "  구급차 속도: $($Params.amb_velocity) km/h" -ForegroundColor $Colors.Info
    Write-Host "  UAV 속도: $($Params.uav_velocity) km/h" -ForegroundColor $Colors.Info
    Write-Host "  시뮬레이션 반복: $($Params.total_samples)회" -ForegroundColor $Colors.Info
    Write-Host "  랜덤 시드: $($Params.random_seed)" -ForegroundColor $Colors.Info
    Write-Host ""
    Write-Host "  🎲 생성모드: 대한민국 전국 완전랜덤 (면적가중치 제거됨)" -ForegroundColor $Colors.Accent
    Write-Host ""
}

function Confirm-DefaultSettings {
    param([hashtable]$DefaultParams)
    
    Show-DefaultParameters $DefaultParams
    
    Write-Host ""
    $useDefault = Read-Host "위 설정을 모든 시뮬레이션에 일괄 적용하시겠습니까? [Y/N]"
    
    return ($useDefault -eq 'Y' -or $useDefault -eq 'y')
}

function Get-AvailableSidos {
    param([string]$ProjectPath)
    
    Write-StatusLine "🗺️" "시도 목록 로드 중..." $Colors.Info
    
    try {
        # 하드코딩된 시도 목록 사용 (인코딩 문제 회피)
        $sidos = @(
            "서울특별시",
            "부산광역시", 
            "대구광역시",
            "인천광역시",
            "광주광역시",
            "대전광역시",
            "울산광역시",
            "세종특별자치시",
            "경기도",
            "충청북도",
            "충청남도",
            "전라북도",
            "전라남도",
            "경상북도",
            "경상남도",
            "제주특별자치도",
            "강원특별자치도"
        )
        
        Write-StatusLine "✅" "시도 목록 로드 완료" $Colors.Success "$($sidos.Count)개 시도"
        return $sidos
        
    } catch {
        Write-StatusLine "❌" "시도 목록 로드 실패" $Colors.Error $_.Exception.Message
        # 기본 시도 목록 반환
        return @(
            "서울특별시",
            "부산광역시", 
            "대구광역시",
            "인천광역시",
            "광주광역시",
            "대전광역시",
            "울산광역시",
            "세종특별자치시",
            "경기도",
            "충청북도",
            "충청남도",
            "전라북도",
            "전라남도",
            "경상북도",
            "경상남도",
            "제주특별자치도",
            "강원특별자치도"
        )
    }
}

function Get-GenerationMode {
    Write-Host ""
    Write-Host "🎯 좌표 생성 모드를 선택하세요:" -ForegroundColor $Colors.Accent
    Write-Host ""
    
    Write-Host "  [1] 🎲 대한민국 전국 완전랜덤" -ForegroundColor $Colors.Highlight
    Write-Host "      • SHP 파일 기반 정확한 행정구역 경계 준수" -ForegroundColor $Colors.Debug
    Write-Host "      • 모든 시도 동일 확률 (면적가중치 제거됨)" -ForegroundColor $Colors.Debug
    Write-Host "      • 해상/무효 지역 자동 제외 (Naver API 검증)" -ForegroundColor $Colors.Debug
    Write-Host ""
    Write-Host "  [2] 🏙️ 특정 시도 선택" -ForegroundColor $Colors.Highlight
    Write-Host "      • ctprvn.shp 파일의 시도 경계 내에서만 생성" -ForegroundColor $Colors.Debug
    Write-Host "      • 선택된 시도의 폴리곤 내부에서 균등 분포" -ForegroundColor $Colors.Debug
    Write-Host ""
    Write-Host "  [3] 📍 수동 좌표 입력" -ForegroundColor $Colors.Highlight
    Write-Host "      • 위도/경도를 직접 입력하여 정확한 위치 지정" -ForegroundColor $Colors.Debug
    Write-Host "      • 범위: 위도 33.1~38.6, 경도 124.6~131.0" -ForegroundColor $Colors.Debug
    Write-Host ""
    
    do {
        $choice = Read-Host "선택 [1/2/3]"
    } while ($choice -notin @('1', '2', '3'))
    
    return $choice
}

function Get-SidoSelection {
    param([array]$AvailableSidos)
    
    if ($AvailableSidos.Count -eq 0) {
        Write-Host "❌ 사용 가능한 시도가 없습니다. 기본 목록을 사용합니다." -ForegroundColor $Colors.Error
        $AvailableSidos = @(
            "서울특별시", "부산광역시", "대구광역시", "인천광역시",
            "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
            "경기도", "충청북도", "충청남도", "전라북도",
            "전라남도", "경상북도", "경상남도", "제주특별자치도", "강원특별자치도"
        )
    }
    
    Write-Host ""
    Write-Host "시도를 선택하세요:" -ForegroundColor $Colors.Info
    Write-Host ""
    
    for ($i = 0; $i -lt $AvailableSidos.Count; $i++) {
        Write-Host "  [$($i+1)] $($AvailableSidos[$i])" -ForegroundColor $Colors.Highlight
    }
    
    Write-Host ""
    do {
        $choice = Read-Host "시도 번호 선택 (1-$($AvailableSidos.Count))"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            Write-Host "❌ 번호를 입력해주세요." -ForegroundColor $Colors.Error
            continue
        }
        try {
            $sidoIndex = [int]$choice - 1
            if ($sidoIndex -lt 0 -or $sidoIndex -ge $AvailableSidos.Count) {
                Write-Host "❌ 1-$($AvailableSidos.Count) 사이의 숫자를 입력해주세요." -ForegroundColor $Colors.Error
                continue
            }
            break
        } catch {
            Write-Host "❌ 올바른 숫자를 입력해주세요." -ForegroundColor $Colors.Error
            continue
        }
    } while ($true)
    
    $selectedSido = $AvailableSidos[$sidoIndex]
    Write-StatusLine "✅" "시도 선택" $Colors.Success $selectedSido
    
    return $selectedSido
}

function Get-ManualCoordinates {
    Write-Host ""
    Write-Host "좌표를 입력하세요:" -ForegroundColor $Colors.Info
    
    do {
        $userValue = Read-Host "  위도 (33.1 ~ 38.6)"
        try {
            $latitude = [float]$userValue
            if ($latitude -ge 33.1 -and $latitude -le 38.6) {
                break
            } else {
                Write-Host "❌ 위도는 33.1~38.6 범위여야 합니다." -ForegroundColor $Colors.Error
            }
        } catch {
            Write-Host "❌ 올바른 숫자를 입력해주세요." -ForegroundColor $Colors.Error
        }
    } while ($true)

    do {
        $userValue = Read-Host "  경도 (124.6 ~ 131.0)"
        try {
            $longitude = [float]$userValue
            if ($longitude -ge 124.6 -and $longitude -le 131.0) {
                break
            } else {
                Write-Host "❌ 경도는 124.6~131.0 범위여야 합니다." -ForegroundColor $Colors.Error
            }
        } catch {
            Write-Host "❌ 올바른 숫자를 입력해주세요." -ForegroundColor $Colors.Error
        }
    } while ($true)

    Write-StatusLine "✅" "수동 좌표 입력" $Colors.Success "($latitude, $longitude)"

    return @{
        Latitude = $latitude
        Longitude = $longitude
    }
}

function Get-SimulationParameters {
    param([hashtable]$DefaultParams)
    
    Write-Host ""
    Write-Host "파라미터를 수정하시겠습니까?" -ForegroundColor $Colors.Info
    $modify = Read-Host "[Y/N]"
    
    if ($modify -eq 'Y' -or $modify -eq 'y') {
        $params = $DefaultParams.Clone()
        
        Write-Host ""
        Write-Host "새 값을 입력하세요 (Enter = 기본값 유지):" -ForegroundColor $Colors.Info
        
        $userValue = Read-Host "  환자 수 [$($params.incident_size)]"
        if ($userValue) { $params.incident_size = [int]$userValue }

        $userValue = Read-Host "  구급차 수 [$($params.amb_size)]"
        if ($userValue) { $params.amb_size = [int]$userValue }

        $userValue = Read-Host "  UAV 수 [$($params.uav_size)]"
        if ($userValue) { $params.uav_size = [int]$userValue }

        $userValue = Read-Host "  구급차 속도 [$($params.amb_velocity)]"
        if ($userValue) { $params.amb_velocity = [int]$userValue }

        $userValue = Read-Host "  UAV 속도 [$($params.uav_velocity)]"
        if ($userValue) { $params.uav_velocity = [int]$userValue }

        $userValue = Read-Host "  시뮬레이션 반복 [$($params.total_samples)]"
        if ($userValue) { $params.total_samples = [int]$userValue }

        $userValue = Read-Host "  랜덤 시드 [$($params.random_seed)]"
        if ($userValue) { $params.random_seed = [int]$userValue }

        return $params
    } else {
        return $DefaultParams
    }
}


function Get-AdvancedOptions {
    <#
      병원선정/AMB/Patient 동적 옵션 입력 (환경변수 전달용)
      - 기존 흐름은 그대로, 여기서 받은 값은 GlobalParams에 저장만 함
    #>
    Write-Host ""
    Write-StyledHeader "⚙️ 고급 옵션(병원선정/AMB/Patient)" $Colors.Header

    # 기본값
    $QueuePolicyDefault = "0"
    $UtilByTierDefault  = "1:0.656,11:0.461,etc:0.461"
    $BufferRatioDefault = 1.5

    # queue_policy
    do {
        $QueuePolicy = Read-Host "queue_policy (0 | capa/2 | capa/3 | 0.5 등) [기본=$QueuePolicyDefault]"
        if ([string]::IsNullOrWhiteSpace($QueuePolicy)) { $QueuePolicy = $QueuePolicyDefault }
        $ok = ($QueuePolicy -match '^(0|capa/\d+(\.\d+)?|0?\.\d+|1(\.0+)?)$')
        if (-not $ok) { Write-Host "형식 오류: 0, capa/k, 0<비율≤1 허용" -ForegroundColor $Colors.Warning }
    } until ($ok)

    # util_by_tier
    $UtilByTierRaw = Read-Host "util_by_tier (예: $UtilByTierDefault) [기본=$UtilByTierDefault]"
    if ([string]::IsNullOrWhiteSpace($UtilByTierRaw)) { $UtilByTierRaw = $UtilByTierDefault }

    # buffer_ratio
    $buf = Read-Host "buffer_ratio [기본=$BufferRatioDefault]"
    if ([string]::IsNullOrWhiteSpace($buf)) { $buf = $BufferRatioDefault }
    $BufferRatio = [double]$buf

    # AMB 옵션


    # Patient override 여부
    $UsePatientOverride = Read-Host "patient_info 파라미터를 수정하시겠습니까? (Y/N) [기본=N]"
    $PatientJson = $null
    if ($UsePatientOverride -in @('Y','y')) {
        function LocalRead-Ratio([string]$name,[double]$def){ 
            $x=Read-Host "$name 비율(기본=$def)"; if([string]::IsNullOrWhiteSpace($x)){return $def}; return [double]$x 
        }
        $rRed    = LocalRead-Ratio "Red" 0.10
        $rYellow = LocalRead-Ratio "Yellow" 0.30
        $rGreen  = LocalRead-Ratio "Green" 0.50
        $rBlack  = LocalRead-Ratio "Black" 0.10
        $sum = $rRed+$rYellow+$rGreen+$rBlack
        if ([math]::Abs($sum-1.0) -gt 0.0001) {
            Write-Host "비율 합이 1.0이 아닙니다. override 미적용." -ForegroundColor $Colors.Warning
        } else {
            $PatientJson = @{
                ratio = @{
                    Red    = $rRed
                    Yellow = $rYellow
                    Green  = $rGreen
                    Black  = $rBlack
                }
            } | ConvertTo-Json -Depth 5 -Compress
        }
    }

    # hospital.max_send_coeff (선택)
    $MaxSendCoeff = Read-Host "hospital.max_send_coeff (a,b) [기본=1.0,1.0] (입력 예: 1.0,1.0) (※반드시 숫자,숫자만 입력)"

    return @{
        QueuePolicy = $QueuePolicy
        UtilByTier  = $UtilByTierRaw
        BufferRatio = $BufferRatio
        AmbTarget   = $AmbTarget
        AmbMaxDistKm= $AmbMaxDistKm
        PatientJson = $PatientJson
        MaxSendCoeff= $MaxSendCoeff
    }
}
function Set-IndividualSimulations {
    param(
        [int]$SimCount,
        [hashtable]$DefaultParams,
        [array]$AvailableSidos,
        [bool]$UseDefaultAll
    )
    
    # 시도 목록 검증
    if ($null -eq $AvailableSidos -or $AvailableSidos.Count -eq 0) {
        Write-Host "⚠️ 시도 목록이 비어있습니다. 기본 목록을 사용합니다." -ForegroundColor $Colors.Warning
        $AvailableSidos = @(
            "서울특별시", "부산광역시", "대구광역시", "인천광역시",
            "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
            "경기도", "충청북도", "충청남도", "전라북도",
            "전라남도", "경상북도", "경상남도", "제주특별자치도", "강원특별자치도"
        )
    }
    
    $simConfigs = @()
    
    for ($i = 1; $i -le $SimCount; $i++) {
        Write-StyledHeader "⚙️ 시뮬레이션 #$i 설정" $Colors.Header

        $config = @{
            Id = $i
            Mode = "korea_random"
            SidoName = $null
            Latitude = $null
            Longitude = $null
            Parameters = $DefaultParams.Clone()
        }

        if (-not $UseDefaultAll) {
            # 이전 설정 복사 옵션 (2번째부터)
            if ($i -gt 1) {
                Write-Host "이전 시뮬레이션 설정을 복사하시겠습니까?" -ForegroundColor $Colors.Info
                $copyPrev = Read-Host "[Y/N]"

                if ($copyPrev -eq 'Y' -or $copyPrev -eq 'y') {
                    $config = $simConfigs[$i-2] | ConvertTo-Json -Depth 20 | ConvertFrom-Json
                    $config.Id = $i

                    Write-Host ""
                    Write-Host "어떤 항목을 수정하시겠습니까?" -ForegroundColor $Colors.Info
                    Write-Host "  [1] 생성모드만 변경"
                    Write-Host "  [2] 파라미터만 변경"  
                    Write-Host "  [3] 전체 다시 설정"
                    Write-Host "  [4] 그대로 사용"

                    $modifyChoice = Read-Host "선택 [1/2/3/4]"

                    switch ($modifyChoice) {
                        "1" { 
                            # 생성모드만 변경
                            $modeChoice = Get-GenerationMode
                            switch ($modeChoice) {
                                "1" { 
                                    $config.Mode = "korea_random"
                                    $config.SidoName = $null
                                    $config.Latitude = $null
                                    $config.Longitude = $null
                                }
                                "2" { 
                                    $config.Mode = "sido"
                                    $config.SidoName = Get-SidoSelection $AvailableSidos
                                    $config.Latitude = $null
                                    $config.Longitude = $null
                                }
                                "3" { 
                                    $config.Mode = "manual"
                                    $manualCoords = Get-ManualCoordinates
                                    $config.SidoName = $null
                                    $config.Latitude = $manualCoords.Latitude
                                    $config.Longitude = $manualCoords.Longitude
                                }
                            }
                        }
                        "2" { 
                            # 파라미터만 변경
                            $config.Parameters = Get-SimulationParameters $config.Parameters
                        }
                        "3" { 
                            # 전체 다시 설정 (아래 일반 설정으로)
                            $config = @{
                                Id = $i
                                Mode = "korea_random"
                                SidoName = $null
                                Latitude = $null
                                Longitude = $null
                                Parameters = $DefaultParams.Clone()
                            }
                        }
                        "4" { 
                            # 그대로 사용 (아무것도 안함)
                        }
                    }

                    if ($modifyChoice -ne "3") {
                        $simConfigs += [PSCustomObject]$config
                        continue
                    }
                }
            }

            # 생성 모드 선택
            $modeChoice = Get-GenerationMode

            switch ($modeChoice) {
                "1" { 
                    $config.Mode = "korea_random"
                }
                "2" { 
                    $config.Mode = "sido"
                    $config.SidoName = Get-SidoSelection $AvailableSidos
                }
                "3" { 
                    $config.Mode = "manual"
                    $manualCoords = Get-ManualCoordinates
                    $config.Latitude = $manualCoords.Latitude
                    $config.Longitude = $manualCoords.Longitude
                }
            }

            # 파라미터 설정
            $config.Parameters = Get-SimulationParameters $DefaultParams
        }

        $simConfigs += [PSCustomObject]$config

        # 설정 요약 표시
        Write-Host ""
        Write-Host "  시뮬레이션 #$i 설정 완료" -ForegroundColor $Colors.Success
        Write-Host "  ──────────────────────────" -ForegroundColor $Colors.Success
        switch ($config.Mode) {
            "korea_random" { 
                Write-Host "  🎯 모드: 전국 완전랜덤 (면적가중치 제거됨)" -ForegroundColor $Colors.Info
            }
            "sido" { 
                Write-Host "  🎯 모드: $($config.SidoName) 지역" -ForegroundColor $Colors.Info
            }
            "manual" { 
                Write-Host "  🎯 모드: 수동 ($($config.Latitude), $($config.Longitude))" -ForegroundColor $Colors.Info
            }
        }
        Write-Host "  ⚙️ 환자: $($config.Parameters.incident_size), 구급차: $($config.Parameters.amb_size), UAV: $($config.Parameters.uav_size)" -ForegroundColor $Colors.Debug
        Write-Host ""
    }

    return $simConfigs
}

# ==================== 실행 전 검토 함수 ====================

function Show-ExperimentReview {
    param(
        [array]$SimConfigs,
        [hashtable]$GlobalParams
    )
    
    Write-StyledHeader "📋 실험 설정 최종 검토" $Colors.Header
    
    # 전체 요약 계산
    $totalSims = $SimConfigs.Count
    
    # 예상 소요시간 계산 (4분 기준)
    $baseTimePerSim = 4  # 디폴트 기준 4분
    $estimatedMinutes = $totalSims * $baseTimePerSim
    $estimatedHours = [math]::Floor($estimatedMinutes / 60)
    $remainingMinutes = $estimatedMinutes % 60
    
    $timeText = if ($estimatedHours -gt 0) {
        "${estimatedHours}시간 ${remainingMinutes}분"
    } else {
        "${estimatedMinutes}분"
    }
    



    # 시간 텍스트 기본값 보정
    if (-not $timeText) { $timeText = "N/A" }


    Write-Host ""
    Write-Host "  예상 소요시간" -ForegroundColor $Colors.Header
    Write-Host "  ─────────────" -ForegroundColor $Colors.Header
    Write-Host "  예상 소요시간: $timeText" -ForegroundColor $Colors.Info
    Write-Host ""


    
    foreach ($config in $SimConfigs) {
        # 안전한 속성 접근
        $configParams = if ($config -is [PSCustomObject]) { 
            $config.Parameters 
        } else { 
            $config["Parameters"] 
        }
        
        # 좌표 정보
        $locationInfo = switch ($config.Mode) {
            "korea_random" { 
                "전국완전랜덤 (17개 시도 동일확률)" 
            }
            "sido" { 
                "시도: $($config.SidoName)" 
            }
            "manual" { 
                "수동: ($($config.Latitude), $($config.Longitude))" 
            }
        }
        
        # 파라미터 정보 추출 (안전하게)
        $incidentSize = if ($configParams -is [PSCustomObject]) {
            $configParams.incident_size
        } else {
            $configParams["incident_size"]
        }
        $ambSize = if ($configParams -is [PSCustomObject]) {
            $configParams.amb_size
        } else {
            $configParams["amb_size"]
        }
        $uavSize = if ($configParams -is [PSCustomObject]) {
            $configParams.uav_size
        } else {
            $configParams["uav_size"]
        }
        $ambVelocity = if ($configParams -is [PSCustomObject]) {
            $configParams.amb_velocity
        } else {
            $configParams["amb_velocity"]
        }
        $uavVelocity = if ($configParams -is [PSCustomObject]) {
            $configParams.uav_velocity
        } else {
            $configParams["uav_velocity"]
        }
        $totalSamples = if ($configParams -is [PSCustomObject]) {
            $configParams.total_samples
        } else {
            $configParams["total_samples"]
        }
        $randomSeed = if ($configParams -is [PSCustomObject]) {
            $configParams.random_seed
        } else {
            $configParams["random_seed"]
        }
        
        Write-Host ""
        Write-Host "  시뮬레이션 #$($config.Id)" -ForegroundColor $Colors.Highlight
        Write-Host "  ────────────────────────" -ForegroundColor $Colors.Highlight
        Write-Host "    위치: $locationInfo" -ForegroundColor $Colors.Info
        Write-Host "    환자: ${incidentSize}명, 구급차: ${ambSize}대, UAV: ${uavSize}대" -ForegroundColor $Colors.Info
        Write-Host "    속도: 구급차 ${ambVelocity}km/h, UAV ${uavVelocity}km/h" -ForegroundColor $Colors.Info
        Write-Host "    반복: ${totalSamples}회, 시드: $randomSeed" -ForegroundColor $Colors.Info
    }
    
    # API 사용량 정확 계산
    $totalDirectionsCalls = 0
    $totalGeocodingCalls = 0
    
    foreach ($config in $SimConfigs) {
        # 파라미터 안전하게 추출
        $configParams = if ($config -is [PSCustomObject]) { 
            $config.Parameters 
        } else { 
            $config["Parameters"] 
        }
        
        $incidentSize = if ($configParams -is [PSCustomObject]) {
            $configParams.incident_size
        } else {
            $configParams["incident_size"]
        }
        
        # Directions API 호출량 계산
        $directionsPerSim = $incidentSize + $incidentSize + ($incidentSize * ($incidentSize - 1) / 2)
        $totalDirectionsCalls += $directionsPerSim
        
        # Geocoding API: 좌표 생성 성공시 1회 (재시도 포함 최대 5회)
        $geocodingPerSim = if ($config.Mode -ne "manual") { 5 } else { 0 }  # 수동입력은 geocoding 불필요
        $totalGeocodingCalls += $geocodingPerSim
    }

    $totalAPICalls = $totalDirectionsCalls + $totalGeocodingCalls
    
    Write-Host ""
    Write-Host "  ⚠️ 예상 Naver API 호출량" -ForegroundColor $Colors.Warning
    Write-Host "  ─────────────────────────" -ForegroundColor $Colors.Warning
    Write-Host "    • Directions 5: $($totalDirectionsCalls.ToString('N0'))회 (거리 계산)" -ForegroundColor $Colors.Debug
    Write-Host "    • Reverse Geocoding: $($totalGeocodingCalls.ToString('N0'))회 (좌표 검증)" -ForegroundColor $Colors.Debug
    Write-Host "    • 이 예상 호출: $($totalAPICalls.ToString('N0'))회" -ForegroundColor $Colors.Warning
    
    if ($totalAPICalls -gt 1000) {
        Write-Host "    💰 참고: Naver API 무료 한도 확인 필요" -ForegroundColor $Colors.Warning
    }
    Write-Host ""
}

# ==================== 시뮬레이션 실행 함수들 ====================

function Invoke-ScenarioGeneration {
    param(
        [PSCustomObject]$Config,
        [hashtable]$GlobalParams,
        [hashtable]$ApiKeys
    )
    
    Write-Host ""
    Write-StatusLine "🔧" "시나리오 생성 중" $Colors.Progress "시뮬레이션 #$($Config.Id)"
    
    $startTime = Get-Date
    
    # API 키 환경변수로 설정
    $env:NAVER_CLIENT_ID = $ApiKeys.ClientId
    $env:NAVER_CLIENT_SECRET = $ApiKeys.ClientSecret

    # [ADDED] 병원/AMB/Patient 옵션을 환경변수로 전달
    if ($GlobalParams.ContainsKey('QueuePolicy')) { $env:MCI_QUEUE_POLICY = $GlobalParams.QueuePolicy } else { $env:MCI_QUEUE_POLICY = "0" }
    if ($GlobalParams.ContainsKey('UtilByTier'))  { $env:MCI_UTIL_BY_TIER = $GlobalParams.UtilByTier }
    if ($GlobalParams.ContainsKey('BufferRatio')) { $env:MCI_BUFFER_RATIO = "$($GlobalParams.BufferRatio)" }
    if ($GlobalParams.ContainsKey('PatientJson') -and $GlobalParams.PatientJson) { 
        $env:PATIENT_CONFIG_JSON = $GlobalParams.PatientJson 
    } else { $env:PATIENT_CONFIG_JSON = $null }
    if ($GlobalParams.ContainsKey('MaxSendCoeff') -and $GlobalParams.MaxSendCoeff) { 
        $env:MCI_MAX_SEND_COEFF = $GlobalParams.MaxSendCoeff 
    } else { $env:MCI_MAX_SEND_COEFF = $null }
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    
    # Python 명령어 구성 (공백으로 분리된 인수들)
    $pythonArgs = @(
        "make_csv_yaml_dynamic.py",
        "--base_path", "`"$ProjectPath`"",
        "--incident_size", "$($Config.Parameters.incident_size)",
        "--amb_size", "$($Config.Parameters.amb_size)",
        "--uav_size", "$($Config.Parameters.uav_size)",
        "--amb_velocity", "$($Config.Parameters.amb_velocity)",
        "--uav_velocity", "$($Config.Parameters.uav_velocity)",
        "--total_samples", "$($Config.Parameters.total_samples)",
        "--random_seed", "$($Config.Parameters.random_seed)",
        "--experiment_id", "`"$($GlobalParams.ExperimentId)`""
    )
    # 사용자 입력이 비어있지 않으면 추가
    if (-not [string]::IsNullOrWhiteSpace($GlobalParams.MaxSendCoeff)) {
        $pythonArgs += @("--hospital_max_send_coeff", "`"$($GlobalParams.MaxSendCoeff)`"")
    }
    # 재사용 모드 전달 (config 우선, 없으면 전역값)
    if ($Config.PSObject.Properties.Name -contains "ReuseFrom" -and $Config.ReuseFrom) {
        $pythonArgs += @("--reuse_from", "`"$($Config.ReuseFrom)`"")
    } elseif ($GlobalParams.PSObject.Properties.Name -contains "ReuseFrom" -and $GlobalParams.ReuseFrom) {
        $pythonArgs += @("--reuse_from", "`"$($GlobalParams.ReuseFrom)`"")
        # 요약에도 반영될 수 있도록 Config에 주입
        try { $Config | Add-Member -NotePropertyName ReuseFrom -NotePropertyValue $GlobalParams.ReuseFrom -Force } catch {}
    }

    
    
    # 좌표 방식에 따른 추가 인수
    switch ($Config.Mode) {
        "korea_random" {
            $pythonArgs += @("--generate_coord", "--coord_mode", "korea_random")
        }
        "sido" {
            $pythonArgs += @("--generate_coord", "--coord_mode", "sido", "--sido_name", "`"$($Config.SidoName)`"")
        }
        "manual" {
            $pythonArgs += @("--latitude", "$($Config.Latitude)", "--longitude", "$($Config.Longitude)")
        }
    }
    
    # 명령어 문자열로 결합 (디버그용)
    $cmdString = "python " + ($pythonArgs -join " ")
    Write-Host "     실행 명령: $cmdString" -ForegroundColor $Colors.Debug

    # ===== 핵심 수정: CMD를 통한 conda 환경 실행 =====
    
    # 작업 디렉토리를 ProjectPath로 설정
    Push-Location $ProjectPath
    
    try {
        # CMD를 통해 conda 환경에서 Python 실행
        $condaCmd = "conda activate $CondaEnv"
        $pythonCmd = "python " + ($pythonArgs -join " ")
        $fullCmd = "$condaCmd && $pythonCmd"
        
        Write-Host "     CMD 실행: $fullCmd" -ForegroundColor $Colors.Debug
        
        # CMD 실행 (UTF-8 인코딩 포함)
        $output = & cmd /c "chcp 65001 >nul 2>&1 && $fullCmd" 2>&1
        
        # PowerShell 7에서 문자열 배열을 단일 문자열로 변환
        if ($output -is [array]) {
            $outputStr = $output -join "`n"
        } else {
            $outputStr = $output.ToString()
        }
        
    } catch {
        Write-Host "     ❌ 명령 실행 실패: $($_.Exception.Message)" -ForegroundColor $Colors.Error
        $outputStr = $_.Exception.Message
    } finally {
        # 원래 디렉토리로 복원
        Pop-Location
    }
    
    $duration = ((Get-Date) - $startTime).TotalSeconds

    Write-Host "     Python 출력:" -ForegroundColor $Colors.Debug
    Write-Host "     $outputStr" -ForegroundColor $Colors.Debug

    # 좌표 정보 추출
    $coordinateInfo = @{
        Latitude = $null
        Longitude = $null
        Address = $null
        RoadAddress = $null
        Area1 = $null
        Area2 = $null
        Area3 = $null
        Area4 = $null
    }

    # PowerShell 좌표 정보 추출 로직 (간소화된 버전)

    # 좌표 정보 추출
    $coordinateInfo = @{
        Latitude = $null
        Longitude = $null
        Address = $null
        RoadAddress = $null
        Area1 = $null
        Area2 = $null
        Area3 = $null
        Area4 = $null
    }

    # ===== 1단계: COORDINATE_INFO JSON 파싱 (최우선) =====
    if ($outputStr -match "COORDINATE_INFO:({.*})") {
        try {
            $coordJson = $matches[1] | ConvertFrom-Json
            
            $coordinateInfo.Latitude = $coordJson.latitude
            $coordinateInfo.Longitude = $coordJson.longitude
            $coordinateInfo.Address = $coordJson.full_address
            $coordinateInfo.RoadAddress = $coordJson.road_address
            $coordinateInfo.Area1 = $coordJson.area1
            $coordinateInfo.Area2 = $coordJson.area2
            $coordinateInfo.Area3 = $coordJson.area3
            $coordinateInfo.Area4 = $coordJson.area4
            
            Write-Host "     ✅ COORDINATE_INFO JSON 파싱 성공" -ForegroundColor $Colors.Success
            $coordFound = $true
        } catch {
            Write-Host "     ⚠️ COORDINATE_INFO JSON 파싱 실패: $($_.Exception.Message)" -ForegroundColor $Colors.Warning
            $coordFound = $false
        }
    } else {
        $coordFound = $false
    }

    # ===== 2단계: 기존 패턴 매칭 (백업) =====
    if (-not $coordFound) {
        $coordPatterns = @(
            "📍\s*좌표 생성: \(([0-9\.]+),\s*([0-9\.]+)\)\s*-\s*(.+)",
            "좌표 생성: \(([0-9\.]+),\s*([0-9\.]+)\)\s*-\s*(.+)",
            "좌표.*\(([0-9\.]+),\s*([0-9\.]+)\).*-\s*(.+)"
        )
        
        foreach ($pattern in $coordPatterns) {
            if ($outputStr -match $pattern) {
                $coordinateInfo.Latitude = $matches[1]
                $coordinateInfo.Longitude = $matches[2]
                
                if ($matches.Count -gt 3) {
                    $fullAddress = $matches[3].Trim()
                    $coordinateInfo.Address = $fullAddress
                    
                    # 주소 파싱
                    $addressParts = $fullAddress.Split(' ')
                    if ($addressParts.Length -ge 1) {
                        $coordinateInfo.Area1 = $addressParts[0]
                    }
                    if ($addressParts.Length -ge 2) {
                        $coordinateInfo.Area2 = $addressParts[1]
                    }
                    if ($addressParts.Length -ge 3) {
                        $coordinateInfo.Area3 = $addressParts[2]
                    }
                    if ($addressParts.Length -ge 4) {
                        $coordinateInfo.Area4 = ($addressParts[3..($addressParts.Length-1)] -join ' ')
                    }
                }
                
                Write-Host "     ✅ 패턴 매칭 성공" -ForegroundColor $Colors.Success
                $coordFound = $true
                break
            }
        }
    }

    # ===== 3단계: 결과 확인 =====
    if ($coordFound) {
        Write-Host "     ✅ 좌표 정보 추출 성공:" -ForegroundColor $Colors.Success
        Write-Host "       위도: $($coordinateInfo.Latitude)" -ForegroundColor $Colors.Debug
        Write-Host "       경도: $($coordinateInfo.Longitude)" -ForegroundColor $Colors.Debug
        Write-Host "       주소: $($coordinateInfo.Address)" -ForegroundColor $Colors.Debug
        Write-Host "       도로명주소: $($coordinateInfo.RoadAddress)" -ForegroundColor $Colors.Debug
    } else {
        Write-Host "     ❌ 좌표 정보 추출 실패" -ForegroundColor $Colors.Error
        Write-Host "     Python 출력에서 COORDINATE_INFO를 찾을 수 없습니다" -ForegroundColor $Colors.Error
    }

    $dataOrigin = $null
    if ($outputStr -match "DATA_ORIGIN\s*:\s*(.+)") { $dataOrigin = $matches[1].Trim() }

    # Config 경로 추출
    $configPath = $null
    
    # Config 경로 패턴 매칭
    $configPatterns = @(
        "Config 파일 경로:\s*(.+\.yaml)",
        "config.*경로:\s*(.+\.yaml)",
        "✅.*config.*:\s*(.+\.yaml)",
        "Config.*path.*:\s*(.+\.yaml)"
    )
    
    foreach ($pattern in $configPatterns) {
        if ($outputStr -match $pattern) {
            $configPath = $matches[1].Trim().Trim('"', "'")
            Write-Host "     패턴 매칭된 Config 경로: $configPath" -ForegroundColor $Colors.Debug
            break
        }
    }
    
    # 예상 경로 생성
    if (-not $configPath -and $coordinateInfo.Latitude -and $coordinateInfo.Longitude) {
        $coordFolder = "($($coordinateInfo.Latitude),$($coordinateInfo.Longitude))"
        $configPath = Join-Path $ProjectPath "scenarios\$($GlobalParams.ExperimentId)\$coordFolder\config_$coordFolder.yaml"
        Write-Host "     예상 Config 경로 생성: $configPath" -ForegroundColor $Colors.Debug
    }
    
    # 절대경로로 변환
    if ($configPath) {
        if (-not [System.IO.Path]::IsPathRooted($configPath)) {
            $configPath = Join-Path $ProjectPath $configPath
        }
        $configPath = [System.IO.Path]::GetFullPath($configPath)
        
        Write-Host "     최종 Config 경로: $configPath" -ForegroundColor $Colors.Debug
        
        if (Test-Path $configPath) {
            Write-StatusLine "✅" "시나리오 생성 완료" $Colors.Success "소요시간: $([math]::Round($duration, 1))초"
            Write-Host "     ✅ Config 파일 확인됨: $configPath" -ForegroundColor $Colors.Success
            
            return @{
                ConfigPath = $configPath
                Duration = $duration
                Output = $outputStr
                CoordinateInfo = $coordinateInfo
            }
        } else {
            Write-Host "     ❌ Config 파일이 존재하지 않음: $configPath" -ForegroundColor $Colors.Error
            
            # 최근 생성된 config 파일 찾기
            $recentConfigs = Get-ChildItem -Path $ProjectPath -Recurse -Filter "config_*.yaml" -ErrorAction SilentlyContinue | 
                             Sort-Object LastWriteTime -Descending | 
                             Select-Object -First 3
            
            if ($recentConfigs) {
                Write-Host "     🔍 최근 생성된 config 파일들:" -ForegroundColor $Colors.Warning
                foreach ($file in $recentConfigs) {
                    Write-Host "       • $($file.FullName)" -ForegroundColor $Colors.Warning
                }
                
                $configPath = $recentConfigs[0].FullName
                Write-Host "     🔄 최근 파일 사용: $configPath" -ForegroundColor $Colors.Success
                
                return @{
                    ConfigPath = $configPath
                    Duration = $duration
                    Output = $outputStr
                    CoordinateInfo = $coordinateInfo
                }
            }
        }
    }
    
    # 실패한 경우
    Write-StatusLine "❌" "Config 파일을 찾을 수 없음" $Colors.Error
    Write-Host "     전체 Python 출력:" -ForegroundColor $Colors.Error
    Write-Host "     $outputStr" -ForegroundColor $Colors.Error
    
    return @{
        ConfigPath = $null
        Duration = $duration
        Output = $outputStr
        CoordinateInfo = $coordinateInfo
    }
}

function Invoke-Simulation {
    param(
        [string]$ConfigPath,
        [PSCustomObject]$Config,
        [string]$CondaEnv
    )
    
    Write-Host ""
    Write-StatusLine "🚀" "시뮬레이션 실행 중" $Colors.Progress "시뮬레이션 #$($Config.Id)"
    
    $startTime = Get-Date
    
    try {
        # Config 파일 존재 확인
        if (-not (Test-Path $ConfigPath)) {
            Write-StatusLine "❌" "Config 파일 없음" $Colors.Error $ConfigPath
            return @{ Success = $false; Duration = 0 }
        }
        
        # 인코딩 환경변수 설정
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        
        # 작업 디렉토리 설정
        Push-Location $ProjectPath
        
        try {
            # ===== 핵심 수정: CMD를 통한 conda 환경 실행 =====
            $condaCmd = "conda activate $CondaEnv"
            $pythonCmd = "python main.py --config_path `"$ConfigPath`""
            $fullCmd = "$condaCmd && $pythonCmd"
            
            Write-Host "     실행 명령: $fullCmd" -ForegroundColor $Colors.Debug
            
            # CMD 실행
            $result = & cmd /c "chcp 65001 >nul 2>&1 && $fullCmd" 2>&1
            $exitCode = $LASTEXITCODE
            
            # 문자열 변환
            if ($result -is [array]) {
                $resultStr = $result -join "`n"
            } else {
                $resultStr = $result.ToString()
            }
            
        } finally {
            Pop-Location
        }
        
        $elapsed = ((Get-Date) - $startTime).TotalSeconds
        
        # 로그 저장
        $logStatus = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
        $logPath = Save-ExperimentLog -Config $Config -GlobalParams $script:GlobalParams -ConfigPath $ConfigPath -Status $logStatus -ExitCode $exitCode -Output $resultStr
        
        if ($exitCode -eq 0) {
            Write-StatusLine "✅" "시뮬레이션 완료" $Colors.Success "소요시간: $([math]::Round($elapsed, 1))초"
            return @{ Success = $true; Duration = $elapsed; LogPath = $logPath }
        } else {
            Write-StatusLine "❌" "시뮬레이션 실패" $Colors.Error "종료코드: $exitCode"
            
            # 오류 메시지 표시
            $errorLines = $resultStr -split "`n" | Where-Object { $_ -match "error|exception|traceback|ValueError" } | Select-Object -First 5
            foreach ($line in $errorLines) {
                Write-Host "     $line" -ForegroundColor $Colors.Error
            }
            
            return @{ Success = $false; Duration = $elapsed; LogPath = $logPath }
        }
    } catch {
        Write-StatusLine "❌" "시뮬레이션 예외" $Colors.Error $_.Exception.Message
        $logPath = Save-ExperimentLog -Config $Config -GlobalParams $script:GlobalParams -ConfigPath $ConfigPath -Status "EXCEPTION" -ExitCode -1 -Output $_.Exception.Message
        return @{ Success = $false; Duration = 0; LogPath = $logPath }
    }
}

function Invoke-Simulation {
    param(
        [string]$ConfigPath,
        [PSCustomObject]$Config,
        [string]$CondaEnv
    )
    
    Write-Host ""
    Write-StatusLine "🚀" "시뮬레이션 실행 중" $Colors.Progress "시뮬레이션 #$($Config.Id)"
    
    $startTime = Get-Date
    
    try {
        # Config 파일 존재 확인
        if (-not (Test-Path $ConfigPath)) {
            Write-StatusLine "❌" "Config 파일 없음" $Colors.Error $ConfigPath
            return @{ Success = $false; Duration = 0 }
        }
        
        # 인코딩 환경변수 설정
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        
        # conda activate 및 main.py 실행
        $cmd = "conda activate $CondaEnv && cd `"$ProjectPath`" && python -X utf8 main.py --config_path `"$ConfigPath`""
        Write-Host "     실행 명령: $cmd" -ForegroundColor $Colors.Debug
        
        $result = & cmd /c "chcp 65001 >nul && $cmd" 2>&1
        $exitCode = $LASTEXITCODE
        
        $elapsed = ((Get-Date) - $startTime).TotalSeconds
        
        # 상세 로그 저장
        $logStatus = if ($exitCode -eq 0) { "SUCCESS" } else { "FAILED" }
        $logPath = Save-ExperimentLog -Config $Config -GlobalParams $script:GlobalParams -ConfigPath $ConfigPath -Status $logStatus -ExitCode $exitCode -Output ($result -join "`n")
        
        if ($exitCode -eq 0) {
            Write-StatusLine "✅" "시뮬레이션 완료" $Colors.Success "소요시간: $([math]::Round($elapsed, 1))초"
            return @{ Success = $true; Duration = $elapsed; LogPath = $logPath }
        } else {
            Write-StatusLine "❌" "시뮬레이션 실패" $Colors.Error "종료코드: $exitCode"
            
            # 오류 메시지 표시
            $errorLines = $result | Where-Object { $_ -match "error|exception|traceback|ValueError" } | Select-Object -First 5
            foreach ($line in $errorLines) {
                Write-Host "     $line" -ForegroundColor $Colors.Error
            }
            
            return @{ Success = $false; Duration = $elapsed; LogPath = $logPath }
        }
    } catch {
        Write-StatusLine "❌" "시뮬레이션 예외" $Colors.Error $_.Exception.Message
        $logPath = Save-ExperimentLog -Config $Config -GlobalParams $script:GlobalParams -ConfigPath $ConfigPath -Status "EXCEPTION" -ExitCode -1 -Output $_.Exception.Message
        return @{ Success = $false; Duration = 0; LogPath = $logPath }
    }
}

function Save-ExperimentSummary {
    param(
        [array]$SimConfigs,
        [array]$Results,
        [hashtable]$GlobalParams,
        [TimeSpan]$TotalTime,
        [array]$DetailedTimes
    )
    
    $summaryDir = "scenarios\$($GlobalParams.ExperimentId)"
    if (-not (Test-Path $summaryDir)) {
        New-Item -ItemType Directory -Path $summaryDir -Force | Out-Null
    }
    
    # 통합 CSV 생성
    $summaryData = @()
    
    for ($i = 0; $i -lt $SimConfigs.Count; $i++) {
        $config = $SimConfigs[$i]
        
        # 안전한 결과 접근
        $result = if ($i -lt $Results.Count -and $null -ne $Results[$i]) { 
            $Results[$i] 
        } else { 
            @{Success=$false; Duration=0; LogPath=""} 
        }
        
        # 안전한 시간 정보 접근
        $timeDetail = if ($i -lt $DetailedTimes.Count -and $null -ne $DetailedTimes[$i]) { 
            $DetailedTimes[$i] 
        } else { 
            @{
                ScenarioStart = "-"
                ScenarioDuration = 0
                SimulationStart = "-"
                SimulationDuration = 0
                CompleteTime = "-"
                TotalDuration = 0
                CoordinateInfo = @{}
            }
        }
        
        # ===== 좌표 정보 개선된 처리 =====
        $coordInfo = $timeDetail.CoordinateInfo
        if (-not $coordInfo -or $coordInfo -eq @{}) {
            $coordInfo = @{
                Latitude = $null
                Longitude = $null
                Address = $null
                RoadAddress = $null
                Area1 = $null
                Area2 = $null
                Area3 = $null
                Area4 = $null
            }
        }
        
        # 도로명주소 처리 개선
        $roadAddress = if ($coordInfo.RoadAddress -and $coordInfo.RoadAddress.Trim() -ne "") {
            $coordInfo.RoadAddress
        } elseif ($coordInfo.Address -and $coordInfo.Address.Trim() -ne "") {
            # 전체 주소 사용 (더 이상 지번주소라고 명시하지 않음)
            $coordInfo.Address
        } else {
            "주소 정보 없음"
        }
        
        # 안전한 속성 접근
        $configParams = if ($config -is [PSCustomObject]) { 
            $config.Parameters 
        } else { 
            $config["Parameters"] 
        }
        
        $coordText = switch ($config.Mode) {
            "korea_random" { "전국완전랜덤" }
            "sido" { $config.SidoName }
            "manual" { "($($config.Latitude),$($config.Longitude))" }
            default { "알 수 없음" }
        }
        
        # 파라미터 안전하게 추출
        $incidentSize = if ($configParams -is [PSCustomObject]) {
            $configParams.incident_size
        } else {
            $configParams["incident_size"]
        }
        # ... (나머지 파라미터들도 동일하게)
        
        
$summaryData += [PSCustomObject]@{
        '실험ID'              = $GlobalParams.ExperimentId
        '순번'                = $config.Id
        '생성모드'            = $config.Mode
        '생성유형'            = $( if ($dataOrigin) { $dataOrigin } elseif ($Config.PSObject.Properties.Name -contains 'ReuseFrom' -and $Config.ReuseFrom) { '재사용' } else { '신규생성' } )
        '좌표정보'            = $coordText
        '실제위도'            = if ($coordInfo.Latitude) { $coordInfo.Latitude } else { "-" }
        '실제경도'            = if ($coordInfo.Longitude) { $coordInfo.Longitude } else { "-" }
        '주소'                = if ($coordInfo.Address) { $coordInfo.Address } else { "-" }
        '도로명주소'          = $roadAddress
        '시도'                = if ($coordInfo.Area1) { $coordInfo.Area1 } else { "-" }
        '시군구'              = if ($coordInfo.Area2) { $coordInfo.Area2 } else { "-" }
        '읍면동'              = if ($coordInfo.Area3) { $coordInfo.Area3 } else { "-" }
        '리'                  = if ($coordInfo.Area4) { $coordInfo.Area4 } else { "-" }
        '시나리오생성_시작'   = $timeDetail.ScenarioStart
        '시나리오생성_소요(초)' = if ($timeDetail.ScenarioDuration -is [double] -or $timeDetail.ScenarioDuration -is [int]) { [math]::Round($timeDetail.ScenarioDuration, 2) } else { 0 }
        '시뮬레이션_시작'     = $timeDetail.SimulationStart
        '시뮬레이션_소요(초)' = if ($result.Duration -is [double] -or $result.Duration -is [int]) { [math]::Round($result.Duration, 2) } else { 0 }
        '실험_완료시간'       = $timeDetail.CompleteTime
        '좌표별_총소요(초)'    = if ($timeDetail.TotalDuration -is [double] -or $timeDetail.TotalDuration -is [int]) { [math]::Round($timeDetail.TotalDuration, 2) } else { 0 }
        '성공여부'            = if ($result.Success -eq $true) { "성공" } else { "실패" }
        '로그파일'            = if ($result.LogPath) { $result.LogPath } else { "-" }
        '환자수'              = $incidentSize
        'max_send_coeff'      = $( 
            if ($env:MCI_MAX_SEND_COEFF) { 
            $env:MCI_MAX_SEND_COEFF 
            } 
            elseif ($configPath -and -not [string]::IsNullOrWhiteSpace($configPath) -and (Test-Path $configPath)) {
            try { 
                ((Get-Content -Raw $configPath | ConvertFrom-Yaml).hospital.max_send_coeff) -join ',' 
            } catch { 
                $m = [regex]::Match((Get-Content -Raw $configPath), 'max_send_coeff\s*:\s*\[([^\]]+)\]');
                if ($m.Success) { 
                '[' + $m.Groups[1].Value + ']' 
                } else { 
                '[1,1]' 
                } 
            }
            } 
            else { 
            '[1,1]' 
            }
        )
        '구급차수'            = if ($configParams -is [PSCustomObject]) { $configParams.amb_size } else { $configParams["amb_size"] }
        'UAV수'               = if ($configParams -is [PSCustomObject]) { $configParams.uav_size } else { $configParams["uav_size"] }
        '구급차속도'          = if ($configParams -is [PSCustomObject]) { $configParams.amb_velocity } else { $configParams["amb_velocity"] }
        'UAV속도'             = if ($configParams -is [PSCustomObject]) { $configParams.uav_velocity } else { $configParams["uav_velocity"] }
        '시뮬레이션반복'      = if ($configParams -is [PSCustomObject]) { $configParams.total_samples } else { $configParams["total_samples"] }
        '랜덤시드'            = if ($configParams -is [PSCustomObject]) { $configParams.random_seed } else { $configParams["random_seed"] }
}
    }
    
    # CSV로 저장
    $csvPath = "$summaryDir\$($GlobalParams.ExperimentId)_summary.csv"
    $summaryData | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8BOM
    
    Write-StatusLine "📄" "실험 요약 저장" $Colors.Success $csvPath
    
    return $csvPath
}



# ==================== 메인 실행 ====================

Clear-Host
Write-StyledHeader "🔬 MCI 재난 시뮬레이션 자동화 시스템 Complete v5.0 (완전한 버전)" $Colors.Header

Write-Host "  적대적 재난 에이전트 생성을 활용한 복합재난 대응기술개발" -ForegroundColor $Colors.Debug
Write-Host "  개발자: 류연우 | $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor $Colors.Debug
Write-Host ""
Write-Host ""

# 1단계: 필수 설정
if ([string]::IsNullOrWhiteSpace($ProjectPath)) {
    $ProjectPath = Get-ProjectPath
}

if (Test-Path $ProjectPath) {
    Set-Location $ProjectPath
    Write-StatusLine "✅" "프로젝트 경로 확인" $Colors.Success $ProjectPath
} else {
    Write-StatusLine "❌" "프로젝트 경로 오류" $Colors.Error $ProjectPath
    exit 1
}

$condaEnv = Get-CondaEnvironment
$apiKeys = Get-NaverAPIKeys

# 필수 요구사항 검사
$issues = Test-Prerequisites -ProjectPath $ProjectPath
if ($issues.Count -gt 0) {
    Write-Host ""
    Write-Host "⚠️ 다음 문제들을 해결해주세요:" -ForegroundColor $Colors.Warning
    foreach ($issue in $issues) {
        Write-Host "  • $issue" -ForegroundColor $Colors.Error
    }
    exit 1
}

# 1.5단계: 패키지 설치 확인
Install-PythonPackages -CondaEnv $condaEnv

# 2단계: 전역 설정
$simCount = Get-SimulationCount
$globalParams = Get-GlobalParameters

# [ADDED] 고급 옵션 입력: 병원선정/AMB/Patient
$advancedOpts = Get-AdvancedOptions
$globalParams["QueuePolicy"]  = $advancedOpts.QueuePolicy
$globalParams["UtilByTier"]   = $advancedOpts.UtilByTier
$globalParams["BufferRatio"]  = $advancedOpts.BufferRatio
$globalParams["AmbTarget"]    = $advancedOpts.AmbTarget
$globalParams["PatientJson"]  = $advancedOpts.PatientJson
$globalParams["MaxSendCoeff"] = $advancedOpts.MaxSendCoeff

# 전역 변수에 저장 (로그 함수에서 사용)
$script:GlobalParams = $globalParams

# 3단계: 디폴트 파라미터
$defaultParams = Get-DefaultParameters
$useDefaultAll = Confirm-DefaultSettings $defaultParams

# 4단계: 시도 목록 로드
$script:AvailableSidos = Get-AvailableSidos -ProjectPath $ProjectPath

# 5단계: 개별 시뮬레이션 설정
$simConfigs = Set-IndividualSimulations -SimCount $simCount -DefaultParams $defaultParams -AvailableSidos $script:AvailableSidos -UseDefaultAll $useDefaultAll

# 6단계: 실행 전 검토
Show-ExperimentReview -SimConfigs $simConfigs -GlobalParams $globalParams

if (-not $SkipConfirmation) {
    $confirm = Read-Host "`n계속하시겠습니까? [Y/N]"
    if ($confirm -ne 'Y' -and $confirm -ne 'y') {
        Write-StatusLine "ℹ️" "사용자 취소" $Colors.Warning
        exit 0
    }
}

# 7단계: 실험 실행 (수정됨 - 배열 크기 일치 보장)
$experimentStartTime = Get-Date
$results = @()
$detailedTimes = @()

Write-Host ""
Write-StyledHeader "🔥 실험 진행" $Colors.Progress

# 사전에 배열 크기를 simConfigs와 동일하게 초기화
for ($i = 0; $i -lt $simConfigs.Count; $i++) {
    $results += @{ Success = $false; Duration = 0; LogPath = "" }
    $detailedTimes += @{
        ScenarioStart = "-"
        ScenarioDuration = 0
        SimulationStart = "-"
        SimulationDuration = 0
        CompleteTime = "-"
        TotalDuration = 0
    }
}

for ($i = 0; $i -lt $simConfigs.Count; $i++) {
    $config = $simConfigs[$i]
    $idx = $i + 1
    
    Write-Host ""
    
    # 진행 상황 헤더 (개선된 UI)
    Write-Host "  🚀 실험 #$idx 시작" -ForegroundColor $Colors.Progress
    Write-Host "  ────────────────────" -ForegroundColor $Colors.Progress
    Write-Host "  [$idx/$($simConfigs.Count)] 실험 진행 중..." -ForegroundColor $Colors.Info
    Write-Host ""
    Write-Host "  좌표: $(switch ($config.Mode) {
        'korea_random' { '전국완전랜덤 (17개 시도 동일확률)' }
        'sido' { $config.SidoName }
        'manual' { "($($config.Latitude), $($config.Longitude))" }
    })" -ForegroundColor $Colors.Info
    Write-Host "  환자: $($config.Parameters.incident_size)명, 차량: 구급차 $($config.Parameters.amb_size)대 + UAV $($config.Parameters.uav_size)대" -ForegroundColor $Colors.Info
    Write-Host ""
    
    $coordStartTime = Get-Date
    
    # 시나리오 생성
    $scenarioStartTime = Get-Date
    $scenarioResult = Invoke-ScenarioGeneration -Config $config -GlobalParams $globalParams -ApiKeys $apiKeys
    
    $simResult = @{ Success = $false; Duration = 0; LogPath = "" }
    $simStartTime = $null
    
    if ($scenarioResult.ConfigPath) {
        # 시뮬레이션 실행
        $simStartTime = Get-Date
        $simResult = Invoke-Simulation -ConfigPath $scenarioResult.ConfigPath -Config $config -CondaEnv $condaEnv
    } else {
        Write-StatusLine "❌" "시나리오 생성 실패" $Colors.Error
        # 실패 로그 저장
        $logPath = Save-ExperimentLog -Config $config -GlobalParams $globalParams -ConfigPath "N/A" -Status "SCENARIO_FAILED" -ExitCode -1 -Output $scenarioResult.Output
        $simResult.LogPath = $logPath
    }
    
    $coordEndTime = Get-Date
    $coordElapsed = ($coordEndTime - $coordStartTime).TotalSeconds
    
    # 좌표 정보 저장
    $coordinateInfo = $scenarioResult.CoordinateInfo
    if (-not $coordinateInfo) {
        $coordinateInfo = @{
            Latitude = $null
            Longitude = $null
            Address = $null
            RoadAddress = $null
            Area1 = $null
            Area2 = $null
            Area3 = $null
            Area4 = $null
        }
    }
    
    # 결과 저장 (배열 인덱스에 직접 할당)
    $results[$i] = $simResult
    $detailedTimes[$i] = @{
        ScenarioStart = $scenarioStartTime.ToString("yyyy-MM-dd HH:mm:ss")
        ScenarioDuration = $scenarioResult.Duration
        SimulationStart = if ($simStartTime) { $simStartTime.ToString("yyyy-MM-dd HH:mm:ss") } else { "-" }
        SimulationDuration = $simResult.Duration
        CompleteTime = $coordEndTime.ToString("yyyy-MM-dd HH:mm:ss")
        TotalDuration = $coordElapsed
        CoordinateInfo = $coordinateInfo
    }
    
    # 진행률 및 ETA 표시
    $elapsed = (Get-Date) - $experimentStartTime
    Show-ProgressBar -Current $idx -Total $simConfigs.Count -Activity "실험 진행" -Elapsed $elapsed -ShowETA $true
    Write-Host ""
    
    # 실험 완료 상태
    $statusIcon = if ($simResult.Success) { "✅" } else { "❌" }
    $statusText = if ($simResult.Success) { "성공" } else { "실패" }
    $statusColor = if ($simResult.Success) { $Colors.Success } else { $Colors.Error }
    
    Write-Host ""
    Write-Host "$statusIcon 실험 #$idx $statusText - 소요시간: $([math]::Round($coordElapsed, 1))초" -ForegroundColor $statusColor
}

$totalTime = (Get-Date) - $experimentStartTime

# ==================== 실험 결과 출력 수정 ====================

Write-Host ""
Write-StyledHeader "📊 실험 결과 요약" $Colors.Header

# 정확한 성공/실패 통계 계산
$totalExperiments = $simConfigs.Count
$successCount = 0
$failCount = 0

# 결과 배열에서 정확한 카운트
for ($i = 0; $i -lt $results.Count; $i++) {
    if ($results[$i] -and $results[$i].Success -eq $true) {
        $successCount++
    } else {
        $failCount++
    }
}

# 성공률 계산 (안전한 나누기)
$successRate = if ($totalExperiments -gt 0) {
    [math]::Round(($successCount / $totalExperiments) * 100, 1)
} else {
    0
}

# 평균 시간 계산 (안전한 처리)
$avgScenarioTime = if ($detailedTimes.Count -gt 0) {
    $validScenarioTimes = $detailedTimes | Where-Object { 
        $_.ScenarioDuration -is [double] -or $_.ScenarioDuration -is [int] -and $_.ScenarioDuration -gt 0
    } | ForEach-Object { $_.ScenarioDuration }
    
    if ($validScenarioTimes.Count -gt 0) {
        [math]::Round(($validScenarioTimes | Measure-Object -Average).Average, 1)
    } else { 0 }
} else { 0 }

$avgSimTime = if ($results.Count -gt 0) {
    $validSimTimes = $results | Where-Object { 
        $_.Duration -is [double] -or $_.Duration -is [int] -and $_.Duration -gt 0
    } | ForEach-Object { $_.Duration }
    
    if ($validSimTimes.Count -gt 0) {
        [math]::Round(($validSimTimes | Measure-Object -Average).Average, 1)
    } else { 0 }
} else { 0 }

# 깔끔한 결과 요약
Write-Host ""
Write-Host "  🎉 실험 완료" -ForegroundColor $Colors.Success
Write-Host "  ──────────────" -ForegroundColor $Colors.Success
Write-Host "  총 소요시간: $($totalTime.ToString('hh\:mm\:ss'))" -ForegroundColor $Colors.Info
Write-Host "" -ForegroundColor $Colors.Info
Write-Host "  설정한 실험: $totalExperimentsᄀ개" -ForegroundColor $Colors.Info
Write-Host "  실제 결과: $($results.Count)개" -ForegroundColor $Colors.Info
Write-Host "  성공: $successCountᄀ개" -ForegroundColor $Colors.Info
Write-Host "  실패: $failCountᄀ개" -ForegroundColor $Colors.Info
Write-Host "  성공률: $successRate%" -ForegroundColor $Colors.Info
Write-Host ""
Write-Host "  평균 시나리오 생성: ${avgScenarioTime}초" -ForegroundColor $Colors.Info
Write-Host "  평균 시뮬레이션: ${avgSimTime}초" -ForegroundColor $Colors.Info
Write-Host ""

# 개별 실험 결과 요약 (정확한 매칭)
if ($results.Count -gt 0) {
    Write-Host ""
    Write-Host "📋 개별 실험 결과:" -ForegroundColor $Colors.Accent
    
    for ($i = 0; $i -lt $simConfigs.Count; $i++) {
        $result = if ($i -lt $results.Count) { $results[$i] } else { @{Success=$false; Duration=0; LogPath=""} }
        $config = $simConfigs[$i]
        
        $statusIcon = if ($result.Success) { "✅" } else { "❌" }
        $statusText = if ($result.Success) { "성공" } else { "실패" }
        $statusColor = if ($result.Success) { $Colors.Success } else { $Colors.Error }
        
        $locationText = switch ($config.Mode) {
            "korea_random" { "전국완전랜덤" }
            "sido" { $config.SidoName }
            "manual" { "($($config.Latitude),$($config.Longitude))" }
        }
        
        $logText = if ($result.LogPath) { " [로그: $($result.LogPath)]" } else { "" }
        $resultDuration = if ($result.Duration -is [double] -or $result.Duration -is [int]) { $result.Duration } else { 0 }
        
        Write-Host ("  {0} 실험 #{1}: {2} - {3} ({4:F1}초){5}" -f $statusIcon, $config.Id, $statusText, $locationText, $resultDuration, $logText) -ForegroundColor $statusColor
    }
}

# 실험 요약 저장
Save-ExperimentSummary -SimConfigs $simConfigs -Results $results -GlobalParams $globalParams -TotalTime $totalTime -DetailedTimes $detailedTimes
$global:LastSummaryPath = 'Save-ExperimentSummary -SimConfigs $simConfigs -Results $results -GlobalParams $globalParams -TotalTime $totalTime -DetailedTimes $detailedTimes' 



# 실험 로그 표시
Show-ExperimentLogs -GlobalParams $globalParams



Write-Host ""

# 최종 완료 메시지 (개선된 UI)
Write-Host ""
Write-Host "  🎉 작업 완료" -ForegroundColor $Colors.Success
Write-Host "  ──────────────" -ForegroundColor $Colors.Success
Write-Host "  모든 실험이 완료되었습니다!" -ForegroundColor $Colors.Info
Write-Host "" -ForegroundColor $Colors.Info
Write-Host "  📂 결과 위치: scenarios\$($globalParams.ExperimentId)\" -ForegroundColor $Colors.Info
Write-Host "  📊 통합 요약: scenarios\$($globalParams.ExperimentId)\$($globalParams.ExperimentId)_summary.csv" -ForegroundColor $Colors.Info
Write-Host "  📝 실험 로그: experiment_logs\ 폴더" -ForegroundColor $Colors.Info
Write-Host "" -ForegroundColor $Colors.Info


if (-not $SkipConfirmation) {
    Write-Host ""
    Read-Host "엔터 키를 눌러 종료하세요"
}