"""假的 C 调度服务（8780），给离线开发和测试用。

只实现 A 用到的那几个路径：health / state / commands/next / commands/<id> / events。
**不是 C 的实现**，也不代表业务规则；它存在的意义是让 A 的客户端能对着真 HTTP 跑。

用法：

    referee = FakeCReferee(token="t")
    base_url = referee.start()      # http://127.0.0.1:<随机端口>
    ...
    referee.stop()
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from robot_speech.team_protocol import (
    ENVELOPE_FIELDS,
    PROTOCOL_VERSION,
    new_id,
)

TERMINAL = ("cancelled", "expired", "succeeded", "failed")


class FakeCReferee:
    def __init__(self, *, token: str = "test-token", source: str = "A") -> None:
        self.token = token
        self.source = source
        self.instance_id = new_id()
        self.commands: List[Dict[str, Any]] = []
        self.by_id: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.cancelled: set = set()
        self.seen: Dict[Any, str] = {}
        self.rejected_accepts: set = set()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> str:
        referee = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # 安静
                return

            def do_GET(self) -> None:  # noqa: N802
                referee._handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                referee._handle_post(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.referee = referee  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # -- 造数据 ------------------------------------------------------------

    def enqueue(
        self,
        command_type: str,
        payload: Dict[str, Any],
        *,
        game_id: Optional[str] = None,
        input_epoch: int = 0,
        timeout_ms: int = 15000,
        target: str = "A",
    ) -> Dict[str, Any]:
        command = {
            "protocol_version": PROTOCOL_VERSION,
            "command_id": new_id(),
            "game_id": game_id or new_id(),
            "input_epoch": input_epoch,
            "target": target,
            "command_type": command_type,
            "timeout_ms": timeout_ms,
            "payload": payload,
        }
        self.commands.append(command)
        self.by_id[command["command_id"]] = command
        return command

    def request_cancel(self, command_id: str) -> None:
        self.cancelled.add(command_id)

    def results(self) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["event_type"] == "task.result"]

    def events_of(self, event_type: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["event_type"] == event_type]

    # -- 处理 --------------------------------------------------------------

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/v1/health":
            self._send(handler, 200, self._ok({"protocol_version": PROTOCOL_VERSION,
                                               "service_status": "ready",
                                               "server_instance_id": self.instance_id,
                                               "modules": {"A": "ready"}}))
            return

        if path == "/api/v1/state/public":
            self._send(handler, 200, self._ok({"state": {"phase": "idle", "game_id": None}}))
            return

        if path.startswith("/api/v1/modules/") and path.endswith("/commands/next"):
            if not self._authorized(handler):
                return
            command = self.commands.pop(0) if self.commands else None
            self._send(handler, 200, self._ok({"command": command}))
            return

        if path.startswith("/api/v1/commands/"):
            command_id = path.rsplit("/", 1)[-1]
            command = self.by_id.get(command_id)
            if command is None:
                self._send(handler, 404, self._error("NOT_FOUND", "命令不存在"))
                return
            self._send(handler, 200, self._ok({
                "command": {
                    "command_id": command_id,
                    "status": "cancelled" if command_id in self.cancelled else "queued",
                    "cancel_requested": command_id in self.cancelled,
                }
            }))
            return

        self._send(handler, 404, self._error("NOT_FOUND", f"未知路径 {path}"))

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        if urlparse(handler.path).path != "/api/v1/events":
            self._send(handler, 404, self._error("NOT_FOUND", "未知路径"))
            return
        if not self._authorized(handler):
            return

        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length)
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(handler, 400, self._error("BAD_REQUEST", "不是合法 JSON"))
            return

        if tuple(event) != ENVELOPE_FIELDS:
            self._send(handler, 400, self._error("BAD_REQUEST", "信封字段不符"))
            return

        if event["event_type"] == "task.accepted" and event["command_id"] in self.rejected_accepts:
            self._send(handler, 200, {"ok": False, "code": "COMMAND_NOT_RUNNABLE",
                                      "message": "任务不可运行", "replayed": False,
                                      "server_time": self._now(),
                                      "server_instance_id": self.instance_id,
                                      "data": {"disposition": "ignored_for_game", "command_status": "queued"}})
            return

        key = (event["source"], event["request_id"])
        fingerprint = json.dumps(event, sort_keys=True, ensure_ascii=False)
        replayed = False
        if key in self.seen:
            if self.seen[key] != fingerprint:
                self._send(handler, 409, self._error("REQUEST_CONFLICT", "同编号不同内容"))
                return
            replayed = True
        else:
            self.seen[key] = fingerprint
            self.events.append(event)

        self._send(handler, 200, {
            "ok": True,
            "code": "OK",
            "message": "事件已接收",
            "replayed": replayed,
            "server_time": self._now(),
            "server_instance_id": self.instance_id,
            "data": {"disposition": "recorded", "command_status": "running"},
        })

    # -- 工具 --------------------------------------------------------------

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        header = handler.headers.get("Authorization") or ""
        if header != f"Bearer {self.token}":
            self._send(handler, 401, self._error("UNAUTHORIZED", "令牌无效"))
            return False
        if not handler.headers.get("X-Roban-Instance"):
            self._send(handler, 400, self._error("BAD_REQUEST", "缺少 X-Roban-Instance"))
            return False
        return True

    def _ok(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "code": "OK", "message": "", "replayed": False,
                "server_time": self._now(), "server_instance_id": self.instance_id, "data": data}

    def _error(self, code: str, message: str) -> Dict[str, Any]:
        return {"ok": False, "code": code, "message": message, "replayed": False,
                "server_time": self._now(), "server_instance_id": self.instance_id, "data": {}}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def _send(self, handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


__all__ = ["FakeCReferee"]
