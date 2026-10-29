# 安装部署文档

适用：视频批量转字幕工具（开源 Whisper 版，源代码 `video_subtitle.py`）。
流程只有一条：ffmpeg 抽音频 → faster-whisper 本地识别 → 按断句规则出 SRT。
不需要 Key、账号、联网计费，模型下载一次后全程本地离线跑。

本文只讲“装好、能跑”。跑起来之后怎么选模型、怎么写提示词、怎么调精度，
见 `USAGE.md`。两个文档不要混着看，先装好，再去看用法。

包里文件一览（解压后直接能看到这些，不要多套一层文件夹）：

- `README.md`：总览和快速上手
- `INSTALL.md`：本文件，安装部署
- `USAGE.md`：使用手册
- `video_subtitle.py`：源代码，Python 直接跑，不用编译
- `requirements.txt`：依赖，只有两行
- `deploy_windows.bat`：Windows 一键部署（cmd）
- `deploy_ubuntu.sh`：Ubuntu 一键部署（bash）
- `deploy_ubuntu_large-v3.sh`：Ubuntu 定制版，模型已定死 large-v3、路径已定死为集群路径
- `build_windows.bat`：可选，在 Windows 上编成 `VideoSub.exe`
- `run_windows.bat`：可选，免编译快捷方式，只适合全局装了依赖时用

支持的输入格式：mp4、mkv、avi、mov、wmv、flv、webm、m4v，
以及 mp3、wav、m4a、aac、flac。

## 1. 准备三样东西

- Python 3.10 或更新的 64 位版本。
- ffmpeg，能在终端里跑 `ffmpeg -version`。
- 磁盘：模型 small 约 466MB、medium 约 1.5GB、large-v3-turbo 约 1.6GB、
  large-v3 约 3GB，另加视频总大小 2 倍以上的空闲（抽中间音频、写字幕要用）。

字幕口径先定好，后面不再重复：视频里念什么，字幕就显示这个读音对应的
内容，不人为增加内容。老师念“二重积分”，字幕就是“二重积分”，不额外加
符号；口头没念、只写在黑板上的公式，字幕里也不凭空补。唯一的例外是
希腊字母：只用字符，如 Ω、λ，见 `USAGE.md`。

## 2. Windows 安装（PowerShell）

下面是 PowerShell 版命令，不要和 cmd、bash 的命令混在一个终端里贴。
例子用 `D:\video`，换成你自己的目录时，只改最上面三行。

```powershell
# 只改这 3 行，其他不用改
$Root = "D:\video"
$VideoDir = "$Root\video"
$ModelDir = "$Root\models"

# 0. 进入源码目录
cd "$Root\video-subtitle-windows"

# 1. 验证 Python 和 ffmpeg
python --version
ffmpeg -version

# 2. 建虚拟环境（已有 .venv 就跳过，不用重建）
python -m venv .venv

# 3. 最安全激活：只改当前这一个终端，关掉就失效，不用管理员
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# 4. 升级 pip，装依赖
python -m pip install --upgrade pip
pip install -r requirements.txt

# 5. 验证依赖：av 必须是 18.x
pip show faster-whisper
pip show av
```

### 2.1 Python 没装好怎么办

去 python.org 下 Python 3.10 或更新的 64 位安装包，安装时**必须勾选
Add Python to PATH**，再点 Install。关掉旧终端，重开一个 PowerShell，
`python --version` 能打出版本号才算好。打不出就是没勾选，重装时勾上。

### 2.2 ffmpeg 没装好怎么办

任选一种，推荐第一种：

```powershell
winget install --id Gyan.FFmpeg -e
```

其他装法（三选一，不用全装）：`choco install ffmpeg` 或 `scoop install ffmpeg`。

手动装法：从 gyan.dev 下 `ffmpeg-release-essentials.zip`，解压后把
`bin` 这一层（例如 `C:\ffmpeg\bin`，不是 `C:\ffmpeg`）加进系统 PATH。
管理员 PowerShell 加 PATH：

```powershell
setx /M PATH "$env:Path;C:\ffmpeg\bin"
```

`setx` 不影响已打开的终端，改完必须重开终端，再跑 `ffmpeg -version` 验证。

只把 `ffmpeg.exe` 拷到源码目录是不够的。程序用 `shutil.which("ffmpeg")`
在 PATH 里找，PATH 里没有就报“找不到 ffmpeg”，所以 `bin` 目录一定要进 PATH。

winget 装到最后报 `copy_file: Access is denied` 时，不要换版本、换源、
重装 Python。那是 winget 把解压好的文件拷进默认 Packages 目录时被拒绝，
绕过法是装到 D 盘，不走默认目录：

