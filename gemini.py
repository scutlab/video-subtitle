#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini API helper for lecture-subtitle transcription and proofreading.

Authentication: set the GEMINI_API_KEY environment variable to a key from
Google AI Studio (https://aistudio.google.com/apikey). The key is read only
from the environment; never paste it into a file, a log, or chat.

Usage:
  gemini.py list-models
  gemini.py transcribe <audio.mp3> <model> --out <out.srt> [--title <section>]
  gemini.py proofread <srt_file> <model> [--out <path>]

transcribe sends one audio file to the model and asks for a verbatim SRT.
For audio longer than ~10 minutes, prefer batch_transcribe.py, which splits
the audio into 5-minute chunks first: whole-file transcription drifts in
timestamps on long recordings.

proofread sends an existing SRT (e.g. from Whisper) to the model with
instructions to correct ASR errors only, keeping numbering and timestamps
unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

HOST = "generativelanguage.googleapis.com"
BASE = f"https://{HOST}/v1beta"


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("未设置 GEMINI_API_KEY 环境变量，"
                         "请先在 Google AI Studio 申请密钥并 export GEMINI_API_KEY=...")
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call(method: str, path: str, body: dict | None = None, timeout: int = 300) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("x-goog-api-key", _api_key())
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:2000]
        raise RuntimeError(f"Gemini API HTTP {e.code}: {detail}") from e


def list_models() -> None:
    data = call("GET", "/models?pageSize=100")
    for m in data.get("models", []):
        methods = ",".join(m.get("supportedGenerationMethods", []))
        print(f"{m['name']}\t{m.get('displayName', '')}\t{methods}")


def _extract_text(data: dict) -> str:
    texts = []
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                texts.append(part["text"])
    result = "".join(texts)
    if not result.strip():
        raise RuntimeError(f"模型未返回文本：{json.dumps(data, ensure_ascii=False)[:1000]}")
    return result


PROOFREAD_PROMPT = """你是一名中文大学微积分课程字幕校对员。下面是一份由语音识别（Whisper）转写的讲课字幕。

任务：逐条校对，只修正语音识别造成的错误，包括：
- 同音/近音错字（例如“奇函数”误作“击函数”、“被积函数”误作“背积函数”、“积分区域”误作“几温区域”、“对称性”误作“对称信制”/“对称信征”）；
- 数学符号与术语的误转（Ω、λ、ΔVi、ξi、ηi、体积元素 dv 等，按上下文还原）；
- 明显的口误转写和漏字。

严格遵守：
- 不改动任何时间轴和序号，不增删条目，不合并、不拆分条目；
- 不改变原意，不润色、不改写讲课口语，只改错字错词；
- 无法确定的地方保留原文，不要猜测生造内容；
- 只输出校对后的完整 SRT 全文，格式与原文完全一致（序号、时间轴、空行），不要附加任何解释、前言或校对说明。

原文如下：
"""


def proofread(srt_path: str, model: str, out_path: str | None) -> None:
    with open(srt_path, encoding="utf-8") as f:
        srt = f.read()
    body = {
        "contents": [{"parts": [{"text": PROOFREAD_PROMPT + srt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 30000},
    }
    result = _extract_text(call("POST", f"/models/{model}:generateContent", body))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        sys.stdout.write(result)


TRANSCRIBE_PROMPT = """你是一名中文大学微积分课程讲课转写员。音频是《微积分》{section}节的讲课录音，主讲教师讲授该节的微积分内容。

任务：逐字转写全部讲课内容，只输出标准 SRT 字幕全文，不要附加任何解释、前言或说明。

严格遵守：
- 每条字幕对应一句完整或自然断开的话，时长一般 2-8 秒，不把一长段话塞进一条；
- 时间戳格式为 HH:MM:SS,mmm，起止时间单调递增、无重叠、无倒流，覆盖整段音频（从 00:00:00,000 附近开始，到音频结尾附近结束）；
- 数学术语按上下文准确还原：三重积分、被积函数、积分区域、体积元素、柱面坐标、球面坐标、对称性、奇函数、Ω、λ、ΔVi、ξi、ηi、dv 等；易错词必须写对：被积函数（不是“背积函数”）、奇函数（不是“击函数”）、积分区域（不是“几温区域”）、对称性（不是“对称信制/对称信征”）、任取（不是“认取”）；
- 数学符号直接用 Unicode 希腊字母和上下标字符（λ、Ω、Δ、ξ、η、ζ、ΔVᵢ、Ω₁、x² 等），不要用 LaTeX 的 $...$ 格式，也不要把希腊字母拼写成英文单词（如 Omega）；
- 同音词按数学语境取正确写法，不要猜测生造内容，听不清的地方保留最可能的原文；
- 只输出 SRT 全文（序号、时间轴、文本、空行），不要输出其他内容。
"""


def transcribe(audio_path: str, model: str, out_path: str, section: str = "课程") -> None:
    import base64

    prompt = TRANSCRIBE_PROMPT.format(section=section)
    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")
    body = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "audio/mpeg", "data": audio_b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 65536},
    }
    result = _extract_text(call("POST", f"/models/{model}:generateContent", body, timeout=600))
    # Strip possible markdown code fence around the SRT.
    result = result.strip()
    if result.startswith("```"):
        result = result.split("\n", 1)[1] if "\n" in result else result
        if result.rstrip().endswith("```"):
            result = result.rstrip()[: -len("```")].rstrip()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result + "\n")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "list-models":
        list_models()
        return 0
    if len(argv) >= 4 and argv[1] == "transcribe":
        out = None
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
        if not out:
            raise SystemExit("transcribe 需要 --out <srt路径>")
        section = "课程"
        if "--title" in argv:
            section = argv[argv.index("--title") + 1]
        transcribe(argv[2], argv[3], out, section)
        return 0
    if len(argv) >= 4 and argv[1] == "proofread":
        out = None
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
        proofread(argv[2], argv[3], out)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
