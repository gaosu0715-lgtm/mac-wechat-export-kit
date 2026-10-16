# Mac WeChat Export Kit

一个用于 Mac 微信的实验性完整引导工具包：从正常安装、已登录过的本人账号开始，经过预检、本机同意、临时副本、限时取钥、验证、退出恢复，最后只读导出指定会话。已有逐库 raw key 时，也可直接使用原来的导出入口。

当前版本为 `0.2.0` 源码实验版。完整引导已经实现并用模拟系统接口与合成数据库测试；另行授权的一次真实 bootstrap-only 测试已完成两库取钥认证及只读 schema 验证。自动正常退出曾失败，随后独立恢复确认副本已退出并禁用、原版完整性不变且正在运行；用户已确认原版正常。**未执行新版真实会话导出，也不能称全流程自动验收通过。**不能承诺无交互、所有版本可用。账号自动发现、后台静默采集、跨账号扫描和媒体恢复仍不提供；这不是微信官方项目。

## 从零引导，不要求预先取得密钥

前置条件是本人已经正常安装并登录过的微信、本地已有聊天数据库、兼容的 Apple Xcode/LLDB 与 Python、可信 SQLCipher 4 库。完整导出还需要该 Python 环境的 Zstandard；仅取钥与恢复的 `--bootstrap-only` 不要求解压依赖。不会自动安装依赖或调整系统安全设置。当前取钥适配仅覆盖 Apple Silicon 原生环境、macOS 27.0.1、微信 4.1.13 build 269602；版本、签名、应用组或权限前提不符就停止。

先在项目根目录准备专用 Python 环境；选择能加载当前 Xcode LLDB 的 Python 3.9+，不修改系统 Python：

```sh
python3 -m venv .venv-release
. .venv-release/bin/activate
python -m pip --isolated --index-url https://pypi.org/simple -r requirements-optional.txt
```

后续本页的 `python3` 命令在这个已激活环境中执行。若只体验核心合成样本，可不安装可选包；完整导出则需要 Zstandard。2026-10-15 已在本项目专用环境用 Python 3.9.6、Zstandard 0.25.0 跑过全部 119 项合成/模拟测试（含 4 项 SQLCipher 测试），0 跳过；这不代表该虚拟环境的真实 LLDB、登录或恢复链路已验收。SQLCipher 动态库仍需自行从可信来源准备并审阅，本项目不附带；来源入口和许可见 [依赖清单](docs/DEPENDENCIES.md)。

复制 [完整流程配置模板](examples/setup.example.json) 到仓库外的私有位置，按说明填写，文件由当前用户拥有且权限为 `0600`。只指定自己的精确账号数据库目录，不让工具寻找账号。`state_dir` 是尚不存在、名以 `private-` 开头的绝对路径。`expected_username` 和 `self_username` 可以保持空字符串：取钥并恢复后，只读解析所选昵称/备注和该会话参与者，再让你确认唯一身份绑定；同名、群聊或无法证明本人身份时停止，不选第一条。

```sh
# 只读预检与计划，不取钥、不签名、不启动微信、不读加密页。
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit plan \
  --config '<private-setup-config>'

# 真正操作入口：只有经你另行确认真实操作范围后，才在本机交互终端执行。
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit guide \
  --config '<private-setup-config>'
```

引导会显示账号与会话范围，要求输入“同意本机取钥”，然后让你正常退出原版。它只复制并重签临时副本主应用，保留沙盒、Hardened Runtime、嵌套厂商签名和 application-groups。等到“取钥已就绪”后，你在副本中自行进入自己的账号、完成所需手机确认。采集只启动一次，最多 120 秒、128 次有限内存读取；只有盐匹配后才读取受限参数。两库都经过页认证与 SQLCipher 只读 schema 验证后，才私密保存 raw keys。

副本共享原账号的数据容器，登录和同步可能写入本机数据并被客户端察觉；不能把后续只读导出说成整个流程零写入。完成采集并脱离调试器后，如副本仍运行，引导会显示本次副本位置，请你通过副本菜单正常退出并输入“副本已退出”；不能区分窗口时停止，不猜测。工具不发送应用退出请求，核验无副本残留后才禁用副本、检查原版并按需通过精确可执行路径恢复。你确认原版正常、确认唯一联系人绑定后，才开始导出。

