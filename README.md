# Codex Session Bridge

**电脑上聊到一半，拿起手机接着聊。还是同一个 Codex 会话。**

把 Paseo 接到 VPS 上已有的 Codex managed daemon，让 Codex Desktop 和 Paseo 读写同一份会话。新开的聊天会自动发现，消息、标题和归档状态也能在两边接上，不用每次手动导入。

Shared Codex sessions between Desktop and Paseo, through the same private daemon on your Linux host.

## 能做什么

- 在 Desktop 开始聊天，在 Paseo 继续；从 Paseo 新建的聊天也能回到 Desktop 查看、继续。
- 自动发现已保存的普通会话，不必逐条绑定。空白的新聊天要先发送一条消息。
- 共享原生会话 ID 和历史，包括消息与工具执行记录。
- 同步标题、归档和恢复归档；重新打开仍在执行的会话时，恢复它的运行状态。
- 连接中断后重连，不用靠再发一句话触发同步。

```text
Codex Desktop ───────────┐
                        ├── Codex managed daemon ── 同一份原生会话
Paseo ── Session Bridge ─┘
```

Bridge 走同一用户的私有 Unix socket，无需给 Codex 新开一个公网端口。同步器维护的是 Paseo 中的会话入口和状态，不复制一套聊天档案。

## 先看兼容范围

这是一个社区集成包，包含桥接程序、同步器和 Paseo 兼容补丁。**当前不是可通过 `paseo plugin add` 安装的原生插件。** 安装器会检查版本，再修改指定的 Paseo 服务端文件。

| 项目 | 当前支持 |
| --- | --- |
| 服务端系统 | Linux，同一系统用户运行 Paseo 与 Codex |
| Paseo 服务端 | **0.15.3** |
| Codex managed daemon | **0.167.1** |
| 运行环境 | Node.js ≥ 24、Python ≥ 3.11 |
| 已验证的交互入口 | Codex Desktop、连接到该主机的 Paseo |

这里的 Codex 版本指 **VPS 上的 managed daemon**，不只是终端里另装的 `codex` 命令版本。

普通 Codex CLI 保存的历史可以被发现。但独立的 `codex resume` 有自己的写入锁，**目前不保证它与 Desktop 同时写同一会话**。也不包含跨 VPS 复制、账号同步、SSH 自动连接修复或所有客户端界面的完全一致。

## 安装

先在 Linux 主机上准备好已经能用的 Paseo 和 Codex managed daemon，让它们使用同一系统用户。Desktop 也要连接到这台主机。

从 **[Releases 下载发布包](https://github.com/Foreseer299/codex-session-bridge/releases)**，解压后进入目录：

```bash
npm ci

# 先检查，默认不会修改现有安装
python3 scripts/install.py \
  --paseo-home "$HOME/.paseo" \
  --paseo-package /path/to/node_modules/@getpaseo/server \
  --codex-home "$HOME/.codex"
```

把 `/path/to/node_modules/@getpaseo/server` 换成正在运行的 Paseo 服务端包目录。检查通过后，给同一条命令加上 `--apply` 执行安装。然后重启 Paseo 服务端，并保持同步器运行：

```bash
npm run watch
```

不知道包目录在哪、如何常驻或怎么验收？看 **[完整安装与操作指南](docs/installation.md)**。遇到问题看 **[排错与回退](docs/troubleshooting.md)**。

## 装好后怎么用

1. 在 Desktop 的这台远程主机上新建聊天，发送一条消息。
2. 到 Paseo 中打开同一台主机，等自动发现后打开该会话。
3. 在 Paseo 回复，再回到 Desktop 查看。反过来从 Paseo 新建，也做一次。

同步器需要持续运行；关闭 `npm run watch` 的终端会停止后台发现。可以按指南配置 systemd 用户服务。

安装不会替你开启 Full access，也不会改 Codex 的审批策略。需要什么权限，在对应主机和客户端中明确设置。

## 升级与卸载

Paseo 或 Codex 更新后，请先确认兼容版本。安装器遇到不匹配的版本或文件会停止，不会强行套用旧补丁。升级前后的步骤见 [升级与回退](docs/troubleshooting.md#升级前先做什么)。

卸载入口：

```bash
python3 scripts/install.py --uninstall

# 确认预览无误后恢复文件
python3 scripts/install.py --uninstall --apply
```

第一条命令只预览，第二条执行恢复。安装备份用于恢复被修改的文件；如果文件在安装后又被改过，卸载会拒绝覆盖，先按提示处理。卸载不会删除原生 Codex 聊天记录。

## 一起完善

如果它帮你少切了几个窗口，欢迎点个 ⭐。

遇到问题欢迎提 Issue：带上系统、Paseo 和 daemon 版本、复现步骤，以及去掉隐私信息的错误日志。先别贴完整聊天记录或配置文件。

基于 [Paseo](https://github.com/getpaseo/paseo) 和 [Codex](https://github.com/openai/codex)。这是独立社区项目，与两者官方无隶属关系。

## License

[Apache-2.0](LICENSE)。上游代码与补丁的许可说明见 [NOTICE](NOTICE)。
