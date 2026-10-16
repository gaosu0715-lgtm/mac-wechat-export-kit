# 依赖与许可证清单

本地整理日期：2026-10-15。本次经明确授权仅在项目 `.venv-release` 从 PyPI 安装 Zstandard 0.25.0；不修改系统 Python，不随项目分发虚拟环境、动态库、Python 解释器或第三方包。许可适用范围分开记录，不给外部二进制套用项目 MIT。

| 项目 | 用途 / 要求 | 许可 / 分发状态 |
| --- | --- | --- |
| 项目新增源码与文档 | Python 3.9+ 工具、中文说明、人工样本与测试 | MIT；见根 `LICENSE`，所有者发布前确认 |
| acmerfight Gist 的 `sqlcipher_probe.py`、`capture_keys.py` 部分实现 | SQLCipher ctypes 与 raw-key 页认证的来源，固定修订见 `SOURCES.md` | MIT；原文完整保留，见 `NOTICE` 与 `licenses/upstream-MIT.md` |
| Python 与标准库 | CLI、XML、HTML、JSON、hashlib、ctypes、unittest；本轮为 3.9.6 | Python/PSF 相关许可由解释器分发者提供；未打包解释器 |
| SQLCipher 4 Community | 真实加密库访问；本轮已有 4.18.0 CommonCrypto 库用于合成测试和另行授权的一次真实两库只读 schema 验证 | 上游 BSD 风格许可；未分发，使用者需核对自己的版本和构建依赖 |
| SQLite | 合成样本、SQLCipher 底层事务/WAL | SQLite 核心为 public domain；本项目不分发其二进制 |
| `zstandard>=0.22,<1` | 完整 guide 导出路径的前置依赖；bootstrap-only 不需要；直接 export 可缺失但会保留未解码占位；系统 Python 未修改，项目专用虚拟环境已装 0.25.0 并完成合成验证 | python-zstandard 为 BSD 3-Clause，底层 zstd 另有 BSD/GPL 双许可及随包声明；未随源码分发；本次安装包 metadata 与随包 LICENSE 确认 BSD-3-Clause |
| Apple Xcode / LLDB / debugserver | 与运行 Python ABI 兼容的 LLDB Python API、固定 Apple 启动配置 | LLVM LLDB 为 Apache-2.0 with LLVM exceptions；Apple 工具分发受其 Xcode/系统条款约束；未复制或分发 |
| macOS codesign / ditto / LaunchServices / 系统框架 | 预检、副本准备、进程退出核验和恢复、GUI 权限窗口观察；当前版不调用 osascript 退出应用 | 系统提供，不在仓库内分发；工具不批准权限或修改安全设置 |
| setuptools>=61 | 仅构建/可选安装使用；直接 `PYTHONPATH=src` 不需要 | MIT；本轮未执行构建安装或下载 |
| GitHub Actions checkout/setup-python | 未来 CI 所用工作流动作 | 外部 MIT 项目；仅引用动作，未运行云端 CI |

SQLCipher Commercial / Enterprise 的许可不等同于 Community；不得因存在 `sqlite3_key` 接口就假定某个库可再分发。CommonCrypto 是系统提供的运行能力，不在项目中复制 Apple 组件。

官方核对入口：

- [Python 许可](https://docs.python.org/3/license.html)
- [SQLCipher Community 源码许可证](https://github.com/sqlcipher/sqlcipher/blob/master/LICENSE.md)
- [SQLCipher raw key 与 API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)
- [SQLite 版权](https://www.sqlite.org/copyright.html)
- [python-zstandard 许可](https://github.com/indygreg/python-zstandard/blob/main/LICENSE)
- [zstd 许可](https://github.com/facebook/zstd/blob/dev/LICENSE)

直接 `PYTHONPATH=src` 可执行核心合成测试，不依赖构建工具。可选依赖范围不是锁定环境，也不是对未来版本的兼容承诺；如计划提供二进制包或安装包，需先补构建清单、精确版本与逐项许可审查。
