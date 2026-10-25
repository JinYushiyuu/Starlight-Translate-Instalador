"""Executa funções em segundas threads e devolve o resultado na thread da interface."""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Relay(QObject):
    @Slot(object, str, object)
    def deliver(self, task, kind: str, payload) -> None:
        cb = getattr(task, "cb_" + kind, None)
        if cb:
            cb(payload)


_relay: Optional[_Relay] = None
_alive: set = set()


class Task(QThread):
    sig = Signal(object, str, object)

    def __init__(self, fn: Callable[[Callable[[Any], None]], Any]):
        super().__init__()
        self._fn = fn
        self.cb_done = None
        self.cb_fail = None
        self.cb_progress = None

    def run(self) -> None:
        try:
            result = self._fn(lambda data: self.sig.emit(self, "progress", data))
        except BaseException as e:  # noqa: BLE001 - repassado para a interface
            self.sig.emit(self, "fail", e)
        else:
            self.sig.emit(self, "done", result)


def run_task(
    fn: Callable[[Callable[[Any], None]], Any],
    on_done: Optional[Callable[[Any], None]] = None,
    on_fail: Optional[Callable[[BaseException], None]] = None,
    on_progress: Optional[Callable[[Any], None]] = None,
) -> Task:
    """`fn` recebe uma função `emit(dado)` para reportar progresso."""
    global _relay
    if _relay is None:
        _relay = _Relay()
    t = Task(fn)
    t.cb_done, t.cb_fail, t.cb_progress = on_done, on_fail, on_progress
    t.sig.connect(_relay.deliver)
    _alive.add(t)
    t.finished.connect(lambda: _alive.discard(t))
    t.start()
    return t
