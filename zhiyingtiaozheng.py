# 趋势市止盈调整逻辑
from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Dict, List, Optional, Tuple

import binance_sdk as sdk
from binance.um_futures import UMFutures
from peizhi import GridConfig, MarketMode
from zhiyingguanli import LifecycleManager, LifecycleRecord


@dataclass
class TpAdjustmentResult:
    parent_order_id: int
    old_tp_order_id: int
    new_tp_order_id: Optional[int]
    old_tp_price: float
    new_tp_price: float
    skipped_reason: Optional[str] = None


class TrendTakeProfitAdjuster:
    def __init__(
        self,
        client: UMFutures,
        config: GridConfig,
        lifecycle_manager: LifecycleManager,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.client = client
        self.config = config
        self.lifecycle_manager = lifecycle_manager
        self.logger = logger or logging.getLogger(self.__class__.__name__)

    def adjust_take_profit_for_trend(
        self,
        current_price: float,
        long_step_ratio: float,
        short_step_ratio: float,
    ) -> List[TpAdjustmentResult]:
        if self.config.market_mode != MarketMode.TREND:
            self.logger.debug("非趋势市，跳过止盈调整")
            return []

        results: List[TpAdjustmentResult] = []
        try:
            self.lifecycle_manager.reload_from_disk()
            grid_records = self._collect_grid_records(current_price)
            tp_records = self._index_tp_records()
        except Exception as exc:
            self.logger.exception("加载本地止盈记录失败: %s", exc)
            return results

        for grid_record in grid_records:
            tp_record: Optional[LifecycleRecord] = None
            try:
                tp_record = tp_records.get(grid_record.order_id)
                if tp_record is None:
                    continue
                target_price = self._calculate_tp_price(
                    entry_price=grid_record.price,
                    entry_side=grid_record.entry_side,
                    long_step_ratio=long_step_ratio,
                    short_step_ratio=short_step_ratio,
                )
                if not self._should_move_tp(tp_record.price, target_price, current_price):
                    results.append(
                        TpAdjustmentResult(
                            parent_order_id=grid_record.order_id,
                            old_tp_order_id=tp_record.order_id,
                            new_tp_order_id=None,
                            old_tp_price=tp_record.price,
                            new_tp_price=target_price,
                            skipped_reason="移动幅度不足0.1%",
                        )
                    )
                    continue
                result = self._replace_tp_order(grid_record, tp_record, target_price)
                results.append(result)
            except Exception as exc:
                self.logger.exception(
                    "止盈调整异常 parent_id=%s error=%s", grid_record.order_id, exc
                )
                results.append(
                    TpAdjustmentResult(
                        parent_order_id=grid_record.order_id,
                        old_tp_order_id=tp_record.order_id if tp_record else 0,
                        new_tp_order_id=None,
                        old_tp_price=tp_record.price if tp_record else 0.0,
                        new_tp_price=grid_record.price,
                        skipped_reason="止盈调整异常",
                    )
                )

        return results

    def _collect_grid_records(self, current_price: float) -> List[LifecycleRecord]:
        lower = current_price * (1 - self.config.position_adjustment_range)
        upper = current_price * (1 + self.config.position_adjustment_range)
        records = []
        for record in self.lifecycle_manager.list_records():
            if record.type != "GRID" or record.status != "FILLED":
                continue
            if record.entry_side not in ("BUY", "SELL"):
                continue
            if record.price < lower or record.price > upper:
                continue
            records.append(record)
        return records

    def _index_tp_records(self) -> Dict[int, LifecycleRecord]:
        mapping: Dict[int, LifecycleRecord] = {}
        for record in self.lifecycle_manager.list_tp_records():
            if record.parent_id is None:
                continue
            mapping[record.parent_id] = record
        return mapping

    def _calculate_tp_price(
        self,
        entry_price: float,
        entry_side: Optional[str],
        long_step_ratio: float,
        short_step_ratio: float,
    ) -> float:
        min_profit_ratio = 0.001
        if entry_side == "BUY":
            step_ratio = max(long_step_ratio, min_profit_ratio)
            target = entry_price + entry_price * step_ratio
        else:
            step_ratio = max(short_step_ratio, min_profit_ratio)
            target = entry_price - entry_price * step_ratio
        return self._round_price(target)

    def _should_move_tp(
        self, current_tp_price: float, target_tp_price: float, current_price: float
    ) -> bool:
        if current_price <= 0:
            return False
        move_ratio = abs(target_tp_price - current_tp_price) / current_price
        return move_ratio >= 0.001

    def _round_price(self, value: float) -> float:
        return round(value, 1)

    def _replace_tp_order(
        self,
        grid_record: LifecycleRecord,
        tp_record: LifecycleRecord,
        target_price: float,
    ) -> TpAdjustmentResult:
        order_info = sdk.get_order(
            self.client, symbol=self.config.symbol, order_id=tp_record.order_id
        )
        if not order_info.get("ok"):
            self.logger.warning("查询止盈单失败 order_id=%s info=%s", tp_record.order_id, order_info)
            return TpAdjustmentResult(
                parent_order_id=grid_record.order_id,
                old_tp_order_id=tp_record.order_id,
                new_tp_order_id=None,
                old_tp_price=tp_record.price,
                new_tp_price=target_price,
                skipped_reason="查询止盈单失败",
            )
        data = order_info.get("data") or {}
        quantity = float(data.get("origQty") or 0)
        if quantity <= 0:
            return TpAdjustmentResult(
                parent_order_id=grid_record.order_id,
                old_tp_order_id=tp_record.order_id,
                new_tp_order_id=None,
                old_tp_price=tp_record.price,
                new_tp_price=target_price,
                skipped_reason="止盈数量为空",
            )
        cancel_result = sdk.cancel_order(
            self.client, symbol=self.config.symbol, order_id=tp_record.order_id
        )
        if not cancel_result.get("ok"):
            self.logger.warning("撤销止盈单失败 order_id=%s result=%s", tp_record.order_id, cancel_result)
            return TpAdjustmentResult(
                parent_order_id=grid_record.order_id,
                old_tp_order_id=tp_record.order_id,
                new_tp_order_id=None,
                old_tp_price=tp_record.price,
                new_tp_price=target_price,
                skipped_reason="撤销止盈单失败",
            )

        tp_side, position_side = self._resolve_tp_side(grid_record.entry_side)
        client_order_id = self._build_client_order_id(grid_record.order_id)
        new_order = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=round(quantity, 2),
            price=target_price,
            time_in_force="GTC",
            position_side=position_side,
            client_order_id=client_order_id,
        )
        if not new_order.get("ok"):
            self.logger.warning("新止盈单下单失败 parent_id=%s result=%s", grid_record.order_id, new_order)
            return TpAdjustmentResult(
                parent_order_id=grid_record.order_id,
                old_tp_order_id=tp_record.order_id,
                new_tp_order_id=None,
                old_tp_price=tp_record.price,
                new_tp_price=target_price,
                skipped_reason="新止盈单下单失败",
            )

        new_order_id = int(new_order["data"]["orderId"])
        self.lifecycle_manager.remove_record(tp_record.order_id)
        self.lifecycle_manager.add_tp(
            order_id=new_order_id,
            price=target_price,
            parent_id=grid_record.order_id,
            entry_side=grid_record.entry_side,
            tp_side=tp_side,
            status="NEW",
        )
        self.logger.info(
            "止盈单调整完成 parent=%s old=%s new=%s price=%.4f",
            grid_record.order_id,
            tp_record.order_id,
            new_order_id,
            target_price,
        )
        return TpAdjustmentResult(
            parent_order_id=grid_record.order_id,
            old_tp_order_id=tp_record.order_id,
            new_tp_order_id=new_order_id,
            old_tp_price=tp_record.price,
            new_tp_price=target_price,
        )

    def _resolve_tp_side(self, entry_side: Optional[str]) -> Tuple[str, str]:
        if entry_side == "BUY":
            return "SELL", "LONG"
        return "BUY", "SHORT"

    def _build_client_order_id(self, parent_order_id: int) -> str:
        suffix = int(time.time() * 1000) % 100000
        client_id = f"tpadj{parent_order_id}{suffix}"
        return client_id[:32]
