# 架构与边界

```mermaid
flowchart LR
    U[本机同意与精确账号选择] --> F[只读预检与固定版本适配]
    F --> B0[私有临时副本 / 仅签主应用]
    B0 --> R[一次限时 LLDB / 盐匹配参数]
    R --> A[两库 HMAC / SQLCipher raw key 验证]
    A --> X[脱离 / 正常退出 / 原版恢复确认]
    X --> K
    C[本机私有配置] --> S[明确两库路径与权限检查]
    K[私有逐库 raw key] --> D[SQLCipher 4 只读适配器]
    S --> D
    D --> B[联系人精确唯一匹配及内部 ID 绑定]
    B --> T[指定会话表的一致读取事务]
    T --> P[内容白名单与显式占位]
    P --> O[JSON / TXT / 离线 HTML]
    O --> V[计数 / ID / 排序 / SHA-256]
```

配置只接受声明的字段。库文件由明确路径与摘要选定；不会搜索本机的库或账号。密钥 JSON 只接受两个相对数据库名到 `enc_key` 的映射，且配置和密钥文件均要求当前用户拥有的 `0600` 常规文件。

`bootstrap.py` 是引导状态机，系统操作在 `mac_host.py` 中，LLDB 参数读取在 `runtime_capture.py` 中，纯验证策略在 `capture_policy.py` 中，journal 在 `session.py` 中。原版未退出、版本不符、非本机交互终端或未明确同意时，没有副本签名和秘密读取。`plan` 不读加密页；`recover` 不读密钥或数据库页。恢复与用户确认完成后才解析唯一联系人绑定并导出，两个内部 ID 可以在 setup 中留空。`guide --bootstrap-only` 则在恢复确认后停止。

`permission_windows.py` 是逐文件审查后复用的系统窗口观察器，只读当前 GUI session 与允许的系统 agent 最小按钮特征，不读微信 UI 正文或截图，不申请权限。无法判定时停止。该模块的 native backend 只在真实预检/引导时实例化，测试使用合成快照。

`cipher.py` 通过 `sqlite3_open_v2(..., SQLITE_OPEN_READONLY)`、`query_only=ON` 和 `sqlite3_db_readonly` 核实生产连接。原始数据库密钥使用 `x'<hex>'` 字面量传给 `sqlite3_key`，避免把 raw key 再按密码派生。SQLCipher 页认证仍由库完成；成功执行 schema 查询才说明该连接可读。工具不包含旧 `PageCodec`。

`exporter.py` 先按昵称或备注精确查询联系人，要求一行且内部 ID 等于配置中的预期值。会话表名由该 ID 的 MD5 构造；此处 MD5 仅是表命名约定，不承担密码或完整性功能。直接 export 使用明确配置的身份。完整 guide 在恢复后只读取该会话参与者的 Name2Id，与已选账号目录做唯一匹配；不唯一或不匹配就停止，最终还须用户确认。出现第三人、未知非系统发送方、重复本地 ID 或计数不一致时停止。

消息读取在一个事务中先计数，再按 `(create_time, local_id)` 分页。只从目标表收集发送方对应的 `Name2Id` 条目；正文仅对文字、系统和分享类型读取。联系人库与消息库是先后建立的两个连接，不承诺跨库原子快照；进行账号迁移或联系人身份变更时应停止后重新确认绑定。

每页最多 2,000 条，每条输入/解压正文上限 10 MiB。Zstandard 缺失、坏 UTF-8、XML 无法解析和超限都有状态。XML 拒绝 DTD/ENTITY；只提取可读允许字段。合并转发只保留摘要，不展开内部记录。

输出通过独占创建写入，HTML 全部转义并带 `default-src 'none'` CSP，无外部依赖。正文、导出全部 JSON 与 ID 集合的最终核对仍使用内存，因此不是无限规模流式工具。极大单会话可能因内存不足失败，应保留失败边界，不跳过校验。

`verify` 只接受预期产物文件名集合，拒绝清单路径穿越、符号链接、摘要不符、JSON/HTML 计数不符、重复 ID 和排序错误。清单并无签名，不能抵抗能够同时改写清单与产物的人。

接口 `opener(relative)` 便于用合成 SQLite 适配器测试；公共 CLI 没有选择普通 SQLite 后端的参数。测试写库入口 `fixture_write=True` 仅供人工数据库测试，生产调用不使用它。
