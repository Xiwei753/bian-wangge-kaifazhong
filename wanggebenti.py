#网格本体，包括动态网格和其他文件发送来过来的下单指令，防止好几个文件同时下单冲突
#然后把下单指令发送给binance sdk.py文件
#所有的多单的开仓和空单的平仓是一个算法，所有的空单的开仓和多单的平仓是一个算法。所有文件都是一样的

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
import importlib.util
import time

from peizhi import GridConfig


def _load_sdk_module():
    sdk_path = Path(__file__).with_name("binance sdk.py")
    spec = importlib.util.spec_from_file_location("binance_sdk", sdk_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 binance sdk.py 模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sdk = _load_sdk_module()


@dataclass
class GridOrderState:
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    last_center_price: Optional[float] = None


class GridEngine:
    def __init__(self, config: GridConfig):
        self.config = config
        self.client = sdk.create_um_client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self.state = GridOrderState()

    def _get_current_price(self) -> float:
        result = sdk.get_ticker_price(self.client, self.config.symbol)
        if not result["ok"]:
            raise RuntimeError(f"获取价格失败: {result}")
        return float(result["data"]["price"])

    def _calc_grid_prices(self, center_price: float) -> Dict[str, float]:
        step = center_price * self.config.grid_step_ratio
        return {"buy": center_price - step, "sell": center_price + step}

    def _place_opening_orders(self, center_price: float) -> None:
        prices = self._calc_grid_prices(center_price)
        buy = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=self.config.fixed_order_size,
            price=prices["buy"],
            time_in_force="GTC",
        )
        sell = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side="SELL",
            order_type="LIMIT",
            quantity=self.config.fixed_order_size,
            price=prices["sell"],
            time_in_force="GTC",
        )
        if not buy["ok"] or not sell["ok"]:
            raise RuntimeError(f"开仓单下单失败: buy={buy} sell={sell}")
        self.state.buy_order_id = int(buy["data"]["orderId"])
        self.state.sell_order_id = int(sell["data"]["orderId"])
        self.state.last_center_price = center_price

    def _place_take_profit(self, side: str, entry_price: float) -> None:
        step = entry_price * self.config.grid_step_ratio
        if side == "BUY":
            tp_price = entry_price + step
            tp_side = "SELL"
        else:
            tp_price = entry_price - step
            tp_side = "BUY"
        result = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=self.config.fixed_order_size,
            price=tp_price,
            time_in_force="GTC",
            reduce_only=True,
        )
        if not result["ok"]:
            raise RuntimeError(f"止盈单下单失败: {result}")

    def initialize(self) -> None:
        center_price = self._get_current_price()
        self._place_opening_orders(center_price)

    def _cancel_opposite(self, order_id: Optional[int]) -> None:
        if order_id is None:
            return
        sdk.cancel_order(self.client, symbol=self.config.symbol, order_id=order_id)

    def _handle_filled_order(self, order_id: int, side: str, price: float) -> None:
        self._place_take_profit(side=side, entry_price=price)
        if side == "BUY":
            self._cancel_opposite(self.state.sell_order_id)
        else:
            self._cancel_opposite(self.state.buy_order_id)
        self._place_opening_orders(price)

    def sync_once(self) -> None:
        open_orders = sdk.get_open_orders(self.client, symbol=self.config.symbol)
        if not open_orders["ok"]:
            raise RuntimeError(f"查询挂单失败: {open_orders}")
        open_ids = {int(o["orderId"]) for o in open_orders["data"]}
        for order_id, side in (
            (self.state.buy_order_id, "BUY"),
            (self.state.sell_order_id, "SELL"),
        ):
            if order_id is None or order_id in open_ids:
                continue
            order = sdk.get_order(self.client, symbol=self.config.symbol, order_id=order_id)
            if not order["ok"]:
                raise RuntimeError(f"查询订单失败: {order}")
            status = order["data"].get("status")
            if status == "FILLED":
                fill_price = float(order["data"].get("avgPrice") or order["data"].get("price"))
                self._handle_filled_order(order_id, side, fill_price)


def run_grid_loop() -> None:
    config = GridConfig()
    engine = GridEngine(config)
    engine.initialize()
    while True:
        engine.sync_once()
        time.sleep(config.check_interval)
