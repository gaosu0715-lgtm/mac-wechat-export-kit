# 完整本机引导流程

本版从“正常安装、本人已登录过、本机已有数据”的微信开始，不要求先提供密钥。实际登录、所需手机确认以及准确选择本人账号由人完成。开发工具、SQLCipher 和系统访问许可是共同前置依赖；Zstandard 只用于完整导出，bootstrap-only 不要求。预检发现当前模式所需依赖缺少就停止，不自动安装或批准权限。

## 依赖准备与账号选择

先确认所用 Python 能加载当前 Xcode 的 LLDB Python API；若需完整导出，还须能加载 Zstandard。`plan` 从固定 `/usr/bin/lldb -P` 与选定 developer tools 获取模块，不猜测 Homebrew 或其他 Python 的 ABI；它只导入检查，不启动 target。解释器不兼容就换到经审阅的兼容环境，不把任意 `PYTHONPATH` 注入被调试应用。当前系统 Python 未改动；项目专用 `.venv-release` 已获授权安装 Zstandard 0.25.0，119 项合成/模拟测试全通过，但没有用该虚拟环境做真实 LLDB 预检。当所选解释器缺少 Zstandard 时，`plan --bootstrap-only` 不将它列为当前模式阻碍，但始终保留 `full_export_missing_dependencies`；完整 guide 会在同意和签名之前因缺失而停止。若用户另行决定准备导出依赖，可在选定兼容的 Python 环境中安装 `requirements-optional.txt`，再重新运行合成测试；这不是脚本会自动执行的步骤。

SQLCipher 使用使用者自行审阅的 Community 4 动态库，不附带商业构建或来源不明的预编译包。配置前核对分发来源、构建依赖和实际库文件 SHA-256；摘要一致只核对字节，不能证明库可信。开发工具与库的入口见 [依赖清单](DEPENDENCIES.md)。

账号目录由人明确选择为自己标准本机位置中的一个 `db_storage`。可在本机文件管理器确认当前用户 `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/` 下自己对应的目录；本工具不会列出多个账号让代理推测，也不会自动遍历目录。权限不足、无法确认哪个账号属于自己、原版尚未登录过或本地两库不存在时，到此停止。

| 阶段 | 工具行为 | 需要人的操作 / 失败边界 |
| --- | --- | --- |
| 配置 | 只读 `0600` setup 文件；明确原版、本人单个账号目录、库摘要、目标昵称/备注和新私有会话目录 | 自行在本机填写，不上传；两个内部 ID 可留空，后续只解析所选会话 |
| `plan` | 核对 macOS、原生 arm64、固定版本/build、SIP enabled、当前用户路径、源签名/文件、15 项原 entitlement、既有 GUI/权限观察能力、SQLCipher 摘要及 LLDB/Python ABI | 不复制、不签名、不启动微信，不读数据库页；不支持或权限不符退出；依模式报告就绪情况，完整导出缺 Zstandard 始终可见 |
| 本机同意 | `guide` 拒绝非交互终端，没有 `--yes` 或后台模式；显示精确账号与会话范围及共享容器风险 | 输入“同意本机取钥”；用户同意是声明，不能自动证明所有权，也不能授予 macOS 权限 |
| 原版退出 | 建立 `0700` 新会话和 `0600` 日志；请人从原版菜单正常退出，并核实无其残留进程 | 保存草稿；未退出则不准备副本 |
| 准备副本 | `ditto` 复制到本次 `WeChat-trial.disabled`；验证复制前后字节；只签主应用一次 | 副本与原账号共享应用组/容器，可能同步写入；不覆盖原版或旧会话 |
| 适配签名 | 从可信原版 15 项中移除应用/团队身份两项，加入 get-task-allow、disable-library-validation，保持 15 项；application-groups、sandbox、allow-jit 等其余项原样保留 | 不增加 unsigned-executable-memory，不深度重签厂商组件；完整验证失败停止 |
| 准备取钥 | 只读取明确两库各第一页 4096 字节用于盐与 HMAC 对照；重新核对原版与副本；改名为 `.app` | 不读取其他分库或会话，不附加已有进程，不自动尝试第二次 |
| 运行取钥 | 本次新建 LLDB target、一个系统 CommonCrypto 函数入口断点，替换环境，抑制被调试进程 stdio | 等“取钥已就绪”后再在副本进入账号并完成手机确认；窗口出现不等于就绪 |
| 参数验证 | 断点须是预期模块 UUID、函数入口及本次断点；只有 16 字节盐匹配后才读取 1–256 字节输入；两轮路径直接使用 32 字节 raw key，密码路径只派生一次 | 不扫描内存、对象或运行时字符串；异常信号、未知断点、所有权变化停止，不自动继续 |
| 密钥验证 | 两库都通过第一页 HMAC，首个页面未变化；用 raw literal 经 SQLCipher 4 只读 schema 查询再次验证；完成后独占写入 `keys.json` | 不保存未验证候选，不保存仅部分命中；密钥不进命令、控制台、普通会话日志或 Git |
| 收尾恢复 | 删除本次断点、脱离；副本仍运行时显示本次位置，请人通过副本菜单正常退出并确认；只核验进程，不发送退出请求。无活动/禁用副本进程后，只注销本次副本注册并改回 `.disabled`；原版完整性匹配才按需启动精确原版可执行文件 | 不能区分窗口则停止；人工确认后仍有残留立即交回 `recover`，不循环重试；已运行原版不退出、不重复启动；仅剩原版辅助进程不能算恢复成功 |
| 身份确认 | 人确认原版正常；只读精确匹配昵称/备注，读取目标表涉及的 Name2Id；本人须与选定账号目录匹配；再显示绑定供人确认 | 多个同名、群聊、第三人或本人身份无从核实即停止；不浏览其他聊天内容 |
| 导出 | 原有只读单会话导出器输出 JSON/TXT/分页 HTML，核对计数、唯一 ID、顺序与摘要 | 不扫描其他分库、不恢复媒体，不承诺全量历史 |

