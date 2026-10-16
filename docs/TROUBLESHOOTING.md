# 故障排查

错误日志只输出固定代码，避免泄露路径、正文和密钥。不要把私有配置、原始库或完整导出附到公开 issue。

| 现象/代码 | 含义与下一步 |
| --- | --- |
| `private_file_requires_owner_and_0600` | 配置或密钥文件的所有者/权限不符。自行核对所选文件；工具不会改权限 |
| `symlink_rejected` / `sidecar_symlink_rejected` | 选择实际规范路径，检查父目录及 WAL/SHM 链接，不删掉检查 |
| `key_scope_requires_exact_two_databases` | 私有清单只允许两个固定相对库名，不能直接使用全库密钥清单 |
| `raw_key_requires_64_hex` | 要求 32 字节 raw key 的 64 位十六进制表示，不是口令；不要重复 PBKDF2 |
| `library_digest_mismatch` | 库字节与手工审阅的摘要不符，停止并查明来源；不要自动信任新摘要 |
| `sqlcipher_api_missing` / `sqlcipher_4_required` | 普通 SQLite 或不支持的构建，需自行提供可信 SQLCipher 4；本轮不安装 |
| `cipher_query_failed` | 可能是密钥、页参数、损坏、锁或 schema 不符，不能单凭此码确定原因；不启用原生 SQL 日志 |
| `contact_missing_ambiguous_or_binding_changed` | 显示名不唯一、未匹配或内部 ID 不一致；人工重新确认，不能自动选第一项 |
| `unexpected_conversation_participant` / `non_system_sender_unresolved` | 一对一身份边界不成立，停止，不把未知人当本人 |
| `zstandard_unavailable` 内容状态 | 缺可选包，该正文未恢复；导出计数不等于全部文字成功解码 |
| `structured_content_unparsed` / `forward_summary_not_expanded` | 保留未展开事实，不把原始 XML 或附件凭据补进输出 |
| `output_digest_mismatch` | 文件发生变化；在本机检查，不更新摘要来掩盖问题 |
| `operation_failed` | 未公开的系统/解析错误、路径缺失、输出已存在或环境缺失等；按配置和权限逐项本地核对 |
| `interactive_local_terminal_required` | guide/recover 只接受人在本机终端操作，不提供静默或 `--yes` 绕过 |
| `unsupported_macos_version` / `unsupported_wechat_version` | 当前取钥 profile 不符；只退出，不删除版本或签名检查 |
| `zstandard_required_for_guide` | 完整导出引导缺前置依赖，在签名和取钥前停止；bootstrap-only 不要求此依赖；本轮不安装软件 |
| `system_permission_observer_stopped` | 当前系统权限窗口已出现或无法可靠判定，停止，不自动点击允许 |
| `capture_deadline` / `capture_resource_limit` | 单次采集预算已耗尽，恢复并保留失败记录；不能自动续时或重试 |
| `manual_debugger_cleanup_required` | 秘密读取已停止，保持终端，由用户正常退出副本后完成脱离；不要直接关闭终端 |
| `manual_copy_quit_required` | 本次活动或禁用副本仍有进程。当前版会显示精确本机位置并请人通过副本菜单正常退出；确认后仍有残留则停止，稍后只运行本次 recover，不重跑取钥 |
| `original_integrity_changed` | 原版不再匹配本次预检，禁止自动启动/修复原版，交回用户检查 |
| `recovery_path_overlap` | 原版路径与私有会话重叠，拒绝恢复；不要修改 journal 来绕过检查 |
| `original_main_not_observed` / `original_process_owner_changed` | 只见原版辅助进程或用户身份不符；不能当作原版恢复成功，也不自动重复启动；交回用户检查 |
| `contact_missing_ambiguous_or_group` / `self_identity_requires_explicit_confirmation` | 取钥后仅解析所选会话仍无法唯一核实身份；不自动猜测，原版已恢复，可留在此处 |

WAL 由 SQLite/SQLCipher 按其事务机制读取。复制单独 `.db` 可能漏掉已提交的 WAL 消息；本工具不主动 checkpoint，不把不完整副本当作完整历史。`READONLY` 不等于不会参与 SHM 协调，详见 [SQLite WAL 文档](https://www.sqlite.org/wal.html)。

## 本轮自动退出失败：证据与修正

修复前一次真实测试的记录表明，两库认证完成后 `MacHost.restore` 抛出 `manual_copy_quit_required`，清理未完成并阻止导出。稍后的独立只读检查发现副本已无进程、原版在运行，随后只做恢复并取得用户正常使用确认。这个先后顺序不能证明哪个退出事件送达了哪个应用，也不能把客户端退出原因倒推为已知。

能从源码确定的是：旧 `normal_quit` 使用 `tell application "<副本路径>" to quit`，没有将请求绑定到本次进程；原版与副本仍使用相同 bundle identifier，因此不能把路径字符串当作已经验证的进程目标。它设置了 4 秒 AppleScript、5 秒外层超时，之后观察 10 秒，但忽略返回码、stdout/stderr；超时与拒绝都折叠成一个布尔失败。此前未保存这些诊断，故无法追溯确认本次具体是请求被拒绝、超时、目标解析还是客户端处理延迟。没有证据断言 TCC 拒绝、原版被误退出或应用损坏。

当前选择移除该自动退出路径，不新增 PID 退出、信号或系统权限操作。由人核对本次副本、从其菜单正常退出，工具只验证进程已消失；无法区分窗口就停止。一次人工确认后仍有残留则明确交回人工恢复，不自动反复尝试。已运行原版不会收到退出请求或重复启动；只见原版辅助进程不能记为恢复成功。

恢复开始会清除旧成功/用户确认，分别记录副本清理、原版完整性、整体恢复及用户确认。主流程错误与恢复错误分开保留，后续成功恢复不会把取钥失败改为成功。调试器脱离失败时，提示被中断或状态未知不能提前销毁 debugger 或进入原版恢复。以上修复只做了模拟及合成回归，没有再次运行真实微信，不能称已真实验证修复后的完整流程。

## 历史启动诊断，仅供理解

此前临时副本出现过主程序与嵌套厂商库 TeamID / library validation 不一致。另一次受控对比中，丢失 `application-groups` 时 `bootstrap_check_in` 返回 1100，恢复该项后返回 0。保留了沙盒、Hardened Runtime 和嵌套厂商签名；该调用返回 0 不代表登录或取钥成功。

历史捕获使用 `capture15_once.py` 获得数据库级 raw keys，捕获子任务与应用清理结果分别记录；二者不是同一个成功条件。具体耗时、账号、私有统计和操作记录不随此项目发布。

这些诊断不是通用修复指令。0.2.0 的 guide 只把经过审查的固定 profile 纳入明确同意、有限取钥与恢复流程；本轮只有一次修复前的核心取钥真实验证及后续恢复，修复后的人工退出衔接尚未真实运行。新的实际操作仍需另行确认版本/目标/时间和恢复范围，见 [真实验证授权](LIVE_VALIDATION.md)。不能把历史一次成功泛化到所有系统。不建议在 issue 中提供调试转储、内存片段或密钥。
