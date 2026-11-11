# Codex Session Bridge

**电脑上聊到一半，拿起手机接着聊。VPS 上的 Codex 也一样。**

手机能连接桌面 Codex，却可能看不到它通过 SSH 连接的 VPS 会话。这个插件通过 Paseo 给 VPS 会话补上一个手机入口，让你接着查看、发消息和操作；Paseo 与 Codex Desktop 使用的是**同一个原生会话**，新聊天、消息、标题和归档状态双向接续。

ChatGPT 手机端可以继续处理它能访问的桌面会话；VPS 上的工作则可以从 Paseo 接着做，不必等手机端把 SSH 会话显示出来。

Shared VPS Codex sessions between Desktop and Paseo. Install once, pick up the same conversation from your phone.

## 一条命令安装

在已经运行 Paseo 和 Codex managed daemon 的 Linux 主机上执行：

```bash
npx --yes github:Foreseer299/codex-session-bridge#v0.2.0
```

这条命令通过 Paseo 官方插件接口安装，并等待自动配置结果。安装后能在 `paseo plugin ls` 中管理。

不用手找安装路径、编辑 JSON、另开同步终端或配置 systemd。插件会自动识别当前 Paseo 安装、配置桥接，并随 Paseo 管理同步进程。若 Paseo 的插件总开关原来关闭，安装会开启它；原先已标记为启用的其他插件也会运行。

**首次安装会校验并应用三个兼容补丁，等待 Paseo 的任务空闲后自动重启 worker。** 客户端可能短暂断线后重连；正在运行任务时，安装生效需要等待。不会重启 VPS 或 Codex daemon。

需要的环境：**Paseo 0.15.3、Codex managed daemon 0.167.1、Linux、Node.js ≥24、Python ≥3.11，以及 `git`、`npm`、`patch`**。Paseo 与 Codex 要由同一系统用户运行。这里的 daemon 版本不是终端中另一份 `codex` 的版本。

以前装过 v0.1.0 手动版？先按 [迁移说明](docs/installation.md#从-v010-迁移)恢复原件，再安装插件。

[完整安装与操作指南](docs/installation.md) · [排错与回退](docs/troubleshooting.md) · [发布包](https://github.com/Foreseer299/codex-session-bridge/releases)

## 装好之后

- 在 Desktop 新开聊天，手机 Paseo 中自动发现；从 Paseo 新开，也能回到 Desktop 继续。
- 共享原生会话 ID、消息和工具执行记录，不必逐条导入。
- 双向同步标题、归档和恢复归档。
- 重新打开运行中的会话时接回状态，连接断开后自动重连。
- 同步进程随插件启动、停止，不需要自己守着终端。

```text
Codex Desktop ── SSH ────────────────────┐
                                        ├── VPS Codex daemon ── 同一份会话
手机 Paseo ── VPS Paseo + Session Bridge ─┘
```

Bridge 使用主机内部的私有 Unix socket，不给 Codex 新开公网端口。只要 VPS 上的 Paseo 和 Codex daemon 保持运行，Paseo 入口不依赖电脑转发。

## 手机端能做到哪一步

“桌面上的本地聊天能看见，SSH 主机上的聊天却不出现”已有公开问题报告：[#23062](https://github.com/openai/codex/issues/23062)、[#24730](https://github.com/openai/codex/issues/24730)。官方文档中的场景描述不能代替客户端实际可用性。本插件通过 Paseo 提供同会话入口，解决这类接续需求，不要求你先解决手机端的 SSH 会话发现问题。

插件不会修改 ChatGPT 手机 App，也不会把 Desktop 专属工具、所有客户端设置或权限自动搬到 Paseo。普通 Codex CLI 保存的历史可以被发现，但独立 `codex resume` 与 Desktop 同时写同一会话仍不在保证范围内。

安装保留现有审批策略，不替你开启 Full access。跨 VPS 复制、账号同步和 SSH 自动连接修复也不属于本插件。

## 管理与卸载

```bash
# 查看状态、日志
paseo plugin ls codex-session-bridge
paseo plugin logs codex-session-bridge

# 停用或移除
paseo plugin disable codex-session-bridge
paseo plugin remove codex-session-bridge
```

停用或移除后，插件会恢复自己管理的配置字段和兼容补丁，保留聊天记录。需要重载时仍会等待 Paseo 空闲；若相关文件被其他程序改过，会停止恢复并保留备份。详见 [卸载与回退](docs/troubleshooting.md#卸载与回退)。

## 一起完善

如果它帮你少切了几个窗口，欢迎点个 ⭐。

遇到问题欢迎提 Issue：带上版本、复现步骤和去掉隐私信息的错误日志。先别贴完整配置或聊天记录。[隐私与发布检查](docs/privacy.md)

基于 [Paseo](https://github.com/getpaseo/paseo) 和 [Codex](https://github.com/openai/codex)。这是独立社区项目，与两者官方无隶属关系。

## License

[Apache-2.0](LICENSE)。上游代码与补丁说明见 [NOTICE](NOTICE)。
