# 使用手册

适用：视频批量转字幕工具（开源 Whisper 版，源代码 `video_subtitle.py`）。
先按 `INSTALL.md` 装好、首跑通过，再看本文。本文只讲“怎么跑、怎么调”。

一句话流程：扫描目录 → ffmpeg 抽 16kHz 单声道 WAV → faster-whisper 转录
（词级时间戳 + VAD）→ 断句 → SRT（可选同时出 VTT）。模型整批只加载一次，
单个文件失败不中断整批，明细写在视频目录下的 `subtitle_batch.log`（CSV）。

输出规则：默认与视频同目录、同文件名，只换后缀，例如
`D:\video\video\讲座01.mp4` → `D:\video\video\讲座01.srt`。
已有同名字幕时默认跳过不覆盖，加 `--force` 才重做。
临时 WAV 处理完后删除，`--keep-audio` 可保留排查。
原视频不会被改动。

## 1. 最基本用法

Windows PowerShell 版（已激活 venv，当前目录是源码目录）：

```powershell
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models"
```

Ubuntu bash 版（已激活 venv，或用 `.venv/bin/python` 全路径）：

```bash
.venv/bin/python video_subtitle.py ~/video --model-dir ~/models
```

不填 `--model-dir` 时，模型用系统默认缓存，命令就是：

```powershell
python video_subtitle.py "D:\video\video"
```

正常过程是：打印“正在加载 Whisper 模型：small…”→ 打印“共 N 个文件，
语言=zh，模型=small，格式=srt”→ 转录时只占一行、用 `\r` 原地刷新进度条，
显示文件序号、百分比、已用时间、预计剩余时间、实时倍速 → 转完换行打印
`[完成] 文件名 -> N 条字幕`，最后打印“完成：成功 N，跳过 N，失败 N”。

验证三件事再整批：视频目录里多了一个同名 `.srt`；用记事本打开 `.srt`，
时间轴和说话对得上；视频目录里有 `subtitle_batch.log`。

常用变体（按需加，不用全加）：

```powershell
# 同时生成 SRT 和 VTT
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --format both
# 递归处理子目录
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --recursive
# 已有字幕也重做
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --force
# 字幕输出到另一个目录（保持输入目录下的相对结构）
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --output-dir "D:\video\字幕"
# 把输出重定向到日志文件时，关掉单行进度条（只打印开始和完成）
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --no-progress
```

首跑建议：先只放 1 个 1～3 分钟短视频做首跑验证，验证通过后再放整批。
不要一上来就整批，调参数时也只拿同一段 1～3 分钟音频对比，一次只改一个变量，
否则不知道是哪一步起作用。

## 2. 模型怎么选（全部模型命令）

| 模型 | 大致体积（int8） | 仓库名（单独下载时用） | 适合 |
| --- | --- | --- | --- |
| tiny | 约 75MB | `Systran/faster-whisper-tiny` | 最快，先出草稿、机器很弱时；中文错字较多 |
| base | 约 142MB | `Systran/faster-whisper-base` | 速度与精度折中 |
| small（默认） | 约 466MB | `Systran/faster-whisper-small` | 中文日常字幕够用，推荐起点 |
| medium | 约 1.5GB | `Systran/faster-whisper-medium` | 精度更好，CPU 上明显变慢 |
| large-v3-turbo | 约 1.6GB | `mobiuslabsgmbh/faster-whisper-large-v3-turbo`，不是 Systran | 更好模型的首选：精度接近 large-v3，速度快得多，有显卡时优先 |
| large-v3 | 约 3GB | `Systran/faster-whisper-large-v3` | 精度最高，但 CPU 上最慢，适合不赶时间、要抠最后一点精度的批量 |

换模型不用改代码，只换 `--model` 后面的名字，其他参数、输出格式、
字幕口径都不变。带 `.en` 的模型是纯英文，不能用于中文；
`distil-large-v3` 也是英文向，中文课不要用它代替 large-v3。

下面是集群（Slurm，2 张 RTX 3090）上的全部模型命令，一次只跑其中一行，
不要六行一起跑，会互相覆盖 SRT。先设好公共变量：

```bash
cd /nfs/hb236/xyh/229/video/video-subtitle-windows
export HF_ENDPOINT="https://hf-mirror.com"
PROMPT="这是一堂高等数学课，讲解三重积分的定义、性质和对称性，涉及被积函数、有界闭区域、微元法、分割、近似代替、求和、取极限、奇函数、偶函数、积分区域、体积元素。"
HOTWORDS="三重积分,被积函数,有界闭区域,微元法,分割,近似代替,求和,取极限,奇函数,偶函数,对称性,积分区域,体积元素"
```

