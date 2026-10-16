# 来源、固定修订与逐文件审查

## 许可证核查结论

2026-10-15 只读获取公开 GitHub Gist API 的固定修订：

`https://api.github.com/gists/0a01249ef72970d07a2603dbb629e80f/c98dbb10cf23c30e83d5d744905101b0880887a0`

响应首个 history version 为 `c98dbb10cf23c30e83d5d744905101b0880887a0`，文件集合包含 `LICENSE`，正文是 MIT，版权为 `Copyright (c) 2026 Contributors`。旧工作中审查的 LICENSE 与该内容逐字节相同。公开可见并不是核查依据；这里依据的是该固定修订的明确授权文本。

固定修订页面：[上游](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f/c98dbb10cf23c30e83d5d744905101b0880887a0)。许可证文件的固定内容地址：[LICENSE](https://gist.githubusercontent.com/acmerfight/0a01249ef72970d07a2603dbb629e80f/raw/7d3ab8fb06f41434d2a341c36e68dcdf0a5adfbd/LICENSE)。

本地环境通过公开 API 读取核对，没有登录、创建远程仓库或联系作者。网页抓取器无法直接打开固定修订，故不将抓取器失败写成“无许可”。API 响应只在临时审查位置保留，不随项目发布整个 Gist 或无关文件。

## 旧工作读取范围及决定

项目整理阶段只读技术总结和下表明确列出的源码/许可证。没有读取旧聊天原文、导出 HTML/TXT/JSON、数据库、密钥或凭据。没有递归复制旧目录，也没有执行旧脚本。后续单独授权的 bootstrap-only 测试只额外读取旧路径批准记录中的精确账号根字段，以限定同一本人账号；没有枚举其他账号或带入该记录，实际新采集范围与结果见 `VALIDATION.md`。

| 旧文件（相对旧工作源码目录） | 审查结论 | 本项目处理 |
| --- | --- | --- |
| `LICENSE` | 与固定上游 MIT 原文相同 | 逐字保留于 `docs/licenses/upstream-MIT.md` |
| `sqlcipher_probe.py` | 相对固定上游仅调整私有库加载、关闭日志及密钥文件检查；旧私有路径不能发布 | 只复用 ctypes/DB 封装；新 `cipher.py` 改用显式库摘要、严格两库清单与稳定错误；删除旧 CLI/self-test 依赖 |
| `export_selected_chat.py` | 本次私有导出扩展；联系人、路径和轮次写死，依赖旧调试策略 | `content.py` / `exporter.py` 审慎改编可读字段、离线渲染与校验行为；配置、会话绑定与输出流程重新实现；不复制任何个人值 |
| `db_scope.py` | 独立路径检查有复用价值，但旧函数会枚举消息分库 | 新 `safety.py` 独立实现固定两库和链接拒绝；不带旧枚举函数 |
| `capture15_policy.py` | 混合签名、取钥、硬编码联系人和路径策略 | 0.2.0 完整审查纯验证部分；改编 15 项变更与盐匹配/HMAC 策略到 `capture_policy.py`，删除个人值与旧轮次接口 |
| `capture15_once.py` | 成功私有调试入口，含应用状态与账号路径依赖 | 0.2.0 审查全文件，改编单次启动、入口断点、模块等待、有限读取和独立清理到 `runtime_capture.py` / `bootstrap.py`；不执行旧脚本，不复制个人配置 |
| `wechat_db.py` | 私有版与上游有差异；含账号发现与多分库读取 | 仅审查开头及 Reader 接口，不整体复制，不保留扫描逻辑 |
| `test_export_selected_chat.py` | 仅合成数据，但导入私有联系人常量和旧工程 | 新测试单独编写，合成名称与密钥重新定义；验证同类重要边界 |
| `validate_engine.py` | 人工加密库测试与 raw key 语义验证 | 仅参考覆盖目标，新写加密库与 WAL 测试；不执行旧脚本 |
| `app_group_once.py` | application-groups 修复及只签主应用的成功路径 | 审查 entitlement 变更、一次签名与副本完整性；在 `mac_host.py` / `capture_policy.py` 重新组织，不迁移诊断探测入口 |
| `signing_metadata.py` | entitlement XML/树解析及排除主文件/CodeResources 的嵌套摘要 | 改编解析与摘要为显式 host 操作，增加特殊文件/外部链接/资源拒绝；不保留过期签名路线 |
| `cwd_comparison_once.py` | LLDB launch 配置、精确应用路径、正常退出与安全脱离 | 审查相关函数，移除个人环境与历史对照轮次；重组为 native host 与可注入 runtime |
| `permission_windows.py` | 独立、无个人值的当前系统 GUI/agent 最小特征观察器 | 逐字复用源码并添加来源/版权头；不读微信 UI、不自动申请权限；原字节摘要见下表 |
| `lldb_control.py` | live-state、stop ID、所有权与错误脱敏辅助逻辑 | 审查其约束，未整体复制；运行时状态与所有权约束在本版单独实现 |
| `library_exception_once.py` | 较早的库验证例外试验，先于恢复应用组的最终路线 | 只比较签名与完整性检查，不迁移其旧 entitlement 集合或诊断入口 |
| `test_app_group_mock.py` / `test_capture_startup.py` | 旧合成签名与启动等待回归源码 | 审查覆盖目标和事件边界，本版测试重新组织；未运行旧测试或读取其真实结果 |
| 固定上游 `capture_keys.py` | MIT 的 raw-key HMAC 和参数形状；公共 CLI 含本项目不采用的递归扫描、强制结束和原始错误输出 | 只复用/改编纯认证与候选算法，保留原版权；不照搬其 CLI |
| 固定上游 `bootstrap_keys.py` | MIT，但公共包装的深度重签和自动目录选择不符合本版边界 | 仅比较来源，未复制实现；使用成功私有流程的精确主应用签名与恢复路线 |
| 技术总结 | 仅用于确认历史环境、诊断事实与能力边界 | 手工提炼泛化说明；不复制原报告、姓名、路径、私密统计或完整时间线 |

以上来源审查不宣称旧私有文件都是上游文件，也不宣称新项目是 clean-room 实现。私有工作所增加的内容与本轮新增内容按所有者的开源整理请求准备为 MIT；实际对外发布前，仍由所有者确认权利与范围。没有从 WeFlow 复制实现。上游提及的其他取钥项目未被引入，也不主张其许可覆盖本项目。

## 摘要追溯（SHA-256）

这些仅为源码和许可证摘要，不是数据库、密钥或聊天摘要：

| 对象 | SHA-256 |
| --- | --- |
| 固定上游 LICENSE / 旧 LICENSE | `72380798af61d6131287b0dd3c8dc5345535df641002fece3a02d7ef109c5f8e` |
| 固定上游 `sqlcipher_probe.py` | `5133370736ef2f5d0119c4cca942ecb56ec4db632b95f1c591d35d863e22f68b` |
| 固定上游 `capture_keys.py` | `0b0b9f9296bf02219c07537827ed9ce97671611ffeab36572bedb267a7704d65` |
| 固定上游 `bootstrap_keys.py`（审查，未复制） | `ce8596107df3ca3715c8b63b522bbcc84148207217fade3b642975323c65b31c` |
| 旧 `sqlcipher_probe.py` | `b54f2b85c72920135ca250c801a8240468613da857cf74abca39fd77cbd574de` |
| 旧 `wechat_db.py` | `5f876e3eb8503d7e03f39964e48a8751443c18ae7b6e64847b0679d8e448b9d3` |
| 旧 `export_selected_chat.py` | `795e4f50c2d380b5bf7512ac9fd6df6677f410b3e44e90d956fce5b1d203b94a` |
| 旧 `db_scope.py` | `bd712b2ae19bed421b6e27e99be1ef599c5c4eeedeff79d5bbfa862f130f5a75` |
| 旧 `capture15_policy.py` | `d6a8a59900c42c0b9184445cbcc2ee9820a3cbd409fc055b9f2fbbc53c34a97a` |
| 旧 `capture15_once.py` | `1a6525943c68901cb52f3bc16ed927d316ab24753022713b1ce2a3d578e02d6e` |
| 旧 `test_export_selected_chat.py` | `5a2dfa9c2c34749baed943bb73d5067f099685f5a59b7902ba8deab5ad4cab8c` |
| 旧 `cwd_comparison_once.py` | `88acaf8844ad84d9549e5de360500387f1462f8242d0ae4512965ca8af145f54` |
| 旧 `signing_metadata.py` | `86c87c5b21865d181d67becf7665f5fc1d05e328c34e763489f072b286496ba0` |
| 旧 `app_group_once.py` | `b5c19ef278d3ff38be07dc4b7aecd52f13bc3a18e2b4622f587dc11507eb3772` |
| 旧 `permission_windows.py` | `5a3749b782882396167821965e5b878192abb4a4aadeff0f5c6b1b96489e542a` |
| 旧 `lldb_control.py` | `f69e34d23fab4d8b47f3252132c87d9d1f160e9ddc7d9030f2960b3eea3ff3dc` |

0.2.0 的模块级归属：`capture_policy.py` 含上游 MIT 算法与本次私有策略的改编；`runtime_capture.py` / `mac_host.py` 源自上述逐项审查的私有成功流程；`permission_windows.py` 为保留原文的本次私有实现；`bootstrap.py` / `session.py` 为本轮新增组织代码。所有相关声明保留于模块头与 NOTICE，最终发布署名由所有者确认。新增测试是重新编写的合成/模拟测试，不宣称复用了真实运行证据。

一次真实测试暴露退出故障后，本轮新增修复移除了旧 AppleScript 应用退出请求，改为用户菜单退出后观察核验；补充独立恢复、错误历史与接管异常保护。没有引入新的第三方实现或依赖；修复只运行模拟/合成测试，未再次实际操作微信。

尚未发布的源文件以当前目录为准；发布前应重新运行审查脚本并查看 diff。若之后新增来源不明或无明确许可的实现，先隔离，不通过改名/改写后附 MIT 来规避来源问题；必要时由所有者获得原作者明确再分发许可。本轮不联系第三方。