上述人工退出衔接是本次真实测试暴露自动退出失败后的修复，目前只有模拟回归，尚未再次真实运行；此前真实取钥成功的证据不覆盖这次修改。原因边界见 [退出故障说明](docs/TROUBLESHOOTING.md)。

Ctrl-C 或在私有会话目录创建空的 `cancel.request` 可停止采集；之后仍需完成恢复。自动脱离失败时，工具保持调试器所有权，停止所有秘密读取，明确等待你正常退出副本，避免销毁调试器导致应用被强制结束。不要在这一步关闭终端。正常退出或原版核验失败则保留状态、阻止导出，不强制结束进程、不自动重试。

```sh
# 仅恢复已有会话；不重新取钥、不签名、不读取密钥或聊天、不导出。
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit recover \
  --state '<existing-private-session-directory>'
```

[完整步骤与实现边界](docs/BOOTSTRAP.md) · [真实验证的范围与授权](docs/LIVE_VALIDATION.md)。真实 bootstrap-only 与合成测试的分项结果见 [验证记录](docs/VALIDATION.md)，包括自动退出失败及后续独立恢复。

只验证取钥和恢复、避免重复导出时，另行授权后使用 `guide --bootstrap-only --config '<private-setup-config>'`；该模式在恢复确认后停止，不解析联系人、不读取会话表、不生成导出。

`plan --bootstrap-only --config '<private-setup-config>'` 可单独核对该模式；若当前解释器缺少 Zstandard，它仍明确报告完整导出的依赖缺口，不将仅取钥模式就绪说成完整导出就绪。

## 先用合成样本体验

需要 Python 3.9+。在项目根目录运行，不需要安装软件、登录微信或访问任何真实账号：

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 examples/synthetic_demo.py --output private-demo
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit verify --output private-demo
```

用浏览器打开 `private-demo/HTML/index.html`。样本中的身份、文字和消息均为人工生成。此演示使用临时 SQLite 合成库，不证明真实微信或 SQLCipher 可用。重复演示要换一个不存在的输出目录。

测试默认跳过没有依赖的 SQLCipher 与 Zstandard 项，并显示原因；跳过不算通过。实际测试记录见 [验证记录](docs/VALIDATION.md)。

## 已有密钥时直接导出

只处理你拥有或已获明确授权的数据。密钥本身覆盖数据库，不能按联系人隔离；会话限制由本工具的查询与校验实现。输出仍含私密聊天，必须留在私有位置。

需要自行准备：

- 当前账号的精确 `db_storage` 路径，仅上述两库；工具不会自动寻找账号或分库。
- 两库各自已有的 32 字节 raw key，保存为私有 JSON 文件；不接受密码，不再次 PBKDF2 派生。
- 明确确认的联系人昵称或备注、该联系人的内部 ID，以及本人的内部 ID。显示名必须唯一匹配，匹配结果还必须等于指定 ID；不支持群聊。
- 来自可信来源、已审阅并计算 SHA-256 的 SQLCipher 4 动态库；本项目不分发该二进制。填写摘要是核对字节一致性，不能替代确认来源可信。
- 如消息内容使用 Zstandard 压缩，需要兼容的 `zstandard` Python 包。缺少时保留 `zstandard_unavailable` 占位，并计入结果，不把它当作恢复文字。依赖安装由使用者另行决定。

密钥文件格式如下。尖括号是说明占位符，不是有效密钥，不要把真实文件提交到仓库：

```json
{
  "keys": {
    "contact/contact.db": {"enc_key": "<64-hex-characters>"},
    "message/message_0.db": {"enc_key": "<64-hex-characters>"}
  }
}
```

旧私有清单如果含其他分库、盐值或绝对路径索引，本版会拒绝；需由使用者在私有位置人工整理为精确两库格式，不要公开原文件。

复制 [配置模板](examples/config.example.json) 到仓库以外的私有目录，填入实际信息。配置与密钥文件必须属于当前用户、权限为 `0600`；请自行在明确选定的文件上设置权限。本工具只检查权限，不调整源文件权限。配置中的所有文件路径需为实际存在的绝对规范路径，不能经过符号链接。时区用 IANA 名称，模板默认 `UTC`。

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit export \
  --config '<private-config-file>' --output '<new-private-output-directory>'
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m mac_wechat_export_kit verify \
  --output '<same-output-directory>'
```