```bash
# 1. tiny
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model tiny --gpus auto --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force

# 2. base
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model base --gpus auto --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force

# 3. small（默认）
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model small --gpus auto --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force

# 4. medium
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model medium --gpus auto --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force

# 5. large-v3-turbo（有显卡时优先推荐）
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model large-v3-turbo --gpus auto --beam-size 10 --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force

# 6. large-v3（精度最高，最慢）
.venv/bin/python video_subtitle.py /nfs/hb236/xyh/229/video/video --model-dir "/nfs/hb236/xyh/229/video/models" --model large-v3 --gpus auto --beam-size 10 --initial-prompt "$PROMPT" --hotwords "$HOTWORDS" --force
```

第一次跑新视频时去掉 `--force`，已有 SRT 要重做时才必须加。
`turbo` 和 `large-v3` 那两行加了 `--beam-size 10`，其他档默认 5 就够了。

CPU 上保持默认 `--compute-type int8`，不要为了大模型改成 `float32`，
那样更慢、更占内存；有 NVIDIA 显卡时才用 `--device cuda --compute-type float16`。
换模型不会删旧模型，磁盘会多占一份，两个大模型都下就都要留空间。
离线验证：`HF_HUB_OFFLINE=1` 跑 1 个短视频能过，验证完要重开终端清掉
这个变量，再整批，否则新模型下不下来。

## 3. 参数一览

`python video_subtitle.py --help` 能看到全部参数，常用参数如下：

| 参数 | 含义 | 默认 |
| --- | --- | --- |
| input_dir（位置参数） | 要处理的目录 | 必填 |
| --language | 识别语言：zh、en 等，也接受 zh-CN | zh |
| --model | tiny / base / small / medium / large-v3-turbo / large-v3 | small |
| --model-dir | 模型缓存目录 | 系统默认缓存 |
| --device | auto（默认，优先 GPU，有卡用卡，没卡用 CPU）/ cpu / cuda | auto |
| --gpus | 多卡并行：0,1 或 auto，见第 7 节 | 空（只用第一张卡） |
| --compute-type | int8（默认，又快又省显存，多卡时推荐）/ float16（显卡常用） | int8 |
| --format | srt / vtt / both | srt |
| --recursive | 递归子目录 | 不递归 |
| --force | 已有字幕也重做 | 不覆盖 |
| --output-dir | 字幕输出到另一个目录（保持相对结构） | 与视频同目录 |
| --keep-audio | 保留中间 WAV | 不保留 |
| --no-progress | 关闭单行进度条（只打印开始/完成，适合重定向到日志文件时用） | 显示进度条 |
| --beam-size | 束搜索宽度：越大越准、越慢 | 5 |
| --no-vad | 关闭 VAD 静音过滤：说话声音小、VAD 误切丢句时试 | 开启 VAD |
| --initial-prompt | 给模型的上下文提示，如课程名和专业术语，能减少同音词错字（只帮选词，不往输出里加文字） | 空 |
| --hotwords | Whisper 原生偏向词，逗号分隔，解码时优先选这些词，可与 --initial-prompt 叠加；只能重转音频时用，不能改已有 SRT | 空 |
| --greek-format / --no-greek-format | 希腊字母只用字符，如 Ω、λ | 开 |
| --audio-filter | ffmpeg 音频滤波，如 loudnorm,highpass=f=80，音量忽大忽小或有低频噪声时试 | 空 |
| --max-chars | 单条字幕最大字符数 | 42 |
| --max-duration | 单条字幕最长秒数 | 6 |
| --max-gap | 词间停顿超过该秒数就断句 | 0.8 |
| --merge-min-chars | 短句合并：短于该字数的条目尽量往后并，0 表示关闭 | 10 |
| --merge-min-duration | 短句合并：短于该秒数的条目尽量往后并 | 1.5 |
| --merge-max-chars | 短句合并后单条最多字数 | 80 |
| --merge-max-duration | 短句合并后单条最长秒数 | 12 |
| --correct-with-muse | 用 Muse API 再校对一遍（默认关闭，需 MODEL_API_KEY） | 关闭 |
| --muse-model | Muse 模型名 | muse-spark-1.3 |
| --muse-base-url | Meta Model API 地址 | https://api.meta.ai/v1 |
| --muse-chunk-size | Muse 矫正时每段多少条字幕 | 40 |

