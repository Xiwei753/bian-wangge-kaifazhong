#网格本体，包括动态网格和其他文件发送来过来的下单指令，防止好几个文件同时下单冲突
#然后把下单指令发送给binance sdk.py文件
#所有的多单的开仓和空单的平仓是一个算法，所有的空单的开仓和多单的平仓是一个算法。所有文件都是一样的

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import importlib.util
import threading
import time

from peizhi import GridConfig
from zhiyingguanli import TakeProfitRegistry


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
    last_filled_side: Optional[str] = None
    # 新增：记录最后成交的时间戳 (毫秒)
    last_fill_time: Dict[str, int] = field(
        default_factory=lambda: {"BUY": 0, "SELL": 0}
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
        self.tp_registry = TakeProfitRegistry()
        self.stop_event = threading.Event()
        self.polling_active = False

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

    def _decide_grid_steps(self, center_price: float) -> Tuple[Optional[float], Optional[float]]:
        default_buy_step = center_price * self._get_open_step_ratio("BUY")
        default_sell_step = center_price * self._get_open_step_ratio("SELL")

        current_score = 0.5 
        threshold = 0.7
        current_direction = "UP" 

        if current_score < threshold:
            return default_buy_step, default_sell_step
        else:
            if current_direction == "UP":
                return default_buy_step, None
            else:
                return None, default_sell_step

    def _place_opening_orders(self, center_price: float) -> None:
        buy_step, sell_step = self._decide_grid_steps(center_price)
        order_size = self._round_quantity(self.config.fixed_order_size)
        self.state.last_center_price = self._round_price(center_price)
        
        if buy_step is not None:
            buy_price = center_price - buy_step
            buy = sdk.new_order(
                self.client,
                symbol=self.config.symbol,
                side="BUY",
                order_type="LIMIT",
                quantity=order_size,
                price=self._round_price(buy_price),
                time_in_force="GTC",
                position_side="LONG"
            )
            if buy["ok"]:
                self.state.buy_order_id = int(buy["data"]["orderId"])
                self.logger.info(f"挂买单成功: 价格 {self._round_price(buy_price)}")
            else:
                self.logger.error(f"挂买单失败: {buy}")
        else:
            self.state.buy_order_id = None

        if sell_step is not None:
            sell_price = center_price + sell_step
            sell = sdk.new_order(
                self.client,
                symbol=self.config.symbol,
                side="SELL",
                order_type="LIMIT",
                quantity=order_size,
                price=self._round_price(sell_price),
                time_in_force="GTC",
                position_side="SHORT"
            )
            if sell["ok"]:
                self.state.sell_order_id = int(sell["data"]["orderId"])
                self.logger.info(f"挂卖单成功: 价格 {self._round_price(sell_price)}")
            else:
                self.logger.error(f"挂卖单失败: {sell}")
        else:
            self.state.sell_order_id = None

    def _get_position_amount(self, position_side: str) -> float:
        res = sdk.get_position_risk(self.client, symbol=self.config.symbol)
        if not res["ok"]:
            self.logger.warning(f"查询持仓失败: {res}")
            return 0.0
        
        for pos in res["data"]:
            if pos["positionSide"] == position_side:
                return abs(float(pos["positionAmt"]))
        return 0.0

    def _place_take_profit(self, side: str, entry_price: float, quantity: float) -> Optional[int]:
        step = entry_price * self._get_take_profit_step_ratio(side)
        
        if side == "BUY":
            tp_price = entry_price + step
            tp_side = "SELL"
            pos_side = "LONG"
        else:
            tp_price = entry_price - step
            tp_side = "BUY"
            pos_side = "SHORT"
            
        real_position = self._get_position_amount(pos_side)
        if real_position == 0:
            self.logger.warning(f"【严重警告】试图挂止盈单，但真实持仓为0！已取消下单。PosSide={pos_side}")
            self.state.last_entry_price[side] = None
            self.state.last_entry_quantity[side] = None
            self.state.tp_order_id[side] = None
            return None

        actual_qty = min(quantity, real_position)
        order_size = self._round_quantity(actual_qty)
        tp_price = self._round_price(tp_price)
        
        result = sdk.new_order(
            self.client,
            symbol=self.config.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=order_size,
            price=tp_price,
            time_in_force="GTC",
            position_side=pos_side
        )
        
        if not result["ok"]:
            raise RuntimeError(f"止盈单下单失败: {result}")
        order_id = int(result["data"]["orderId"])
        self.tp_registry.add_record(
            order_id=order_id,
            price=tp_price,
            entry_side=side,
            tp_side=tp_side,
        )
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
        try:
            res = sdk.change_position_mode(self.client, dual_side=True)
            if not res['ok'] and res.get('status_code') != 400: 
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
        self.state.last_filled_side = side
        if side == "BUY":
            self.state.buy_order_id = None
        else:
            self.state.sell_order_id = None
        if side == "BUY":
            self._cancel_opposite(self.state.sell_order_id)
        else:
            self._cancel_opposite(self.state.buy_order_id)
        self._place_opening_orders(price)

    def handle_ws_fill(self, order_id: int, side: str, price: float, quantity: float, event_time: int) -> None:
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
        self.state.last_filled_side = side
        # 记录成交时间戳
        self.state.last_fill_time[side] = event_time
        self.polling_active = self.config.enable_polling_after_ws_fill
        if side == "BUY":
            self.state.buy_order_id = None
        else:
            self.state.sell_order_id = None
        if side == "BUY":
            self._cancel_opposite(self.state.sell_order_id)
        else:
            self._cancel_opposite(self.state.buy_order_id)
        self._place_opening_orders(price)

        # WS 负责下单/撤单/止盈
        self.state.tp_order_id[side] = self._place_take_profit(
            side=side, entry_price=price, quantity=quantity
        )

    def _ensure_take_profit_orders(self) -> None:
        for side in ("BUY", "SELL"):
            entry_price = self.state.last_entry_price.get(side)
            entry_qty = self.state.last_entry_quantity.get(side)
            
            if not entry_price or not entry_qty:
                continue
                
            # ▼▼▼▼▼▼ 核心：5秒冷却时间锁 ▼▼▼▼▼▼
            last_time = self.state.last_fill_time.get(side) or 0
            current_time = int(time.time() * 1000)
            
            # 如果成交在5秒内，主循环什么都不做，完全信任 WS
            if current_time - last_time < 5000:
                continue
            # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
                
            tp_order_id = self.state.tp_order_id.get(side)
            
            if tp_order_id:
                tp_order = sdk.get_order(
                    self.client, symbol=self.config.symbol, order_id=tp_order_id
                )
                if tp_order["ok"]:
                    status = tp_order["data"].get("status")
                    if status in ["NEW", "PARTIALLY_FILLED"]:
                        continue 
                    if status == "FILLED":
                        self.tp_registry.remove_record(tp_order_id)
                        self.state.tp_order_id[side] = None
                        continue
                    self.tp_registry.remove_record(tp_order_id)
                    self.state.tp_order_id[side] = None 
                else:
                    # 查单失败不置空，等待下次重试
                    self.logger.warning(f"查询止盈单失败 (保留ID待下次重试): {tp_order}")
                    continue

            self.logger.info(
                "检测到止盈单缺失 (已过5秒安全期) entry_side=%s entry_price=%.4f qty=%.4f，补单",
                side,
                entry_price,
                entry_qty,
            )
            self.state.tp_order_id[side] = self._place_take_profit(
                side=side, entry_price=entry_price, quantity=entry_qty
            )

    def sync_once(self) -> None:
        if not self.config.enable_polling_after_ws_fill or not self.polling_active:
            return
        filled_side = self.state.last_filled_side
        if filled_side not in ("BUY", "SELL"):
            return
        pending_side = "SELL" if filled_side == "BUY" else "BUY"
        pending_order_id = (
            self.state.sell_order_id if pending_side == "SELL" else self.state.buy_order_id
        )
        if pending_order_id is not None:
            order = sdk.get_order(self.client, symbol=self.config.symbol, order_id=pending_order_id)
            if order["ok"]:
                status = order["data"].get("status")
                if status in ["NEW", "PARTIALLY_FILLED"]:
                    self._cancel_opposite(pending_order_id)
                elif status == "FILLED":
                    fill_price = float(order["data"].get("avgPrice") or order["data"].get("price"))
                    fill_qty = float(order["data"].get("executedQty") or 0)
                    update_time = int(order["data"].get("updateTime") or 0)
                    self.state.last_fill_time[pending_side] = update_time
                    self._handle_filled_order(pending_order_id, pending_side, fill_price, fill_qty)
                else:
                    if pending_side == "SELL":
                        self.state.sell_order_id = None
                    else:
                        self.state.buy_order_id = None

        entry_price = self.state.last_entry_price.get(filled_side)
        if entry_price:
            rounded_entry = self._round_price(entry_price)
            if self.state.last_center_price != rounded_entry:
                self.logger.info("检测到网格未按成交价部署，重新挂网格开仓单: %.4f", entry_price)
                self._place_opening_orders(entry_price)
        
        self._ensure_take_profit_orders()

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
        order_id = int(order.get("i") or 0)
        status = order.get("X")
        event_time = int(payload.get("E") or 0) # 获取事件时间戳
        
        logger.info(
            "订单更新 order_id=%s symbol=%s side=%s status=%s exec_type=%s avg_price=%s last_qty=%s",
            order_id,
            order.get("s"),
            order.get("S"),
            status,
            exec_type,
            avg_price,
            last_qty,
        )
        if order_id and engine.tp_registry.has_record(order_id):
            if status in ["FILLED", "CANCELED", "EXPIRED", "REJECTED"]:
                engine.tp_registry.remove_record(order_id)
        is_opening_order = order_id in (engine.state.buy_order_id, engine.state.sell_order_id)
        if exec_type == "TRADE" and last_qty > 0 and avg_price > 0:
            if is_opening_order:
                engine.handle_ws_fill(
                    order_id=order_id,
                    side=str(order.get("S")),
                    price=avg_price,
                    quantity=last_qty,
                    event_time=event_time, # 传进去
                )
    else:
        logger.debug("用户数据流事件=%s payload=%s", event_type, payload)


# === 保活线程 ===
def _keep_stream_alive(engine: GridEngine, listen_key: str, stop_event: threading.Event):
    logger = logging.getLogger("KeepAlive")
    logger.info("启动 User Data Stream 保活线程 (每30分钟续期一次)")
    while not stop_event.is_set():
        for _ in range(1800): 
            if stop_event.is_set(): return
            time.sleep(1)
        try:
            logger.info(f"正在续期 ListenKey: {listen_key[:6]}...")
            res = sdk.renew_listen_key(engine.client, listen_key)
            if res["ok"]: logger.info("ListenKey 续期成功！")
            else: logger.warning(f"ListenKey 续期失败: {res}")
        except Exception as e:
            logger.error(f"保活线程异常: {e}")


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
            
        keep_alive_stop = threading.Event()
        keep_alive_thread = threading.Thread(
            target=_keep_stream_alive,
            args=(engine, listen_key, keep_alive_stop),
            daemon=True,
            name="KeepAlive"
        )
        keep_alive_thread.start()
        
        ws_app = sdk.subscribe_user_data_ws(
            listen_key=listen_key,
            on_message=on_message,
            use_testnet=engine.config.use_testnet,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        ws_app.run_forever(ping_interval=20, ping_timeout=10)
        
        keep_alive_stop.set()
        
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
