# 排错与回退

先确认故障出在哪一层：Desktop 能否连接目标主机、Codex daemon 是否可用、Paseo 是否运行、watcher 是否持续运行。只修改出问题的一层，通常不需要重装整套环境。

## 新聊天没有出现

依次确认：

1. 两个客户端选的是同一台主机，使用同一用户和 Codex home。
2. 新聊天已发送消息并保存；只有空标签页时不会被发现。
3. `npm run watch` 或对应服务仍在运行，日志没有连接错误。
4. 会话没有归档，也不是临时会话或子代理会话。
5. 等待几个同步周期，再刷新客户端列表。

普通会话会自动发现；不是只绑定安装时打开的那一条。发现入口不代表所有原生 CLI 会话都能被多个进程同时写入。

## 有历史，但发消息失败

读取历史成功只证明找到了会话，不能证明已连接到正确的 writer。

- 确认 Paseo 安装补丁后已重启，实际运行的服务端目录就是安装器修改的目录。
- 确认桥接连接的是 Desktop 所用的 managed daemon 私有 socket。
- 如果正在用独立 `codex resume` 操作这条会话，先结束那个进程，再从已验证的 Desktop / Paseo 入口继续。

不要通过启动第二个 `codex app-server` 或复制聊天文件来绕过锁。

## 提示只能继续导入的 Desktop 会话

例如出现 `Use this provider to continue an imported Codex Desktop conversation`，通常需要检查 provider 配置和兼容补丁是否都已载入。只改桥接命令、不更新新建会话相关的 Paseo 代码，会留下只能继续导入聊天的旧行为。

重新运行安装预检，确认包路径、版本和文件检查通过；检查是不是另一份全局或本地 Paseo 安装正在运行。不要直接删除聊天记录再重试。

## Socket 不存在、连接被拒绝或权限不足

```bash
test -S "$HOME/.codex/app-server-control/app-server-control.sock" \
  && echo 'socket exists'
```

没有 socket：先恢复 managed daemon 自身，再启动 bridge。连接被拒绝：socket 文件可能还在，但后台进程没有正常监听。权限不足：确认 Paseo、watcher 和 daemon 由同一用户运行。

不要把 socket 改成所有人可写，也不要为了排错把它转发到公网。它本来就只需在主机内部使用。

## 运行中回合看起来卡住

查看 daemon 是否仍在执行，再查看 bridge 与 watcher 日志。重连恢复的是已有回合，不应该额外提交一轮生成。

如果只有某个 Desktop 专属工具卡片等待操作，回到 Desktop 处理；Paseo 不会自动具备 Desktop 的全部工具。重新打开客户端后先确认当前回合状态，不要连发相同任务。

## 归档、标题或列表没有马上更新

消息传输和会话列表同步是不同的路径。先检查 watcher；前台终端关闭后，bridge 仍可能让已打开的聊天继续工作，但新会话发现和元数据同步会停止。

归档和恢复归档属于同步范围。永久删除、不同主机间的迁移、客户端窗口布局不属于。

## Full access 为什么没有自动打开

安装器不会替用户放宽权限。先检查当前回合实际使用的客户端设置和目标主机的 Codex 配置；旧会话的设置也可能与新建会话不同。

Full access 和双向同步是两件事。不要为了消除同步错误而更改与连接无关的审批策略。

## 升级前先做什么

本版本适配 Paseo `0.15.3` 和 Codex managed daemon `0.167.1`。上游升级可能改变内部文件或协议，因此本包不会承诺“跟着 latest 自动可用”。

推荐顺序：

1. 等当前任务结束，停止 watcher 和 Paseo 服务端。
2. 使用**当前安装包**卸载集成并恢复安装备份。
3. 升级 Paseo / Codex，先验证它们各自能正常使用。
4. 获取明确支持新版本的本包，先预检再安装。
5. 重启 Paseo 和 watcher，重新做一次双向新建、接续与归档验收。

如果尚无对应适配版本，请保留已验证的组合，或暂时卸载集成。不要跳过版本保护强行套补丁。

## 卸载与回退

若配置了本文示例的用户服务，先停止并禁用它：

```bash
systemctl --user disable --now codex-session-bridge.service
```

前台运行则按 `Ctrl+C`。停止 Paseo 服务端，然后在原安装目录执行：

```bash
python3 scripts/install.py --uninstall

# 确认预览无误后恢复文件
python3 scripts/install.py --uninstall --apply
```

第一条命令仅预览，第二条才执行恢复。按安装器输出完成恢复，再启动 Paseo。保留原安装目录及其状态文件，直到确认卸载成功。

如果安装器报告文件已在安装后变化，它会拒绝覆盖。先查看该文件是被上游升级还是自己修改，保留需要的改动，再按错误信息恢复对应版本。不要把旧备份直接覆盖到新版本的 Paseo 上。

卸载只处理本包安装时记录的改动，不删除原生 Codex 历史。安装备份用于回退本包改动，不是聊天记录备份。

## 提 Issue 时带什么

- Linux 发行版与架构。
- Node、Python、Paseo 服务端与 managed daemon 的版本。
- 出问题的方向：Desktop → Paseo，还是 Paseo → Desktop。
- 是新建、继续、改名、归档，还是断线恢复时发生。
- 一段足够重现问题的操作说明，以及相关错误日志。

隐藏日志中的密钥、主机地址和个人路径，不要上传整个 Codex home、Paseo 数据目录或真实聊天档案。通常版本和错误附近的几行日志就够开始排查。