## 4. 分句规则（字幕可读性的核心）

满足任一条件就断开一条字幕：

1. 遇到句末标点（。！？.!?；;）且当前条目不为空；
2. 当前条目时长超过 6 秒（`--max-duration`）；
3. 当前条目字符数超过 42 个字符（`--max-chars`）；
4. 词与词之间的静音间隔超过 0.8 秒（`--max-gap`）。

不满足时继续累积。中文按字拼接不加空格，其他语言按词加空格。
时间戳取该条第一个词的开始时间、最后一个词的结束时间，并向外各留
0.05 秒缓冲，避免字幕刚好卡在发音起点。

字幕格式：默认 SRT，时间格式 `HH:MM:SS,mmm`，编号从 1 开始，条目间空行
分隔，几乎所有播放器、剪辑软件都支持。可选 VTT（Web 播放器常用，
时间格式 `HH:MM:SS.mmm`，文件头为 `WEBVTT`），用 `--format vtt` 或
`--format both` 生成。播放时字幕和视频同名、同目录，大多数播放器会自动
加载，没自动加载时手动在播放器里打开对应的 `.srt` 即可。

## 5. 提高准确性：按这个顺序试，别一次全改

先分清是哪种“不好”，再对症下药。

1. **换大模型（效果最明显）**：small → medium → large-v3-turbo。
   命令只换模型名，其他不变。
2. **给专业术语提示（数学课尤其管用）**：见第 6 节。
3. **说话声音小、句子被切掉时，关 VAD**：默认 VAD 会跳过静音段，
   音量小的尾音、停顿后的半句容易被误切，加 `--no-vad` 试。
4. **再加束搜索宽度**：`--beam-size 10`（默认 5），搜索更充分、错字更少，
   但大约慢一倍，只在前三步还不够时再加。
5. **原音频本身差时，先处理音频**：音量忽大忽小、有低频嗡嗡声、
   有背景音乐时，模型再大也救不回来。先用滤波试：
   `--audio-filter "loudnorm,highpass=f=80"`。如果人耳听着都含糊、
   回声大、好几个人同时说话，那是源音频问题，换更清晰的录音比换模型更有效。
6. **精度优先时换计算精度**：默认 CPU 是 int8；有显卡时用
   `--device cuda --compute-type float16`；CPU 上想抠最后一点精度可试
   `--compute-type float32`，但会更慢、更占内存。

不建议一上来就全开：medium + beam 10 + float32 在 CPU 上可能比 small
慢好几倍，先按 1 → 2 → 3 的顺序试，够用就停。

## 6. 高数课专用：提示词、偏向词、希腊字母、碎句

### 6.1 提示词和偏向词：两个分开治，两个叠加用

Whisper 是通用模型，不认识“二重积分、被积函数、极坐标”时很容易写成
同音错字。治法是两个参数叠加，只在重转音频时生效，不能改已有 SRT，
已有 SRT 要改必须加 `--force` 重跑：

- `--initial-prompt`：一句话的上下文，写这节课真正会出现的词，
  只帮模型在同音词里选对词，不会往输出里加文字。默认不开。
  三重积分的现成例子：
  `这是一堂高等数学课，讲解三重积分的定义、性质和对称性，涉及被积函数、有界闭区域、微元法、分割、近似代替、求和、取极限、奇函数、偶函数、积分区域、体积元素。`
- `--hotwords`：逗号分隔的术语列表，解码时优先选这些词。
  faster-whisper 1.2.1 的 `transcribe` 确有 `hotwords` 参数，
  所有模型尺寸都能用，一次转录内完成偏向，不用跑两次。
  三重积分的现成例子：
  `三重积分,被积函数,有界闭区域,微元法,分割,近似代替,求和,取极限,奇函数,偶函数,对称性,积分区域,体积元素`

合并原则：偏向词可以合并，但不要一次全塞。合并到 50-60 个可接受，
150 个以上会稀释、误触发。推荐“通用核心 + 本章专用”两层合并：
通用核心约 30 个（被积函数、积分区域、有界闭区域、有界开区域、
开区域、闭区域、有界、无界、奇函数、偶函数、对称性、连续函数、可积、
微元法、分割、近似代替、求和、取极限等），再加本章专用约 20 个
（三重积分、二重积分、累次积分、直角坐标、极坐标、柱面坐标、球面坐标、
雅可比行列式、轮换对称性、体积元素、面积元素等）。换到级数那章时，
后面那段换成级数的词，前面通用核心不动。
`--initial-prompt` 不要跨章合并成一大段，越具体越好，模型后面那部分
基本就忽略了。

