#!/usr/bin/env python3
"""网盘通 CLI 轻入口。

功能实现已拆分到 scripts/pancli/engine.py，本文件只负责注册路径并转发：
  python3 pan.py <命令> ...   # 等价于完整入口
路径关联：
  pan.py            -> pancli/engine.py (实现)
  credentials.py    -> 系统凭据库封装
  pan_mcp.py        -> MCP 服务
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pancli.engine import build_parser, main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
