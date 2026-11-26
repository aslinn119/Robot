# Roban 裁判网络服务

负责人：C 刘杰。接口版本：1.0。两种玩法已完成软件模拟集成；真机模式尚未开放。

## 统一位置

Windows 挂载路径：`Z:\team_project_ws\src\Robot_checkout\robot_referee\network_service`

机器人路径：`/home/lemon/team_project_ws/src/Robot_checkout/robot_referee/network_service`

| 位置 | 用途 |
|---|---|
| `src/network_v1/` | C 裁判、任务队列、日志、视觉证据及 D 接口适配 |
| `src/vendor_d/strategy.py` | D 交付的纯策略原样快照；来源及哈希见 docs |
| `tools/run_referee_server.py` | 启动 C 裁判服务 |
| `tools/run_d_strategy_client.py` | 拉取 D 策略任务并调用 D 算法；不执行动作 |
| `tools/run_tests.py` | 自动测试入口 |
| `docs/HTTP_INTERFACE_V1.md` | 全组正式 HTTP 接口规范 |
| `docs/D_STRATEGY_INTEGRATION.md` | D 策略字段映射与验证说明 |
| `runtime/` | 私密日志，Git 忽略；禁止作为交付物转发 |

## 机器人上准备环境

在 SSH 的 Linux 终端运行：

```bash
cd /home/lemon/team_project_ws/src/Robot_checkout/robot_referee/network_service
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/run_tests.py
```

首次运行才需建虚拟环境、安装依赖。如果系统提示缺少 python3-venv，先由机器人维护者安装该系统组件；不使用系统 pip 覆盖厂商依赖。

## C 启动服务

同一运行目录只启动一个裁判进程。C 为 A/B/C/D 生成四个不同的令牌，各成员只配置自己的令牌。令牌不要写入仓库或群内公开文档。

```bash
export ROBAN_TOKEN_A="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export ROBAN_TOKEN_B="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export ROBAN_TOKEN_C="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export ROBAN_TOKEN_D="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
.venv/bin/python tools/run_referee_server.py
```

默认仅本机 `http://127.0.0.1:8780`。同一机器人上的模块可以直接使用该地址。需要从其他电脑连接时，由 C 使用 `--host 0.0.0.0` 启动，队友改用 `http://10.129.108.111:8780`，并确保访问的是这台机器人。当前只用于受控实验室网络。

## D 启动策略客户端

在另一个 SSH 终端进入本目录，设置与 C 完全相同的 D 令牌，然后：

```bash
export ROBAN_TOKEN_D='由C单独提供的D令牌'
.venv/bin/python tools/run_d_strategy_client.py --server http://127.0.0.1:8780
```

客户端只拉取 `strategy` 队列。它调用 D 已交付的 `suggest`、`answer_suggestion` 函数。动作队列仍由 D 的动作端负责；本客户端不会点头、摇头或播放动作。

同一角色只允许运行一个实例；重启客户端发生 MODULE_CONFLICT 时，不要反复改实例抢占。当前尚无模块重置接口，需要 C 停止本次模拟服务后重启；未完成局会归档为中断。

## A、B 调用方式

- A：配置 A 令牌，心跳注册后拉取 `/api/v1/modules/A/commands/next?lane=main`，按正式文档回报任务阶段和结果。
- B：配置 B 令牌，拉取 B/main；采集证据先上传，再回报 capture 结果；登记只在 B 私密界面确认。
- C：使用 C 令牌创建 mock 对局及管理暂停、恢复、退出。
- D：策略脚本可直接使用；motion 队列需 D 的动作客户端另行对接。

当前所有新局都必须使用 `runtime_mode: "mock"`；`robot` 会返回 503。服务不会自动执行厂商 ROS 动作。实际语音、识牌和动作仍需分别验收。

## 已验证与未验证

D 原始算法的 56 条合法路径已通过 Windows 上 D/C 完整对局集成，最多七问。共享部署代码会再次以 Z 盘代码运行测试。

Windows 测试不等同于机器人 Linux 环境运行验证。本次同步不会自动安装机器人依赖或启动机器人服务；上述 Linux 启动步骤需在 SSH 终端执行。
