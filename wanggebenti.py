#网格本体，包括动态网格和其他文件发送来过来的下单指令，防止好几个文件同时下单冲突
#然后把下单指令发送给binance sdk.py文件
#所有的多单的开仓和空单的平仓是一个算法，所有的空单的开仓和多单的平仓是一个算法。所有文件都是一样的

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Dict, Optional
import importlib.util
import threading
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
    last_entry_price: Dict[str, Optional[float]] = field(
        default_factory=lambda: {"BUY": None, "SELL": None}
    )
    last_entry_quantity: Dict[str, Optional[float]] = field(
        default_factory=lambda: {"BUY": None, "SELL": None}
    )
    tp_order_id: Dict[str, Optional[int]] = field(
        default_factory=lambda: {"BUY": None, "SELL": None}
    )


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
        self.stop_event = threading.Event()

    def _round_price(self, value: float) -> float:
        return round(value, 1)

    def _round_quantity(self, value: float) -> float:
        return round(value, 2)

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
        order_size = self._round_quantity(self.config.fixed_order_size)
        
        # === 修复：添加 position_side 参数以支持双向持仓 ===
        buy = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=order_size,
            price=self._round_price(prices["buy"]),
            time_in_force="GTC",
            position_side="LONG"  # 开多单属于 LONG 方向
        )
        
        sell = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side="SELL",
            order_type="LIMIT",
            quantity=order_size,
            price=self._round_price(prices["sell"]),
            time_in_force="GTC",
            position_side="SHORT" # 开空单属于 SHORT 方向
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
            self._round_price(prices["buy"]),
            self._round_price(prices["sell"]),
        )

    def _place_take_profit(self, side: str, entry_price: float, quantity: float) -> int:
        step = entry_price * self._get_take_profit_step_ratio(side)
        
        # === 修复：根据持仓方向确定 position_side ===
        if side == "BUY":
            # 之前是开多(BUY)，现在要平多，操作是卖(SELL)，持仓方向是 LONG
            tp_price = entry_price + step
            tp_side = "SELL"
            pos_side = "LONG"
        else:
            # 之前是开空(SELL)，现在要平空，操作是买(BUY)，持仓方向是 SHORT
            tp_price = entry_price - step
            tp_side = "BUY"
            pos_side = "SHORT"
            
        order_size = self._round_quantity(quantity)
        tp_price = self._round_price(tp_price)
        
        result = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=order_size,
            price=tp_price,
            time_in_force="GTC",
            reduce_only=True, # 依然保持只减仓
            position_side=pos_side # 必须指定方向
        )
        
        if not result["ok"]:
            raise RuntimeError(f"止盈单下单失败: {result}")
        order_id = int(result["data"]["orderId"])
        self.logger.info(
            "止盈单已下达 entry_side=%s tp_side=%s tp_price=%.4f qty=%.2f order=%s",
            side,
            tp_side,
            tp_price,
            order_size,
            result["data"],
        )
        return order_id

    def initialize(self) -> None:
        self.logger.info("正在初始化策略...")
        
        # === 新增：确保账户处于双向持仓模式 ===
        try:
            # 尝试设置为双向持仓 (True)
            # 如果已经是双向持仓，API可能会报错 "No need to change position side."，这是正常的，可以忽略
            res = sdk.change_position_mode(self.client, dual_side=True)
            if not res['ok'] and res.get('status_code') != 400: 
                # 400 通常意味着“不需要修改”，其他错误才打印警告
                self.logger.warning(f"设置持仓模式警告: {res}")
        except Exception as e:
            self.logger.warning(f"设置持仓模式异常 (如果是 'No need to change' 可忽略): {e}")

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

    def _handle_filled_order(self, order_id: int, side: str, price: float, quantity: float) -> None:
        self.logger.info(
            "成交 order_id=%s side=%s price=%.4f qty=%.4f", order_id, side, price, quantity
        )
        self.state.last_entry_price[side] = price
        self.state.last_entry_quantity[side] = quantity
        self.state.tp_order_id[side] = None 
        
        if side == "BUY":
            self._cancel_opposite(self.state.sell_order_id)
        else:
            self._cancel_opposite(self.state.buy_order_id)
        self._place_opening_orders(price)

    def handle_ws_fill(self, order_id: int, side: str, price: float, quantity: float) -> None:
        if quantity <= 0:
            return
        self.logger.info(
            "WS成交 order_id=%s side=%s price=%.4f qty=%.4f",
            order_id,
            side,
            price,
            quantity,
        )
        self.state.last_entry_price[side] = price
        self.state.last_entry_quantity[side] = quantity
        self.state.tp_order_id[side] = self._place_take_profit(
            side=side, entry_price=price, quantity=quantity
        )

    def _ensure_take_profit_orders(self, open_ids: set[int]) -> None:
        for side in ("BUY", "SELL"):
            entry_price = self.state.last_entry_price.get(side)
            entry_qty = self.state.last_entry_quantity.get(side)
            
            if not entry_price or not entry_qty:
                continue
                
            tp_order_id = self.state.tp_order_id.get(side)
            
            if tp_order_id and tp_order_id in open_ids:
                continue
            
            if tp_order_id:
                tp_order = sdk.get_order(
                    self.client, symbol=self.config.symbol, order_id=tp_order_id
                )
                if tp_order["ok"] and tp_order["data"].get("status") == "FILLED":
                    continue
                self.state.tp_order_id[side] = None
            
            self.logger.info(
                "检测到止盈单缺失 entry_side=%s entry_price=%.4f qty=%.4f，重新下单",
                side,
                entry_price,
                entry_qty,
            )
            self.state.tp_order_id[side] = self._place_take_profit(
                side=side, entry_price=entry_price, quantity=entry_qty
            )

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
                fill_qty = float(order["data"].get("executedQty") or 0)
                self._handle_filled_order(order_id, side, fill_price, fill_qty)
        
        self._ensure_take_profit_orders(open_ids)

    def run_order_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.sync_once()
            except Exception:
                self.logger.exception("主线程下单/撤单循环异常")
            time.sleep(self.config.check_interval)

    def stop(self) -> None:
        self.stop_event.set()


