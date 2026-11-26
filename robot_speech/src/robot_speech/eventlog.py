"""JSONL 事件日志：一次运行 = 一个文件，一个事件 = 一行。

目的很单一：下次上机时，**只看日志就能判断**问题出在播报、开窗、识别回传还是裁判响应。

字段约定（每行都有）：

| 字段 | 含义 |
| --- | --- |
| `seq` | 自增序号，判断顺序 |
| `ts` | 单调时钟读数（秒），**不能跨进程比较**；进程启动时间另记一条 |
| `event` | 事件名，如 `speak.result` / `window.open` / `input.stale` |
| `session` | 本次运行的标签 |
| `game_id` | 局号 |
| `turn` | 第几轮对话，从 1 开始 |
| `result` | 该事件的结局（`ok` / `failed` / `stale` …） |
| `request_id` | 相关请求编号（有则记） |
| `window` | 本次开窗身份（有则记） |
| `pending` | C 的待确认项身份（有则记） |
| `data` | 事件附加信息 |
| `text` | **默认不记**；只有显式开启才写原始语音/播报文本 |

为什么用单调时钟：耗时计算不受系统时间调整影响。代价是它不能跨进程比较，
所以第一行会记录一个墙钟时间戳作为锚点。

隐私：默认只记意图和状态，不记玩家说了什么。需要复现问题时用 `include_text=True`
显式打开，并注意日志文件不要提交进仓库。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, TextIO


class EventLog:
    """把事件写成 JSONL。

    `stream` 为 None 时只在内存里累积（测试和离线分析用）。
    """

    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        session: str = "session",
        include_text: bool = False,
        clock=time.monotonic,
    ) -> None:
        self._stream = stream
        self._session = session
        self._include_text = include_text
        self._clock = clock
        self._seq = 0
        self._turn = 0
        self._game_id: Optional[str] = None
        self.records: List[Dict[str, Any]] = []

    # -- 上下文 ------------------------------------------------------------

    def bind_game(self, game_id: str) -> None:
        self._game_id = game_id

    def set_turn(self, turn: int) -> None:
        self._turn = turn

    @property
    def include_text(self) -> bool:
        return self._include_text

    @property
    def records_readonly(self) -> List[Dict[str, Any]]:
        return list(self.records)

    # -- 写入 --------------------------------------------------------------

    def emit(
        self,
        event: str,
        *,
        result: str = "ok",
        request_id: Optional[str] = None,
        window: Optional[str] = None,
        pending: Optional[str] = None,
        text: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._seq += 1
        record: Dict[str, Any] = {
            "seq": self._seq,
            "ts": round(self._clock(), 6),
            "event": event,
            "session": self._session,
            "game_id": self._game_id,
            "turn": self._turn,
            "result": result,
        }
        if request_id:
            record["request_id"] = request_id
        if window:
            record["window"] = window
        if pending:
            record["pending"] = pending
        if self._include_text and text is not None:
            record["text"] = text
        if data:
            record["data"] = dict(data)

        self.records.append(record)

        if self._stream is not None:
            self._stream.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")
            self._stream.flush()

        return record

    def anchor(self, wall_time: Optional[float] = None) -> Dict[str, Any]:
        """记一条墙钟锚点，方便把单调时钟换算成可读时间。"""
        return self.emit(
            "log.anchor",
            data={
                "wall": time.time() if wall_time is None else wall_time,
                "mono_now": round(self._clock(), 6),
            },
        )

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.flush()
            finally:
                self._stream.close()
                self._stream = None


__all__ = ["EventLog"]