各章关键词速查（用哪章就取哪章，不要全塞进一次）：

- 极限与连续：极限、左右极限、无穷小、无穷大、等价无穷小、夹逼定理、
  单调有界定理、连续、间断点、可去间断点、跳跃间断点、无穷间断点、
  振荡间断点、介值定理、零点定理、有界性定理、最大值最小值定理、
  一致连续、有界、有界函数、无界、有界闭区间、开区间、闭区间、
  半开半闭区间、邻域、去心邻域、δ邻域、ε邻域、内点、外点、边界点、
  聚点、孤立点、开集、闭集、边界
- 导数与微分：导数、左导数、右导数、可导、可微、微分、高阶导数、
  隐函数、参数方程、对数求导法、链式法则、莱布尼茨公式、罗尔定理、
  拉格朗日中值定理、柯西中值定理、洛必达法则、泰勒公式、麦克劳林公式、
  佩亚诺余项、拉格朗日余项、单调性、极值、拐点、凹凸性、渐近线、曲率、曲率半径
- 不定积分与定积分：原函数、不定积分、换元积分法、分部积分法、有理函数、
  三角代换、定积分、牛顿莱布尼茨公式、变上限积分、变下限积分、奇偶性、
  周期性、广义积分、反常积分、瑕积分、无穷限积分、平面图形面积、
  旋转体体积、弧长、侧面积、质心、形心
- 多元函数微分学：偏导数、全微分、全增量、方向导数、梯度、链式法则、
  隐函数定理、雅可比行列式、极值、条件极值、拉格朗日乘数法、黑塞矩阵、
  驻点、鞍点、开区域、闭区域、有界区域、无界区域、有界闭区域、
  有界开区域、单连通区域、多连通区域、区域、开集、闭集、内点、边界点
- 重积分：二重积分、三重积分、累次积分、积分区域、被积函数、积分变量、
  直角坐标、极坐标、柱面坐标、球面坐标、雅可比行列式、对称性、奇偶性、
  轮换对称性、体积元素、面积元素、微元法、分割、近似代替、求和、取极限、
  有界闭区域、有界开区域、开区域、闭区域、有界区域、无界区域、
  连续函数、可积、曲顶柱体、柱体体积
- 曲线积分与曲面积分：第一类曲线积分、第二类曲线积分、对弧长的曲线积分、
  对坐标的曲线积分、格林公式、平面曲线积分与路径无关、全微分方程、
  第一类曲面积分、第二类曲面积分、对面积的曲面积分、对坐标的曲面积分、
  高斯公式、斯托克斯公式、散度、旋度、通量、环流量、保守场、势函数、
  方向余弦、法向量、切向量、开区域、闭区域、有界闭区域、单连通区域、多连通区域
- 无穷级数：数项级数、正项级数、交错级数、绝对收敛、条件收敛、比较判别法、
  比值判别法、根值判别法、积分判别法、莱布尼茨判别法、幂级数、收敛半径、
  收敛区间、收敛域、泰勒级数、麦克劳林级数、傅里叶级数、傅里叶系数、
  正弦级数、余弦级数、狄利克雷条件、逐项求导、逐项积分、阿贝尔定理
- 微分方程：一阶线性微分方程、可分离变量、齐次方程、伯努利方程、
  全微分方程、积分因子、二阶常系数线性微分方程、特征方程、特征根、
  通解、特解、初始条件、欧拉方程、降阶法、常数变易法、定义域、开区域、闭区域、有界
- 向量与空间解析几何：向量、数量积、向量积、混合积、平面方程、直线方程、
  点法式、一般式、截距式、方向向量、法向量、夹角、距离、柱面、锥面、
  旋转面、椭球面、双曲面、抛物面、空间曲线、切线、法平面、曲率、挠率

### 6.2 希腊字母：只用字符（默认开）

希腊字母只用字符，例如 Ω、λ、Δ、Σ、θ、φ，不要写英文名 Omega、Lambda，
也不要写中文读音欧米伽、拉姆达。代码里 `--greek-format` 默认开着，
Whisper 输出“欧米伽 / Omega / Omega Ω / Ω”里的任何一种，都会归一成“Ω”；
已经是“Ω”的不变，不会重复加；时间戳原样不动；只做希腊字母这一类，
不碰其他术语和公式。想关掉时加 `--no-greek-format`。

