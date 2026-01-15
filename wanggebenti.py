#网格本体，包括动态网格和其他文件发送来过来的下单指令，防止好几个文件同时下单冲突
#然后把下单指令发送给binance sdk.py文件
#所有的多单的开仓和空单的平仓是一个算法，所有的空单的开仓和多单的平仓是一个算法。所有文件都是一样的

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Dict, Optional
import importlib.util
import time

from peizhi import GridConfig


def _load_sdk_module():
    sdk_path = Path(__file__).with_name("binance_sdk.py")
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
        self.logger = logging.getLogger(self.__class__.__name__)
        self.client = sdk.create_um_client(
            api_key=config.get_api_key(),
            api_secret=config.get_api_secret(),
            base_url=config.get_um_base_url(),
            timeout=config.request_timeout,
        )
        self.state = GridOrderState()

    def _get_current_price(self) -> float:
        result = sdk.get_ticker_price(self.client, self.config.symbol)
        if not result["ok"]:
            raise RuntimeError(f"获取价格失败: {result}")
        return float(result["data"]["price"])

    def _get_open_step_ratio(self, side: str) -> float:
        if side == "BUY":
            return self.config.long_open_short_tp_step_ratio
        return self.config.short_open_long_tp_step_ratio

    def _get_take_profit_step_ratio(self, entry_side: str) -> float:
        if entry_side == "BUY":
            return self.config.short_open_long_tp_step_ratio
        return self.config.long_open_short_tp_step_ratio

    def _calc_grid_prices(self, center_price: float) -> Dict[str, float]:
        buy_step = center_price * self._get_open_step_ratio("BUY")
        sell_step = center_price * self._get_open_step_ratio("SELL")
        return {"buy": center_price - buy_step, "sell": center_price + sell_step}

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
        self.logger.info(
            "开仓挂单完成 center=%.4f buy_id=%s sell_id=%s buy_price=%.4f sell_price=%.4f",
            center_price,
            self.state.buy_order_id,
            self.state.sell_order_id,
            prices["buy"],
            prices["sell"],
        )

    def _place_take_profit(self, side: str, entry_price: float) -> None:
        step = entry_price * self._get_take_profit_step_ratio(side)
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
        self.logger.info(
            "止盈单已下达 entry_side=%s tp_side=%s tp_price=%.4f order=%s",
            side,
            tp_side,
            tp_price,
            result["data"],
        )

    def initialize(self) -> None:
        center_price = self._get_current_price()
        self._place_opening_orders(center_price)

    def _cancel_opposite(self, order_id: Optional[int]) -> None:
        if order_id is None:
            return
        result = sdk.cancel_order(self.client, symbol=self.config.symbol, order_id=order_id)
        if not result["ok"]:
            self.logger.warning("撤单失败 order_id=%s result=%s", order_id, result)
            return
        self.logger.info("撤单完成 order_id=%s result=%s", order_id, result["data"])

    def _handle_filled_order(self, order_id: int, side: str, price: float) -> None:
        self.logger.info("成交 order_id=%s side=%s price=%.4f", order_id, side, price)
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


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


if __name__ == "__main__":
    try:
        _setup_logging()
        print("正在启动网格策略...")
        run_grid_loop()
    except KeyboardInterrupt:
        print("程序已停止。")
    except Exception as e:
        logging.exception("网格策略运行失败")
        print(f"发生错误: {e}")