```powershell
winget install --id Gyan.FFmpeg -e --location "D:\ffmpeg" --accept-source-agreements --accept-package-agreements
Get-ChildItem "D:\ffmpeg" -Recurse -Filter "ffmpeg.exe"
```

一般在 `D:\ffmpeg\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe`，把它的 `bin`
加进用户 PATH，重开终端验证。旧 PATH 里只删含 `WinGet\Packages\Gyan.FFmpeg`
的那一项，保留 `WinGet\Links` 和 `D:\ffmpeg` 的新项。还不行就直接手动下载解压，
不经过 winget，同样是把 `bin` 加进 PATH。

### 2.3 激活报“禁止运行脚本”怎么办

这是 PowerShell 执行策略在拦本地脚本，不是 venv 没建好。
按下面三种办法任选一种，不用重建 venv：

办法 A（推荐，只影响当前终端，关掉就失效，最安全）：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

办法 B（一劳永逸，只影响当前用户，不需要管理员）：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

不要用 `-Scope LocalMachine`，那个要管理员，还改整台电脑的策略，没必要。

办法 C（不想改任何策略，跳过激活，直接用 venv 里的 Python）：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe video_subtitle.py "D:\video\video" --model-dir "D:\video\models"
```

激活只是把 `python` 临时指向 venv 里的 Python，直接写全路径效果完全一样。
后面默认你已激活，如果你用办法 C，就把后面所有 `python ...` 换成
`.\.venv\Scripts\python.exe ...`。

激活成功后，提示符前面会多一个 `(.venv)`，例如
`(.venv) PS D:\video\video-subtitle-windows>`，看到它才算激活成功。

### 2.4 Windows 一键部署（cmd，不用 PowerShell）

包里 `deploy_windows.bat` 在 cmd 里跑，不激活、不跑 `Activate.ps1`，
所以执行策略拦不住它。用法：

```bat
REM 只部署环境，不跑转录：
deploy_windows.bat
REM 部署完直接跑指定视频目录：
deploy_windows.bat "D:\video\video"
```

bat 里模型目录默认 `D:\video\models`，模型默认 `medium`，换目录或换模型时，
先打开 bat 把最上面 `MODEL_DIR` 和 `MODEL` 两行改成你自己的。
Token 不要写进 bat，只在同一个 cmd 里设：`set HF_TOKEN=hf_你复制的Token`。

## 3. Ubuntu / Linux 安装（bash）

核心代码不用改。`video_subtitle.py` 用的都是跨平台写法
（`Path`、`shutil.which("ffmpeg")`、`subprocess`、`tempfile`）。
Windows 专用的只是 `.bat` 和 `VideoSub.exe`，在 Ubuntu 下不用它们。

### 3.1 一键部署

```bash
chmod +x deploy_ubuntu.sh
# 只部署环境，不跑转录
./deploy_ubuntu.sh
# 部署完直接跑指定视频目录
./deploy_ubuntu.sh ~/video
```

脚本最上面只改 `MODEL_DIR` / `MODEL` / `GPUS` / `CUDA_VARIANT` 四行，
顺序是：apt 装 python3 / python3-venv / ffmpeg → 建 venv → 升级 pip 装依赖 →
验证 faster-whisper 和 av（不是 18.x 时自动降级）→ 检测到 NVIDIA GPU 时
自动补装 CUDA 版 ctranslate2 → 没带目录时只部署并打印下一步命令，
带目录时直接转录。

### 3.2 手动部署（和脚本做的事一样）

```bash
# 1. 装系统依赖（Ubuntu 22.04 / 24.04，python3-venv 是建 venv 必需的）
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg unzip

# 2. 验证
python3 --version
ffmpeg -version

# 3. 解压源码（假设 zip 在 ~/Downloads）
unzip ~/Downloads/video-subtitle-windows.zip -d ~/video-subtitle
cd ~/video-subtitle

# 4. 建虚拟环境并激活（Linux 下是 source，没有执行策略问题）
python3 -m venv .venv
source .venv/bin/activate

