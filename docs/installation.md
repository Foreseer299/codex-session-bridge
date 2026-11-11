# 安装与操作指南

安装命令在**运行 Paseo 与 Codex 的 Linux 主机**上执行。手机和电脑是连接入口，无需各装一份插件。

## 先确认已有环境

插件连接已有的 Codex managed daemon，不负责安装 Codex、登录账号或创建 SSH 连接。安装前应当能做到：

- Desktop 已连接目标主机，在远程项目中正常聊天。
- Paseo 服务端在同一主机运行，手机能连接它。
- Paseo 与 Codex 使用同一个系统用户。

| 项目 | v0.2.0 支持范围 |
| --- | --- |
| 系统 | Linux |
| Paseo 服务端 | 0.15.3 |
| Codex managed daemon | 0.167.1 |
| Node.js | ≥24，使用当前 Paseo 的 Node |
| Python | ≥3.11，`python3` 可用 |
| 安装工具 | `git`、`npm`、`patch` |

插件会自动识别正在运行的 Paseo 包、CLI、Node 与 home。Codex home 优先读取 Paseo 进程环境中的 `CODEX_HOME`，未设置时使用 `$HOME/.codex`；它必须是 Desktop 正在使用的那份 home。

不要为安装插件另起一个独立 `codex app-server`。两个后台即使读到相同文件，也不等于共享同一个运行实例。

## 安装

```bash
npx --yes github:Foreseer299/codex-session-bridge#v0.2.0
```

这条命令先通过官方 SDK 开启插件功能，再把 Git 发布版本注册为真正的 Paseo 插件，并等待配置结果。无需 npm 账号。此前已经启用 Paseo 插件功能时，也可以直接用原生命令：

```bash
paseo plugin add https://github.com/Foreseer299/codex-session-bridge.git --ref v0.2.0
```

使用完整 Git URL，因为目前未登记到 Paseo 插件目录。首次直接 `plugin add` 且总开关关闭时，Paseo 0.15.3 的安装响应可能短暂显示 `failed`，随后后台加载；建议用上面会等待结果的 npx 命令。真正的成功标志是插件日志中的 `ready`，不是仅看到安装记录。

正常安装会自动完成：

1. Paseo 获取插件与固定的运行依赖。
2. 安装阶段检查 Node/Python、Codex 版本和 socket，通过 Paseo 官方 SDK 开启插件总开关；加载后再识别宿主路径、校验原件哈希与配置。
3. 将运行文件放入 Paseo home 下的 `plugin-state/codex-session-bridge/runtime`，保存本机私有回退资料。
4. 写入所需桥接配置、应用三个版本锁定的兼容补丁。
5. 等所有 Paseo 任务空闲后，通过 Paseo 官方接口重启 worker，使补丁生效，再启动同步进程。

如果插件总开关原来关闭，开启后原先已标记为启用的其他插件也会开始运行。无需另行执行开启命令。

不需要手动执行 `npm ci`、查找 `node_modules`、编辑配置或创建 systemd 服务。Paseo 原来的 supervisor 与终端会保留；客户端在 worker 重启时可能短暂重连。若有任务持续运行，插件会等待，不应把这段等待误认为安装已即时生效。

查看安装进度：

```bash
paseo plugin ls codex-session-bridge
paseo plugin logs codex-session-bridge
```

`running` 表示插件已被 Paseo 加载；仍需看日志确认配置、兼容补丁和重启阶段已经完成，然后做下面的双向验收。安装不启动模型任务。

如果平时用 `--home` 选择特定 Paseo 实例，安装和管理插件时也给 `paseo` 命令加同一个 `--home`。这是选择目标实例，无需再提供服务端包路径。

## 双向验收

先用两个短聊天验证：

