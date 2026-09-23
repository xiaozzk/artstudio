#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容转发 —— 真正的工具已移到 `tools/sprite/outline-part.py`。

为什么保留这个文件：assets/eva_bone/parts/outline.json 的 note 里写着 python tools/outline-part.py 的复现命令，
删掉这个路径会让那些历史履历 / 数据文件里的复现命令失效。**新代码请直接用新路径。**
"""
import os
import runpy
import sys

_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprite", "outline-part.py")
sys.argv[0] = _REAL
runpy.run_path(_REAL, run_name="__main__")