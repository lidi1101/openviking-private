@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM 配置区域（按需修改）
REM ============================================================
REM INF 文件名（必须和实际 INF 一致）
set "DRIVER_INF_NAME=FileProtector.inf"

REM fltmc 里的过滤器名称（Altitude 那个过滤器名字）
set "FILTER_NAME=FileProtector"

REM 服务名（INF 里 ServiceName / ServiceInstall 里的 Name）
set "DRIVER_SERVICE_NAME=FileProtector"

REM 脚本所在目录 & INF 绝对路径
set "SCRIPT_DIR=%~dp0"
REM 为避免路径里有 .. 等问题，转成绝对路径
for %%I in ("%SCRIPT_DIR%.") do set "SCRIPT_DIR=%%~fI\"

cd /d "%SCRIPT_DIR%"
set "DRIVER_INF_PATH=%SCRIPT_DIR%%DRIVER_INF_NAME%"

echo [INFO] Driver INF path: "%DRIVER_INF_PATH%"

REM ============================================================
REM 定位 pnputil.exe（关键）
REM ============================================================
set "PNPUTIL_EXE=C:\Windows\System32\pnputil.exe"

REM 兼容 32 位进程在 64 位系统上的 System32 重定向问题
if not exist "%PNPUTIL_EXE%" (
    if exist "%SystemRoot%\Sysnative\pnputil.exe" (
        set "PNPUTIL_EXE=%SystemRoot%\Sysnative\pnputil.exe"
    )
)

if not exist "%PNPUTIL_EXE%" (
    echo [ERROR] Cannot find pnputil.exe.
    echo         Tried:
    echo           %SystemRoot%\System32\pnputil.exe
    echo           %SystemRoot%\Sysnative\pnputil.exe
    exit /b 10
)

REM ============================================================
REM 检查管理员权限
REM ============================================================
echo.
echo [*] Checking for administrator privileges...
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run from an elevated CMD. Run as administrator.
    exit /b 1
)
echo [OK] Administrator privileges confirmed.

REM ============================================================
REM Step 1 - 如果驱动已加载，先卸载过滤器
REM ============================================================
echo.
echo [*] Checking if filter is already loaded...

fltmc filters | findstr /I "%FILTER_NAME%" >nul 2>&1
if errorlevel 1 (
    echo [*] Filter "%FILTER_NAME%" is not currently loaded.
) else (
    echo [*] Filter "%FILTER_NAME%" is loaded, trying to unload...
    fltmc unload "%FILTER_NAME%"
    if errorlevel 1 (
        echo [WARN] Failed to unload filter "%FILTER_NAME%". A reboot may be required.
    ) else (
        echo [OK] Filter "%FILTER_NAME%" was unloaded successfully.
    )
)

REM ============================================================
REM Step 2 - 停止并删除旧的服务（如果存在）
REM ============================================================
echo.
echo [*] Checking driver service: "%DRIVER_SERVICE_NAME%" ...

sc query "%DRIVER_SERVICE_NAME%" >nul 2>&1
if "%errorlevel%"=="0" (
    echo [*] Service "%DRIVER_SERVICE_NAME%" found, trying to stop and delete...

    sc stop "%DRIVER_SERVICE_NAME%" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Failed to stop service "%DRIVER_SERVICE_NAME%". It may already be stopped.
    ) else (
        echo [OK] Service "%DRIVER_SERVICE_NAME%" stopped.
    )

    sc delete "%DRIVER_SERVICE_NAME%" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Failed to delete service "%DRIVER_SERVICE_NAME%". It may be removed with the driver package.
    ) else (
        echo [OK] Service "%DRIVER_SERVICE_NAME%" deleted.
    )
) else (
    echo [*] Service "%DRIVER_SERVICE_NAME%" not found. Nothing to stop/delete.
)

REM ============================================================
REM Step 3 - 卸载旧的驱动包（可选，基于 pnputil /enum-drivers 输出为中文）
REM ============================================================
echo.
echo [*] Searching for existing driver package with Original Name: "%DRIVER_INF_NAME%" ...

set "CurrentPub="
set "CurrentOrg="

for /f "delims=" %%L in ('"%PNPUTIL_EXE%" /enum-drivers') do (
    set "line=%%L"

    REM 去掉行首空格
    for /f "tokens=* delims= " %%T in ("!line!") do set "lineTrim=%%T"

    if "!lineTrim!"=="" (
        REM 空行，跳过
    ) else (
        REM 下面两段假设系统是中文，行里包含“发布名称”和“原始名称”
        if not "!lineTrim:发布名称=!"=="!lineTrim!" (
            REM 新的 PublishedName 行
            set "CurrentPub="
            for %%F in (!lineTrim!) do set "CurrentPub=%%F"
            set "CurrentOrg="
        ) else (
            if not "!lineTrim:原始名称=!"=="!lineTrim!" (
                REM 新的 OriginalName 行
                set "CurrentOrg="
                for %%F in (!lineTrim!) do set "CurrentOrg=%%F"

                if /I "!CurrentOrg!"=="%DRIVER_INF_NAME%" (
                    echo [MATCH] OriginalName = "%DRIVER_INF_NAME%", PublishedName = "!CurrentPub!"
                    "%PNPUTIL_EXE%" /delete-driver "!CurrentPub!" /uninstall
                )
            )
        )
    )
)
echo.
echo [*] Old driver removal step completed (if any existed).
echo.
echo [DONE] Driver uninstallation completed.
endlocal
exit /b 0
