#!/usr/bin/env bash
# ============================================================
# Ubuntu 自动部署 + 可选转录（deploy_windows.bat 的 Ubuntu 版）
#
# 用法（在 Ubuntu 终端里，不是在 PowerShell / cmd 里）：
#   只部署环境，不跑转录：
#     ./deploy_ubuntu.sh
#   部署完直接跑指定视频目录（medium 模型，GPU 自动用）：
#     ./deploy_ubuntu.sh ~/video
#   换模型目录或模型时，先改下面 MODEL_DIR / MODEL / GPUS 三行。
#   设 HF Token（可选，和下载在同一个终端里，Token 不要写进这个文件）：
#     export HF_TOKEN="hf_你复制的Token"
#     ./deploy_ubuntu.sh ~/video
#
# 和 Windows bat 版的区别，只有这几点：
# - 不用 .bat，不用 Activate.ps1，也没有执行策略问题，
#   激活是 source .venv/bin/activate，部署全程用 .venv/bin/python 全路径；
# - 系统依赖用 apt 装（python3 / python3-venv / ffmpeg），不是 winget / choco；
# - 路径是 ~/video 这种斜杠写法，不是 D:\video；
# - 检测到 NVIDIA GPU 时，会自动补装 CUDA 版 ctranslate2，
#   这样 --gpus 才能真正用上 GPU，否则只能回落 CPU。
# ============================================================

# ---- 只改下面这几行 ----
MODEL_DIR="$HOME/models"
MODEL="medium"
GPUS="auto"            # auto=检测到的全部卡，0,1=两张卡并行，1=只用第二张卡，空=只用第一张卡
CUDA_VARIANT="cuda12"  # GPU 机器才用，CUDA 11 的机器改成 cuda11

# ---- 下面不用改 ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1
VENV_PY=".venv/bin/python"
VENV_PIP=".venv/bin/pip"

echo "[1/6] 检查 Python 和 ffmpeg ..."
if ! command -v python3 >/dev/null 2>&1 || ! command -v ffmpeg >/dev/null 2>&1; then
    echo "缺 python3 或 ffmpeg，正在用 apt 安装（需要 sudo，可能会问密码）..."
    sudo apt update || { echo "apt update 失败，请检查网络后重跑"; exit 1; }
    sudo apt install -y python3 python3-venv python3-pip ffmpeg || { echo "apt 安装失败，请手动装好 python3 / python3-venv / ffmpeg 后重跑"; exit 1; }
fi
python3 --version
ffmpeg -version 2>/dev/null | head -n 1

echo "[2/6] 创建虚拟环境（已有就跳过）..."
if [ ! -x "$VENV_PY" ]; then
    python3 -m venv .venv || { echo "建 venv 失败：先确认已装 python3-venv（sudo apt install -y python3-venv）"; exit 1; }
fi

echo "[3/6] 升级 pip，安装依赖 ..."
"$VENV_PY" -m pip install --upgrade pip || { echo "升级 pip 失败"; exit 1; }
"$VENV_PIP" install -r requirements.txt || { echo "装依赖失败，请看上面的 pip 报错"; exit 1; }

echo "[4/6] 验证依赖（av 必须是 18.x，requirements.txt 已锁定 av 小于 19）..."
"$VENV_PIP" show faster-whisper
"$VENV_PIP" show av
AV_VERSION="$("$VENV_PIP" show av 2>/dev/null | awk '/^Version:/ {print $2}')"
if [ -n "$AV_VERSION" ] && [ "${AV_VERSION%%.*}" != "18" ]; then
    echo "av 是 $AV_VERSION，不是 18.x，正在自动降级到 18.x ..."
    "$VENV_PIP" install "av<19" || { echo "降级 av 失败"; exit 1; }
    "$VENV_PIP" show av
fi

echo "[5/6] GPU 检查（有卡才装 CUDA 版，没有卡就跳过，CPU 也能跑）..."
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "检测到 NVIDIA GPU，正在安装 CUDA 版 ctranslate2（$CUDA_VARIANT）..."
    nvidia-smi --query-gpu=index,name --format=csv
    "$VENV_PIP" install "ctranslate2[$CUDA_VARIANT]" || echo "警告：CUDA 版装失败，GPU 模式可能跑不了，CPU 模式仍可用，见 README 双 GPU 一节"
else
    echo "未检测到 NVIDIA GPU，跳过 CUDA 版安装，稍后按 CPU / auto 模式跑"
fi

echo "[6/6] 环境已部署好。"
echo "下一步（把视频目录换成你自己的）："
echo "  .venv/bin/python video_subtitle.py ~/video --model-dir \"$MODEL_DIR\" --model $MODEL --gpus $GPUS"

if [ -n "${1:-}" ]; then
    echo ""
    echo "正在处理：$1"
    GPU_ARGS=()
    if [ -n "$GPUS" ]; then
        GPU_ARGS=(--gpus "$GPUS")
    fi
    "$VENV_PY" video_subtitle.py "$1" --model-dir "$MODEL_DIR" --model "$MODEL" "${GPU_ARGS[@]}"
    RC=$?
    echo ""
    if [ "$RC" -eq 0 ]; then
        echo "完成。字幕在视频目录里，和视频同名、后缀 .srt；明细见视频目录下的 subtitle_batch.log。"
    else
        echo "转录结束，返回码 $RC（个别文件失败时程序也会返回非 0，明细见视频目录下的 subtitle_batch.log）。"
        exit "$RC"
    fi
fi
