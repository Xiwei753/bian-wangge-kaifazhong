#网格本体，包括动态网格和其他文件发送来过来的下单指令，防止好几个文件同时下单冲突
#然后把下单指令发送给binance sdk.py文件
#所有的多单的开仓和空单的平仓是一个算法，所有的空单的开仓和多单的平仓是一个算法。所有文件都是一样的

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import importlib.util
import importlib
import queue
import random
import threading
import time

import peizhi as peizhi_module
from peizhi import GridConfig, MarketMode
from qushifenxi import AdvancedTrendAnalyzer, StrategyDecision
from tuisong import push_wechat
from zhiyingguanli import LifecycleManager
from zhiyingtiaozheng import TrendTakeProfitAdjuster
from zhibiaojisuan import TechnicalIndicators


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
class KlineBuffer:
    max_size: int = 100
    _klines: List[Dict[str, object]] = field(default_factory=list, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def load_initial(self, klines: List[Dict[str, object]]) -> None:
        with self._lock:
            self._klines = sorted(klines, key=lambda item: item["open_time"])
            if len(self._klines) > self.max_size:
                self._klines = self._klines[-self.max_size :]

    def add_or_update(self, kline: Dict[str, object]) -> None:
        with self._lock:
            open_time = kline["open_time"]
            for index, existing in enumerate(self._klines):
                if existing["open_time"] == open_time:
                    self._klines[index] = kline
                    return
            self._klines.append(kline)
            if len(self._klines) > self.max_size:
                self._klines.pop(0)

    def snapshot(self) -> List[Dict[str, object]]:
        with self._lock:
            return list(self._klines)


@dataclass
class GridOrderState:
    buy_order_id: Optional[int] = None
    sell_order_id: Optional[int] = None
    buy_client_order_id: Optional[str] = None
    sell_client_order_id: Optional[str] = None
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
    tp_client_order_id: Dict[str, Optional[str]] = field(
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
        self.lifecycle_manager = LifecycleManager()
        self.stop_event = threading.Event()
        self.trade_queue: queue.Queue[TradeTask] = queue.Queue()
        self.kline_buffer = KlineBuffer(max_size=100)
        self._indicator_lock = threading.Lock()
        self.latest_indicators: Dict[str, float] = {}
        self.trend_analyzer = AdvancedTrendAnalyzer(config)
        self.tp_adjuster = TrendTakeProfitAdjuster(
            client=self.client,
            config=self.config,
            lifecycle_manager=self.lifecycle_manager,
            logger=self.logger,
        )
        self._decision_lock = threading.Lock()
        self.current_decision: Optional[StrategyDecision] = None
        self._push_queue: "queue.Queue[str]" = queue.Queue()
        self._push_thread = threading.Thread(
            target=self._push_worker,
            name="wechat_push_worker",
            daemon=True,
        )
        self._push_thread.start()

    def update_indicators(self, indicators: Dict[str, float]) -> None:
        with self._indicator_lock:
            self.latest_indicators = indicators

    def _set_current_decision(self, decision: StrategyDecision) -> None:
        with self._decision_lock:
            self.current_decision = decision
        self.config.market_mode = decision.market_mode

    def _push_message(self, message: str) -> None:
        if not self.config.enable_wechat_push:
            return
        if not self.config.wechat_webhook_url:
            return
        try:
            self._push_queue.put_nowait(message)
        except Exception as exc:
            self.logger.warning("推送消息入队失败: %s", exc)

    def _push_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                message = self._push_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                ok = push_wechat(message, self.config.wechat_webhook_url)
                if not ok:
                    self.logger.warning("企业微信推送失败: %s", message)
            except Exception as exc:
                self.logger.warning("企业微信推送异常: %s", exc)
            finally:
                self._push_queue.task_done()

    def _get_current_decision(self) -> Optional[StrategyDecision]:
        with self._decision_lock:
            return self.current_decision

    def analyze_initial_trend(self) -> Optional[StrategyDecision]:
        decision = self.analyze_market()
        if decision is None:
            self.logger.warning("历史K线为空，无法进行趋势分析")
            return None
        self.logger.info(
            "启动趋势分析完成 market_mode=%s score=%.2f strength=%.2f",
            decision.market_mode.value,
            decision.score,
            decision.strength,
        )
        return decision

    def analyze_market(self) -> Optional[StrategyDecision]:
        klines = self.kline_buffer.snapshot()
        if not klines:
            return None
        decision = self.trend_analyzer.analyze(klines)
        self._set_current_decision(decision)
        return decision

    def _build_client_order_id(self, task: "TradeTask", action: str) -> str:
        base = f"g{task.task_type[:2]}{task.order_id}{action}"
        return base[:32]

    def _get_current_price_with_retry(self, task: "TradeTask") -> Optional[float]:
        result = self._rest_call_with_retry(
            task,
            "get_ticker_price",
            sdk.get_ticker_price,
            client=self.client,
            symbol=self.config.symbol,
        )
        if not result or not result.get("ok"):
            self.logger.warning("获取价格失败: %s", result)
            return None
        return float(result["data"]["price"])

    def _is_duplicate_client_order_error(self, error: Optional[str]) -> bool:
        if not error:
            return False
        normalized = error.lower()
        return "duplicate" in normalized and "client" in normalized

    def _rest_call_with_retry(
        self,
        task: "TradeTask",
        action: str,
        api_func,
        client_order_id: Optional[str] = None,
        allow_duplicate_check: bool = True,
        **kwargs,
    ) -> Optional[Dict[str, object]]:
        max_attempts = 5
        base_delay = 0.5
        last_error = None
        last_client_order_id = client_order_id
        for attempt in range(1, max_attempts + 1):
            try:
                if client_order_id and "client_order_id" not in kwargs:
                    kwargs["client_order_id"] = client_order_id
                result = api_func(**kwargs)
            except Exception as exc:
                last_error = str(exc)
                result = None
            if result is None:
                retryable = True
            else:
                if isinstance(result.get("data"), dict):
                    last_client_order_id = (
                        result["data"].get("clientOrderId") or last_client_order_id
                    )
                if result.get("ok"):
                    return result
                last_error = result.get("error")
                if (
                    allow_duplicate_check
                    and client_order_id
                    and self._is_duplicate_client_order_error(last_error)
                ):
                    lookup = self._rest_call_with_retry(
                        task,
                        "get_order",
                        sdk.get_order,
                        client_order_id=client_order_id,
                        allow_duplicate_check=False,
                        client=self.client,
                        symbol=self.config.symbol,
                        orig_client_order_id=client_order_id,
                    )
                    if lookup and lookup.get("ok"):
                        return lookup
                    return lookup or result

                retryable = bool(result.get("retryable"))

            if not retryable:
                return result

            if attempt < max_attempts:
                jitter = random.uniform(0, 0.2)
                delay = base_delay * (2 ** (attempt - 1)) + jitter
                time.sleep(delay)
            else:
                self.logger.error(
                    "REST任务重试失败 task_type=%s order_id=%s client_order_id=%s action=%s error=%s",
                    task.task_type,
                    task.order_id,
                    last_client_order_id,
                    action,
                    last_error,
                )
                return result

        return None

    def _round_price(self, value: float) -> float:
        return round(value, self.config.price_precision)

    def _round_quantity(self, value: float) -> float:
        return round(value, self.config.qty_precision)

    def _get_latest_order_size(self) -> float:
        try:
            importlib.reload(peizhi_module)
            latest_config = peizhi_module.GridConfig()
            self.config.fixed_order_size = latest_config.fixed_order_size
        except Exception as exc:
            self.logger.warning("读取最新下单数量失败: %s", exc)
        return self._round_quantity(self.config.fixed_order_size)

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

        decision = self._get_current_decision()
        if decision is None:
            return default_buy_step, default_sell_step
        if decision.market_mode == MarketMode.CONSOLIDATION:
            return default_buy_step, default_sell_step

        buy_step = center_price * decision.long_step
        sell_step = center_price * decision.short_step
        return buy_step, sell_step

    def _place_opening_order_side(
        self, center_price: float, side: str, task: "TradeTask"
    ) -> Optional[int]:
        step = center_price * self._get_open_step_ratio(side)
        order_size = self._get_latest_order_size()
        self.state.last_center_price = self._round_price(center_price)
        if side == "BUY":
            price = center_price - step
            position_side = "LONG"
            action = "ob"
            client_order_id = self._build_client_order_id(task, action)
            result = self._rest_call_with_retry(
                task,
                "new_order_buy",
                sdk.new_order,
                client_order_id=client_order_id,
                client=self.client,
                symbol=self.config.symbol,
                side="BUY",
                order_type="LIMIT",
                quantity=order_size,
                price=self._round_price(price),
                time_in_force="GTC",
                position_side=position_side,
            )
            if result and result.get("ok"):
                self.state.buy_order_id = int(result["data"]["orderId"])
                self.state.buy_client_order_id = client_order_id
                self.logger.info(
                    "挂买单成功: 价格 %s 数量 %s",
                    self._round_price(price),
                    order_size,
                )
                return self.state.buy_order_id
            self.logger.error("挂买单失败: %s", result)
            return None
        price = center_price + step
        position_side = "SHORT"
        action = "os"
        client_order_id = self._build_client_order_id(task, action)
        result = self._rest_call_with_retry(
            task,
            "new_order_sell",
            sdk.new_order,
            client_order_id=client_order_id,
            client=self.client,
            symbol=self.config.symbol,
            side="SELL",
            order_type="LIMIT",
            quantity=order_size,
            price=self._round_price(price),
            time_in_force="GTC",
            position_side=position_side,
        )
        if result and result.get("ok"):
            self.state.sell_order_id = int(result["data"]["orderId"])
            self.state.sell_client_order_id = client_order_id
            self.logger.info(
                "挂卖单成功: 价格 %s 数量 %s",
                self._round_price(price),
                order_size,
            )
            return self.state.sell_order_id
        self.logger.error("挂卖单失败: %s", result)
        return None

    def _place_opening_orders(self, center_price: float, task: "TradeTask") -> None:
        buy_step, sell_step = self._decide_grid_steps(center_price)
        order_size = self._get_latest_order_size()
        self.state.last_center_price = self._round_price(center_price)
        
        if buy_step is not None:
            buy_price = center_price - buy_step
            buy_client_order_id = self._build_client_order_id(task, "ob")
            buy = self._rest_call_with_retry(
                task,
                "new_order_buy",
                sdk.new_order,
                client_order_id=buy_client_order_id,
                client=self.client,
                symbol=self.config.symbol,
                side="BUY",
                order_type="LIMIT",
                quantity=order_size,
                price=self._round_price(buy_price),
                time_in_force="GTC",
                position_side="LONG",
            )
            if buy and buy.get("ok"):
                self.state.buy_order_id = int(buy["data"]["orderId"])
                self.state.buy_client_order_id = buy_client_order_id
                self.lifecycle_manager.add_grid(
                    order_id=self.state.buy_order_id,
                    price=self._round_price(buy_price),
                    entry_side="BUY",
                    status="NEW",
                )
                self.logger.info(
                    "挂买单成功: 价格 %s 数量 %s",
                    self._round_price(buy_price),
                    order_size,
                )
                self._push_message(
                    "挂买单 side=BUY price={price:.4f} qty={qty:.4f}".format(
                        price=self._round_price(buy_price),
                        qty=order_size,
                    )
                )
            else:
                self.logger.error(f"挂买单失败: {buy}")
        else:
            self.state.buy_order_id = None
            self.state.buy_client_order_id = None

        if sell_step is not None:
            sell_price = center_price + sell_step
            sell_client_order_id = self._build_client_order_id(task, "os")
            sell = self._rest_call_with_retry(
                task,
                "new_order_sell",
                sdk.new_order,
                client_order_id=sell_client_order_id,
                client=self.client,
                symbol=self.config.symbol,
                side="SELL",
                order_type="LIMIT",
                quantity=order_size,
                price=self._round_price(sell_price),
                time_in_force="GTC",
                position_side="SHORT",
            )
            if sell and sell.get("ok"):
                self.state.sell_order_id = int(sell["data"]["orderId"])
                self.state.sell_client_order_id = sell_client_order_id
                self.lifecycle_manager.add_grid(
                    order_id=self.state.sell_order_id,
                    price=self._round_price(sell_price),
                    entry_side="SELL",
                    status="NEW",
                )
                self.logger.info(
                    "挂卖单成功: 价格 %s 数量 %s",
                    self._round_price(sell_price),
                    order_size,
                )
                self._push_message(
                    "挂卖单 side=SELL price={price:.4f} qty={qty:.4f}".format(
                        price=self._round_price(sell_price),
                        qty=order_size,
                    )
                )
            else:
                self.logger.error(f"挂卖单失败: {sell}")
        else:
            self.state.sell_order_id = None
            self.state.sell_client_order_id = None

    def handle_trend_entry(self, center_price: float) -> None:
        task = TradeTask(
            order_id=int(time.time() * 1000),
            side="TREND_SWITCH",
            price=center_price,
            quantity=0,
            task_type="trend_switch",
        )
        self.logger.info("进入趋势市，撤单并重新挂单 center=%.4f", center_price)
        self._push_message("市场切换: 进入趋势市 center={:.4f}".format(center_price))
        self._cancel_opposite(self.state.buy_order_id, self.state.buy_client_order_id, task)
        self._cancel_opposite(self.state.sell_order_id, self.state.sell_client_order_id, task)
        self.state.buy_order_id = None
        self.state.buy_client_order_id = None
        self.state.sell_order_id = None
        self.state.sell_client_order_id = None
        self._place_opening_orders(center_price, task)

    def handle_consolidation_entry(self, center_price: float) -> None:
        task = TradeTask(
            order_id=int(time.time() * 1000),
            side="CONSOLIDATION_SWITCH",
            price=center_price,
            quantity=0,
            task_type="consolidation_switch",
        )
        self.logger.info("进入震荡市，撤单并重新挂单 center=%.4f", center_price)
        self._push_message("市场切换: 进入震荡市 center={:.4f}".format(center_price))
        self._cancel_opposite(self.state.buy_order_id, self.state.buy_client_order_id, task)
        self._cancel_opposite(self.state.sell_order_id, self.state.sell_client_order_id, task)
        self.state.buy_order_id = None
        self.state.buy_client_order_id = None
        self.state.sell_order_id = None
        self.state.sell_client_order_id = None
        self._place_opening_orders(center_price, task)

    def _place_take_profit(
        self,
        side: str,
        entry_price: float,
        quantity: float,
        task: "TradeTask",
        parent_id: Optional[int] = None,
    ) -> Optional[int]:
        step = entry_price * self._get_take_profit_step_ratio(side)
        
        if side == "BUY":
            tp_price = entry_price + step
            tp_side = "SELL"
            pos_side = "LONG"
        else:
            tp_price = entry_price - step
            tp_side = "BUY"
            pos_side = "SHORT"
            
        order_size = self._round_quantity(quantity)
        tp_price = self._round_price(tp_price)
        
        tp_action = "tpb" if side == "BUY" else "tps"
        tp_client_order_id = self._build_client_order_id(task, tp_action)
        result = self._rest_call_with_retry(
            task,
            "new_order_take_profit",
            sdk.new_order,
            client_order_id=tp_client_order_id,
            client=self.client,
            symbol=self.config.symbol,
            side=tp_side,
            order_type="LIMIT",
            quantity=order_size,
            price=tp_price,
            time_in_force="GTC",
            position_side=pos_side,
        )
        
        if not result or not result.get("ok"):
            self.logger.error("止盈单下单失败: %s", result)
            return None
        order_id = int(result["data"]["orderId"])
        record_parent_id = parent_id if parent_id is not None else task.order_id
        self.state.tp_client_order_id[side] = tp_client_order_id
        self.lifecycle_manager.add_tp(
            order_id=order_id,
            price=tp_price,
            quantity=order_size,
            parent_id=record_parent_id,
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
            leverage_res = sdk.change_leverage(
                self.client,
                self.config.symbol,
                self.config.leverage,
            )
            if leverage_res and not leverage_res.get("ok"):
                self.logger.warning(f"设置杠杆警告: {leverage_res}")
            margin_res = sdk.change_margin_type(
                self.client,
                self.config.symbol,
                self.config.margin_mode,
            )
            if margin_res and not margin_res.get("ok"):
                self.logger.warning(f"设置保证金模式警告: {margin_res}")
        except Exception as e:
            self.logger.warning(f"设置持仓模式异常 (如果是 'No need to change' 可忽略): {e}")

        center_price = self._get_current_price()
        init_task = TradeTask(
            order_id=0,
            side="INIT",
            price=center_price,
            quantity=0,
            task_type="init",
        )
        self._place_opening_orders(center_price, init_task)

    def _cancel_opposite(
        self, order_id: Optional[int], client_order_id: Optional[str], task: "TradeTask"
    ) -> None:
        if order_id is None and client_order_id is None:
            return
        result = self._rest_call_with_retry(
            task,
            "cancel_order",
            sdk.cancel_order,
            client=self.client,
            symbol=self.config.symbol,
            order_id=order_id,
            orig_client_order_id=client_order_id,
        )
        if not result or not result.get("ok"):
            self.logger.warning("撤单失败 order_id=%s result=%s", order_id, result)
            return
        canceled_order_id = order_id
        if canceled_order_id is None:
            canceled_order_id = result.get("data", {}).get("orderId")
        if canceled_order_id is not None:
            self.lifecycle_manager.remove_record(canceled_order_id)
        self.logger.info("撤单完成 order_id=%s result=%s", order_id, result["data"])

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
        self.trade_queue.put(
            TradeTask(order_id=order_id, side=side, price=price, quantity=quantity)
        )

    def process_trade_task(self, task: "TradeTask") -> None:
        self.state.last_entry_price[task.side] = task.price
        self.state.last_entry_quantity[task.side] = task.quantity
        self.lifecycle_manager.update_status(task.order_id, "FILLED")
        if task.side == "BUY":
            opposite_order_id = self.state.sell_order_id
            opposite_client_order_id = self.state.sell_client_order_id
            self.state.buy_order_id = None
            self.state.buy_client_order_id = None
        else:
            opposite_order_id = self.state.buy_order_id
            opposite_client_order_id = self.state.buy_client_order_id
            self.state.sell_order_id = None
            self.state.sell_client_order_id = None
        if task.side == "BUY":
            self._cancel_opposite(opposite_order_id, opposite_client_order_id, task)
        else:
            self._cancel_opposite(opposite_order_id, opposite_client_order_id, task)
        self._place_opening_orders(task.price, task)
        buy_step, sell_step = self._decide_grid_steps(task.price)
        next_buy_price = self._round_price(task.price - buy_step) if buy_step else None
        next_sell_price = self._round_price(task.price + sell_step) if sell_step else None
        self._push_message(
            "开仓成交 side={side} price={price:.4f} qty={qty:.4f} "
            "next_buy={next_buy} next_sell={next_sell}".format(
                side=task.side,
                price=task.price,
                qty=task.quantity,
                next_buy=next_buy_price if next_buy_price is not None else "-",
                next_sell=next_sell_price if next_sell_price is not None else "-",
            )
        )

        self.state.tp_order_id[task.side] = self._place_take_profit(
            side=task.side, entry_price=task.price, quantity=task.quantity, task=task
        )


    def stop(self) -> None:
        self.stop_event.set()


def _run_depth_ws(config: GridConfig, stop_event: threading.Event) -> None:
    logger = logging.getLogger("DepthWS")

    def on_message(_: sdk.websocket.WebSocketApp, message: str) -> None:
        try:
            logger.debug("收到盘口消息长度=%s", len(message))
        except Exception:
            logger.exception("处理盘口 WS 消息异常")

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


def _normalize_rest_kline(raw: List[object]) -> Dict[str, object]:
    return {
        "open_time": int(raw[0]),
        "open": float(raw[1]),
        "high": float(raw[2]),
        "low": float(raw[3]),
        "close": float(raw[4]),
        "volume": float(raw[5]),
        "close_time": int(raw[6]),
        "is_closed": True,
    }


def _normalize_ws_kline(raw: Dict[str, object]) -> Dict[str, object]:
    return {
        "open_time": int(raw["t"]),
        "open": float(raw["o"]),
        "high": float(raw["h"]),
        "low": float(raw["l"]),
        "close": float(raw["c"]),
        "volume": float(raw["v"]),
        "close_time": int(raw["T"]),
        "is_closed": bool(raw["x"]),
    }


def _calculate_indicators(engine: GridEngine) -> Optional[Dict[str, float]]:
    klines = engine.kline_buffer.snapshot()
    if not klines:
        return None
    closes = [float(item["close"]) for item in klines]
    atr_value = TechnicalIndicators.atr(klines, period=engine.config.atr_length)
    bollinger = TechnicalIndicators.bollinger_bands(closes, period=20, std_dev=2)
    momentum = TechnicalIndicators.momentum(closes, short_period=5, medium_period=10)
    return {
        "ema_fast": TechnicalIndicators.ema(closes, period=7),
        "ema_slow": TechnicalIndicators.ema(closes, period=25),
        "rsi": TechnicalIndicators.rsi(closes, period=14),
        "atr": atr_value,
        "bb_upper": bollinger["upper"],
        "bb_middle": bollinger["middle"],
        "bb_lower": bollinger["lower"],
        "momentum_short": momentum["short"],
        "momentum_medium": momentum["medium"],
        "price": closes[-1],
    }


def _load_initial_klines(engine: GridEngine) -> None:
    logger = logging.getLogger("KlineInit")
    interval = f"{engine.config.timeframe_minutes}m"
    result = sdk.get_klines(
        engine.client,
        symbol=engine.config.symbol,
        interval=interval,
        limit=100,
    )
    if not result.get("ok"):
        logger.error("初始化拉取K线失败: %s", result)
        return
    raw_klines = result.get("data") or []
    normalized = [_normalize_rest_kline(item) for item in raw_klines]
    engine.kline_buffer.load_initial(normalized)
    logger.info("已加载历史K线数量=%s interval=%s", len(normalized), interval)


def _run_kline_ws(engine: GridEngine, stop_event: threading.Event) -> None:
    logger = logging.getLogger("KlineWS")
    interval = f"{engine.config.timeframe_minutes}m"

    def on_message(_: sdk.websocket.WebSocketApp, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("K线消息解析失败: %s", message)
            return
        if payload.get("e") != "kline":
            logger.debug("忽略非K线消息: %s", payload.get("e"))
            return
        kline = payload.get("k")
        if not isinstance(kline, dict):
            logger.warning("K线字段缺失: %s", payload)
            return
        normalized = _normalize_ws_kline(kline)
        engine.kline_buffer.add_or_update(normalized)
        indicators = _calculate_indicators(engine)
        if indicators:
            engine.update_indicators(indicators)
            logger.debug(
                "指标更新 price=%s rsi=%s ema_fast=%s ema_slow=%s atr=%s",
                indicators["price"],
                indicators["rsi"],
                indicators["ema_fast"],
                indicators["ema_slow"],
                indicators["atr"],
            )
        current_price = indicators["price"] if indicators else float(normalized["close"])
        previous_decision = engine._get_current_decision()
        decision = engine.analyze_market()
        if decision:
            market_switched = (
                previous_decision is not None
                and previous_decision.market_mode != decision.market_mode
            )
            if market_switched:
                logger.info(
                    "市场切换 %s -> %s score=%.2f strength=%.2f",
                    previous_decision.market_mode.value,
                    decision.market_mode.value,
                    decision.score,
                    decision.strength,
                )
            if market_switched and decision.market_mode == MarketMode.TREND:
                engine.handle_trend_entry(current_price)
            elif market_switched and decision.market_mode == MarketMode.CONSOLIDATION:
                engine.handle_consolidation_entry(current_price)
        try:
            active_decision = decision or engine._get_current_decision()
            if active_decision and active_decision.market_mode == MarketMode.TREND:
                long_step_ratio = active_decision.long_step
                short_step_ratio = active_decision.short_step
            else:
                long_step_ratio = engine.config.long_open_short_tp_step_ratio
                short_step_ratio = engine.config.short_open_long_tp_step_ratio
            engine.tp_adjuster.adjust_take_profit_for_trend(
                current_price=current_price,
                long_step_ratio=long_step_ratio,
                short_step_ratio=short_step_ratio,
            )
        except Exception as exc:
            logger.exception("WS止盈调整异常: %s", exc)
        if normalized["is_closed"]:
            logger.info("K线收盘 open_time=%s close=%s", normalized["open_time"], normalized["close"])

    def on_error(_: sdk.websocket.WebSocketApp, error: Exception) -> None:
        logger.error("K线 WS 错误: %s", error)

    def on_close(_: sdk.websocket.WebSocketApp, status_code: int, msg: str) -> None:
        logger.warning("K线 WS 关闭 code=%s msg=%s", status_code, msg)

    def on_open(_: sdk.websocket.WebSocketApp) -> None:
        logger.info("K线 WS 已连接 interval=%s", interval)

    ws_app = sdk.subscribe_kline_ws(
        symbol=engine.config.symbol,
        interval=interval,
        on_message=on_message,
        use_testnet=engine.config.use_testnet,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )

    while not stop_event.is_set():
        ws_app.run_forever(ping_interval=20, ping_timeout=10)
        if stop_event.is_set():
            break
        logger.warning("K线 WS 断开，5秒后重连")
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
        if order_id and engine.lifecycle_manager.has_tp_record(order_id):
            if status in ["CANCELED", "EXPIRED", "REJECTED"]:
                engine.lifecycle_manager.remove_record(order_id)
            if status == "FILLED":
                tp_record = engine.lifecycle_manager.get_record(order_id)
                parent_id = tp_record.parent_id if tp_record else None
                engine._push_message(
                    "止盈成交 side={side} price={price:.4f} qty={qty:.4f}".format(
                        side=str(order.get("S")),
                        price=avg_price,
                        qty=last_qty,
                    )
                )
                engine.lifecycle_manager.remove_record(order_id)
                if parent_id:
                    engine.lifecycle_manager.remove_record(parent_id)
        is_opening_order = order_id in (engine.state.buy_order_id, engine.state.sell_order_id)
        if exec_type == "TRADE" and last_qty > 0 and avg_price > 0:
            if is_opening_order:
                engine.handle_ws_fill(
                    order_id=order_id,
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
    backoff_delay = 5

    def _is_connection_reset_error(error: Exception) -> bool:
        if isinstance(error, ConnectionResetError):
            return True
        err_no = getattr(error, "errno", None)
        if err_no == 10054:
            return True
        return "10054" in str(error)

    def _sleep_with_backoff(reason: str) -> None:
        nonlocal backoff_delay
        logger.warning("%s，%s秒后重试", reason, backoff_delay)
        time.sleep(backoff_delay)
        backoff_delay = min(backoff_delay * 2, 60)

    def on_message(_: sdk.websocket.WebSocketApp, message: str) -> None:
        try:
            _handle_user_data_message(engine, logger, message)
        except Exception as exc:
            if _is_connection_reset_error(exc):
                logger.warning("用户数据 WS 连接被重置: %s", exc)
                return
            logger.exception("处理用户数据 WS 消息异常")

    def on_error(_: sdk.websocket.WebSocketApp, error: Exception) -> None:
        if _is_connection_reset_error(error):
            logger.warning("用户数据 WS 连接被重置: %s", error)
            return
        logger.error("用户数据 WS 错误: %s", error)

    def on_close(_: sdk.websocket.WebSocketApp, status_code: int, msg: str) -> None:
        logger.warning("用户数据 WS 关闭 code=%s msg=%s", status_code, msg)

    def on_open(_: sdk.websocket.WebSocketApp) -> None:
        nonlocal backoff_delay
        backoff_delay = 5
        logger.info("用户数据 WS 已连接")

    while not stop_event.is_set():
        listen_key_result = sdk.new_listen_key(engine.client)
        if not listen_key_result["ok"]:
            _sleep_with_backoff(f"获取 listenKey 失败: {listen_key_result}")
            continue
        listen_key = listen_key_result["data"].get("listenKey")
        if not listen_key:
            _sleep_with_backoff(f"listenKey 为空: {listen_key_result}")
            continue
            
        reconnect_event = threading.Event()

        def _keepalive_loop() -> None:
            while not stop_event.is_set() and not reconnect_event.is_set():
                if reconnect_event.wait(timeout=1800):
                    break
                result = sdk.renew_listen_key(engine.client, listen_key)
                if not result.get("ok"):
                    logger.error("listenKey 续期失败，准备重连: %s", result)
                    reconnect_event.set()
                    try:
                        ws_app.close()
                    except Exception:
                        logger.exception("关闭用户数据 WS 异常")
                    break

        ws_app = sdk.subscribe_user_data_ws(
            listen_key=listen_key,
            on_message=on_message,
            use_testnet=engine.config.use_testnet,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        keepalive_thread = threading.Thread(
            target=_keepalive_loop,
            name="UserDataWSKeepalive",
            daemon=True,
        )
        keepalive_thread.start()
        ws_app.run_forever(ping_interval=20, ping_timeout=10)
        reconnect_event.set()
        keepalive_thread.join(timeout=2)

        if stop_event.is_set():
            break
        _sleep_with_backoff("用户数据 WS 断开")

    if "listen_key" in locals():
        sdk.close_listen_key(engine.client, listen_key)


@dataclass(frozen=True)
class TradeTask:
    order_id: int
    side: str
    price: float
    quantity: float
    task_type: str = "ws_fill"


def _trade_worker(engine: GridEngine, stop_event: threading.Event) -> None:
    logger = logging.getLogger("TradeWorker")
    while not stop_event.is_set() or not engine.trade_queue.empty():
        try:
            task = engine.trade_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            engine.process_trade_task(task)
        except Exception:
            logger.exception("处理交易任务失败 task=%s", task)
        finally:
            engine.trade_queue.task_done()


def run_grid_loop() -> None:
    config = GridConfig()
    engine = GridEngine(config)
    engine._push_message(
        "网格策略启动: symbol={symbol} timeframe={timeframe}m "
        "长仓步长={long_step:.4f} 空仓步长={short_step:.4f}".format(
            symbol=config.symbol,
            timeframe=config.timeframe_minutes,
            long_step=config.long_open_short_tp_step_ratio,
            short_step=config.short_open_long_tp_step_ratio,
        )
    )
    _load_initial_klines(engine)
    engine.analyze_initial_trend()
    engine.initialize()
    depth_thread = threading.Thread(
        target=_run_depth_ws,
        args=(config, engine.stop_event),
        name="DepthWS",
        daemon=True,
    )
    kline_thread = threading.Thread(
        target=_run_kline_ws,
        args=(engine, engine.stop_event),
        name="KlineWS",
        daemon=True,
    )
    user_data_thread = threading.Thread(
        target=_run_user_data_ws,
        args=(engine, engine.stop_event),
        name="UserDataWS",
        daemon=True,
    )
    trade_thread = threading.Thread(
        target=_trade_worker,
        args=(engine, engine.stop_event),
        name="TradeWorker",
        daemon=True,
    )
    depth_thread.start()
    kline_thread.start()
    user_data_thread.start()
    trade_thread.start()
    engine.stop_event.wait()


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
