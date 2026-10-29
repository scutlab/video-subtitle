@echo off
REM 不用编译 exe，直接在 Windows 上跑 Python 版（功能与 exe 完全一样）
REM 前置：已装 Python 3.10+（勾选 Add Python to PATH），ffmpeg.exe 已在 PATH 或本目录
REM 首次运行：pip install -r requirements.txt（之后会自动下载 small 模型，约 466MB）
REM 用法：run_windows.bat "D:\Videos"
REM       run_windows.bat "D:\Videos" --model base --format both --recursive
setlocal
python --version || (echo 请先安装 Python 并加入 PATH & pause & exit /b 1)
ffmpeg -version >nul 2>&1 || echo 警告：未在 PATH 找到 ffmpeg，运行时仍需把 ffmpeg.exe 放在本目录或加入 PATH
if not exist "%~dp0video_subtitle.py" (echo 找不到 video_subtitle.py，请把本批处理与 video_subtitle.py 放在同一目录 & pause & exit /b 1)
python "%~dp0video_subtitle.py" %*
pause
