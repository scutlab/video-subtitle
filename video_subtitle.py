#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频批量转字幕工具 VideoSub（开源 Whisper 版）
流程：ffmpeg 抽音频(16kHz 单声道 WAV) -> faster-whisper（开源 Whisper 实现，
     CTranslate2 推理，本地离线运行，无需任何 Key / 账号 / 联网计费）
     词级时间戳 + VAD 过滤 -> 按断句规则切分 -> SRT / VTT，每个视频一份字幕。

模型只加载一次，整批文件共用；首次运行会自动从 Hugging Face 下载所选模型，
之后离线可用。可用 --model-dir 把模型放在固定目录，随 exe 一起拷贝也行。
用法示例（Windows）：
    VideoSub.exe "D:\\Videos"
    VideoSub.exe "D:\\Videos" --model small --language zh --format both --recursive
    VideoSub.exe "D:\\Videos" --model base --device cpu
"""
import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac",
}
SENTENCE_END = set("。！？.!?；;")
MAX_CHARS = 42        # 一条字幕最多字符数
MAX_DURATION = 6.0    # 一条字幕最长秒数
MAX_GAP = 0.8         # 词间静音超过该秒数就断句
TIME_PAD = 0.05       # 首尾各留的缓冲，避免字幕卡在发音起点

# 模型大小参考（faster-whisper，int8 下体积更小，仅作选型参考）：
# tiny ~75MB：最快，中文草稿可用，错字较多；base ~142MB：速度与精度折中
# small ~466MB：默认，中文日常字幕够用；medium ~1.5GB：精度更好，CPU 较慢
# large-v3 / large-v3-turbo：精度最高，CPU 上很慢，只建议有显卡时用


@dataclass
class Word:
    text: str
    start: float  # 秒
    end: float    # 秒


@dataclass
class Cue:
    words: list = field(default_factory=list)

    @property
    def start(self):
        return max(0.0, self.words[0].start - TIME_PAD)

    @property
    def end(self):
        return self.words[-1].end + TIME_PAD

    def text(self, language: str) -> str:
        # 中文/日文按字拼接不加空格，其他语言按词加空格
        if language.startswith(("zh", "ja")):
            return "".join(w.text for w in self.words)
        return " ".join(w.text for w in self.words)


def normalize_language(language: str) -> str:
    """faster-whisper 用 zh / en 这类短码；zh-CN、en-US 也接受，自动取前段。"""
    lang = (language or "zh").strip().lower().replace("_", "-")
    return lang.split("-")[0] or "zh"


def fmt_hms(seconds: float) -> str:
    """秒数 -> MM:SS 或 HH:MM:SS，用于进度条的已用/剩余时间。"""
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def short_name(name: str, limit: int = 20) -> str:
    """文件名太长时截断，避免进度条一行写不下、换行刷屏。"""
    return name if len(name) <= limit else name[: limit - 1] + "…"


class InPlaceProgress:
    """单行原地进度条：只用 \\r 回到行首重写，绝不 print 换行刷屏。

    转录中途不管更新多少次，终端里始终只占这一行，之前的文字不会被
    一行行顶上去；转录结束时才换行一次，然后 [完成]/[失败] 再正常打印。
    进度 = 已转录音频时长 / 音频总时长（faster-whisper 的 info.duration），
    剩余时间 = 已用时间 / 进度 - 已用时间，倍速 = 已转录时长 / 已用时间。
    """

    def __init__(self, label: str, enabled: bool = True):
        self.label = label
        self.enabled = enabled
        self.start = time.time()
        self.last_len = 0
        self.last_update = 0.0
        self.last_percent = -1
        self.updated = False

    def update(self, processed: float, total: float) -> None:
        if not self.enabled:
            return
        now = time.time()
        elapsed = now - self.start
        if total and total > 0:
            progress = min(1.0, max(0.0, processed / total))
            percent = int(progress * 100)
        else:
            progress, percent = 0.0, 0
        # 节流：同一百分比 0.2 秒内不重复刷，避免闪烁和 CPU 浪费；
        # 100% 一定要刷出来，不能被节流吞掉。
        if percent == self.last_percent and percent < 100 and now - self.last_update < 0.2:
            return
        self.last_percent = percent
        self.last_update = now
        self.updated = True
        width = 25
        filled = int(progress * width)
        bar = "#" * filled + "-" * (width - filled)
        speed = (processed / elapsed) if elapsed > 0 else 0.0
        eta = (elapsed / progress - elapsed) if progress > 0.01 else None
        line = (
            f"{self.label} {percent:3d}% [{bar}] "
            f"已用 {fmt_hms(elapsed)} 剩余约 {fmt_hms(eta) if eta is not None else '--:--'} "
            f"{speed:.1f}x"
        )
        # 用空格擦掉上一行更长的残留，再回到行首，下次重写会覆盖整行。
        sys.stdout.write("\r" + line + " " * max(0, self.last_len - len(line)))
        sys.stdout.flush()
        self.last_len = len(line)

    def finish(self) -> None:
        """结束：只换行一次，让下一行 [完成]/[失败] 从新行开始。"""
        if not self.enabled or not self.updated:
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.updated = False
        self.last_len = 0


def check_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "找不到 ffmpeg。请先安装并加入 PATH（Windows：把 ffmpeg.exe "
            "放在 VideoSub.exe 同目录或装入 PATH 后再运行）。"
        )
    return path


def extract_audio(video: Path, wav_path: Path, audio_filter: str = "") -> None:
    """只抽音频，转 Whisper 常用格式：16kHz 单声道 PCM WAV。

    audio_filter 不为空时作为 ffmpeg -af 传入，例如
    "loudnorm,highpass=f=80"（响度归一 + 去低频噪声），
    适合原音频音量忽大忽小、有低频嗡嗡声时提精度；不填就是原样抽音。
    """
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
    ]
    if audio_filter:
        cmd += ["-af", audio_filter]
    cmd += ["-acodec", "pcm_s16le", str(wav_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg 抽音频失败：{proc.stderr.strip() or '无输出音频'}")


def detect_gpus() -> list:
    """用 nvidia-smi 查本机 GPU 编号，查不到（没卡、没驱动、没装 nvidia-smi）就返回空列表。

    只做检测，不装驱动、不改系统，失败时调用方按单卡 / CPU 处理。
    """
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return []
        return [int(line.strip()) for line in proc.stdout.splitlines()
                if line.strip().isdigit()]
    except Exception:
        return []


def parse_gpu_list(value: str) -> list:
    """解析 --gpus：空 -> []，auto -> nvidia-smi 检测到的卡，0,1 -> [0, 1]，1 -> [1]。

    去重但保持顺序，非法值直接报错，让用户在启动时就发现，而不是跑一半才失败。
    """
    if not value:
        return []
    value = value.strip().lower()
    if value in ("none", "cpu"):
        return []
    if value == "auto":
        return detect_gpus()
    result = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
        except ValueError as exc:
            raise ValueError(f"--gpus 格式不对：{value!r}，应为 0,1 或 auto") from exc
        if idx < 0:
            raise ValueError(f"--gpus 里不能有负数：{idx}")
        if idx not in result:
            result.append(idx)
    return result


def load_model(model_size: str, device: str, compute_type: str, model_dir: str,
               device_index: int = 0):
    """只在整批开始时加载一次模型；多卡时每张卡各加载一次（见 main 的多卡分支）。

    device="auto" 是 faster-whisper 自带的优先逻辑：有 GPU 就用 GPU，
    没 GPU 就回落到 CPU，所以默认 auto 就是“优先用 GPU”。
    device="cuda" 时 device_index 指定用哪张卡，0 是第一张卡。
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "未安装 faster-whisper，请先执行：pip install -r requirements.txt"
        ) from exc
    kwargs = {"device": device, "compute_type": compute_type}
    if device == "cuda":
        kwargs["device_index"] = device_index
    if model_dir:
        kwargs["download_root"] = model_dir
    label = f"GPU {device_index}" if device == "cuda" else device
    print(f"正在加载 Whisper 模型：{model_size}（{label}，首次运行会下载模型，之后离线可用）…")
    return WhisperModel(model_size, **kwargs)


