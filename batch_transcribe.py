#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch-transcribe a directory of lecture videos with Gemini.

Pipeline per video: extract audio (16 kHz mono MP3, kept for reuse) ->
split into 5-minute chunks -> transcribe each chunk with gemini.py ->
offset chunk timestamps and merge into one SRT -> convert LaTeX to
plain Unicode (latex_to_plain.py) -> validate.

Why chunks: whole-file transcription drifts in timestamps on recordings
longer than ~10 minutes (in one real case the timestamps jumped from
595 s to 3600 s mid-file). Five-minute chunks keep timestamps honest.

Resumable: audio, chunk SRTs and the progress file are kept, so a
re-run skips finished videos and finished chunks.

Usage:
  export GEMINI_API_KEY=...
  python3 batch_transcribe.py --videos ./videos --audio-dir ./audio \
      --out-dir ./srt --model gemini-3.8-flash [--chunk 300]

  --videos: directory of .mp4 files (file stem is used as the title)
  --audio-dir: extracted audio is saved here and never deleted
  --out-dir: one <stem>.srt per video, plus progress.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from latex_to_plain import to_plain  # noqa: E402

GEMINI_PY = os.path.join(HERE, "gemini.py")

_ENTRY_RE = re.compile(
    r'(?m)^(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s*\n'
    r'(.*?)(?=^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3} --> |\Z)', re.S)


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def duration(path: str) -> float:
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip())


def parse_srt(text: str):
    # Regex-based: Gemini sometimes omits the blank line between entries,
    # so splitting on blank lines silently collapses entries.
    def ts(s):
        h, m, sec = s.replace(',', '.').split(':')
        return int(h) * 3600 + int(m) * 60 + float(sec)

    return [(ts(a), ts(b), txt.strip())
            for _, a, b, txt in _ENTRY_RE.findall(text)]


def fmt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def merge_chunks(chunk_files, offsets):
    rows = []
    for cf, off in zip(chunk_files, offsets):
        for a, b, txt in parse_srt(open(cf, encoding='utf-8').read()):
            rows.append((a + off, b + off, txt))
    rows.sort(key=lambda r: r[0])
    out = []
    for i, (a, b, txt) in enumerate(rows, 1):
        if i > 1 and a < rows[i - 2][1]:
            a = rows[i - 2][1]  # clamp tiny overlaps
        if b <= a:
            b = a + 0.5
        out.append(f"{i}\n{fmt(a)} --> {fmt(b)}\n{txt}\n")
    return '\n'.join(out)


def validate(path: str, dur: float) -> dict:
    rows = parse_srt(open(path, encoding='utf-8').read())
    txt = open(path, encoding='utf-8').read()
    mono = all(rows[i][1] <= rows[i + 1][0] + 0.001 for i in range(len(rows) - 1))
    return {'entries': len(rows), 'first_start': rows[0][0], 'last_end': rows[-1][1],
            'duration': dur, 'monotonic': mono, 'has_dollar': '$' in txt,
            'has_backslash': '\\' in txt, 'end_within_duration': rows[-1][1] <= dur + 2}


def transcribe_chunk(audio_chunk, title, raw, model, attempt_limit=3):
    for attempt in range(1, attempt_limit + 1):
        # Accept any non-empty parseable result; short closing chunks
        # can legitimately be only a few hundred bytes.
        if os.path.exists(raw) and len(parse_srt(open(raw, encoding='utf-8').read())) > 0:
            return True
        r = subprocess.run([sys.executable, GEMINI_PY, 'transcribe', audio_chunk, model,
                            '--out', raw, '--title', title],
                           capture_output=True, text=True, timeout=900)
        if r.returncode == 0 and os.path.exists(raw):
            try:
                if len(parse_srt(open(raw, encoding='utf-8').read())) > 0:
                    return True
            except Exception:
                pass
        log(f'  chunk 转写失败第{attempt}次:', (r.stderr or '')[-200:])
        time.sleep(20)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--videos', required=True)
    ap.add_argument('--audio-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--model', default='gemini-3.8-flash')
    ap.add_argument('--chunk', type=int, default=300)
    args = ap.parse_args()

    os.makedirs(args.audio_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)
    chunkdir = os.path.join(args.out_dir, '.chunks')
    os.makedirs(chunkdir, exist_ok=True)
    progress_path = os.path.join(args.out_dir, 'progress.json')
    progress = json.load(open(progress_path)) if os.path.exists(progress_path) else {}

    videos = sorted(f for f in os.listdir(args.videos) if f.lower().endswith('.mp4'))
    for fname in videos:
        stem = fname[:-4]
        if progress.get(stem, {}).get('status') == 'done':
            log('跳过已完成:', stem)
            continue
        log('开始:', stem)
        video = os.path.join(args.videos, fname)
        audio = os.path.join(args.audio_dir, stem + '.mp3')
        if not os.path.exists(audio):
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', video,
                            '-vn', '-ac', '1', '-ar', '16000', '-b:a', '64k', audio], check=True)
            log('音频已抽取:', stem, os.path.getsize(audio), 'bytes')
        dur = duration(audio)
        n = int(dur // args.chunk) + (1 if dur % args.chunk > 1 else 0)
        chunk_files, offsets, failed = [], [], False
        for i in range(n):
            off = i * args.chunk
            chunk_audio = os.path.join(chunkdir, f"{stem}_part{i}.mp3")
            raw_chunk = os.path.join(chunkdir, f"{stem}_part{i}.srt")
            plain_chunk = os.path.join(chunkdir, f"{stem}_part{i}_plain.srt")
            if not os.path.exists(chunk_audio):
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', str(off), '-i', audio,
                                '-t', str(args.chunk), '-ac', '1', '-ar', '16000', '-b:a', '64k',
                                chunk_audio], check=True)
            if not os.path.exists(plain_chunk):
                if not transcribe_chunk(chunk_audio, stem, raw_chunk, args.model):
                    failed = True
                    break
                open(plain_chunk, 'w', encoding='utf-8').write(
                    to_plain(open(raw_chunk, encoding='utf-8').read()))
            chunk_files.append(plain_chunk)
            offsets.append(off)
            log(f'  {stem} 段{i + 1}/{n} 完成')
        if failed:
            progress[stem] = {'status': 'chunk_failed'}
            json.dump(progress, open(progress_path, 'w'), ensure_ascii=False, indent=1)
            continue
        plain = os.path.join(args.out_dir, stem + '.srt')
        open(plain, 'w', encoding='utf-8').write(merge_chunks(chunk_files, offsets))
        try:
            v = validate(plain, dur)
        except Exception as e:  # noqa: BLE001
            progress[stem] = {'status': 'validate_failed', 'error': str(e)}
            json.dump(progress, open(progress_path, 'w'), ensure_ascii=False, indent=1)
            log('校验失败:', stem, e)
            continue
        progress[stem] = {'status': 'done', **v}
        json.dump(progress, open(progress_path, 'w'), ensure_ascii=False, indent=1)
        log('完成:', stem, v)
    done = sum(1 for v in progress.values() if v.get('status') == 'done')
    log(f'全部完成：成功 {done}/{len(videos)}')


if __name__ == '__main__':
    main()
