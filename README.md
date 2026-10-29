# 视频批量转字幕工具（开源 Whisper 版）

用 ffmpeg 抽音频 → 开源 Whisper（faster-whisper，CTranslate2 本地推理）
做识别并拿到词级时间戳 → 按断句规则切成字幕条目 → 每个视频生成一份同名
`.srt`（可选同时生成 `.vtt`）。不需要 Key、账号、联网计费，模型下载一次后
全程本地离线跑。源代码就是 `video_subtitle.py`，Python 直接跑，不用编译。

字幕口径：视频里念什么，字幕就显示这个读音对应的内容，不人为增加内容。
老师念“二重积分”，字幕就是“二重积分”，不额外加符号；口头没念、只写在
黑板上的公式，字幕里也不凭空补。唯一的例外是希腊字母：只用字符，
如 Ω、λ，详见 `USAGE.md` 第 6.2 节。

## 文档怎么看

- 先装好：看 `INSTALL.md`（安装部署文档）
- 再学怎么用：看 `USAGE.md`（使用手册）
- 旧的 `WINDOWS_SETUP.md` 已合并进上面两个文档，不要再用它，以免两个版本冲突

## 快速上手（3 步，细节见 INSTALL.md）

```bash
# Ubuntu / Linux
./deploy_ubuntu.sh ~/video
# Windows cmd
deploy_windows.bat "D:\video\video"
```

装好后，先只放 1 个 1～3 分钟短视频，跑通再整批：

```bash
# Ubuntu
.venv/bin/python video_subtitle.py ~/video --model-dir ~/models --model small
# Windows PowerShell（已激活 venv）
python video_subtitle.py "D:\video\video" --model-dir "D:\video\models" --model small
```

已有字幕默认跳过，重做加 `--force`。模型整批只加载一次，单个文件失败
不中断整批，明细写在视频目录下的 `subtitle_batch.log`。

## 模型速查

| 模型 | 体积（int8） | 建议 |
| --- | --- | --- |
| tiny | 约 75MB | 最快，先出草稿 |
| base | 约 142MB | 速度与精度折中 |
| small（默认） | 约 466MB | 中文日常够用，推荐起点 |
| medium | 约 1.5GB | 精度更好 |
| large-v3-turbo | 约 1.6GB | 有显卡时优先推荐，精度接近 large-v3 且快得多 |
| large-v3 | 约 3GB | 精度最高，最慢 |

换模型只换 `--model` 后面的名字。全部模型命令、提示词、偏向词、
希腊字母、双 GPU、Muse 矫正，见 `USAGE.md`。

## 包里文件

- `video_subtitle.py`：源代码
- `requirements.txt`：依赖（`faster-whisper>=1.0`，`av<19` 不要去掉，
  av 19 会报 `metadata_errors` 错）
- `deploy_windows.bat` / `deploy_ubuntu.sh` / `deploy_ubuntu_large-v3.sh`：
  一键部署 + 可选转录
- `build_windows.bat`：可选，只在 Windows 上编成 `VideoSub.exe`
- `run_windows.bat`：可选，免编译快捷方式，只适合全局装了依赖时用
- `INSTALL.md` / `USAGE.md`：安装部署文档 / 使用手册