def recognize_words(model, wav_path: Path, language: str, on_progress=None,
                    beam_size: int = 5, vad_filter: bool = True,
                    initial_prompt: str = "", hotwords: str = "") -> list:
    """用 faster-whisper 转录，返回词级时间戳列表。

    segments 是边转录边产出的生成器，每产出一段就按该段结束时间
    回调一次进度，调用方据此更新单行进度条；转录结束时再回调一次
    100%，避免最后一段结束时间小于总时长时进度卡在 90% 多不动。

    调精度用的四个开关：
    - beam_size 越大，搜索越充分、错字越少，但越慢（5 -> 10 约慢一倍）；
    - vad_filter=False 时不跳过静音段，适合说话声音小、VAD 误切时；
    - initial_prompt 是给模型的上下文提示，例如课程名和专业术语，
      能显著减少同音词错成别的词（数学课尤其明显）；
    - hotwords 是 Whisper 原生的偏向词：逗号分隔的术语列表，解码时
      优先选这些词，例如“三重积分,被积函数,奇函数,偶函数”。
      它和 initial_prompt 可以叠加，前者是整句上下文，后者是逐词偏向。
      注意：hotwords / initial_prompt 都是在转录音频时起作用，
      不能拿来改已经生成的 SRT 文本——Whisper 的输入只能是音频，
      没有“输入一段文字、输出一段改对的文字”这个接口，
      所以用 large-v3“矫正”本质上是重转音频，不是像 Muse 那样改文本。
    """
    segments, info = model.transcribe(
        str(wav_path),
        language=language,
        word_timestamps=True,
        vad_filter=vad_filter,    # 默认跳过静音/纯音乐段，减少幻觉字幕
        beam_size=beam_size,
        initial_prompt=(initial_prompt or None),
        hotwords=(hotwords or None),
    )
    total = float(getattr(info, "duration", 0) or 0)
    words = []
    for seg in segments:
        seg_words = getattr(seg, "words", None)
        if seg_words:
            for w in seg_words:
                text = (w.word or "").strip()
                if text:
                    words.append(Word(text, float(w.start), float(w.end)))
        elif (seg.text or "").strip():
            # 兜底：该段拿不到词级时间戳时，用整段起止时间当一个“词”
            words.append(Word(seg.text.strip(), float(seg.start), float(seg.end)))
        if on_progress is not None:
            on_progress(float(seg.end), total)
    if on_progress is not None and total > 0:
        on_progress(total, total)
    if not words:
        raise RuntimeError("未识别到任何语音（可能是无声/纯音乐/语言不匹配）")
    words.sort(key=lambda w: w.start)
    return words


