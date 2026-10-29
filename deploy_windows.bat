@echo off
REM ============================================================
REM 部署指南（cmd 版，一键部署 + 可选转录）
REM 原理：直接用 venv 里的 Python 全路径，不激活、不跑 Activate.ps1，
REM       所以 PowerShell 的执行策略拦不住它，也不用改任何策略。
REM 用法（在 cmd 里，不是在 PowerShell 里）：
REM   只部署环境，不跑转录：
REM     deploy_windows.bat
REM   部署完直接跑指定视频目录（medium 模型）：
REM     deploy_windows.bat "D:\video\video"
REM   换模型目录或模型时，先改下面 MODEL_DIR 和 MODEL 两行。
REM   设 HF Token（可选，和下载在同一个 cmd 里）：
REM     set HF_TOKEN=hf_你复制的Token
REM     deploy_windows.bat "D:\video\video"
REM 注意：Token 不要写进这个 bat 文件里，不要发给别人。
REM ============================================================
setlocal
set MODEL_DIR=D:\video\models
set MODEL=medium

cd /d "%~dp0"
echo [1/5] 检查 Python 和 ffmpeg ...
python --version || (echo 请先安装 Python 并勾选 Add Python to PATH & pause & exit /b 1)
ffmpeg -version >nul 2>&1 || (echo 请先安装 ffmpeg 并加入 PATH，见 README 第 2 步 & pause & exit /b 1)

echo [2/5] 创建虚拟环境（已有就跳过）...
if not exist ".venv\Scripts\python.exe" python -m venv .venv

echo [3/5] 升级 pip，安装依赖 ...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

echo [4/5] 验证依赖（av 必须是 18.x，requirements.txt 已锁定 av 小于 19）...
.venv\Scripts\python.exe -m pip show faster-whisper
.venv\Scripts\python.exe -m pip show av
REM 如果上面显示 av 是 19.x，在 PowerShell 里跑：pip install "av<19"，再验证一次。

echo [5/5] 环境已部署好。
echo 下一步（把视频目录换成你自己的）：
echo   .venv\Scripts\python.exe video_subtitle.py "D:\video\video" --model-dir "%MODEL_DIR%" --model %MODEL%
if not "%~1"=="" (
  echo.
  echo 正在处理：%~1
  .venv\Scripts\python.exe video_subtitle.py "%~1" --model-dir "%MODEL_DIR%" --model %MODEL%
)
echo.
echo 完成。字幕在视频目录里，和视频同名、后缀 .srt；明细见视频目录下的 subtitle_batch.log。
pause
