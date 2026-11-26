# C 模块接口说明 v0.2

> **已作废（2026-11-26）**：全组已改用根目录的 `TEAM_INTERFACE.md`（v1.0，HTTP + 任务拉取）。
> 本文件仅作历史对照，**不要按它开发**。
> C 侧说明：原有 `RefereeService.handle` 的 propose/confirm 属于**内部 v0.4 接口**，
> 由 C 在网络适配层转换，其他成员不需要也不应该直接调用。

当前是本地 Python 接口，尚未提供 ROS、HTTP 或其他网络服务。

## 调用

from event_service import RefereeService
service = RefereeService()
state = service.public_state()
response = service.handle(event)

## 请求结构

```json
{
  "game_id": "从 public_state 获取的当前局号",
  "request_id": "调用方生成的唯一操作编号",
  "event_type": "propose",
  "payload": {"kind": "gt", "number": 5}
}
```

支持事件：
- propose：payload 恰为 kind、number。kind 为 gt/lt/eq/submit/exit；exit 的 number 为 null，其余为 1～10 整数。
- confirm / cancel：payload 恰为 pending_id、version，必须取自对应待确认内容。
- new_game：payload 为 {}，仅当前局结束后接受。

普通问题和提交使用 propose，确认后才生效。propose 返回 state.pending，调用方保存其 pending_id 与 version，再在用户确认时原样带回。异步适配器必须在打开收音窗口时绑定这些字段，不能收到迟到的“是”后才查询并绑定新问题。

## 去重与重试

同 game_id + request_id + 完全相同内容，返回缓存的原响应，并置 duplicate=true；不会再次执行。相同编号改变内容返回 request_conflict。
新的一次正式重复提问生成新 request_id；网络重试沿用原编号。
已处理旧请求的重试可返回历史快照（包括 new_game），不会修改当前局；旧局未处理的消息返回 stale_game。
响应 state 是处理时快照，UI 刷新应调用 public_state 获取当前状态，不可用历史快照回退画面。
业务拒绝也会缓存；修正输入应创建新请求。格式错误和未知旧局消息不缓存。
所有执行用进程内锁串行处理，响应和查询均返回副本。

## 响应

包含 request_id、ok、code、message、duplicate、state。
state 包含 game_id、phase、remaining、history、pending、finished、result。
秘密数字在对局中不公开，正常最终提交结束后才增加 revealed_number；主动退出不公开牌值。

## 边界

去重和状态仅在当前进程内保存；进程重启会丢失。未实现缓存清理、日志持久化、暂停恢复、双向玩法、私密视觉登记、策略服务、播报状态和动作反馈。现阶段统一使用全真调试回答。
Windows Python 3.13 用于离线开发，未来 ROS 部署需检查目标 Python 兼容性。

