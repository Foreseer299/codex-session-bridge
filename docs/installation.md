# 安装与操作指南

所有命令都在**运行 Paseo 与 Codex 的 Linux 主机**上执行。电脑、手机只是连接这台主机的入口。

## 1. 确认现有环境

先确保以下两件事分别可用：

- Codex Desktop 能连接到这台主机，正常新建聊天并得到回复。
- Paseo 客户端能连接到这台主机，服务端已安装并正常运行。

本包连接已经存在的 Codex managed daemon，不负责安装、登录或启动它。不要为了安装本包再启动一个独立的 `codex app-server`：它不一定使用 Desktop 正在使用的运行实例。

当前支持：Paseo 服务端 `0.15.3`、Codex managed daemon `0.167.1`、Node.js 24 或以上、Python 3.11 或以上。

```bash
node --version
python3 --version
patch --version
```

Paseo 与 daemon 必须由同一系统用户运行，并使用同一个 Codex home。常见位置为：

| 位置 | 用途 |
| --- | --- |
| `$HOME/.paseo` | Paseo 的配置和会话入口 |
| `$HOME/.codex` | Codex 的配置和原生历史 |
| `$HOME/.codex/app-server-control/app-server-control.sock` | managed daemon 的私有控制 socket |

可以只检查 socket 是否存在，不要打印其中的内容：

```bash
test -S "$HOME/.codex/app-server-control/app-server-control.sock" \
  && echo 'Codex socket exists'
```

自定义过路径时，用你的实际目录。不同的 home 即使属于同一用户，也可能指向不同的会话集合。

## 2. 找到 Paseo 服务端包

安装器需要的是 `@getpaseo/server` 的**包目录**，不是 Paseo 可执行文件，也不是 `$HOME/.paseo`。

先查看全局 npm 包的位置：

```bash
npm root -g
npm ls -g @getpaseo/server --all
```

服务端可能是 `@getpaseo/cli` 的嵌套依赖。若上面的列表没有显示，再检查实际安装目录：

```bash
find "$(npm root -g)" -path '*/@getpaseo/server/package.json' -print
```

把结果末尾的 `/package.json` 去掉，即为 `--paseo-package` 的值。找到多个版本时，以正在运行的 Paseo 所用目录为准。不要只选第一个结果。

如果从源码、本地 npm 目录或其他包管理器安装，检查那份安装里的 `@getpaseo/server/package.json`。要确认版本，可执行：

```bash
node -p "require('/path/to/node_modules/@getpaseo/server/package.json').version"
```

没有对应版本时先停止本次安装，不要把补丁手动贴到其他版本上。

## 3. 解压并预检

下载 GitHub Release 中的发布包，解压到一个打算长期保留的目录。本文用 `$HOME/codex-session-bridge` 举例；不要安装后马上删除这个目录，同步器还会用到它。

下载 `codex-session-bridge-0.1.0.tgz` 与 `SHA256SUMS` 到同一目录后：

```bash
sha256sum --ignore-missing -c SHA256SUMS
mkdir -p "$HOME/codex-session-bridge"
tar -xzf codex-session-bridge-0.1.0.tgz \
  -C "$HOME/codex-session-bridge" --strip-components=1
cd "$HOME/codex-session-bridge"
npm ci

python3 scripts/install.py \
  --paseo-home "$HOME/.paseo" \
  --paseo-package /path/to/node_modules/@getpaseo/server \
  --codex-home "$HOME/.codex"
```

将包路径替换成第 2 步找到的路径。如果 `paseo` 不在 PATH 中，加上 `--paseo-cli /path/to/paseo`。默认只做预检；确认输出中的目录与版本都正确。

安装器会处理桥接入口、同步配置和三个 Paseo 兼容补丁。它不会复制你的登录凭据，不会迁移原生聊天文件，也不会自动修改审批策略。

## 4. 正式安装

等正在执行的回合结束，再停止当前 Paseo 服务端，避免它一边运行一边载入新旧两套代码。使用你原来的服务管理方式停止，**不用停止 Codex managed daemon**。

在相同命令末尾加 `--apply`：

