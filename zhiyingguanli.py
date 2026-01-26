#主要用来长久和断续运行，管理止盈，防止委托单过多和时间过长的止盈单被交易所撤单
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional


@dataclass
class LifecycleRecord:
    order_id: int
    type: str
    parent_id: Optional[int]
    status: str
    price: float
    entry_side: Optional[str] = None
    tp_side: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))


class LifecycleManager:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = storage_path or Path(__file__).with_name("zhiying_records.json")
        self._lock = threading.Lock()
        self._records: Dict[int, LifecycleRecord] = {}
        self._records = self._load_records()

    def _load_records(self) -> Dict[int, LifecycleRecord]:
        records: Dict[int, LifecycleRecord] = {}
        if not self.storage_path.exists():
            return records
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return records
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("records", [])
        else:
            return records
        for item in items:
            try:
                record = self._parse_record(item)
            except (KeyError, TypeError, ValueError):
                continue
            records[record.order_id] = record
        return records

    def reload_from_disk(self) -> None:
        with self._lock:
            self._records = self._load_records()

    def _parse_record(self, item: dict) -> LifecycleRecord:
        record_type = item.get("type")
        if record_type is None:
            record_type = "TP"
        return LifecycleRecord(
            order_id=int(item["order_id"]),
            type=str(record_type),
            parent_id=int(item["parent_id"]) if item.get("parent_id") is not None else None,
            status=str(item.get("status") or "NEW"),
            price=float(item["price"]),
            entry_side=str(item["entry_side"]) if item.get("entry_side") else None,
            tp_side=str(item["tp_side"]) if item.get("tp_side") else None,
            created_at=int(item.get("created_at") or 0),
        )

    def _save(self) -> None:
        data: List[dict] = [asdict(record) for record in self._records.values()]
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add_grid(
        self, order_id: int, price: float, entry_side: str, status: str = "FILLED"
    ) -> None:
        with self._lock:
            self._records[order_id] = LifecycleRecord(
                order_id=order_id,
                type="GRID",
                parent_id=None,
                status=status,
                price=price,
                entry_side=entry_side,
            )
            self._save()

    def add_tp(
        self,
        order_id: int,
        price: float,
        parent_id: Optional[int],
        entry_side: Optional[str],
        tp_side: Optional[str],
        status: str = "NEW",
    ) -> None:
        with self._lock:
            self._records[order_id] = LifecycleRecord(
                order_id=order_id,
                type="TP",
                parent_id=parent_id,
                status=status,
                price=price,
                entry_side=entry_side,
                tp_side=tp_side,
            )
            self._save()

    def remove_record(self, order_id: int) -> None:
        with self._lock:
            if order_id in self._records:
                self._records.pop(order_id, None)
                self._save()

    def update_status(self, order_id: int, status: str) -> None:
        with self._lock:
            record = self._records.get(order_id)
            if record:
                record.status = status
                self._save()

    def has_record(self, order_id: int) -> bool:
        with self._lock:
            return order_id in self._records

    def has_tp_record(self, order_id: int, status: Optional[str] = None) -> bool:
        with self._lock:
            record = self._records.get(order_id)
            if not record or record.type != "TP":
                return False
            if status is not None and record.status != status:
                return False
            return True

    def get_record(self, order_id: int) -> Optional[LifecycleRecord]:
        with self._lock:
            return self._records.get(order_id)

    def list_records(self) -> List[LifecycleRecord]:
        with self._lock:
            return list(self._records.values())

    def list_tp_records(self, status: Optional[str] = None) -> List[LifecycleRecord]:
        with self._lock:
            records = [record for record in self._records.values() if record.type == "TP"]
            if status is not None:
                records = [record for record in records if record.status == status]
            return records
