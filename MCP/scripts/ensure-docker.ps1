# 确保 Docker 环境就绪：引擎未运行则启动 Docker Desktop 并等待，随后拉起依赖容器
# 供 VSCode 一键启动的 preLaunchTask 调用；仅启动依赖(mysql/redis/qdrant)，app 由本地 mvn 运行
$ErrorActionPreference = 'Stop'

function Test-DockerReady {
    try {
        docker version --format '{{.Server.Version}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

# 1) 引擎已就绪则跳过启动
if (Test-DockerReady) {
    Write-Host "[ensure-docker] Docker 引擎已在运行"
} else {
    Write-Host "[ensure-docker] Docker 引擎未运行，正在启动 Docker Desktop ..."
    $candidates = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
        "$env:LocalAppData\Docker\Docker\Docker Desktop.exe"
    )
    $exe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $exe) {
        Write-Error "[ensure-docker] 未找到 Docker Desktop.exe，请确认已安装 Docker Desktop"
        exit 1
    }
    Start-Process $exe | Out-Null

    # 2) 轮询等待引擎就绪（最多约 180 秒）
    $deadline = (Get-Date).AddSeconds(180)
    while (-not (Test-DockerReady)) {
        if ((Get-Date) -gt $deadline) {
            Write-Error "[ensure-docker] 等待 Docker 引擎就绪超时"
            exit 1
        }
        Start-Sleep -Seconds 3
        Write-Host "[ensure-docker] 等待 Docker 引擎就绪 ..."
    }
    Write-Host "[ensure-docker] Docker 引擎已就绪"
}

# 3) 拉起依赖容器（本地 mvn 跑 app，故不启动 app 容器）
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    Write-Host "[ensure-docker] 启动依赖容器 mysql / redis / qdrant ..."
    docker compose up -d mysql redis qdrant
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[ensure-docker] docker compose up 失败"
        exit 1
    }

    # 4) 等待 MySQL 健康（app 的硬依赖）
    Write-Host "[ensure-docker] 等待 MySQL 健康检查通过 ..."
    $deadline = (Get-Date).AddSeconds(120)
    while ($true) {
        $status = (docker inspect --format '{{.State.Health.Status}}' digital-cs-mysql 2>$null)
        if ($status -eq 'healthy') { Write-Host "[ensure-docker] MySQL 已就绪"; break }
        if ((Get-Date) -gt $deadline) {
            Write-Error "[ensure-docker] 等待 MySQL 健康超时（当前状态：$status）"
            exit 1
        }
        Start-Sleep -Seconds 3
    }
} finally {
    Pop-Location
}

Write-Host "[ensure-docker] Docker 环境就绪，继续启动应用"
