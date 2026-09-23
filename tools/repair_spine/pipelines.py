#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容转发 —— 真正的工具已移到 `tools/spine/repair_spine/pipelines.py`。

为什么保留这个文件：**105 份已交付的 交付说明.md** 里写着
`python tools/repair_spine/pipelines.py <cmd> ...` 的复现命令，
删掉这个路径会让那些历史履历的复现命令失效。**新代码请直接用新路径。**
"""
import os
import runpy
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))          # tools/repair_spine
_REAL = os.path.join(os.path.dirname(_HERE), "spine", "repair_spine", "pipelines.py")
sys.argv[0] = _REAL
runpy.run_path(_REAL, run_name="__main__")