def group_cues(words: list, language: str,
               max_chars: int = MAX_CHARS,
               max_duration: float = MAX_DURATION,
               max_gap: float = MAX_GAP) -> list:
    """按断句规则把词切成字幕条目。"""
    cues, current = [], Cue()
    for word in words:
        if current.words:
            prev = current.words[-1]
            gap = word.start - prev.end
            cur_text = current.text(language)
            over_chars = len(cur_text) + len(word.text) > max_chars
            over_time = word.end - current.words[0].start > max_duration
            if gap > max_gap or over_chars or over_time:
                cues.append(current)
                current = Cue()
        current.words.append(word)
        # 句末标点：当前词以句末标点结尾时断句
        if word.text and word.text[-1] in SENTENCE_END:
            cues.append(current)
            current = Cue()
    if current.words:
        cues.append(current)
    return cues


def merge_short_cues(cues: list, language: str,
                     min_chars: int = 10,
                     min_duration: float = 1.5,
                     max_chars: int = 80,
                     max_duration: float = 12.0) -> list:
    """把碎句合并成可读的句子，只合并，不删字、不改词、不改时间顺序。

    碎句的两个来源：一是讲课停顿超过 max_gap，词被切成“第二步,”
    “体积”“称”这种 1 秒都不到的片段；二是句末标点前就断了。
    合并规则（同时满足才并）：
    - 前一条太短：字数 < min_chars 或时长 < min_duration；
    - 或前一条以逗号、顿号、分号结尾（本是半句话，不是完整句）；
    - 合并后字数 <= max_chars 且时长 <= max_duration。
    最后一条如果本身太短，就往前并进上一条（同样受上限约束）。
    时间戳取合并后第一词的开始（减缓冲）和最后词的结束（加缓冲），
    Cue.start / Cue.end 本来就是这样算的，所以不会出现时间倒流。
    """
    if not cues or min_chars <= 0:
        return cues
    merged = []
    for cue in cues:
        if not merged:
            merged.append(cue)
            continue
        prev = merged[-1]
        prev_text = prev.text(language)
        prev_dur = prev.words[-1].end - prev.words[0].start
        merged_text_len = len(prev_text) + len(cue.text(language))
        merged_dur = cue.words[-1].end - prev.words[0].start
        is_short = len(prev_text) < min_chars or prev_dur < min_duration
        is_clause = prev_text and prev_text[-1] in "，、；,;"
        if (is_short or is_clause) and merged_text_len <= max_chars and merged_dur <= max_duration:
            prev.words.extend(cue.words)
        else:
            merged.append(cue)
    # 尾巴碎句往前并
    if len(merged) >= 2:
        last = merged[-1]
        last_text = last.text(language)
        last_dur = last.words[-1].end - last.words[0].start
        prev = merged[-2]
        if (len(last_text) < min_chars or last_dur < min_duration) and \
                len(prev.text(language)) + len(last_text) <= max_chars and \
                last.words[-1].end - prev.words[0].start <= max_duration:
            prev.words.extend(last.words)
            merged.pop()
    return merged


