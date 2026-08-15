@echo off
setlocal

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul

set "APP_NAME=CharaPicker"
set "VERSION=1.0.0"
set "STAGE=rc"
set "VERSION_TAG=1.0.0-rc"
set "PLATFORM_TAG=windows"
set "ARCH_TAG=x64"
set "LOCAL_BUILD=0"
set "TAG_SOURCE="
set "RAW_TAG="
set "PYTHON_CMD=python"
set "SOURCE_DATE_EPOCH="
set "PYTHONHASHSEED=0"

for /f "usebackq tokens=1,* delims==" %%A in (`%PYTHON_CMD% scripts\build_meta.py %*`) do (
  if /i "%%A"=="ERROR" (
    echo Build metadata error: %%B
    goto :error
  )
  set "%%A=%%B"
)

if errorlevel 1 goto :error

set "ZIP_NAME=%APP_NAME%-v%VERSION_TAG%-%PLATFORM_TAG%-%ARCH_TAG%.zip"
set "DIST_DIR=%ROOT_DIR%dist"
set "BUILD_DIR=%ROOT_DIR%build"
set "RELEASE_DIR=%ROOT_DIR%release"
set "STAGE_DIR=%RELEASE_DIR%\%APP_NAME%"
set "ZIP_PATH=%RELEASE_DIR%\%ZIP_NAME%"
set "CHECKSUM_PATH=%ZIP_PATH%.sha256"
set "BUILD_INFO_PATH=%RELEASE_DIR%\build-info.json"
set "DEPENDENCY_INVENTORY_PATH=%RELEASE_DIR%\dependency-inventory.json"

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

%PYTHON_CMD% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
  echo PyInstaller is missing in current Python environment.
  echo Install with: python -m pip install pyinstaller
  goto :error
)

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%" rmdir /s /q "%DIST_DIR%\%APP_NAME%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%DIST_DIR%\%APP_NAME%Updater.exe" del /q "%DIST_DIR%\%APP_NAME%Updater.exe"
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"
if exist "%CHECKSUM_PATH%" del /q "%CHECKSUM_PATH%"
if exist "%BUILD_INFO_PATH%" del /q "%BUILD_INFO_PATH%"
if exist "%DEPENDENCY_INVENTORY_PATH%" del /q "%DEPENDENCY_INVENTORY_PATH%"

echo [1/5] Building one-folder package with main.spec...
echo Version: v%VERSION_TAG%
echo Stage: %STAGE%
echo Platform: %PLATFORM_TAG%
echo Arch: %ARCH_TAG%
if defined RAW_TAG echo Tag: %RAW_TAG% (%TAG_SOURCE%)
if "%LOCAL_BUILD%"=="1" echo Build mode: local
%PYTHON_CMD% -m PyInstaller --noconfirm --clean main.spec
if errorlevel 1 goto :error

echo [2/5] Building standalone update helper with updater.spec...
%PYTHON_CMD% -m PyInstaller --noconfirm --clean updater.spec
if errorlevel 1 goto :error
if not exist "%DIST_DIR%\%APP_NAME%Updater.exe" goto :error
copy /y "%DIST_DIR%\%APP_NAME%Updater.exe" "%DIST_DIR%\%APP_NAME%\%APP_NAME%Updater.exe" >nul
if errorlevel 1 goto :error

echo [3/5] Preparing release folder...
mkdir "%STAGE_DIR%"
xcopy /e /i /y "%DIST_DIR%\%APP_NAME%\*" "%STAGE_DIR%\" >nul
if errorlevel 1 goto :error

for %%F in (README.md LICENSE THIRD_PARTY_NOTICES.md) do (
  if exist "%ROOT_DIR%%%F" copy /y "%ROOT_DIR%%%F" "%STAGE_DIR%\%%F" >nul
)

echo [4/5] Creating normalized archive and build manifest...
set "LOCK_MATCH_ARG=--require-lock-match"
if "%LOCAL_BUILD%"=="1" set "LOCK_MATCH_ARG="
%PYTHON_CMD% scripts\package_release.py ^
  --stage-dir "%STAGE_DIR%" ^
  --archive "%ZIP_PATH%" ^
  --build-info "%BUILD_INFO_PATH%" ^
  --version "%VERSION%" ^
  --stage "%STAGE%" ^
  --version-tag "%VERSION_TAG%" ^
  --tag "%RAW_TAG%" ^
  --platform "%PLATFORM_TAG%" ^
  --arch "%ARCH_TAG%" ^
  --source-date-epoch "%SOURCE_DATE_EPOCH%" ^
  %LOCK_MATCH_ARG%
if errorlevel 1 goto :error

echo [5/5] Done.
echo Output: %ZIP_PATH%
echo Checksum: %CHECKSUM_PATH%
echo Build info: %BUILD_INFO_PATH%
echo Dependency inventory: %DEPENDENCY_INVENTORY_PATH%
popd >nul
exit /b 0

:error
echo Build failed.
popd >nul
exit /b 1
