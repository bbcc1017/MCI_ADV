# 🔬 MCI 재난 시뮬레이션 자동화 시스템
# 작성자: 류연우 - 적대적 재난 에이전트 생성을 활용한 복합재난 대응기술개발
# 수정: 1) weighted=False 반영, 2) UI 개선 및 정리, 3) 진행상황 표시 개선

param(
    [string]$ProjectPath = "",
    [switch]$SkipConfirmation
)

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
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Color
    Write-Host " $Text " -ForegroundColor $Color
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor $Color
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
    
    $bar = "▓" * $filled + "░" * $empty
    
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
    
    Write-Host "📝 실험 로그 저장: $logPath" -ForegroundColor $Colors.Debug
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

function Get-CondaEnvironment {
    Write-StyledHeader "🐍 Conda 환경 탐지" $Colors.Header
    
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
                return "MCI"
            }
        }
        
        Write-Host "사용 가능한 Conda 환경:" -ForegroundColor $Colors.Info
        for ($i = 0; $i -lt $envs.Count; $i++) {
            Write-Host "  [$($i+1)] $($envs[$i])" -ForegroundColor $Colors.Highlight
        }
        
        $choice = Read-Host "환경 번호 선택"
        $selectedEnv = $envs[[int]$choice - 1]
        
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
    
    Write-StatusLine "🔍" "설치된 패키지 확인 중..." $Colors.Info
    
    # 현재 설치된 패키지 목록 가져오기
    $installedPackages = @()
    $missingPackages = @()
    $conflictPackages = @()
    
    try {
        $condaList = & conda list -n $CondaEnv 2>$null
        
        foreach ($pkg in $requiredPackages) {
            $packageLine = $condaList | Where-Object { $_ -match "^$pkg\s+" } | Select-Object -First 1
            
            if ($packageLine) {
                $parts = $packageLine -split '\s+'
                $version = $parts[1]
                $channel = if ($parts.Count -gt 3) { $parts[3] } else { "unknown" }
                
                # 패키지는 있지만 pip으로 설치된 경우 (DLL 충돌 위험)
                if ($channel -eq "pypi") {
                    $conflictPackages += @{Name = $pkg; Version = $version; Channel = $channel}
                    Write-StatusLine "⚠️" "$pkg" $Colors.Warning "$version (pip 설치 - 충돌 위험)"
                } else {
                    $installedPackages += @{Name = $pkg; Version = $version; Channel = $channel}
                    Write-StatusLine "✅" "$pkg" $Colors.Success "$version ($channel)"
                }
            } else {
                $missingPackages += $pkg
                Write-StatusLine "❌" "$pkg" $Colors.Error "미설치"
            }
        }
        
    } catch {
        Write-StatusLine "❌" "패키지 목록 확인 실패" $Colors.Error $_.Exception.Message
        return
    }
    
    # 결과 요약
    Write-Host ""
    Write-InfoBox "📊 패키지 설치 상태" @(
        "✅ 정상 설치: $($installedPackages.Count)개",
        "❌ 미설치: $($missingPackages.Count)개", 
        "⚠️ pip 충돌 위험: $($conflictPackages.Count)개"
    )
    
    # 설치가 필요한 경우만 진행
    if ($missingPackages.Count -eq 0 -and $conflictPackages.Count -eq 0) {
        Write-StatusLine "🎉" "모든 패키지가 이미 정상 설치되어 있습니다!" $Colors.Success
        return
    }
    
    Write-Host ""
    
    # pip 충돌 패키지 처리
    if ($conflictPackages.Count -gt 0) {
        Write-Host "⚠️ 다음 패키지들이 pip으로 설치되어 DLL 충돌을 일으킬 수 있습니다:" -ForegroundColor $Colors.Warning
        foreach ($pkg in $conflictPackages) {
            Write-Host "  • $($pkg.Name) ($($pkg.Version))" -ForegroundColor $Colors.Warning
        }
        Write-Host ""
        
        $fixConflicts = Read-Host "pip 패키지를 제거하고 conda-forge로 재설치하시겠습니까? [Y/N]"
        
        if ($fixConflicts -eq 'Y' -or $fixConflicts -eq 'y') {
            Write-StatusLine "🔧" "pip 패키지 제거 및 재설치 중..." $Colors.Progress
            
            foreach ($pkg in $conflictPackages) {
                try {
                    # pip으로 제거
                    Write-Host "  • $($pkg.Name) 제거 중..." -ForegroundColor $Colors.Debug
                    & cmd /c "conda activate $CondaEnv && pip uninstall $($pkg.Name) -y" 2>&1 | Out-Null
                    
                    # conda-forge로 설치
                    Write-Host "  • $($pkg.Name) conda-forge 설치 중..." -ForegroundColor $Colors.Debug
                    $result = & cmd /c "conda activate $CondaEnv && conda install -c conda-forge $($pkg.Name) -y" 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-StatusLine "✅" "$($pkg.Name) 재설치 완료" $Colors.Success
                    } else {
                        Write-StatusLine "❌" "$($pkg.Name) 재설치 실패" $Colors.Error
                        # 실패 시 미설치 목록에 추가
                        if ($pkg.Name -notin $missingPackages) {
                            $missingPackages += $pkg.Name
                        }
                    }
                } catch {
                    Write-StatusLine "❌" "$($pkg.Name) 처리 실패" $Colors.Error $_.Exception.Message
                    if ($pkg.Name -notin $missingPackages) {
                        $missingPackages += $pkg.Name
                    }
                }
            }
        } else {
            # 충돌 패키지를 미설치 목록에 추가 (재설치 대상)
            foreach ($pkg in $conflictPackages) {
                if ($pkg.Name -notin $missingPackages) {
                    $missingPackages += $pkg.Name
                }
            }
        }
    }
    
    # 미설치 패키지 설치
    if ($missingPackages.Count -gt 0) {
        Write-Host ""
        Write-Host "❌ 다음 패키지들을 설치해야 합니다:" -ForegroundColor $Colors.Error
        foreach ($pkg in $missingPackages) {
            Write-Host "  • $pkg" -ForegroundColor $Colors.Error
        }
        Write-Host ""
        
        $installMissing = Read-Host "누락된 패키지들을 conda-forge에서 설치하시겠습니까? [Y/N]"
        
        if ($installMissing -eq 'Y' -or $installMissing -eq 'y') {
            Write-StatusLine "📥" "누락 패키지 설치 중..." $Colors.Progress
            
            # 패키지를 하나씩 설치 (실패 시 개별 처리 가능)
            $successCount = 0
            $failCount = 0
            
            foreach ($pkg in $missingPackages) {
                try {
                    Write-Host "  • $pkg 설치 중..." -ForegroundColor $Colors.Debug
                    $result = & cmd /c "conda activate $CondaEnv && conda install -c conda-forge $pkg -y" 2>&1
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-StatusLine "✅" "$pkg 설치 완료" $Colors.Success
                        $successCount++
                    } else {
                        Write-StatusLine "❌" "$pkg conda 설치 실패" $Colors.Warning
                        
                        # conda 실패 시 pip으로 재시도 (geopandas 제외)
                        if ($pkg -notin @("geopandas", "shapely", "fiona", "pyproj")) {
                            Write-Host "    → pip으로 재시도..." -ForegroundColor $Colors.Debug
                            $pipResult = & cmd /c "conda activate $CondaEnv && pip install $pkg" 2>&1
                            
                            if ($LASTEXITCODE -eq 0) {
                                Write-StatusLine "✅" "$pkg pip 설치 완료" $Colors.Success
                                $successCount++
                            } else {
                                Write-StatusLine "❌" "$pkg 완전 실패" $Colors.Error
                                $failCount++
                            }
                        } else {
                            Write-StatusLine "❌" "$pkg 설치 실패 (pip 사용 불가)" $Colors.Error
                            $failCount++
                        }
                    }
                } catch {
                    Write-StatusLine "❌" "$pkg 설치 예외" $Colors.Error $_.Exception.Message
                    $failCount++
                }
                
                # 각 패키지 설치 후 잠시 대기 (시스템 안정성)
                Start-Sleep -Milliseconds 500
            }
            
            Write-Host ""
            Write-StatusLine "📊" "설치 완료" $Colors.Info "성공: $successCount개, 실패: $failCount개"
            
            if ($failCount -eq 0) {
                Write-StatusLine "🎉" "모든 패키지 설치 완료!" $Colors.Success
            } elseif ($successCount -gt 0) {
                Write-StatusLine "⚠️" "일부 패키지 설치 실패" $Colors.Warning "수동 설치 필요"
            } else {
                Write-StatusLine "❌" "패키지 설치 실패" $Colors.Error "환경 확인 필요"
            }
        } else {
            Write-StatusLine "⏭️" "패키지 설치 건너뛰기" $Colors.Info
            Write-Host "⚠️ 일부 패키지가 없어 시뮬레이션이 실패할 수 있습니다." -ForegroundColor $Colors.Warning
        }
    }
    
    Write-Host ""
    Write-Host "💡 팁: 패키지 충돌을 피하려면 conda-forge 채널만 사용하세요!" -ForegroundColor $Colors.Info
    Write-Host "   conda install -c conda-forge [패키지명]" -ForegroundColor $Colors.Debug
}

