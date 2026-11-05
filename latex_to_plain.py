#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert LaTeX math fragments in a Gemini SRT to plain Unicode text.

Gemini sometimes writes formulas as LaTeX ($\\lambda$, $\\Delta V_i$,
$\\Omega_1$) even when asked not to. Subtitles display better as real
characters: λ, ΔVᵢ, Ω₁. This module does that conversion, plus the
known homophone fixes for Chinese calculus lectures.

Usage:
  python3 latex_to_plain.py in.srt [out.srt]   # out defaults to in-place
                                                # with suffix _plain.srt
"""
from __future__ import annotations

import re
import sys

GREEK = {'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε',
         'zeta': 'ζ', 'eta': 'η', 'theta': 'θ', 'iota': 'ι', 'kappa': 'κ',
         'lambda': 'λ', 'mu': 'μ', 'nu': 'ν', 'xi': 'ξ', 'pi': 'π', 'rho': 'ρ',
         'sigma': 'σ', 'tau': 'τ', 'phi': 'φ', 'chi': 'χ', 'psi': 'ψ', 'omega': 'ω',
         'Alpha': 'Α', 'Beta': 'Β', 'Gamma': 'Γ', 'Delta': 'Δ', 'Epsilon': 'Ε',
         'Zeta': 'Ζ', 'Eta': 'Η', 'Theta': 'Θ', 'Iota': 'Ι', 'Kappa': 'Κ',
         'Lambda': 'Λ', 'Mu': 'Μ', 'Nu': 'Ν', 'Xi': 'Ξ', 'Pi': 'Π', 'Rho': 'Ρ',
         'Sigma': 'Σ', 'Tau': 'Τ', 'Phi': 'Φ', 'Chi': 'Χ', 'Psi': 'Ψ', 'Omega': 'Ω'}
SUB = str.maketrans('0123456789ainox', '₀₁₂₃₄₅₆₇₈₉ₐᵢₙₒₓ')
SUP = str.maketrans('0123456789+-n', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ')
# Longest names first so \zeta matches before \eta can match inside it.
NAMES = sorted(GREEK, key=len, reverse=True)
GREEK_RE = re.compile(r'\\(' + '|'.join(NAMES) + r')(?![a-zA-Z])')


def to_plain(text: str) -> str:
    def conv(m: re.Match) -> str:
        s = m.group(1)
        s = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', s)
        s = GREEK_RE.sub(lambda mm: GREEK[mm.group(1)], s)
        s = s.replace(r'\cdot', '·')
        s = re.sub(r'_\{([^}]*)\}', lambda mm: mm.group(1).translate(SUB), s)
        s = re.sub(r'_([0-9a-zA-Z])', lambda mm: mm.group(1).translate(SUB), s)
        s = re.sub(r'\^\{([^}]*)\}', lambda mm: mm.group(1).translate(SUP), s)
        s = re.sub(r'\^([0-9a-zA-Z])', lambda mm: mm.group(1).translate(SUP), s)
        s = s.replace('{', '').replace('}', '').replace('\\', '')
        return s

    out = re.sub(r'\$([^$]+)\$', conv, text)
    out = out.replace('Δ V', 'ΔV')
    out = re.sub(r'\bOmega([₀₁₂₃₄₅₆₇₈₉])', r'Ω\1', out)
    out = out.replace('Omega', 'Ω')
    # Known ASR homophone errors in calculus lectures.
    out = out.replace('背积函数', '被积函数')
    out = out.replace('击函数', '奇函数')
    out = out.replace('几温区域', '积分区域')
    out = out.replace('对称信制', '对称性').replace('对称信征', '对称性')
    out = out.replace('认取', '任取')
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace('.srt', '_plain.srt')
    with open(src, encoding='utf-8') as f:
        text = f.read()
    with open(dst, 'w', encoding='utf-8') as f:
        f.write(to_plain(text))
    print(f"已转换：{src} -> {dst}")