| 操作 | 应看到的结果 |
| --- | --- |
| Desktop 在目标远程主机新建聊天并发送消息 | Paseo 的同一主机出现该会话 |
| Paseo 打开它并回复 | Desktop 读到新消息和回复 |
| Paseo 新建另一个 Codex 聊天并发送消息 | Desktop 的该主机历史中出现它 |
| Desktop 打开后继续 | Paseo 能读到后续内容 |
| 一侧改名 | 另一侧会话列表更新 |
| 一侧归档，再恢复归档 | 另一侧状态跟随更新 |

新建但尚未保存的空白聊天不会出现。发现和列表刷新需要几个同步周期，必要时刷新客户端列表。

两边映射到同一个原生 Codex thread ID 才是共享会话。Paseo 自己的入口 ID 可以不同；不用复制聊天文件来对齐它们。

要测试运行中会话，可以在另一侧打开它，确认仍显示执行中。普通独立 `codex resume` 与 Desktop 同时写入不在并发保证内。

## 手机 ChatGPT 与 Paseo 如何配合

ChatGPT 手机端能连接桌面主机，并不代表它会显示桌面通过 SSH 打开的 VPS 会话。已有用户报告桌面本地会话可见、SSH 会话不可见，即使桌面端的远程项目正常可用。[相关问题 #23062](https://github.com/openai/codex/issues/23062)

本插件让 Paseo 连接 VPS 上的 Paseo 服务端，进入 Desktop 正在使用的同一份原生会话。手机 ChatGPT 可以继续处理它能访问的桌面会话；看不到的 VPS 工作，从 Paseo 接着查看和操作。

这个入口不依赖 ChatGPT 手机端能否发现 SSH 会话，也不会修改 ChatGPT App。安装验收以 Desktop ↔ Paseo 的双向接续为准，不把官方文档提到某个场景当成手机端已经可用的证明。

Desktop 专属工具需要回到支持它的客户端处理。权限、模型和客户端设置也不等同于会话历史同步；插件保留原有审批策略，需要 Full access 时由使用者明确设置。

## 日常管理

```bash
# 查看状态和日志
paseo plugin ls codex-session-bridge
paseo plugin logs codex-session-bridge

# 重载插件
paseo plugin reload codex-session-bridge

# 停用后重新启用
paseo plugin disable codex-session-bridge
paseo plugin enable codex-session-bridge

# 移除插件
paseo plugin remove codex-session-bridge
```

同步进程由插件管理，Paseo 正常重启后会恢复；无需另建后台服务。不要再同时运行手动版 `npm run watch`。

停用和卸载的恢复步骤、版本升级注意事项见 [排错与回退](troubleshooting.md)。

## 从 v0.1.0 迁移

v0.1.0 是手工安装包，不能直接在已有补丁上再叠一层插件。先保留旧安装目录与 `.bridge-state/` 备份，等正在执行的任务结束：

1. 停止旧同步器。若使用旧指南中的用户服务，运行 `systemctl --user disable --now codex-session-bridge.service`；前台运行则按 `Ctrl+C`。
2. 停止 Paseo 服务端。在旧安装目录执行 `python3 scripts/install.py --uninstall` 预览，再执行 `python3 scripts/install.py --uninstall --apply` 恢复原件。
3. 以原来的方式启动 Paseo，确认它正常可用。
4. 执行本文的一条 `paseo plugin add … --ref v0.2.0` 命令，再做双向验收。

如果旧文件在安装后又被改动，旧卸载器会拒绝覆盖。先保留自己的改动并核对版本，不要跳过哈希校验；第三方补丁也需要先处理冲突。聊天记录会保留。

## 发布包与开发者安装

[Releases](https://github.com/Foreseer299/codex-session-bridge/releases) 仍提供版本包、源码包和 `SHA256SUMS`，用于核验或离线审阅；通常直接用上面的 Git 安装命令即可。

仓库中的 `scripts/install.py` 保留给手动版迁移与高级排错，不是 v0.2.0 原生插件的常规安装入口。不要同时使用两套安装方式。