## 限时、取消和状态

采集的 120 秒从 LLDB `Launch` 前开始，包括启动、模块等待和用户登录，不能重置。内存读取最多 128 次、总计 32 KiB，每次最多 256 字节；PBKDF 调用最多 256 次。只对明确的初始 exec 事件继续一次；无停止元数据或断点未解析就等待原预算内事件，不提前读参数或宣称就绪。每个 stop ID 不重复继续。

Ctrl-C、取消文件、超时和异常均终止秘密读取，进入独立清理。副本复制/签名/命令本身也有超时，bundle 枚举有数量、体积与时间上限。人的登录或恢复确认等待不计为继续采集；调试器不能安全脱离时，人工收尾可能超出 120 秒，不能将这个时限描述为“整个流程必在 120 秒内完成”。断电、宿主崩溃或关闭终端不能保证自动恢复。

`session.json` 分别记录 `keys_verified`、`capture_complete`、`cleanup_complete`、`original_user_confirmed` 和 `export_complete`。取钥成功但清理失败不会进入导出。`sign-used.json` 与 `launch-used.json` 在操作前独占写入；失败保留标记，不复用会话。`recover` 只读取本次私有会话的配置和原版证据，绝不重新签名、取钥或读取 `keys.json`。

恢复另记 `copy_cleanup_complete`、`original_integrity_unchanged`，每次开始恢复先清除旧成功及用户确认。主流程、恢复、用户确认分别使用 `workflow_error_code`、`recovery_error_code`、`confirmation_error_code`；固定错误留在 `error_history`，恢复成功不抹去主流程失败。即使采集失败，成功恢复后仍请求原版用户确认，随后返回采集失败，不启动导出。调试器仍持有活动进程时，人工接管的 Ctrl-C、提示错误或无法查询状态都不能让流程提前销毁调试器或进入原版恢复。

## 本地私有产物

会话根目录 `0700`；配置、journal、密钥和导出文件 `0600`。应用副本内部保留执行位与原 bundle 布局，由私有根目录保护，不能笼统声称副本每个文件都是 `0600`。目录应保存在可信本机私有位置，名称必须以 `private-` 开头，默认被 Git 排除。

许可来源见 [来源审查](SOURCES.md)。LLDB 使用方式参考 [SBLaunchInfo](https://lldb.llvm.org/python_api/lldb.SBLaunchInfo.html) 与 [SBProcess](https://lldb.llvm.org/python_api/lldb.SBProcess.html)。启动标志 `2 | 512 | 128 | 16384` 沿用固定 Apple 环境已验证的 Debug、DetachOnError、独立进程组、继承调用方 TCC 配置；不是对其他 LLDB 分支的 ABI 承诺，不会由此授予新 TCC 权限。
