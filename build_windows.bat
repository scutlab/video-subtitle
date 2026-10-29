@echo off
REM 在 Windows 上生成 VideoSub.exe（开源 Whisper 版，单文件命令行工具）
REM 前置：已装 Python 3.10+（勾选 Add Python to PATH），ffmpeg.exe 已在 PATH 或本目录
REM 用法：双击或在命令行运行 build_windows.bat，产物在 dist\VideoSub.exe
REM 注意：faster-whisper 打包体积较大；若打包失败，直接用 Python 跑脚本是等效备用路线
setlocal
python --version || (echo 请先安装 Python 并加入 PATH & pause & exit /b 1)
ffmpeg -version >nul 2>&1 || echo 警告：未在 PATH 找到 ffmpeg，运行时仍需把 ffmpeg.exe 放在 VideoSub.exe 同目录
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --onefile --console --name VideoSub --collect-all faster_whisper --collect-all ctranslate2 video_subtitle.py
echo.
echo 完成：dist\VideoSub.exe
echo 用法示例（无需 Key，首次运行自动下载模型）：
echo   dist\VideoSub.exe "D:\Videos"
echo   dist\VideoSub.exe "D:\Videos" --model base --format both --recursive
pause
