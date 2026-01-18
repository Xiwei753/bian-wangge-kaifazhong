#主要用来长久和断续运行，管理止盈，防止委托单过多和时间过长的止盈单被交易所撤单
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional


@dataclass
class TakeProfitRecord:
    order_id: int
    price: float
    entry_side: str
    tp_side: str
    created_at: int


class TakeProfitRegistry:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or Path(__file__).with_name("zhiying_records.json")
        self._lock = threading.Lock()
        self._records: Dict[int, TakeProfitRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("records", [])
        else:
            return
        for item in items:
            try:
                record = TakeProfitRecord(
                    order_id=int(item["order_id"]),
                    price=float(item["price"]),
                    entry_side=str(item["entry_side"]),
                    tp_side=str(item["tp_side"]),
                    created_at=int(item.get("created_at") or 0),
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._records[record.order_id] = record

    def _save(self) -> None:
        data: List[dict] = [asdict(record) for record in self._records.values()]
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_record(self, order_id: int, price: float, entry_side: str, tp_side: str) -> None:
        with self._lock:
            self._records[order_id] = TakeProfitRecord(
                order_id=order_id,
                price=price,
                entry_side=entry_side,
                tp_side=tp_side,
                created_at=int(time.time() * 1000),
            )
            self._save()

    def remove_record(self, order_id: int) -> None:
        with self._lock:
            if order_id in self._records:
                self._records.pop(order_id, None)
                self._save()

    def has_record(self, order_id: int) -> bool:
        with self._lock:
            return order_id in self._records

    def list_records(self) -> List[TakeProfitRecord]:
        with self._lock:
            return list(self._records.values())
