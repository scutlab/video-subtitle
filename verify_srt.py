#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a directory of SRT files (or one file) before packaging/delivery.

Checks per file: entries parse by number+timestamp (not by blank lines,
which Gemini sometimes omits), numbering is sequential, timestamps are
monotonic, the last entry ends within the audio/video duration when a
matching media file is given, and there is no leftover LaTeX ($, backslash)
or known homophone error (背积函数).

Usage:
  python3 verify_srt.py <srt-dir-or-file> [--media-dir <dir>]

Exit code 0 only when every file passes.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

_ENTRY_RE = re.compile(
    r'(?m)^(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\s*\n'
    r'(.*?)(?=^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3} --> |\Z)', re.S)


def ts(s):
    h, m, sec = s.replace(',', '.').split(':')
    return int(h) * 3600 + int(m) * 60 + float(sec)


def media_duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip())


def check(path, media_dir=None):
    text = open(path, encoding='utf-8').read()
    rows = [(ts(a), ts(b), txt.strip())
            for _, a, b, txt in _ENTRY_RE.findall(text)]
    problems = []
    if not rows:
        return ['无法解析出任何条目']
    nums = [int(x) for x in re.findall(r'^(\d+)$', text, re.M)]
    if nums != list(range(1, len(nums) + 1)):
        problems.append(f'序号不连续（共 {len(nums)} 个序号）')
    if len(rows) != len(nums):
        problems.append(f'按空行切分会丢条目：正则解析 {len(rows)} 条，序号 {len(nums)} 个')
    if any(rows[i][1] > rows[i + 1][0] + 0.001 for i in range(len(rows) - 1)):
        problems.append('时间戳不单调/有重叠')
    if '$' in text or '\\' in text:
        problems.append('残留 LaTeX（$ 或反斜杠）')
    if '背积函数' in text:
        problems.append('含“背积函数”，应为“被积函数”')
    if media_dir:
        stem = os.path.splitext(os.path.basename(path))[0]
        for ext in ('.mp4', '.mp3'):
            media = os.path.join(media_dir, stem + ext)
            if os.path.exists(media):
                dur = media_duration(media)
                if rows[-1][1] > dur + 2:
                    problems.append(f'末条 {rows[-1][1]:.1f}s 超出媒体时长 {dur:.1f}s')
                break
    return problems


def main():
    target = sys.argv[1]
    media_dir = None
    if '--media-dir' in sys.argv:
        media_dir = sys.argv[sys.argv.index('--media-dir') + 1]
    files = [target] if os.path.isfile(target) else sorted(
        os.path.join(target, f) for f in os.listdir(target) if f.endswith('.srt'))
    failed = 0
    for path in files:
        problems = check(path, media_dir)
        name = os.path.basename(path)
        if problems:
            failed += 1
            print(f'FAIL {name}: ' + '; '.join(problems))
        else:
            rows = _ENTRY_RE.findall(open(path, encoding='utf-8').read())
            print(f'PASS {name}: {len(rows)} 条')
    print(f'共 {len(files)} 个文件，{len(files) - failed} 通过，{failed} 失败')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