# 5. 升级 pip，装依赖
python -m pip install --upgrade pip
pip install -r requirements.txt
pip show av
```

只跑脚本时不必激活，脚本全程用 `.venv/bin/python` 全路径。
激活只对当前终端有效，检查法是 `which python` 应指向 `.venv/bin/python`，
退出用 `deactivate`。

不要在 `/tmp` 里建 venv 测试，`/tmp` 在很多机器上是 512MB tmpfs，
会报 `No space left on device`，要在家目录下做。

WSL 里跑 Ubuntu 时，Windows D 盘的视频路径要写成 `/mnt/d/video`，
不要直接写 `D:\`。

## 4. Slurm 集群安装（本机实测过的例子）

这是已在 2 张 RTX 3090、驱动 580、CUDA 13.0 的 Slurm 机器上跑过的路径，
只作例子，换机器时把路径换成你自己的，其他步骤不变。

```bash
cd /nfs/hb236/xyh/229/video/video-subtitle-windows
chmod +x deploy_ubuntu_large-v3.sh
# deploy_ubuntu_large-v3.sh 顶部已定死：
# MODEL_DIR="/nfs/hb236/xyh/229/video/models"
# MODEL="large-v3"  GPUS="auto"  CUDA_VARIANT="cuda12"  COMPUTE_TYPE="int8"
./deploy_ubuntu_large-v3.sh /nfs/hb236/xyh/229/video/video
```

注意三点，都是实测踩过的：

- `CUDA_VARIANT` 保持 `cuda12`，不要改成 `cuda13`。nvidia-smi 右上角的
  CUDA 版本是驱动支持的最高版本，驱动向下兼容，CTranslate2 目前只有
  cuda12 / cuda11 extra。`ctranslate2 4.8.4 does not provide the extra 'cuda12'`
  这句警告一般可忽略，真正校验是
  `.venv/bin/python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`
  应返回 2。
- GPU 版依赖要补装，pip 装的 CPU 版不够：venv 里跑
  `pip install "ctranslate2[cuda12]"`（CUDA 11 的机器换成 cuda11）。
  一键脚本里有 GPU 时会自动补装，手动部署时不要漏这步。
- 脚本内部会先 cd 到脚本目录，所以传给脚本的视频参数**必须用绝对路径**，
  相对路径会在 cd 之后找错地方。

## 5. 模型下载

三种方式任选一种，第一次用推荐方式 A，命令最少。

### 5.1 方式 A：第一次运行自动下载（推荐）

不用单独下模型，直接跑转录命令（见 `USAGE.md`），程序在“正在加载
Whisper 模型”时会自己下载。下载完之后就离线可用，以后再跑不用重下。

出现下面这句警告可以忽略，模型是公开的，没登录也能下：

```
Warning: You are sending unauthenticated requests to the HF Hub.
```

### 5.2 方式 B：下载慢时，用镜像 + 多线程

直连 huggingface.co 慢、没登录会被限速时用。**在同一个终端、跑程序之前**
先设下面三行，重开终端要重设。PowerShell 和 bash 的写法不要混：

PowerShell 版：

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
pip install hf_transfer
$env:HF_HUB_ENABLE_HF_TRANSFER=1
```

