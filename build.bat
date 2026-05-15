@echo off
setlocal

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul

set "APP_NAME=CharaPicker"
set "VERSION=0.2.0"
set "STAGE=release"
set "PLATFORM_TAG=windows"
set "ARCH_TAG=x64"
set "LOCAL_BUILD=0"
set "TAG_SOURCE="
set "RAW_TAG="
set "PYTHON_CMD=python"

for /f "usebackq tokens=1,* delims==" %%A in (`%PYTHON_CMD% scripts\build_meta.py %*`) do (
  if /i "%%A"=="ERROR" (
    echo Build metadata error: %%B
    goto :error
  )
  set "%%A=%%B"
)

if errorlevel 1 goto :error

set "DIST_DIR=%ROOT_DIR%dist"
set "BUILD_DIR=%ROOT_DIR%build"
set "RELEASE_DIR=%ROOT_DIR%release"
set "STAGE_DIR=%RELEASE_DIR%\%APP_NAME%"
set "ZIP_NAME=%APP_NAME%-v%VERSION%-%STAGE%-%PLATFORM_TAG%-%ARCH_TAG%.zip"
set "ZIP_PATH=%RELEASE_DIR%\%ZIP_NAME%"

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
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"

echo [1/4] Building one-folder package with main.spec...
echo Version: v%VERSION%
echo Stage: %STAGE%
echo Platform: %PLATFORM_TAG%
echo Arch: %ARCH_TAG%
if defined RAW_TAG echo Tag: %RAW_TAG% (%TAG_SOURCE%)
if "%LOCAL_BUILD%"=="1" echo Build mode: local
%PYTHON_CMD% -m PyInstaller --noconfirm --clean main.spec
if errorlevel 1 goto :error

echo [2/4] Preparing release folder...
mkdir "%STAGE_DIR%"
xcopy /e /i /y "%DIST_DIR%\%APP_NAME%\*" "%STAGE_DIR%\" >nul
if errorlevel 1 goto :error

if exist "%ROOT_DIR%README.md" copy /y "%ROOT_DIR%README.md" "%STAGE_DIR%\README.md" >nul

echo [3/4] Compressing release zip...
set "ZIP_OK=0"
for /l %%I in (1,1,5) do (
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path '%STAGE_DIR%' -DestinationPath '%ZIP_PATH%' -Force" >nul
  if not errorlevel 1 (
    set "ZIP_OK=1"
    goto :zip_done
  )
  timeout /t 2 /nobreak >nul
)

:zip_done
if "%ZIP_OK%"=="0" goto :error

echo [4/4] Done.
echo Output: %ZIP_PATH%
popd >nul
exit /b 0

:error
echo Build failed.
popd >nul
exit /b 1