def muse_correct_texts(texts: list, api_key: str, model: str, base_url: str,
                       timeout: float = 120.0) -> list:
    """调一次 Muse API，校对一小段字幕文本，返回同等数量的校对后文本。

    只用标准库 urllib，不新增 openai 依赖，所以不用 Muse 矫正的用户
    完全不受影响。接口是 Meta Model API 的 OpenAI 兼容端点：
    POST {base_url}/chat/completions，Bearer 鉴权，Key 从环境变量读，
    绝不写进代码、脚本或日志里。
    提示词刻意收紧：只改明显的同音 / 近音错字（例如三种结分、三重积分
    这种），不改时间戳（时间戳根本不发给模型，只发文本），不增删、
    不合并、不拆分条目，不加没念过的公式符号，不确定就保留原文。
    调用方必须校验返回行数，不对就整段回退原文，见 correct_cues_with_muse。
    """
    system_prompt = (
        "你是高等数学课字幕校对员。输入是按时间顺序的一组字幕条目，"
        "每行一条，来自 Whisper 识别，可能有同音 / 近音错字，"
        "例如“三重积分”被写成“三种结分”、“奇函数”被写成“G函数”、"
        "“被积函数”被写成“贝基函数”。你的任务只做一件事："
        "把明显错的术语改回老师实际讲的术语。"
        "严格遵守：不增删、不合并、不拆分条目；不改变每条的意思和语气；"
        "不添加原文没有的公式、解释；不确定时保留原文；"
        "希腊字母例外：一律只写符号，例如 Ω、λ、Δ、Σ、θ、φ，"
        "不要写英文名 Omega、Lambda，也不要写中文读音欧米伽、拉姆达；"
        "只返回校对后的文本，行数和输入完全一致，每行一条，"
        "不要序号、不要 markdown、不要解释、不要多余空行。"
    )
    user_content = "\n".join(texts)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "max_tokens": max(500, sum(len(t) for t in texts) * 2 + 200),
    }
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise RuntimeError(f"Muse API HTTP {exc.code}：{detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Muse API 调用失败：{exc}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Muse API 返回格式不对：{str(body)[:500]}") from exc
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    return lines


def correct_cues_with_muse(cues: list, language: str, api_key: str, model: str,
                           base_url: str, chunk_size: int = 40):
    """用 Muse 分段校对字幕，返回 (新 cues, 改了几条, 失败几段)。

    安全边界比准确率更重要：
    - 时间戳不发给模型，校对后用原条目的首尾词时间重建，时间戳原样不动；
    - 每段校验行数，行数不对、某行空、调用报错，整段回退原文，不写坏 SRT；
    - 改动只体现在文本上，条数不变，所以 SRT 序号和时间轴不会错位。
    """
    if not cues or chunk_size <= 0:
        return cues, 0, 0
    out, changed, failed = [], 0, 0
    for i in range(0, len(cues), chunk_size):
        chunk = cues[i:i + chunk_size]
        texts = [c.text(language) for c in chunk]
        try:
            corrected = muse_correct_texts(texts, api_key, model, base_url)
            if len(corrected) != len(texts) or any(not t for t in corrected):
                raise RuntimeError(f"返回行数不对：输入 {len(texts)} 行，返回 {len(corrected)} 行")
        except Exception as exc:
            print(f"[Muse 矫正] 第 {i + 1} 段失败，已保留原文：{exc}")
            failed += 1
            out.extend(chunk)
            continue
        for cue, new_text in zip(chunk, corrected):
            if new_text != cue.text(language):
                changed += 1
                start = cue.words[0].start if cue.words else 0.0
                end = cue.words[-1].end if cue.words else 0.0
                new_cue = Cue(words=[Word(new_text, start, end)])
                out.append(new_cue)
            else:
                out.append(cue)
    return out, changed, failed