def _run_depth_ws(config: GridConfig, stop_event: threading.Event) -> None:
    logger = logging.getLogger("DepthWS")

    def on_message(_: sdk.websocket.WebSocketApp, message: str) -> None:
        logger.debug("收到盘口消息长度=%s", len(message))

    def on_error(_: sdk.websocket.WebSocketApp, error: Exception) -> None:
        logger.error("盘口 WS 错误: %s", error)

    def on_close(_: sdk.websocket.WebSocketApp, status_code: int, msg: str) -> None:
        logger.warning("盘口 WS 关闭 code=%s msg=%s", status_code, msg)

    def on_open(_: sdk.websocket.WebSocketApp) -> None:
        logger.info("盘口 WS 已连接")

    ws_app = sdk.subscribe_depth_ws(
        symbol=config.symbol,
        on_message=on_message,
        depth_level=10,
        speed_ms=100,
        use_testnet=config.use_testnet,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    while not stop_event.is_set():
        ws_app.run_forever(ping_interval=20, ping_timeout=10)
        if stop_event.is_set():
            break
        logger.warning("盘口 WS 断开，5秒后重连")
        time.sleep(5)
    ws_app.close()


def _handle_user_data_message(
    engine: GridEngine, logger: logging.Logger, message: str
) -> None:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        logger.warning("用户数据流消息解析失败: %s", message)
        return
    event_type = payload.get("e")
    if event_type == "ORDER_TRADE_UPDATE":
        order = payload.get("o", {})
        exec_type = order.get("x")
        last_qty = float(order.get("l") or 0)
        avg_price = float(order.get("ap") or 0)
        logger.info(
            "订单更新 order_id=%s symbol=%s side=%s status=%s exec_type=%s avg_price=%s last_qty=%s",
            order.get("i"),
            order.get("s"),
            order.get("S"),
            order.get("X"),
            exec_type,
            avg_price,
            last_qty,
        )
        if exec_type == "TRADE" and last_qty > 0 and avg_price > 0:
            engine.handle_ws_fill(
                order_id=int(order.get("i")),
                side=str(order.get("S")),
                price=avg_price,
                quantity=last_qty,
            )
    else:
        logger.debug("用户数据流事件=%s payload=%s", event_type, payload)


def _run_user_data_ws(
    engine: GridEngine,
    stop_event: threading.Event,
) -> None:
    logger = logging.getLogger("UserDataWS")

    def on_message(_: sdk.websocket.WebSocketApp, message: str) -> None:
        _handle_user_data_message(engine, logger, message)

    def on_error(_: sdk.websocket.WebSocketApp, error: Exception) -> None:
        logger.error("用户数据 WS 错误: %s", error)

    def on_close(_: sdk.websocket.WebSocketApp, status_code: int, msg: str) -> None:
        logger.warning("用户数据 WS 关闭 code=%s msg=%s", status_code, msg)

    def on_open(_: sdk.websocket.WebSocketApp) -> None:
        logger.info("用户数据 WS 已连接")

    while not stop_event.is_set():
        listen_key_result = sdk.new_listen_key(engine.client)
        if not listen_key_result["ok"]:
            logger.error("获取 listenKey 失败: %s", listen_key_result)
            time.sleep(5)
            continue
        listen_key = listen_key_result["data"].get("listenKey")
        if not listen_key:
            logger.error("listenKey 为空: %s", listen_key_result)
            time.sleep(5)
            continue
        ws_app = sdk.subscribe_user_data_ws(
            listen_key=listen_key,
            on_message=on_message,
            use_testnet=engine.config.use_testnet,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        ws_app.run_forever(ping_interval=20, ping_timeout=10)
        if stop_event.is_set():
            break
        logger.warning("用户数据 WS 断开，5秒后重连")
        time.sleep(5)

    if "listen_key" in locals():
        sdk.close_listen_key(engine.client, listen_key)


def run_grid_loop() -> None:
    config = GridConfig()
    engine = GridEngine(config)
    engine.initialize()
    depth_thread = threading.Thread(
        target=_run_depth_ws,
        args=(config, engine.stop_event),
        name="DepthWS",
        daemon=True,
    )
    user_data_thread = threading.Thread(
        target=_run_user_data_ws,
        args=(engine, engine.stop_event),
        name="UserDataWS",
        daemon=True,
    )
    depth_thread.start()
    user_data_thread.start()
    engine.run_order_loop()


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
