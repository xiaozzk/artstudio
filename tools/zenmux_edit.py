#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容转发 —— 真正的工具已移到 `tools/zenmux/zenmux_edit.py`。

为什么保留这个文件：assets/武僧/reskin_weapon1/交付说明.md 里写着 python tools/zenmux_edit.py cost 的核账命令，
删掉这个路径会让那些历史履历 / 数据文件里的复现命令失效。**新代码请直接用新路径。**
"""
import os
import runpy
import sys

_REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zenmux", "zenmux_edit.py")
sys.argv[0] = _REAL
runpy.run_path(_REAL, run_name="__main__")