```bash
python3 scripts/install.py \
  --paseo-home "$HOME/.paseo" \
  --paseo-package /path/to/node_modules/@getpaseo/server \
  --codex-home "$HOME/.codex" \
  --apply
```

安装器会在本包的 `.bridge-state/` 目录中保存本机状态与备份，运行配置为 `.bridge-state/runtime.json`。保留这个目录，运行和卸载都会用到；不要把它上传到公开仓库。随后以原来的方式启动 Paseo 服务端。

启动同步器：

```bash
npm run watch
```

`watch` 默认读取安装生成的 `.bridge-state/runtime.json`，无需重复输入目录。先保留这个终端，观察日志是否正常。它负责自动发现和会话状态同步；空闲等待不会自行提交模型任务。

需要只执行一次发现和状态同步时，可以在同一目录运行 `npm run sync`；长期使用仍应保持 watcher 运行。

## 5. 验收双向接续

先用两个短聊天验证，避免拿正在执行重要任务的会话试错。

| 操作 | 应看到的结果 |
| --- | --- |
| Desktop 在该远程主机新建聊天并发送消息 | Paseo 的同一主机出现该会话 |
| Paseo 打开它并回复 | Desktop 读到新的消息和回复 |
| Paseo 新建另一个 Codex 聊天并发送消息 | Desktop 的该主机历史中能找到它 |
| Desktop 打开后继续 | Paseo 能读到后续消息 |
| 一侧改名，另一侧重新查看列表 | 标题一致 |
| 一侧归档、恢复归档 | 另一侧对应状态更新 |

新建但尚未保存的空白聊天不会出现。发现并非瞬间完成，等几个同步周期；必要时刷新客户端会话列表。

确认是共享会话的方法是查看两边映射到的原生 Codex thread ID。Paseo 自己的入口 ID 不需要与它相同。不要通过复制聊天文件来“对齐”它们。

若要测试正在执行的回合，可以在另一侧打开它，确认仍显示运行中。不要在两个窗口同时启动两轮互相矛盾的任务；原生 CLI 的独立 `codex resume` 也不在并发写入保证内。

## 6. 可选：让同步器常驻

前台验收通过后，再配置 systemd **用户服务**。这只管理同步器，不替代你已有的 Paseo 或 Codex 服务。

先确定 npm 的绝对路径：

```bash
command -v npm
command -v node
mkdir -p "$HOME/.config/systemd/user"
```

创建 `$HOME/.config/systemd/user/codex-session-bridge.service`：

```ini
[Unit]
Description=Codex Session Bridge metadata watcher

[Service]
Type=simple
WorkingDirectory=%h/codex-session-bridge
ExecStart=/absolute/path/to/npm run watch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

替换 `ExecStart` 为刚才查到的 npm 绝对路径；如果解压目录不同，也修改 `WorkingDirectory`。如果 Node 由 nvm 等工具安装，systemd 不会自动加载交互式 shell 的环境，需在 `[Service]` 中补上实际的可执行文件目录，例如：

```ini
Environment=PATH=/absolute/path/to/node/bin:/usr/local/bin:/usr/bin:/bin
```

先用 `Ctrl+C` 停掉前台 watcher，避免启动两份，再启用服务：

```bash
systemctl --user daemon-reload
systemctl --user enable --now codex-session-bridge.service
systemctl --user status codex-session-bridge.service
journalctl --user -u codex-session-bridge.service -n 50 --no-pager
```

如果希望退出 SSH 后用户服务仍运行，可为当前用户启用 linger：

```bash
loginctl enable-linger "$USER"
```

部分主机需要管理员权限执行这一项。容器或没有 systemd 的环境，可以用现有进程管理器保持 `npm run watch` 运行。

## 权限怎么设置

本包保留现有权限设置。需要 Full access 时，在**目标主机**的 Codex 和 Paseo 设置中明确选择，并用一个普通文件操作验证。只调整自己理解并接受的权限范围。

不要把“共享会话”理解为“所有客户端的每个设置都同步”。模型、审批界面以及仅 Desktop 可用的工具，仍取决于客户端和 daemon 支持的行为。

后续升级、卸载及常见错误见 [排错与回退](troubleshooting.md)。
