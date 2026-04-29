@echo off
setlocal

set "ROOT_DIR=%~dp0"
pushd "%ROOT_DIR%" >nul

set "APP_NAME=CharaPicker"
set "CONDA_ENV=CharaPicker"
# TODO: Versioning and platform tagging are still manual. Integrate git/tag-based version control and dynamic platform identifier.
set "VERSION=0.1.0"
set "PLATFORM_TAG=windows"
set "DIST_DIR=%ROOT_DIR%dist"
set "BUILD_DIR=%ROOT_DIR%build"
set "RELEASE_DIR=%ROOT_DIR%release"
set "STAGE_DIR=%RELEASE_DIR%\%APP_NAME%"
set "ZIP_NAME=%APP_NAME%-v%VERSION%-%PLATFORM_TAG%.zip"
set "ZIP_PATH=%RELEASE_DIR%\%ZIP_NAME%"
set "PYTHON_CMD=conda run -n %CONDA_ENV% python"

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

%PYTHON_CMD% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
  echo PyInstaller is missing in conda env "%CONDA_ENV%".
  echo Install with: conda run -n %CONDA_ENV% python -m pip install pyinstaller
  goto :error
)

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%" rmdir /s /q "%DIST_DIR%\%APP_NAME%"
if exist "%DIST_DIR%\%APP_NAME%.exe" del /q "%DIST_DIR%\%APP_NAME%.exe"
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"

echo [1/4] Building one-folder package with main.spec...
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