# 希腊字母：只用字符，符号用微积分里最常见的那个大小写
# （Ω 是积分区域常用大写，λ、θ、φ 等常用小写，Δ 是增量大写，Σ 是求和大写）
# 用户 2026-10-29 先定英文 + 符号，随后更正为只用字符，覆盖上一版口径。
GREEK_LETTERS = [
    # (英文名, 符号, 中文读音列表)
    ("Alpha", "α", ["阿尔法"]),
    ("Beta", "β", ["贝塔"]),
    ("Gamma", "γ", ["伽马"]),
    ("Delta", "Δ", ["德尔塔"]),
    ("Epsilon", "ε", ["艾普西隆", "伊普西隆"]),
    ("Zeta", "ζ", ["泽塔"]),
    ("Eta", "η", ["伊塔"]),
    ("Theta", "θ", ["西塔"]),
    ("Iota", "ι", ["约塔"]),
    ("Kappa", "κ", ["卡帕"]),
    ("Lambda", "λ", ["拉姆达"]),
    ("Mu", "μ", ["缪"]),
    ("Nu", "ν", ["纽"]),
    ("Xi", "ξ", ["克西"]),
    ("Omicron", "ο", ["奥密克戎"]),
    ("Pi", "π", ["派"]),
    ("Rho", "ρ", ["柔", "罗"]),
    ("Sigma", "Σ", ["西格玛"]),
    ("Tau", "τ", ["陶"]),
    ("Upsilon", "υ", ["宇普西隆"]),
    ("Phi", "φ", ["斐"]),
    ("Chi", "χ", ["希"]),
    ("Psi", "ψ", ["普西"]),
    ("Omega", "Ω", ["欧米伽"]),
]


def format_greek_letters(text: str) -> str:
    """希腊字母一律只用字符，例如 Ω、λ、Δ。

    三种输入都归一到同一种输出，不重复、不丢字：
    - 中文读音“欧米伽” -> “Ω”
    - 英文名“Omega” -> “Ω”
    - “Omega Ω”这种上一版的英文 + 符号 -> “Ω”（去掉英文名，只留符号）
    - 符号“Ω”单独出现 -> 不变
    只做希腊字母这一类，不碰其他术语和公式，时间戳由调用方原样保留。
    """
    if not text:
        return text
    out = text
    for eng, symbol, chinese_names in GREEK_LETTERS:
        # 1. 上一版的英文 + 符号 -> 只留符号
        out = re.sub(
            rf"(?<![A-Za-z]){eng}\s*{re.escape(symbol)}",
            symbol, out, flags=re.IGNORECASE,
        )
        # 2. 中文读音 + 符号 -> 只留符号，再做中文读音单独出现 -> 符号
        for cn in sorted(chinese_names, key=len, reverse=True):
            out = out.replace(f"{cn} {symbol}", symbol)
            out = out.replace(f"{cn}{symbol}", symbol)
            out = out.replace(cn, symbol)
        # 3. 英文名单独出现 -> 符号
        # 注意：不能用 \b，因为中文是 Unicode 词字符，“Omega是”里
        # a 和 是之间没有词边界，\b 会匹配失败；改用前后不是英文字母来界定。
        out = re.sub(
            rf"(?<![A-Za-z]){eng}(?![A-Za-z])",
            symbol, out, flags=re.IGNORECASE,
        )
    return out


def apply_greek_format(cues: list, language: str) -> list:
    """对一组 cues 做希腊格式，返回新 cues，时间戳原样不动。"""
    out = []
    for cue in cues:
        text = cue.text(language)
        new_text = format_greek_letters(text)
        if new_text != text and cue.words:
            start = cue.words[0].start
            end = cue.words[-1].end
            out.append(Cue(words=[Word(new_text, start, end)]))
        else:
            out.append(cue)
    return out