对照表（英文名、符号、中文读音，输出一律只留符号）：
Alpha α 阿尔法、Beta β 贝塔、Gamma γ 伽马、Delta Δ 德尔塔、
Epsilon ε 艾普西隆、Zeta ζ 泽塔、Eta η 伊塔、Theta θ 西塔、
Iota ι 约塔、Kappa κ 卡帕、Lambda λ 拉姆达、Mu μ 缪、
Nu ν 纽、Xi ξ 克西、Omicron ο 奥密克戎、Pi π 派、
Rho ρ 柔、Sigma Σ 西格玛、Tau τ 陶、Upsilon υ 宇普西隆、
Phi φ 斐、Chi χ 希、Psi ψ 普西、Omega Ω 欧米伽。

数学符号读音（老师口头念的时候，提示词和偏向词里可用）：
无穷、积分号、二重积分号、三重积分号、曲线积分号、曲面积分号、
偏导数符号、梯度、纳布拉、增量、求和号、连乘号、属于、不属于、
包含于、并集、交集、空集、约等于、不等于、小于等于、大于等于、
趋于、趋向于、极限、微分、体积元素、面积元素、弧长元素。

注意：Whisper 永不直接输出 LaTeX，SRT 是纯文本；复杂公式应留原画面、
剪辑加图 overlay，或转 MathJax / KaTeX HTML。

### 6.3 碎句太多、术语错太多：两个分开治

碎句（“第二步,”“体积”“称”单独成一条）是分句问题，不是识别问题。
代码里已加短句合并，默认开着：前条短于 10 字或短于 1.5 秒、或以逗号 /
顿号结尾时尽量往后并，合并后不超过 80 字且不超过 12 秒，尾部碎句往前并；
只合并不删字、不改词、不动时间顺序。调法：碎句还多时试
`--max-chars 70 --max-duration 10 --max-gap 1.2`，想关掉合并时把
`--merge-min-chars` 设成 0。

术语错（三种结分→三重积分、G函数→奇函数、贝基函数→被积函数等）
是识别问题，用第 6.1 节的提示词 + 偏向词 + 大模型治，不要用过去被删掉的
替换表把术语硬改成符号 / 公式。提示词后仍错的 Ω / λ / ΔV 属模型边界，
要人工校对符号。

## 7. 双 GPU：优先用 GPU，两张卡分文件并行

口径（已改进代码，不用你自己改）：

- 默认 `--device auto` 就是优先用 GPU：有卡就用卡，没卡回落 CPU，
  想强制用 CPU 时才显式写 `--device cpu`；
- 2 张卡时，`--gpus 0,1` 会每张卡各加载一个模型，把文件轮流分给
  两张卡并行跑。加速来自“不同文件同时在不同卡上跑”，**不是把一个文件
  切开**：只有 1 个文件时，单文件仍只用一张卡，代码会自动只加载
  第一张卡，不浪费第二张卡的显存；
- 多卡时进度条自动关掉，只打印每文件的 `[完成]/[失败]` 一行，
  否则两张卡的进度条会在同一行互相覆盖；
- 每张卡都要够放一个模型：int8 下 small 约 0.5GB、medium 约 1.5GB、
  large-v3-turbo 约 1.6GB、large-v3 约 3GB，多卡时推荐保持默认 int8，
  不要改成 float16（显存翻倍，还可能一张卡放不下大模型）。

先确认卡和驱动（bash 版）：

```bash
nvidia-smi
nvidia-smi --query-gpu=index,name,memory.total --format=csv
```

能看到 2 张卡、驱动正常，才往下走。如果 `nvidia-smi` 找不到命令，
先装驱动（例如 `sudo ubuntu-drivers autoinstall` 后重启），驱动没好之前
不要跑 GPU 模式。GPU 版依赖见 `INSTALL.md` 第 4 节，CPU 版装了也不够。

双卡使用命令（bash 版）：

```bash
cd ~/video-subtitle
source .venv/bin/activate
# 2 张卡并行，文件轮流分给 GPU 0 和 GPU 1
python video_subtitle.py ~/video --model-dir ~/models --model medium --gpus 0,1
# 或者让程序自己检测全部卡（和上面 0,1 效果一样）
python video_subtitle.py ~/video --model-dir ~/models --model medium --gpus auto
# 只用第二张卡（例如第一张卡正在跑别的任务）
python video_subtitle.py ~/video --model-dir ~/models --model medium --gpus 1
# 不填 --gpus 时，auto 只用第一张卡，不是两张卡并行
python video_subtitle.py ~/video --model-dir ~/models --model medium
```

