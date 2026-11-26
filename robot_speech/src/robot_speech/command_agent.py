"""命令循环：拉任务 → 接单 → 开工 → 回传结果（TEAM_INTERFACE §5.2）。

顺序是规范定的，不能省：

    queued → accepted → （查状态）→ started → running → succeeded/failed/cancelled

1. 拉到命令先查本地处理记录；相同 `command_id` 不重复执行。
2. POST `task.accepted`；C 拒绝时**不得开始执行**。
3. 执行前再 GET 命令状态；已取消或已过期就回传 cancelled，不动硬件。
4. POST `task.started` 之后再执行。
5. POST `task.result`，payload 固定三字段 `status/result/error`。

同一执行通道一次只跑一项任务；心跳由独立线程维持，避免长收音把模块判离线。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from .eventlog import EventLog
from .http_client import HttpRefereeClient, RefereeHttpError
from .team_protocol import (
    A_CAPABILITIES,
    ERR_CANCELLED,
    ERR_INTERNAL,
    EVENT_TASK_ACCEPTED,
    EVENT_TASK_RESULT,
    EVENT_TASK_STARTED,
    SOURCE_A,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    build_event,
    build_heartbeat,
    new_id,
)

DEFAULT_HEARTBEAT_INTERVAL = 2.0
DEFAULT_CANCEL_POLL = 0.4
_TERMINAL = frozenset({"cancel_requested", "cancelled", "expired"})


@dataclass(frozen=True)
class HandlerOutcome:
    """一条命令的执行结果。"""

    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    @classmethod
    def success(cls, result: Mapping[str, Any]) -> "HandlerOutcome":
        return cls(STATUS_SUCCESS, dict(result), None)

    @classmethod
    def failure(cls, code: str, message: str) -> "HandlerOutcome":
        # schema 限制 error.message ≤160，超长整条会被 C 拒收
        return cls(STATUS_FAILED, None, {"code": code, "message": str(message)[:160]})

    @classmethod
    def cancelled(cls, message: str = "任务已取消") -> "HandlerOutcome":
        return cls(STATUS_CANCELLED, None, {"code": ERR_CANCELLED, "message": message})

    def to_payload(self) -> Dict[str, Any]:
        return {"status": self.status, "result": self.result, "error": self.error}


class CommandContext:
    """handler 拿到的上下文：命令本身 + 取消检查 + 截止时间。"""

    def __init__(
        self,
        command: Mapping[str, Any],
        client: HttpRefereeClient,
        *,
        clock: Callable[[], float] = time.monotonic,
        cancel_poll_interval: float = DEFAULT_CANCEL_POLL,
    ) -> None:
        self.command = dict(command)
        self._client = client
        self._clock = clock
        self._interval = cancel_poll_interval
        self._last_poll = 0.0
        self._cancelled = False
        self.started_at = clock()
        self.deadline = self.started_at + command["timeout_ms"] / 1000.0

    # -- 便捷属性 ----------------------------------------------------------

    @property
    def payload(self) -> Mapping[str, Any]:
        return self.command["payload"]

    @property
    def command_id(self) -> str:
        return self.command["command_id"]

    @property
    def command_type(self) -> str:
        return self.command["command_type"]

    @property
    def game_id(self) -> str:
        return self.command["game_id"]

    @property
    def input_epoch(self) -> int:
        return self.command["input_epoch"]

    @property
    def timeout_ms(self) -> int:
        return self.command["timeout_ms"]

    def remaining(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def expired(self) -> bool:
        return self._clock() >= self.deadline

    # -- 取消 --------------------------------------------------------------

    def cancel_state(self, *, force: bool = False) -> str:
        """返回 `"running"` / `"cancel_requested"` / `"expired"`。

        按规范每 250～500ms 查一次；`force=True` 立即查。
        """
        if self._clock() >= self.deadline:
            return "expired"
        now = self._clock()
        if not force and (now - self._last_poll) < self._interval:
            return "cancel_requested" if self._cancelled else "running"
        self._last_poll = now
        try:
            state = self._client.command_status(self.command_id)
        except RefereeHttpError:
            # 查不到不等于取消；按超时/本地状态继续
            return "cancel_requested" if self._cancelled else "running"
        if state.get("cancel_requested") or str(state.get("status")) in _TERMINAL:
            self._cancelled = True
            return "cancel_requested"
        return "running"

    def should_stop(self, *, force: bool = False) -> bool:
        return self.cancel_state(force=force) != "running"

    @property
    def cancelled(self) -> bool:
        return self._cancelled


Handler = Callable[[CommandContext], HandlerOutcome]


class CommandAgent:
    """A 的命令循环。"""

    def __init__(
        self,
        client: HttpRefereeClient,
        handlers: Mapping[str, Handler],
        *,
        source: str = SOURCE_A,
        module: Optional[str] = None,
        capabilities: Any = A_CAPABILITIES,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Optional[EventLog] = None,
        runtime_mode: str = "mock",
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
        cancel_poll_interval: float = DEFAULT_CANCEL_POLL,
    ) -> None:
        self._client = client
        self._handlers = dict(handlers)
        self._source = source
        self._module = module or source
        self._capabilities = tuple(capabilities)
        self._clock = clock
        self._sleep = sleep
        self._log = log
        self._runtime_mode = runtime_mode
        self._heartbeat_interval = heartbeat_interval
        self._cancel_poll = cancel_poll_interval

        self._done: set = set()
        self._active: Optional[str] = None
        self._last_heartbeat = 0.0
        self._heartbeat_error: Optional[str] = None
        self._stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    # -- 心跳 --------------------------------------------------------------

    def post_heartbeat(self, module_status: Optional[str] = None) -> Dict[str, Any]:
        # 只读一次快照，避免两次读取之间主线程改了 active，发出自相矛盾的心跳
        active_id = self._active
        status = module_status or ("busy" if active_id else "ready")
        event = build_heartbeat(
            instance_id=self._client.instance_id,
            source=self._source,
            module_status=status,
            active_command_ids=[active_id] if active_id else [],
            capabilities=self._capabilities,
            runtime_mode=self._runtime_mode,
        )
        response = self._client.post_event(event)
        self._last_heartbeat = self._clock()
        self._emit("heartbeat", result="ok", data={"status": status})
        return response

    def start_heartbeat(self) -> None:
        """长收音会阻塞主循环，心跳必须独立线程（6 秒无心跳即判离线）。"""
        if self._heartbeat_thread is not None:
            return
        self._stop.clear()

        def _loop() -> None:
            while not self._stop.is_set():
                try:
                    self.post_heartbeat()
                    self._report_heartbeat_problem(None)
                except RefereeHttpError as exc:
                    self._emit("heartbeat", result="failed", data={"code": exc.code})
                    self._report_heartbeat_problem(exc)
                self._stop.wait(self._heartbeat_interval)

        self._heartbeat_thread = threading.Thread(target=_loop, name="heartbeat", daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        self._heartbeat_thread = None

    def _report_heartbeat_problem(self, exc: Optional[RefereeHttpError]) -> None:
        """心跳失败时在终端留一句话。

        只看 JSONL 日志的话，进程看起来「正常在跑」，其实一个命令都拉不到。
        同一个错误只报一次，恢复时再说一句。
        """
        code = exc.code if exc is not None else None
        if code == self._heartbeat_error:
            return
        self._heartbeat_error = code
        if exc is None:
            print("[A] 心跳已恢复，模块重新在线", flush=True)
            return
        hint = ""
        if exc.code == "MODULE_CONFLICT":
            hint = (
                "（同角色已有实例注册着，通常是上次进程残留；"
                "需要 C 重启裁判服务，本进程会自动重试，不用重启）"
            )
        elif exc.status == 401:
            hint = "（令牌不是服务当前使用的那个）"
        print(f"[A] 心跳失败 {exc.code}{hint}，继续重试", flush=True)

    # -- 主循环 ------------------------------------------------------------

    def run_once(self, *, wait_ms: int = 1000) -> Optional[str]:
        """拉一条命令并处理。返回命令编号；没拉到返回 None。"""
        command = self._client.pull_command(module=self._module, lane="main", wait_ms=wait_ms)
        if command is None:
            return None
        return command["command_id"] if self.handle(command) else None

    def run_forever(self, *, poll_ms: int = 250) -> None:
        self.start_heartbeat()
        try:
            while not self._stop.is_set():
                self.run_once(wait_ms=1000)
                self._sleep(max(0.05, poll_ms / 1000.0))
        finally:
            self.stop_heartbeat()

    # -- 单条命令 ----------------------------------------------------------

    def handle(self, command: Mapping[str, Any]) -> bool:
        """执行一条已校验的命令。返回是否真正跑过（重复/拒绝返回 False）。"""
        command_id = command["command_id"]

        if command_id in self._done:
            self._emit("command.duplicate", request_id=command_id, result="skipped")
            return False
        if self._active is not None:
            self._emit("command.busy", request_id=command_id, result="skipped")
            return False

        handler = self._handlers.get(command["command_type"])

        # ① accepted —— C 拒绝就不能开始执行
        if not self._post(command, EVENT_TASK_ACCEPTED, {}):
            self._emit("command.accepted", request_id=command_id, result="rejected")
            self._done.add(command_id)
            return False

        # ② 执行前再查一次状态：已取消/过期就不动硬件
        try:
            state = self._client.command_status(command_id)
        except RefereeHttpError:
            state = {}
        if state.get("cancel_requested") or str(state.get("status")) in _TERMINAL:
            self._post_result(command, HandlerOutcome.cancelled())
            self._done.add(command_id)
            self._emit("command.cancelled", request_id=command_id, result="cancelled")
            return False

        if handler is None:
            self._post_result(command, HandlerOutcome.failure(ERR_INTERNAL, f"未注册的命令类型 {command['command_type']}"))
            self._done.add(command_id)
            return False

        # ③ started 之后才能执行
        if not self._post(command, EVENT_TASK_STARTED, {}):
            self._done.add(command_id)
            return False

        self._active = command_id
        context = CommandContext(
            command, self._client, clock=self._clock, cancel_poll_interval=self._cancel_poll
        )
        try:
            outcome = handler(context)
        except Exception as exc:  # handler 不能让整个循环挂掉
            outcome = HandlerOutcome.failure(ERR_INTERNAL, f"{type(exc).__name__}: {exc}")
        finally:
            self._active = None

        # ④ 结果
        self._post_result(command, outcome)
        self._done.add(command_id)
        self._emit(
            "command.result",
            request_id=command_id,
            result=outcome.status,
            data={"type": command["command_type"]},
        )
        return True

    # -- 内部 --------------------------------------------------------------

    def _post(self, command: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]) -> bool:
        event = build_event(
            request_id=new_id(),
            game_id=command["game_id"],
            input_epoch=command["input_epoch"],
            source=self._source,
            command_id=command["command_id"],
            event_type=event_type,
            payload=payload,
        )
        try:
            response = self._client.post_event(event)
        except RefereeHttpError as exc:
            self._emit("event.failed", request_id=command["command_id"], result="failed",
                       data={"event": event_type, "code": exc.code})
            return False
        return bool(response.get("ok"))

    def _post_result(self, command: Mapping[str, Any], outcome: HandlerOutcome) -> None:
        self._post(command, EVENT_TASK_RESULT, outcome.to_payload())

    def _emit(self, event: str, *, request_id: Optional[str] = None, result: str = "ok",
              data: Optional[Dict[str, Any]] = None) -> None:
        if self._log is not None:
            self._log.emit(event, request_id=request_id, result=result, data=data)


__all__ = [
    "CommandAgent",
    "CommandContext",
    "HandlerOutcome",
]