替换尖括号参数后再执行。输出父目录需已存在，输出目录必须尚不存在，且不能在数据库根目录内。生产 CLI 只使用 SQLCipher 只读连接，没有普通 SQLite 回退模式。失败仅输出固定错误代码，不回显正文、密钥、配置值或本机路径。

## 输出与范围

| 文件 | 含义 |
| --- | --- |
| `messages.json` | 元数据、按时间与本地 ID 排序的消息、显式内容状态 |
| `messages.txt` | 可读文字与非文字占位 |
| `HTML/index.html`、`HTML/page-*.html` | 离线目录与分页，无脚本、图片或远程资源 |
| `manifest.json` | 完成标记、计数和逐文件 SHA-256；最后写入 |

输出目录 `0700`，文件 `0600`；不覆盖现有目录。失败时可能留下部分输出，没有通过 `verify` 的目录不能当作完整导出。SHA-256 验证只说明清单与当前文件一致，不是数字签名，也不证明来源真实性。

只读取选定会话表；其他会话不导出，其他消息分库不扫描。媒体消息保留类型占位；分享仅提取允许的可读字段，附件密钥和原始 XML 不输出。合并转发内部记录与非文字引用未展开。可读正文或标题本身也可能包含敏感信息，本工具不是脱敏器。

**仅验证 `message_0.db` 的会话快照，不能声称全量历史或支持全部微信版本。** 历史私有工作曾在 Apple Silicon、macOS 27.0.1、微信 4.1.13 build 269602 完成限定会话导出；本版经过重构，尚未重新执行真实会话导出。详见 [支持矩阵](docs/SUPPORT.md)。

## 结构与开发

```text
src/mac_wechat_export_kit/  同意、预检、副本、限时取钥、恢复、只读导出与校验
tests/                    合成 SQLite / 可选加密 SQLCipher 测试
examples/                 占位配置与合成演示
scripts/                  发布候选文件检查
docs/                     架构、支持、来源许可、安全与发布清单
```

[架构](docs/ARCHITECTURE.md) · [故障排查](docs/TROUBLESHOOTING.md) · [数据安全](docs/DATA_SAFETY.md) · [依赖与许可证](docs/DEPENDENCIES.md) · [逐文件来源审查](docs/SOURCES.md) · [发布前清单](docs/RELEASE_CHECKLIST.md)

## 来源与许可

本次路线基于 [acmerfight 的 Gist](https://gist.github.com/acmerfight/0a01249ef72970d07a2603dbb629e80f)，固定修订 `c98dbb10cf23c30e83d5d744905101b0880887a0`；不是直接运行 WeFlow。已通过 GitHub 固定修订 API 核对该版本含 MIT LICENSE，原版权声明保留于 [NOTICE](NOTICE) 与 [原许可证](docs/licenses/upstream-MIT.md)。本项目新增代码和已审查的私有改编按根 [MIT](LICENSE) 发布；上游改编保留原 MIT 归属。SQLCipher、Zstandard、Apple 工具等运行依赖保留各自许可，不能把根许可证解释为所有外部组件均为 MIT。

仅从旧工作中逐项审查必要源码，没有复制旧工程、运行证据、聊天导出、数据库或密钥。完整取钥流程复用了经审查的受限捕获、应用组策略和系统权限窗口观察实现；去掉了个人值、账号扫描、全局结束进程及自动重试。源码仓库为 [gaosu0715-lgtm/mac-wechat-export-kit](https://github.com/gaosu0715-lgtm/mac-wechat-export-kit)。发布仅包含工具源码、文档和合成测试，不附带任何真实账号数据、密钥或第三方二进制。[发布审计](docs/RELEASE_AUDIT.md) 保留测试与发布核验边界。