def fmt_srt(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_vtt(seconds: float) -> str:
    return fmt_srt(seconds).replace(",", ".")


def render_srt(cues: list, language: str) -> str:
    lines = []
    for i, cue in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{fmt_srt(cue.start)} --> {fmt_srt(cue.end)}")
        lines.append(cue.text(language))
        lines.append("")
    return "\n".join(lines)


def render_vtt(cues: list, language: str) -> str:
    lines = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{fmt_vtt(cue.start)} --> {fmt_vtt(cue.end)}")
        lines.append(cue.text(language))
        lines.append("")
    return "\n".join(lines)


def process_one(video: Path, args, model, language: str, log_rows: list,
                index: int = 1, total_files: int = 1) -> str:
    """处理单个文件，返回状态：done / skipped / failed。

    转录进度用同一行原地刷新，不刷屏；失败时也要先把进度行换行，
    再打印 [失败]，否则失败信息会盖在进度条同一行上。
    """
    if args.output_dir:
        # 保持输入目录下的相对结构
        rel = video.relative_to(args.input_dir) if video.is_relative_to(args.input_dir) else Path(video.name)
        out_base = Path(args.output_dir) / rel.with_suffix("")
        out_base.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_base = video.with_suffix("")

    targets = []
    if args.format in ("srt", "both"):
        targets.append(out_base.with_suffix(".srt"))
    if args.format in ("vtt", "both"):
        targets.append(out_base.with_suffix(".vtt"))

    if not args.force and all(t.exists() for t in targets):
        print(f"[跳过] 已有字幕：{video.name}")
        log_rows.append([str(video), "skipped", "已有字幕"])
        return "skipped"

    progress = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            extract_audio(video, wav, args.audio_filter)
            if args.keep_audio:
                kept = out_base.with_suffix(".wav")
                shutil.copyfile(wav, kept)
            progress = InPlaceProgress(
                f"转录 [{index}/{total_files}] {short_name(video.name)}",
                enabled=not args.no_progress,
            )
            words = recognize_words(
                model, wav, language, progress.update,
                beam_size=args.beam_size,
                vad_filter=not args.no_vad,
                initial_prompt=args.initial_prompt,
                hotwords=getattr(args, "hotwords", ""),
            )
        if progress is not None:
            progress.finish()
        cues = group_cues(
            words, language,
            getattr(args, "max_chars", MAX_CHARS),
            getattr(args, "max_duration", MAX_DURATION),
            getattr(args, "max_gap", MAX_GAP),
        )
        cues = merge_short_cues(
            cues, language,
            min_chars=getattr(args, "merge_min_chars", 10),
            min_duration=getattr(args, "merge_min_duration", 1.5),
            max_chars=getattr(args, "merge_max_chars", 80),
            max_duration=getattr(args, "merge_max_duration", 12.0),
        )
        if getattr(args, "greek_format", True):
            cues = apply_greek_format(cues, language)
        orig_cues = None
        if getattr(args, "correct_with_muse", False):
            api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("MUSE_API_KEY")
            if not api_key:
                print("[警告] 已开 --correct-with-muse 但未设 MODEL_API_KEY，"
                      "跳过 Muse 矫正，保留原字幕（Key 请在终端 export，不要写进代码）")
            else:
                orig_cues = cues
                cues, changed, failed = correct_cues_with_muse(
                    cues, language, api_key,
                    getattr(args, "muse_model", "muse-spark-1.3"),
                    getattr(args, "muse_base_url", "https://api.meta.ai/v1"),
                    getattr(args, "muse_chunk_size", 40),
                )
                print(f"[Muse 矫正] 改了 {changed} 条，{failed} 段失败已保留原文")
                if orig_cues is not None and changed > 0 and \
                        any(t.suffix == ".srt" for t in targets):
                    # 矫正前原稿留一份 .orig.srt，方便对照和回退
                    orig_text = render_srt(orig_cues, language)
                    out_base.with_suffix(".orig.srt").write_text(orig_text, encoding="utf-8-sig")
        for target in targets:
            text = render_srt(cues, language) if target.suffix == ".srt" else render_vtt(cues, language)
            target.write_text(text, encoding="utf-8-sig" if target.suffix == ".srt" else "utf-8")
        print(f"[完成] {video.name} -> {len(cues)} 条字幕")
        log_rows.append([str(video), "done", f"{len(cues)} 条"])
        return "done"
    except Exception as exc:  # 单个文件失败不中断整批
        if progress is not None:
            progress.finish()
        print(f"[失败] {video.name}：{exc}")
        log_rows.append([str(video), "failed", str(exc)])
        return "failed"


def collect_files(input_dir: Path, recursive: bool) -> list:
    pattern = "**/*" if recursive else "*"
    files = [p for p in input_dir.glob(pattern)
             if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return sorted(files)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="视频批量转字幕（开源 Whisper，本地离线）")
    parser.add_argument("input_dir", help="要处理的视频目录")
    parser.add_argument("--language", default="zh", help="识别语言：zh、en 等，也接受 zh-CN，默认 zh")
    parser.add_argument("--model", default="small",
                        help="Whisper 模型：tiny / base / small / medium / large-v3-turbo / large-v3，默认 small")
    parser.add_argument("--model-dir", default="",
                        help="模型缓存目录，默认系统缓存；填了可随身携带、离线复用")
    parser.add_argument("--device", default="auto",
                        help="auto（默认，优先 GPU，有卡用卡，没卡用 CPU）/ cpu / cuda")
    parser.add_argument("--gpus", default="",
                        help="多卡并行：0,1 表示同时用 GPU 0 和 GPU 1 分文件并行，auto 表示用 nvidia-smi 检测到的全部卡；"
                             "只填一张卡（如 1）就是只用那张卡；不填时 auto 只用第一张卡")
    parser.add_argument("--compute-type", default="int8",
                        help="计算精度：int8（默认，又快又省显存，多卡时推荐）/ float16（显卡常用）")
    parser.add_argument("--format", choices=["srt", "vtt", "both"], default="srt")
    parser.add_argument("--recursive", action="store_true", help="递归子目录")
    parser.add_argument("--force", action="store_true", help="已有字幕也重做")
    parser.add_argument("--output-dir", default="", help="字幕输出目录，默认与视频同目录")
    parser.add_argument("--keep-audio", action="store_true", help="保留中间 WAV")
    parser.add_argument("--no-progress", action="store_true",
                        help="关闭单行进度条（只打印开始/完成，适合重定向到日志文件时用）")
    parser.add_argument("--beam-size", type=int, default=5,
                        help="束搜索宽度：越大越准、越慢，默认 5，提精度可试 10")
    parser.add_argument("--no-vad", action="store_true",
                        help="关闭 VAD 静音过滤：说话声音小、VAD 误切丢句时试")
    parser.add_argument("--initial-prompt", default="",
                        help="给模型的上下文提示，如课程名和专业术语，能减少同音词错字")
    parser.add_argument("--hotwords", default="",
                        help="Whisper 原生偏向词，逗号分隔，如“三重积分,被积函数,奇函数,偶函数”，"
                             "解码时优先选这些词，可与 --initial-prompt 叠加；只能在重转音频时用，不能改已有 SRT")
    parser.add_argument("--audio-filter", default="",
                        help="ffmpeg 音频滤波，如 loudnorm,highpass=f=80，音量忽大忽小或有低频噪声时试")
    parser.add_argument("--max-chars", type=int, default=MAX_CHARS)
    parser.add_argument("--max-duration", type=float, default=MAX_DURATION,
                        help="单条字幕最长秒数，默认 6，讲课语速慢、停顿多时可试 10")
    parser.add_argument("--max-gap", type=float, default=MAX_GAP,
                        help="词间停顿超过该秒数就断句，默认 0.8，碎句多时可试 1.2")
    parser.add_argument("--merge-min-chars", type=int, default=10,
                        help="短句合并：短于该字数的条目尽量往后并，默认 10，0 表示关闭合并")
    parser.add_argument("--merge-min-duration", type=float, default=1.5,
                        help="短句合并：短于该秒数的条目尽量往后并，默认 1.5")
    parser.add_argument("--merge-max-chars", type=int, default=80,
                        help="短句合并后单条最多字数，默认 80")
    parser.add_argument("--merge-max-duration", type=float, default=12.0,
                        help="短句合并后单条最长秒数，默认 12")
    parser.add_argument("--greek-format", action=argparse.BooleanOptionalAction, default=True,
                        help="希腊字母只用字符，如 Ω、λ（默认开，"
                             "--no-greek-format 可关闭）")
    parser.add_argument("--correct-with-muse", action="store_true",
                        help="用 Muse API 再校对一遍字幕（默认关闭；开启时需在终端设 MODEL_API_KEY，"
                             "只改同音错字、不改时间戳和条数，失败自动回退原文）")
    parser.add_argument("--muse-model", default="muse-spark-1.3",
                        help="Muse 模型名，默认 muse-spark-1.3，控制台里显示其他型号时改成那个名字")
    parser.add_argument("--muse-base-url", default="https://api.meta.ai/v1",
                        help="Meta Model API 地址，默认 https://api.meta.ai/v1")
    parser.add_argument("--muse-chunk-size", type=int, default=40,
                        help="Muse 矫正时每段多少条字幕，默认 40")
    args = parser.parse_args(argv)
    args.input_dir = Path(args.input_dir)
    language = normalize_language(args.language)

    if not args.input_dir.is_dir():
        print(f"目录不存在：{args.input_dir}", file=sys.stderr)
        return 2
    try:
        check_ffmpeg()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    files = collect_files(args.input_dir, args.recursive)
    if not files:
        print(f"目录下没有可处理文件：{args.input_dir}")
        return 0

    # GPU 选择逻辑（优先用 GPU 的关键）：
    # - --gpus 给了卡号，就强制用 cuda，不管 --device 原来是 auto 还是 cpu，
    #   因为填了卡号却还用 CPU 是没有意义的；
    # - --device auto 且没填 --gpus 时，走单模型路径，faster-whisper 自己
    #   优先用第一张 GPU，没 GPU 时回落 CPU；
    # - --device cpu 时忽略 --gpus 之外的 GPU，不进多卡分支。
    try:
        gpus = parse_gpu_list(args.gpus)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if gpus and args.device != "cuda":
        print(f"已指定 GPU {gpus}，优先用 GPU（忽略 --device {args.device}）")
        args.device = "cuda"
    # 多卡并行只在文件数多于 1 且卡数多于 1 时才有意义：
    # 只有 1 个文件时，单文件本身只能用一张卡，加载第二张卡是浪费显存。
    multi_gpus = gpus[:min(len(gpus), len(files))] if len(files) > 1 else gpus[:1]

    print(f"共 {len(files)} 个文件，语言={language}，模型={args.model}，格式={args.format}")
    counts = {"done": 0, "skipped": 0, "failed": 0}
    log_rows = []

    if len(multi_gpus) > 1:
        # 多卡并行：每张卡各加载一个模型（在主线程里按顺序加载，
        # 避免多线程同时初始化 CUDA 抢资源），然后把文件轮流分给各卡，
        # 用线程池并行跑。推理本身在 C++ 里释放了 GIL，所以线程能真正并行；
        # 单文件仍只用一张卡，加速来自“不同文件同时在不同卡上跑”，
        # 不是把一个文件切开。进度条在多线程下会互相覆盖，所以多卡时强制关掉，
        # 只打印每文件的 [完成]/[失败] 一行。
        orig_no_progress = args.no_progress
        args.no_progress = True
        models = {}
        for gpu in multi_gpus:
            try:
                models[gpu] = load_model(args.model, "cuda", args.compute_type,
                                         args.model_dir, device_index=gpu)
            except Exception as exc:
                print(f"GPU {gpu} 加载模型失败，已跳过这张卡：{exc}", file=sys.stderr)
        if not models:
            print("所有 GPU 都加载失败，请检查驱动和 ctranslate2 的 CUDA 版本（见 README 双 GPU 一节）",
                  file=sys.stderr)
            return 2
        if len(models) == 1:
            # 只剩一张卡能用时，退回单卡顺序跑，避免线程池的额外复杂度
            args.no_progress = orig_no_progress
            gpu, model = next(iter(models.items()))
            print(f"只剩 GPU {gpu} 可用，退回单卡顺序处理")
            for i, video in enumerate(files, 1):
                counts[process_one(video, args, model, language, log_rows, i, len(files))] += 1
        else:
            gpu_list = list(models.keys())
            print(f"多 GPU 并行：{len(gpu_list)} 张卡 {gpu_list}，文件轮流分给各卡")

            def _run_one(task):
                idx, video = task
                gpu = gpu_list[(idx - 1) % len(gpu_list)]
                local_log = []
                status = process_one(video, args, models[gpu], language,
                                     local_log, idx, len(files))
                return status, local_log

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(gpu_list)) as pool:
                futures = [pool.submit(_run_one, (i, v))
                           for i, v in enumerate(files, 1)]
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        status, local_log = fut.result()
                    except Exception as exc:
                        print(f"[失败] 并行任务异常：{exc}", file=sys.stderr)
                        status, local_log = "failed", []
                    counts[status] += 1
                    log_rows.extend(local_log)
        # 多卡分支已处理完所有文件，直接跳到写日志
    else:
        # 单卡 / CPU / auto 的原有顺序路径，不变
        single_gpu = multi_gpus[0] if multi_gpus else 0
        try:
            model = load_model(args.model, args.device, args.compute_type,
                               args.model_dir, device_index=single_gpu)
        except Exception as exc:
            print(f"加载模型失败：{exc}", file=sys.stderr)
            return 2
        for i, video in enumerate(files, 1):
            counts[process_one(video, args, model, language, log_rows, i, len(files))] += 1

    log_path = args.input_dir / "subtitle_batch.log"
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["文件", "状态", "备注", datetime.now().isoformat(timespec="seconds")])
        writer.writerows(log_rows)
    print(f"完成：成功 {counts['done']}，跳过 {counts['skipped']}，"
          f"失败 {counts['failed']}。明细见 {log_path}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