# ==================== 나머지 함수들 ====================

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
                    $config = $simConfigs[$i-2].Clone()
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
    $randomCount = ($SimConfigs | Where-Object { $_.Mode -eq "korea_random" }).Count
    $sidoCount = ($SimConfigs | Where-Object { $_.Mode -eq "sido" }).Count
    $manualCount = ($SimConfigs | Where-Object { $_.Mode -eq "manual" }).Count
    
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
    
    # 깔끔한 요약 박스
    Write-Host ""
    Write-Host "  실험 요약" -ForegroundColor $Colors.Header
    Write-Host "  ──────────" -ForegroundColor $Colors.Header
    Write-Host "  총 시뮬레이션: $totalSims개" -ForegroundColor $Colors.Info
    Write-Host "  예상 소요시간: $timeText" -ForegroundColor $Colors.Info
    Write-Host "  생성 모드 분포:" -ForegroundColor $Colors.Info
    Write-Host "    • 전국랜덤: $randomCount개 (완전균등확률)" -ForegroundColor $Colors.Debug
    Write-Host "    • 시도선택: $sidoCount개" -ForegroundColor $Colors.Debug
    Write-Host "    • 수동입력: $manualCount개" -ForegroundColor $Colors.Debug
    Write-Host ""
    
    Write-Host ""
    Write-Host "📝 각 시뮬레이션 상세 설정:" -ForegroundColor $Colors.Accent
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
    Write-Host "    • 총 예상 호출: $($totalAPICalls.ToString('N0'))회" -ForegroundColor $Colors.Warning
    
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
    
    # Python 인코딩 환경변수 강제 설정
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    
    # Python 명령어 구성
    $baseCmd = "python -X utf8 make_csv_yaml_dynamic.py " +
               "--base_path `"$ProjectPath`" " +
               "--incident_size $($Config.Parameters.incident_size) " +
               "--amb_size $($Config.Parameters.amb_size) " +
               "--uav_size $($Config.Parameters.uav_size) " +
               "--amb_velocity $($Config.Parameters.amb_velocity) " +
               "--uav_velocity $($Config.Parameters.uav_velocity) " +
               "--total_samples $($Config.Parameters.total_samples) " +
               "--random_seed $($Config.Parameters.random_seed) " +
               "--experiment_id `"$($GlobalParams.ExperimentId)`""
    
    # 좌표 방식에 따른 명령어 완성
    $pythonCmd = switch ($Config.Mode) {
        "korea_random" {
            $baseCmd + " --generate_coord --coord_mode korea_random"
        }
        "sido" {
            $baseCmd + " --generate_coord --coord_mode sido --sido_name `"$($Config.SidoName)`""
        }
        "manual" {
            $baseCmd + " --latitude $($Config.Latitude) --longitude $($Config.Longitude)"
        }
    }

    if ([string]::IsNullOrWhiteSpace($pythonCmd)) {
        return @{
            ConfigPath = $null
            Duration = 0
            Output = "pythonCmd가 비어 있음"
            CoordinateInfo = $null
        }
    }
    
    Write-Host "     실행 명령: $pythonCmd" -ForegroundColor $Colors.Debug

    # UTF-8 출력 강제
    $output = & cmd /c "chcp 65001 >nul && $pythonCmd" 2>&1
    $outputStr = $output -join "`n"

    $duration = ((Get-Date) - $startTime).TotalSeconds

    # 좌표 정보 추출 (Python 출력에서)
    $coordinateInfo = @{
        Latitude = $null
        Longitude = $null
        Address = $null
        RoadAddress = $null
        Area1 = $null
        Area2 = $null
        Area3 = $null
    }
    
    # 좌표 정보 파싱
    $coordLine = $outputStr | Select-String "좌표 생성: \(([0-9\.]+),([0-9\.]+)\) - (.+)" | Select-Object -First 1
    if ($coordLine) {
        $matches = [regex]::Match($coordLine.Line, "좌표 생성: \(([0-9\.]+),([0-9\.]+)\) - (.+)")
        if ($matches.Success) {
            $coordinateInfo.Latitude = $matches.Groups[1].Value
            $coordinateInfo.Longitude = $matches.Groups[2].Value
            $addressParts = $matches.Groups[3].Value.Split(' ')
            if ($addressParts.Length -ge 2) {
                $coordinateInfo.Area1 = $addressParts[0]
                $coordinateInfo.Area2 = $addressParts[1]
                if ($addressParts.Length -ge 3) {
                    $coordinateInfo.Area3 = $addressParts[2]
                }
                $coordinateInfo.Address = $matches.Groups[3].Value
            }
        }
    }

    # Config 경로 추출
    $configLine = $outputStr | Select-String "Config 파일 경로:" | Select-Object -Last 1
    if ($configLine) {
        $configPath = $configLine.ToString().Split(":")[-1].Trim()

        # 절대 경로로 변환
        if (-not [System.IO.Path]::IsPathRooted($configPath)) {
            $configPath = Join-Path $ProjectPath $configPath
        }

        Write-StatusLine "✅" "시나리오 생성 완료" $Colors.Success "소요시간: $([math]::Round($duration, 1))초"

        if (Test-Path $configPath) {
            return @{
                ConfigPath = $configPath
                Duration = $duration
                Output = $outputStr
                CoordinateInfo = $coordinateInfo
            }
        } else {
            Write-StatusLine "❌" "Config 파일이 존재하지 않음" $Colors.Error $configPath
            return @{
                ConfigPath = $null
                Duration = $duration
                Output = $outputStr
                CoordinateInfo = $coordinateInfo
            }
        }
    } else {
        Write-StatusLine "❌" "Config 경로를 찾을 수 없음" $Colors.Error
        return @{
            ConfigPath = $null
            Duration = $duration
            Output = $outputStr
            CoordinateInfo = $coordinateInfo
        }
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
    
    # 통합 CSV 생성 (UTF8BOM 인코딩)
    $summaryData = @()
    
    # 수정: Results 배열이 SimConfigs와 같은 길이가 되도록 보장
    for ($i = 0; $i -lt $SimConfigs.Count; $i++) {
        $config = $SimConfigs[$i]
        
        # 안전한 결과 접근 - 배열 범위 체크
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
                CoordinateInfo = @{
                    Latitude = $null
                    Longitude = $null
                    Address = $null
                    RoadAddress = $null
                    Area1 = $null
                    Area2 = $null
                    Area3 = $null
                }
            }
        }
        
        # 좌표 정보 추출
        $coordInfo = $timeDetail.CoordinateInfo
        if (-not $coordInfo) {
            $coordInfo = @{
                Latitude = $null
                Longitude = $null
                Address = $null
                RoadAddress = $null
                Area1 = $null
                Area2 = $null
                Area3 = $null
            }
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
        
        $summaryData += [PSCustomObject]@{
            '실험ID' = $GlobalParams.ExperimentId
            '순번' = $config.Id
            '생성모드' = $config.Mode
            '좌표정보' = $coordText
            '실제위도' = if ($coordInfo.Latitude) { $coordInfo.Latitude } else { "-" }
            '실제경도' = if ($coordInfo.Longitude) { $coordInfo.Longitude } else { "-" }
            '주소' = if ($coordInfo.Address) { $coordInfo.Address } else { "-" }
            '도로명주소' = if ($coordInfo.RoadAddress) { $coordInfo.RoadAddress } else { "-" }
            '시도' = if ($coordInfo.Area1) { $coordInfo.Area1 } else { "-" }
            '시군구' = if ($coordInfo.Area2) { $coordInfo.Area2 } else { "-" }
            '읍면동' = if ($coordInfo.Area3) { $coordInfo.Area3 } else { "-" }
            '시나리오생성_시작' = $timeDetail.ScenarioStart
            '시나리오생성_소요(초)' = if ($timeDetail.ScenarioDuration -is [double] -or $timeDetail.ScenarioDuration -is [int]) {
                [math]::Round($timeDetail.ScenarioDuration, 2)
            } else {
                0
            }
            '시뮬레이션_시작' = $timeDetail.SimulationStart
            '시뮬레이션_소요(초)' = if ($result.Duration -is [double] -or $result.Duration -is [int]) {
                [math]::Round($result.Duration, 2)
            } else {
                0
            }
            '실험_완료시간' = $timeDetail.CompleteTime
            '좌표별_총소요(초)' = if ($timeDetail.TotalDuration -is [double] -or $timeDetail.TotalDuration -is [int]) {
                [math]::Round($timeDetail.TotalDuration, 2)
            } else {
                0
            }
            '성공여부' = if ($result.Success -eq $true) { "성공" } else { "실패" }
            '로그파일' = if ($result.LogPath) { $result.LogPath } else { "-" }
            '환자수' = $incidentSize
            '구급차수' = $ambSize
            'UAV수' = $uavSize
            '구급차속도' = $ambVelocity
            'UAV속도' = $uavVelocity
            '시뮬레이션반복' = $totalSamples
            '랜덤시드' = $randomSeed
        }
    }
    
    # CSV로 저장 (UTF8BOM 인코딩)
    $csvPath = "$summaryDir\$($GlobalParams.ExperimentId)_summary.csv"
    $summaryData | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8BOM
    
    Write-StatusLine "📄" "실험 요약 저장" $Colors.Success $csvPath
    
    # 결과 요약 박스
    Write-Host ""
    Write-Host "  📊 저장된 실험 데이터" -ForegroundColor $Colors.Info
    Write-Host "  ───────────────────" -ForegroundColor $Colors.Info
    Write-Host "  • 실험 요약: $csvPath" -ForegroundColor $Colors.Info
    Write-Host "  • 결과 폴더: scenarios\$($GlobalParams.ExperimentId)\" -ForegroundColor $Colors.Info
    
    # 정확한 성공/실패 카운트 계산
    $successfulCount = 0
    $failedCount = 0
    
    for ($i = 0; $i -lt $SimConfigs.Count; $i++) {
        $currentResult = if ($i -lt $Results.Count -and $null -ne $Results[$i]) { 
            $Results[$i] 
        } else { 
            @{Success=$false; Duration=0; LogPath=""} 
        }
        
        if ($currentResult.Success -eq $true) {
            $successfulCount++
        } else {
            $failedCount++
        }
    }
    
    if ($DetailedTimes.Count -gt 0 -and $Results.Count -gt 0) {
        $avgScenarioTime = ($DetailedTimes | Where-Object { $_.ScenarioDuration -is [double] -or $_.ScenarioDuration -is [int] } | Measure-Object -Property ScenarioDuration -Average).Average
        $avgSimTime = ($Results | Where-Object { $_.Duration -is [double] -or $_.Duration -is [int] } | Measure-Object -Property Duration -Average).Average
        
        Write-Host "  • 총 실험: $($SimConfigs.Count)개 (성공: $successfulCount, 실패: $failedCount)" -ForegroundColor $Colors.Info
        Write-Host "  • 전체 소요시간: $($TotalTime.ToString('hh\:mm\:ss'))" -ForegroundColor $Colors.Info
    }
    Write-Host ""
}

function Remove-TemporaryFiles {
    param([string]$ExperimentId)
    
    Write-Host ""
    $cleanup = Read-Host "중간 파일을 삭제하시겠습니까? (결과는 유지됩니다) [Y/N]"
    
    if ($cleanup -eq 'Y' -or $cleanup -eq 'y') {
        $experimentPath = "scenarios\$ExperimentId"
        
        # CSV 파일만 삭제 (summary.csv와 config.yaml은 유지)
        $csvFiles = Get-ChildItem -Path $experimentPath -Recurse -Include "*.csv" -Exclude "*_summary.csv"
        $csvFiles | Remove-Item -Force
        
        Write-StatusLine "🗑️" "중간 파일 삭제 완료" $Colors.Success "삭제된 파일: $($csvFiles.Count)개"
        
        # 압축 옵션
        $compress = Read-Host "실험 폴더를 압축하시겠습니까? [Y/N]"
        if ($compress -eq 'Y' -or $compress -eq 'y') {
            $zipPath = "$experimentPath.zip"
            Compress-Archive -Path $experimentPath -DestinationPath $zipPath -Force
            Write-StatusLine "📦" "압축 완료" $Colors.Success $zipPath
        }
    }
}

# ==================== 메인 실행 ====================

Clear-Host
Write-StyledHeader "🔬 MCI 재난 시뮬레이션 자동화 시스템 v4.4 (UI 개선 & 완전랜덤 반영)" $Colors.Header

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

# ==================== 실험 결과 출력 (깔끔한 UI) ====================

Write-Host ""
Write-StyledHeader "📊 실험 결과 요약" $Colors.Header

# 성공/실패 통계 계산 (정확한 개수 보장)
$successCount = ($results | Where-Object { $_.Success -eq $true }).Count
$failCount = ($results | Where-Object { $_.Success -eq $false }).Count
$totalExperiments = $simConfigs.Count  # 설정된 시뮬레이션 개수 기준

# 배열 크기 일치 확인 및 경고
if ($results.Count -ne $simConfigs.Count) {
    Write-Host "⚠️ 배열 크기 불일치 감지: 설정 $($simConfigs.Count)개, 결과 $($results.Count)개" -ForegroundColor $Colors.Warning
}

# 안전한 평균 계산
$avgScenarioTime = if ($detailedTimes.Count -gt 0) {
    $scenarioDurations = $detailedTimes | ForEach-Object { 
        if ($_.ScenarioDuration -is [double] -or $_.ScenarioDuration -is [int]) {
            $_.ScenarioDuration
        } else {
            0
        }
    }
    [math]::Round(($scenarioDurations | Measure-Object -Average).Average, 1)
} else {
    0
}

$avgSimTime = if ($results.Count -gt 0) {
    $simDurations = $results | ForEach-Object { 
        if ($_.Duration -is [double] -or $_.Duration -is [int]) {
            $_.Duration
        } else {
            0
        }
    }
    [math]::Round(($simDurations | Measure-Object -Average).Average, 1)
} else {
    0
}

# 성공률 계산
$successRate = if ($totalExperiments -gt 0) {
    [math]::Round(($successCount / $totalExperiments) * 100, 1)
} else {
    0
}

# 깔끔한 결과 요약
Write-Host ""
Write-Host "  🎉 실험 완료" -ForegroundColor $Colors.Success
Write-Host "  ──────────────" -ForegroundColor $Colors.Success
Write-Host "  총 소요시간: $($totalTime.ToString('hh\:mm\:ss'))" -ForegroundColor $Colors.Info
Write-Host ""
Write-Host "  설정한 실험: $totalExperiments개" -ForegroundColor $Colors.Info
Write-Host "  실제 결과: $($results.Count)개" -ForegroundColor $Colors.Info
Write-Host "  성공: $successCount개" -ForegroundColor $Colors.Info
Write-Host "  실패: $failCount개" -ForegroundColor $Colors.Info
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
        
        Write-Host ("  {0} 실험 #{1}: {2} - {3} ({4:F1}초){5}" -f $statusIcon, $config.Id, $statusText, $locationText, $resultDuration, $logText) -ForegroundColor $statusColor
    }
}

# 실험 요약 저장
Save-ExperimentSummary -SimConfigs $simConfigs -Results $results -GlobalParams $globalParams -TotalTime $totalTime -DetailedTimes $detailedTimes

# 실험 로그 표시
Show-ExperimentLogs -GlobalParams $globalParams

# 중간 파일 정리
Remove-TemporaryFiles -ExperimentId $globalParams.ExperimentId

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
Write-Host "  🎲 적용된 설정: 전국랜덤 = 17개 시도 완전 동일확률" -ForegroundColor $Colors.Accent


if (-not $SkipConfirmation) {
    Write-Host ""
    Read-Host "엔터 키를 눌러 종료하세요"
}