某张卡加载失败（显存不够、驱动不匹配），程序会打印“GPU X 加载模型失败，
已跳过这张卡”，剩下的卡继续跑；如果两张卡都失败，程序会直接退出并提示
检查驱动和 CUDA 版本，此时先减小模型（large-v3-turbo 换 medium，或
medium 换 small）再试。跑的过程中用 `nvidia-smi` 看两张卡是不是都有进程
和显存占用，只有一张卡在动，说明 `--gpus` 没生效，检查是不是写成了
`--device cpu`（填了 `--gpus` 时程序会强制改成 cuda 并打印提示，
如果没看到这句提示，说明命令没贴对）。

## 8. Muse 矫正（可选，默认关闭）

Whisper 只能重转音频，不能拿 SRT 改文本。Muse 矫正是转完之后再改文本
的第二遍，只用标准库 urllib 调 Meta Model API 的 OpenAI 兼容端点
`POST /v1/chat/completions`，不新增 openai 依赖。

能做什么：只改明显同音 / 近音错，如三种结分→三重积分、G函数→奇函数、
贝基函数→被积函数；希腊字母按第 6.2 节只用字符。不增删 / 合并 / 拆分、
不加没念过的公式，不确定保原文，温度 0.2。

不能做什么：large-v3 本身不能做 Muse 这种“拿 SRT 改文本”，因为 Whisper
输入只能是音频，没有文本进文本出的接口；已生成的 SRT 再喂给它没用，
必须 `--force` 重转。Muse 矫正也不是万能，返回行数不对、空、调用报错时
整段回退原文，改动大于 0 时原稿另存同目录 `*.orig.srt`，时间戳不发给模型，
校对后用原条目首尾时间重建。

Key：这不是聊天 App 登录，是 Meta Model API 的 Key，格式 `LLM|...`、
只显示一次，在终端 `export MODEL_API_KEY="LLM|..."`，**绝不写入代码 /
脚本 / git**。Key 要从 dev.meta.ai 控制台建，需在个人网络上建好再到集群用。
集群调通性先测：

```bash
curl -s https://api.meta.ai/v1/models -H "Authorization: Bearer $MODEL_API_KEY" | head -c 500
```

价格按 token，15 分钟课只有几千 token，单次通常低廉，但 Contributor
档位 Meta 可能用数据训练，介意者用 Standard。模型名控制台如显示其他
（如 `muse-wonder-1.0`），以 `--muse-model` 覆盖默认值为准。

用法：先在短样本上跑，对比 `*.orig.srt` 与校对后 SRT 再决定是否整批。
不设 Key 时开启也不失败，只警告保留原字幕。

```bash
.venv/bin/python video_subtitle.py ~/video --model-dir ~/models --model large-v3-turbo --gpus auto --correct-with-muse
```

## 9. 常见转录问题速查

| 现象 | 原因 | 办法 |
| --- | --- | --- |
| 已有 SRT 没变化 | 默认跳过已有字幕 | 加 `--force` 重做；偏向词、提示词、希腊格式都只能在重转时生效，不能改已有 SRT |
| 碎句多 | 分句阈值太严 | 试 `--max-chars 70 --max-duration 10 --max-gap 1.2`，短句合并默认已开，关掉时 `--merge-min-chars 0` |
| 术语错多 | 通用模型不认识专业词 | 加 `--initial-prompt` + `--hotwords`（第 6.1 节），再换大模型；偏向是优先选不是保证选，残错要人工校对或走 Muse 矫正 |
| 速度慢 | 模型大、CPU、beam 大、float32 | 退回 turbo / medium，`--beam-size` 回 5，`--compute-type int8`，有卡用 `--gpus auto` |
| 某文件失败，整批停了 | 不是程序停了，是单文件失败 | 单文件失败不中断整批，继续下一个，最后看 `subtitle_batch.log` 尾几行和失败文件的备注 |
| 进度条进日志文件很乱 | `\r` 原地刷新进了日志 | 加 `--no-progress`，只打印开始和完成 |
| 说话小、尾音丢了 | VAD 误切 | 加 `--no-vad` 试 |
| 音量忽大忽小、有低频噪声 | 源音频问题 | 加 `--audio-filter "loudnorm,highpass=f=80"`，人耳听着都含糊时换更清晰的录音 |

检查结果的口径：不要只看管道退出码，要看进程、日志尾部、模型和结果文件
是否存盘且可加载，缺一样就是异常。SRT 文件存在且可读、log 成功计数、
模型快照路径能见 `model.bin`，才算跑通。
