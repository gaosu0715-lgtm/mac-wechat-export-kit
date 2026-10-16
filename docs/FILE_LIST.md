# 本地发布候选文件清单

共 50 个源码、配置模板或说明文件。可用 `scripts/release_check.py` 重新枚举当前候选；此清单不包含 `.git/` 与被忽略的 `private-demo/` 合成预览、`.venv-release/` 测试环境。

| 文件 | 用途 |
| --- | --- |
| `.gitignore` | 默认拒绝未知根文件及私密/生成产物 |
| `.gitattributes` | 文本换行 |
| `.github/workflows/ci.yml` | 未来核心合成测试工作流，尚未云端运行 |
| `LICENSE` | 本项目 MIT |
| `NOTICE` | 固定上游、版权与改动说明 |
| `README.md` | 中文使用入口、范围及来源 |
| `pyproject.toml` | 最小包结构、入口、可选依赖 |
| `requirements-optional.txt` | 可选 Zstandard 范围 |
| `src/mac_wechat_export_kit/__init__.py` | 包版本 |
| `src/mac_wechat_export_kit/__main__.py` | 模块入口 |
| `src/mac_wechat_export_kit/cli.py` | 私有配置、export/verify 命令 |
| `src/mac_wechat_export_kit/safety.py` | 路径、范围、私有文件和固定错误 |
| `src/mac_wechat_export_kit/cipher.py` | 已有 raw key 的只读 SQLCipher 适配器 |
| `src/mac_wechat_export_kit/content.py` | 有界解码、可读字段白名单与占位 |
| `src/mac_wechat_export_kit/exporter.py` | 单会话快照、分页、产物与一致性校验 |
| `src/mac_wechat_export_kit/bootstrap.py` | 本机交互同意、完整引导、身份确认与仅恢复/仅取钥模式 |
| `src/mac_wechat_export_kit/capture_policy.py` | 15 项 entitlement 变更、限定参数形状与 raw-key 页认证 |
| `src/mac_wechat_export_kit/mac_host.py` | 固定版本预检、私有副本、一次主应用签名与正常恢复 |
| `src/mac_wechat_export_kit/runtime_capture.py` | 单次 LLDB、入口身份、超时/取消/资源限制与安全脱离 |
| `src/mac_wechat_export_kit/permission_windows.py` | 当前 GUI 系统权限窗口最小特征观察器 |
| `src/mac_wechat_export_kit/session.py` | 私有 journal、阶段状态与单次操作标记 |
| `tests/fixtures.py` | 合成人工库与测试适配器 |
| `tests/test_cipher.py` | 可选加密集成与 WAL 测试 |
| `tests/test_content.py` | 内容、XML、压缩限制与缺依赖测试 |
| `tests/test_exporter.py` | 范围、身份、导出、日志与校验测试 |
| `tests/test_safety.py` | 路径、文件权限、清单与库摘要测试 |
| `tests/test_release_check.py` | 暂存敏感文件和 key 的扫描拒绝回归 |
| `tests/runtime_fakes.py` | 完全合成的 LLDB API，不加载 native 调试器 |
| `tests/test_bootstrap.py` | 同意、取消、恢复、联系人确认与完整引导模拟 |
| `tests/test_capture_policy.py` | 合成 HMAC 页、raw key 语义与 entitlement 策略 |
| `tests/test_runtime_capture.py` | 启动等待、停止身份、读取边界、取消与人工脱离 |
| `tests/test_mac_host.py` | 模拟签名、嵌套摘要、正常退出与原版恢复 |
| `tests/test_permission_windows.py` | 合成 GUI 快照的三态判定与脱敏 |
| `examples/config.example.json` | 全占位配置，不含真实身份/密钥/路径 |
| `examples/setup.example.json` | 完整流程配置；内部身份可留空供取钥后唯一解析 |
| `examples/synthetic_demo.py` | 无真实账号依赖的演示 |
| `scripts/release_check.py` | 只读发布候选扫描 |
| `docs/ARCHITECTURE.md` | 数据流、接口与工程限制 |
| `docs/BOOTSTRAP.md` | 完整引导、人的操作、取消、恢复和状态边界 |
| `docs/LIVE_VALIDATION.md` | 真实验证未执行项、准确授权范围及风险 |
| `docs/DATA_SAFETY.md` | 数据安全与威胁边界 |
| `docs/DEPENDENCIES.md` | 依赖、许可及官方入口 |
| `docs/FILE_LIST.md` | 本清单 |
| `docs/RELEASE_AUDIT.md` | 本次合成复测、隐私许可审计与发布目标阻碍 |
| `docs/RELEASE_CHECKLIST.md` | 所有者确认及发布前核对 |
| `docs/SOURCES.md` | 固定许可核查、逐文件来源、源码摘要 |
| `docs/SUPPORT.md` | 版本/平台/功能支持矩阵 |
| `docs/TROUBLESHOOTING.md` | 固定错误及泛化历史诊断 |
| `docs/VALIDATION.md` | 本轮测试结果与未验证项 |
| `docs/licenses/upstream-MIT.md` | 固定上游 MIT 完整原文 |
