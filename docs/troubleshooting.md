# 排错与回退

先查看插件状态与日志：

```bash
paseo plugin ls codex-session-bridge
paseo plugin logs codex-session-bridge
```

使用自定义 Paseo home 时，为这两条命令加上与平时相同的 `--home`。提 Issue 前去掉日志中的个人路径、主机地址和会话信息。

## 插件已经显示 running，但会话还没有同步

`running` 只代表 Paseo 已加载插件。首次安装还要校验环境、配置桥接、应用兼容补丁，并等待任务空闲后重启 worker。

先看日志是否仍在等待空闲。如果 Paseo 中有运行中或等待处理的任务，完成它们后再等一次自动检查。不要为了加快安装强制结束其他会话。

worker 重启后客户端可能短暂重连。连接恢复后，再查看目标主机的会话列表。

## 安装时提示版本或原始文件不匹配

本版支持 Paseo `0.15.3` 和 Codex managed daemon `0.167.1`。版本相同但源码文件哈希不同，通常意味着安装过旧手动版、第三方补丁或本地改动。

- v0.1.0 用户先按 [迁移步骤](installation.md#从-v010-迁移)恢复原件。
- 第三方补丁用户先核对冲突，保留自己的修改。
- 上游升级后，等待匹配版本的插件，或暂时卸载集成。

不要修改版本号或跳过哈希校验来强行安装。

## 提示找不到 Node、Python、Paseo CLI 或 patch

插件使用当前 Paseo 的 Node，并从当前宿主安装定位 CLI；Python 与系统 `patch` 需要在服务进程的环境中可用。

终端里能找到命令，不代表 systemd 启动的 Paseo 使用同一份 PATH。先核对 Paseo 自身的启动环境，再重载插件：

```bash
paseo plugin reload codex-session-bridge
```

这类主机环境修复不需要手动寻找并填写 Paseo 服务端包目录。

## Socket 不存在、被拒绝或权限不足

插件默认使用 Paseo 进程的 `CODEX_HOME`，未设置时使用 `$HOME/.codex`。其中应有 managed daemon 的私有控制 socket。

没有 socket 时先让 Desktop 正常连接这台主机，确认后台已经启动。连接被拒绝时，可能是 socket 文件残留、后台没有监听。权限不足时，确认 Paseo 与 Codex 由同一系统用户运行。

不要把 socket 改成所有人可写或转发到公网，也不要通过启动第二个独立 app-server 来替代 Desktop 所用的运行实例。

## 新聊天没有出现

依次确认：

1. 两个客户端选的是同一台主机、同一个 Codex home。
2. 新聊天已经发送消息并保存，不能只是空标签页。
3. 插件已完成安装与重启阶段，Paseo 服务端仍在运行。
4. 会话未归档，也不是临时会话或子代理会话。
5. 等几个同步周期，再刷新列表。

插件发现所有符合条件的普通会话，不是只绑定安装时打开的那一条。

## 有历史，但发消息失败

先确认插件没有停在等待重启或冲突阶段。历史可读只表示找到了会话，还需要正确连接当前 writer。

若正在用独立 `codex resume` 操作这条会话，先结束那个进程，再从 Desktop 或 Paseo 继续。不要复制聊天文件来绕过写入锁。

旧手工部署出现 `Use this provider to continue an imported Codex Desktop conversation` 时，核对是否还在使用旧桥接命令；先完成旧版回退，再安装插件。

## 运行中回合看起来卡住

先检查 Codex daemon 是否还在执行，再看插件日志与客户端连接状态。重连应接回已有回合，不会主动再提交一轮生成。

Desktop 专属工具、界面操作或某些交互卡片仍需回到 Desktop 处理。Paseo 共享会话并不代表实现了 Desktop 的每种工具。

## 手机 ChatGPT 仍然看不到 VPS

这可能正是已报告的手机端缺口：桌面本地会话能显示，桌面通过 SSH 使用的远程项目和会话却不出现。见 [#23062](https://github.com/openai/codex/issues/23062) 和 [#24730](https://github.com/openai/codex/issues/24730)；后者按重复问题关闭，不表示功能已经修复。

本插件提供的是 Paseo 中的同会话入口，不会修改 ChatGPT 手机 App。只要 Desktop 与 Paseo 之间已经能双向接续，就可以直接用 Paseo 继续 VPS 工作；无需等待手机 ChatGPT 的列表恢复，也不要为此改写 VPS 聊天文件。

客户端功能后续可能变化，以上报告不代表所有版本都会遇到同一限制。

## 标题、归档或列表没有马上更新

实时消息与列表同步走不同的路径。确认插件同步进程正常，等几个周期后刷新列表。永久删除、跨主机迁移和客户端窗口布局不属于同步范围。

## Full access 没有自动打开

插件保留现有审批与沙箱设置。需要 Full access 时，在目标主机的 Codex 与 Paseo 中明确选择，并用普通文件操作验证。

共享会话不等于共享所有客户端设置，也不应靠放宽权限修复连接问题。

## 升级前先做什么

先阅读目标版本的兼容说明。升级 Paseo 或 Codex 之前，等任务结束并停用插件，让它恢复自己管理的兼容补丁；确认恢复完成后再升级上游。

插件版本更新通过 Paseo 的插件管理完成，可先查看：

```bash
paseo plugin update codex-session-bridge --check
```

准备更新时选择明确支持当前环境的发布版本。不要同时保留手动同步器和原生插件，也不要把旧版本的备份覆盖到新版 Paseo 上。

## 从 v0.2.0 升级到 v0.2.1

这次更换了兼容补丁，先让旧版恢复原件，再安装新版。聊天记录会保留。不要直接用 `plugin update` 覆盖仍由旧版管理的补丁。

1. 等待 Paseo 中的任务结束，执行 `paseo plugin remove codex-session-bridge`。
2. 等待自动回退和 worker 重启完成。若有冲突，先按下文排查，保留恢复状态目录。
3. 执行 `npx --yes github:Foreseer299/codex-session-bridge#v0.2.1`，等待日志显示 `ready`。

安装器发现旧版还在时会明确提示，不会把旧版的 `ready` 当作新版升级成功。

## 子代理一直显示运行中

v0.2.0 会漏转子代理事件，历史恢复也无法准确区分失败结果。升级到 v0.2.1 后，重新进入聊天即可读取最新回合状态；已完成、失败、中断分别显示，不会一律改成成功。

## Paseo 比 Codex 先启动

v0.2.1 会显示 `waiting_for_codex` 并自动重试。Codex 私有后台恢复后继续连接，无需手动重载插件。它不会主动提交模型任务，也不会修改 Windows 的 SSH 自动连接配置。若 Codex 后台始终没有启动，需要先恢复那个后台服务。

## 卸载与回退

临时停用：

```bash
paseo plugin disable codex-session-bridge
```

移除插件：

```bash
paseo plugin remove codex-session-bridge
```

插件会停止同步进程，并恢复自己写入的配置字段与兼容补丁；其他插件或用户后来增加的无关配置会保留。需要重新载入原件时，会等待 Paseo 空闲后自动重启 worker。任务持续运行时，恢复可能仍在等待，不要马上删除本地状态目录。

如果相关字段或补丁文件被其他程序修改，恢复会停止，避免覆盖新改动。保留 Paseo home 下的 `plugin-state/codex-session-bridge/`，核对冲突后再处理；其中有安装记录和原件备份，不要公开上传。

原生 Codex 聊天、Paseo 会话入口与同步元数据不会被删除。移除插件后，原有共享入口可能需要重新启用插件才能继续使用；聊天历史仍然保留在 Codex 中。

v0.1.0 手工安装版使用旧目录中的 `python3 scripts/install.py --uninstall --apply`，详见 [迁移说明](installation.md#从-v010-迁移)。

## 提 Issue 时带什么

- 系统与架构，以及 Paseo、Codex daemon、Node、Python 版本。
- 插件版本和 `plugin ls` 中的状态。
- 出问题的方向与动作：新建、继续、改名、归档或断线恢复。
- 最短复现步骤，以及去掉隐私信息的相关日志。

不要上传完整配置、Codex home、Paseo 数据目录、安装备份或真实聊天档案。