bash 版：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
pip install hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1
```

### 5.3 方式 C：先设 Token，再单独下载

模型本身公开，不登录也能下，登录只是提限速、去掉上面那句警告。
去 huggingface.co 免费注册，在头像 → Settings → Access Tokens 里建一个
Read 权限 Token，建好后只显示一次，立刻复制下来。

PowerShell 版（同一个终端、下载之前）：

```powershell
$env:HF_TOKEN="hf_你复制的Token"
hf download Systran/faster-whisper-medium --cache-dir "D:\video\models"
```

bash 版：

```bash
export HF_TOKEN="hf_你复制的Token"
hf download Systran/faster-whisper-medium --cache-dir ~/models
```

Token 只在当前终端有效，重开终端要重设；不要把 Token 写进代码、
写进脚本、截图发给别人。泄露后去 Access Tokens 里删掉重建即可。

不要用旧命令 `huggingface-cli download`，新版 HF Hub（2.3）里
`huggingface-cli` 已经没有 `download` 子命令，会报
`invalid choice: 'download'`。新命令是 `hf download`，参数一样。
如果 `hf` 也找不到，就用 Python 一行代替：

```bash
python -c "from huggingface_hub import snapshot_download; print(snapshot_download(repo_id='Systran/faster-whisper-medium', cache_dir=r'D:\video\models'))"
```

### 5.4 模型放哪里：`--model-dir` 的正确层级（重要，别套错）

`--model-dir` 本身就是 HF 的 cache_dir，正确结构是**直接**在下面放
`models--...`，不要再套一层 `hub`：

```
D:\video\models\models--Systran--faster-whisper-small\
~/models/models--Systran--faster-whisper-medium\
```

套错会报 `LocalEntryNotFoundError`。验证法：进目录能直接看到
`models--...`，再进 `snapshots` 里的哈希文件夹，能看到 `model.bin`
（small 约 461MB）、`config.json`、`tokenizer.json`、`vocabulary.txt`。

模型整目录要保留 `blobs/refs/snapshots/trees`，不可只拷 `model.bin`，
不可改名为 `small`。相对路径是相对于运行命令时的当前目录，不是视频目录。
下载中断后重跑会续下，不要删缓存；删了 `models--...` 才会从头下。

不填 `--model-dir` 时，模型在系统默认缓存：
Windows 是 `C:\Users\你的用户名\.cache\huggingface\hub\models--...`，
Ubuntu 是 `~/.cache/huggingface/hub/models--...`，那时不填 `--model-dir`
才能复用，填了固定目录反而要重下。

更好模型的仓库名不要写错（见 `USAGE.md` 模型表）：

- large-v3-turbo：`mobiuslabsgmbh/faster-whisper-large-v3-turbo`，不是 Systran
- large-v3：`Systran/faster-whisper-large-v3`
- medium：`Systran/faster-whisper-medium`

带 `.en` 的模型是纯英文，不能用于中文；`distil-large-v3` 也是英文向，
中文课不要用它代替 large-v3。

## 6. 装好后的验证（每步都要看到成功标志再往下走）

```powershell
# Windows PowerShell 版，Ubuntu 把下面换成 .venv/bin/python 和 .venv/bin/pip
pip show faster-whisper
pip show av
ffmpeg -version
```

检查点：

1. `pip show av` 的 Version 是 18.x，不是 19.x。
2. `ffmpeg -version` 能打出版本号。
3. 模型目录下能直接看到 `models--...`，`snapshots` 里有 `model.bin`。
4. 先只放 1 个 1～3 分钟短视频，跑通再整批（命令见 `USAGE.md`）。
5. 视频目录里多了一个同名 `.srt`，时间轴和说话对得上；
   视频目录里有 `subtitle_batch.log`，能看到每条处理结果。

第 1 点不过，后面一定会失败，不要跳过。

## 7. 常见安装问题速查

| 现象 | 原因 | 办法 |
| --- | --- | --- |
| `open() got an unexpected keyword argument 'metadata_errors'` | faster-whisper 1.2.1 调了该参数，但 PyAV 19 已删 | venv 里 `pip install "av<19"`，再 `pip show av` 确认 18.x；`requirements.txt` 已锁定 `av<19`，不要去掉 |
| `LocalEntryNotFoundError` / 找不到模型 | `--model-dir` 多套了一层 `hub`，或只拷了 `model.bin` | 按 5.4 节改成直接 `models--...` 层级，整目录保留 |
| 直连 huggingface.co 超时，`ConnectTimeout` | 直连超时且本地无快照 | 同终端先 `export HF_ENDPOINT="https://hf-mirror.com"`（bash）或 `$env:HF_ENDPOINT="https://hf-mirror.com"`（PowerShell），再单独 `hf download`，下完校验能见 `model.bin`；镜像也超时时查 `curl -I https://hf-mirror.com`、`curl -I https://huggingface.co`、`env \| grep -i proxy` |
| `huggingface-cli download` 报 `invalid choice` | 新版 HF Hub 已把 download 移到 `hf` 下 | 改用 `hf download ...`，不是你打错模型名 |
| 找不到 ffmpeg | `bin` 没进 PATH，只把 exe 拷到源码目录不够 | 把 `bin` 目录加进 PATH，重开终端验证 |
| 激活报禁止运行脚本 | PowerShell 执行策略 | 只用 Process 级绕过（2.3 节办法 A），不要改机器级策略；或直接用 venv 全路径 Python，根本不激活 |
| `/tmp` 里建 venv 报 `No space left` | `/tmp` 是 512MB tmpfs | 在家目录下建 venv，不要在 `/tmp` 里做 |
| GPU 模式报 CUDA / cuBLAS / cuDNN 找不到 | 只装了 CPU 版 ctranslate2 | venv 里补装 `ctranslate2[cuda12]`（CUDA 11 换 cuda11），不要直接退回 CPU |
| `nvidia-smi` 找不到命令 | 驱动没装好 | 先装驱动（例如 `sudo ubuntu-drivers autoinstall` 后重启），驱动没好之前不要跑 GPU 模式 |

## 8. 可选：编成 exe（只在 Windows 上做）

直接跑 Python 已经够用。想做成双击可用的 exe，再做这一步，
而且**必须在 Windows 上做**，Linux 上编出来的是 Linux 程序，Windows 跑不了：

```powershell
build_windows.bat
```

产物在 `dist\VideoSub.exe`，用法和 Python 版完全一样，只是把
`python video_subtitle.py` 换成 `VideoSub.exe`：

```bat
dist\VideoSub.exe "D:\video\video" --model-dir "D:\video\models"
```

注意：编译前要先确认 Python 和 ffmpeg 都已装好；exe 运行时仍然需要
ffmpeg（在 PATH 里，或放在 `VideoSub.exe` 同目录），模型首次运行仍然要
下载，之后离线。打包遇到问题不用死磕，直接用 Python 命令，功能完全一样。
Linux 本机不能生成 Windows 单文件 exe（PyInstaller 不可交叉编译）。
