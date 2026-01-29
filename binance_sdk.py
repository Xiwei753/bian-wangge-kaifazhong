#这个文件是所有binance sdk语法的集合。所有涉及到和交易所交互的东西都从这里走，其他文件获取数据行情之类的要从这里获取
#下单和撤单也是别的文件算出来后决定要不要，然后给这个文件发送一个决定
# 这个文件是所有 binance connector 语法的集合。
# 所有涉及到和交易所交互的东西都从这里走，其他文件获取数据行情之类的要从这里获取。
#url和apikey都写在这里
#需要一个实盘的地址，和api，一个测试的地址和api
#都写到这里。peizhi里面就只写其他的参数

import json
from typing import Any, Callable, Dict, List, Optional

import requests
import websocket
from binance.error import ClientError
from binance.um_futures import UMFutures


def _call(api_func, *args, **kwargs) -> Dict[str, Any]:
    """统一捕获 Binance connector 的异常，便于上层统一处理。"""
    try:
        data = api_func(*args, **kwargs)
        return {"ok": True, "data": data}
    except ClientError as exc:
        status_code = exc.status_code
        retryable = status_code in (418, 429) or 500 <= status_code < 600
        return {
            "ok": False,
            "status_code": status_code,
            "error": exc.error_message,
            "data": getattr(exc, "error_data", None),
            "retryable": retryable,
        }
    except requests.exceptions.RequestException as exc:
        return {
            "ok": False,
            "error": str(exc),
            "data": None,
            "retryable": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "data": None,
            "retryable": True,
        }


def _call_method(client: UMFutures, method_name: str, *args, **kwargs) -> Dict[str, Any]:
    """按名称调用 UMFutures 方法，方法不存在时返回统一错误。"""
    api_func = getattr(client, method_name, None)
    if api_func is None:
        return {
            "ok": False,
            "error": f"UMFutures method '{method_name}' not available.",
            "data": None,
        }
    return _call(api_func, *args, **kwargs)


def create_um_client(
    api_key: str,
    api_secret: str,
    base_url: Optional[str] = None,
    timeout: int = 10,
    **kwargs,
) -> UMFutures:
    """创建 USDT-M 合约客户端。"""
    return UMFutures(
        key=api_key,
        secret=api_secret,
        base_url=base_url,
        timeout=timeout,
        **kwargs,
    )


# ===================== 行情相关 =====================
def get_server_time(client: UMFutures) -> Dict[str, Any]:
    return _call(client.time)


def get_exchange_info(client: UMFutures) -> Dict[str, Any]:
    return _call(client.exchange_info)


def get_klines(
    client: UMFutures,
    symbol: str,
    interval: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call(client.klines, symbol=symbol, interval=interval, limit=limit)


def get_depth(client: UMFutures, symbol: str, limit: int = 100) -> Dict[str, Any]:
    return _call(client.depth, symbol=symbol, limit=limit)


def get_ticker_price(client: UMFutures, symbol: str) -> Dict[str, Any]:
    return _call(client.ticker_price, symbol=symbol)


def get_book_ticker(client: UMFutures, symbol: str) -> Dict[str, Any]:
    return _call(client.book_ticker, symbol=symbol)


def get_mark_price(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    return _call(client.mark_price, symbol=symbol)


def get_funding_rate(
    client: UMFutures, symbol: Optional[str] = None, limit: int = 100
) -> Dict[str, Any]:
    return _call(client.funding_rate, symbol=symbol, limit=limit)


def get_agg_trades(
    client: UMFutures, symbol: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "agg_trades", symbol=symbol, limit=limit)


def get_trades(client: UMFutures, symbol: str, limit: int = 500) -> Dict[str, Any]:
    return _call_method(client, "trades", symbol=symbol, limit=limit)


def get_historical_trades(
    client: UMFutures, symbol: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "historical_trades", symbol=symbol, limit=limit)


def get_continuous_klines(
    client: UMFutures,
    pair: str,
    contract_type: str,
    interval: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "continuous_klines",
        pair=pair,
        contractType=contract_type,
        interval=interval,
        limit=limit,
    )


def get_index_price_klines(
    client: UMFutures, pair: str, interval: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "index_price_klines", pair=pair, interval=interval, limit=limit)


def get_mark_price_klines(
    client: UMFutures, symbol: str, interval: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "mark_price_klines", symbol=symbol, interval=interval, limit=limit)


def get_premium_index_klines(
    client: UMFutures, symbol: str, interval: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "premium_index_klines", symbol=symbol, interval=interval, limit=limit)


def get_ticker_24hr_price_change(
    client: UMFutures, symbol: Optional[str] = None
) -> Dict[str, Any]:
    return _call_method(client, "ticker_24hr_price_change", symbol=symbol)


def get_open_interest(client: UMFutures, symbol: str) -> Dict[str, Any]:
    return _call_method(client, "open_interest", symbol=symbol)


def get_open_interest_hist(
    client: UMFutures,
    symbol: str,
    period: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "open_interest_hist",
        symbol=symbol,
        period=period,
        limit=limit,
    )


def get_top_long_short_position_ratio(
    client: UMFutures,
    symbol: str,
    period: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "top_long_short_position_ratio",
        symbol=symbol,
        period=period,
        limit=limit,
    )


def get_top_long_short_account_ratio(
    client: UMFutures,
    symbol: str,
    period: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "top_long_short_account_ratio",
        symbol=symbol,
        period=period,
        limit=limit,
    )


def get_global_long_short_account_ratio(
    client: UMFutures,
    symbol: str,
    period: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "global_long_short_account_ratio",
        symbol=symbol,
        period=period,
        limit=limit,
    )


def get_taker_long_short_ratio(
    client: UMFutures,
    symbol: str,
    period: str,
    limit: int = 500,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "taker_long_short_ratio",
        symbol=symbol,
        period=period,
        limit=limit,
    )


# ===================== 账户/仓位相关 =====================
def get_account_balance(client: UMFutures) -> Dict[str, Any]:
    return _call(client.balance)


def get_account_information(client: UMFutures) -> Dict[str, Any]:
    return _call_method(client, "account")


def get_position_risk(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    # ▼▼▼▼▼▼▼▼▼ 核心修复 ▼▼▼▼▼▼▼▼▼
    # 官方库的方法名是 get_position_risk
    return _call(client.get_position_risk, symbol=symbol)
    # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲


def get_position_mode(client: UMFutures) -> Dict[str, Any]:
    return _call_method(client, "get_position_mode")


def modify_isolated_position_margin(
    client: UMFutures,
    symbol: str,
    amount: float,
    margin_type: int,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_method(
        client,
        "modify_isolated_position_margin",
        symbol=symbol,
        amount=amount,
        type=margin_type,
        positionSide=position_side,
    )


def get_leverage_bracket(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    return _call_method(client, "leverage_bracket", symbol=symbol)


def get_commission_rate(client: UMFutures, symbol: str) -> Dict[str, Any]:
    return _call_method(client, "commission_rate", symbol=symbol)


def change_leverage(client: UMFutures, symbol: str, leverage: int) -> Dict[str, Any]:
    return _call(client.change_leverage, symbol=symbol, leverage=leverage)


def change_margin_type(client: UMFutures, symbol: str, margin_type: str) -> Dict[str, Any]:
    # margin_type: "ISOLATED" or "CROSSED"
    return _call(client.change_margin_type, symbol=symbol, marginType=margin_type)


def change_position_mode(client: UMFutures, dual_side: bool) -> Dict[str, Any]:
    # dual_side=True 表示双向持仓模式
    return _call(client.change_position_mode, dualSidePosition="true" if dual_side else "false")


# ===================== 下单/撤单 =====================
def new_batch_orders(client: UMFutures, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    params: Dict[str, Any] = {"batchOrders": json.dumps(orders, ensure_ascii=False)}
    return _call_method(client, "new_batch_order", **params)


def cancel_order(
    client: UMFutures,
    symbol: str,
    order_id: Optional[int] = None,
    orig_client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = order_id
    if orig_client_order_id is not None:
        params["origClientOrderId"] = orig_client_order_id
    return _call(client.cancel_order, **params)


def cancel_all_orders(client: UMFutures, symbol: str) -> Dict[str, Any]:
    return _call(client.cancel_open_orders, symbol=symbol)


# ===================== get_open_orders (手动修复版) =====================
def get_open_orders(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    # 绕过 binance-futures-connector 的 orderId 必填 Bug
    def safe_get_open_orders(symbol_arg):
        params = {}
        if symbol_arg:
            params["symbol"] = symbol_arg
        return client.sign_request("GET", "/fapi/v1/openOrders", params)
    return _call(safe_get_open_orders, symbol)
# =========================================================================


# ===================== 【关键修复】使用 query_order 而非 get_order =====================
def get_order(
    client: UMFutures,
    symbol: str,
    order_id: Optional[int] = None,
    orig_client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = order_id
    if orig_client_order_id is not None:
        params["origClientOrderId"] = orig_client_order_id
    
    # 官方库 (binance-connector) 对应的方法名是 query_order
    return _call(client.query_order, **params)


def get_all_orders(
    client: UMFutures, symbol: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "get_all_orders", symbol=symbol, limit=limit)


def get_income_history(
    client: UMFutures, symbol: Optional[str] = None, limit: int = 100
) -> Dict[str, Any]:
    return _call(client.get_income_history, symbol=symbol, limit=limit)


def get_account_trades(
    client: UMFutures, symbol: str, limit: int = 500
) -> Dict[str, Any]:
    return _call_method(client, "account_trades", symbol=symbol, limit=limit)


# ===================== 用户数据流 =====================
def new_listen_key(client: UMFutures) -> Dict[str, Any]:
    return _call_method(client, "new_listen_key")


def renew_listen_key(client: UMFutures, listen_key: str) -> Dict[str, Any]:
    return _call_method(client, "renew_listen_key", listenKey=listen_key)


def close_listen_key(client: UMFutures, listen_key: str) -> Dict[str, Any]:
    return _call_method(client, "close_listen_key", listenKey=listen_key)


# ===================== WebSocket 行情订阅 =====================
def get_ws_base_url(use_testnet: bool = False) -> str:
    """获取 U 本位合约 WebSocket base url。"""
    return "wss://stream.binancefuture.com/ws" if use_testnet else "wss://fstream.binance.com/ws"


def build_depth_stream_name(symbol: str, depth_level: int = 10, speed_ms: int = 100) -> str:
    """构建深度盘口 stream 名称。"""
    symbol_lower = symbol.lower()
    speed_suffix = "100ms" if speed_ms == 100 else "1000ms"
    return f"{symbol_lower}@depth{depth_level}@{speed_suffix}"


def build_kline_stream_name(symbol: str, interval: str) -> str:
    """构建 K 线 stream 名称。"""
    symbol_lower = symbol.lower()
    return f"{symbol_lower}@kline_{interval}"


def subscribe_kline_ws(
    symbol: str,
    interval: str,
    on_message: Callable[[websocket.WebSocketApp, str], None],
    use_testnet: bool = False,
    on_error: Optional[Callable[[websocket.WebSocketApp, Exception], None]] = None,
    on_close: Optional[Callable[[websocket.WebSocketApp, int, str], None]] = None,
    on_open: Optional[Callable[[websocket.WebSocketApp], None]] = None,
) -> websocket.WebSocketApp:
    """订阅指定交易对的 K 线数据，返回 WebSocketApp 实例。"""
    stream = build_kline_stream_name(symbol, interval=interval)
    ws_url = f"{get_ws_base_url(use_testnet=use_testnet)}/{stream}"
    return websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )


def subscribe_depth_ws(
    symbol: str,
    on_message: Callable[[websocket.WebSocketApp, str], None],
    depth_level: int = 10,
    speed_ms: int = 100,
    use_testnet: bool = False,
    on_error: Optional[Callable[[websocket.WebSocketApp, Exception], None]] = None,
    on_close: Optional[Callable[[websocket.WebSocketApp, int, str], None]] = None,
    on_open: Optional[Callable[[websocket.WebSocketApp], None]] = None,
) -> websocket.WebSocketApp:
    """订阅指定交易对的盘口深度数据，返回 WebSocketApp 实例。"""
    stream = build_depth_stream_name(symbol, depth_level=depth_level, speed_ms=speed_ms)
    ws_url = f"{get_ws_base_url(use_testnet=use_testnet)}/{stream}"
    return websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )


def build_user_data_stream_url(listen_key: str, use_testnet: bool = False) -> str:
    """构建用户数据流 WebSocket URL。"""
    return f"{get_ws_base_url(use_testnet=use_testnet)}/{listen_key}"


def subscribe_user_data_ws(
    listen_key: str,
    on_message: Callable[[websocket.WebSocketApp, str], None],
    use_testnet: bool = False,
    on_error: Optional[Callable[[websocket.WebSocketApp, Exception], None]] = None,
    on_close: Optional[Callable[[websocket.WebSocketApp, int, str], None]] = None,
    on_open: Optional[Callable[[websocket.WebSocketApp], None]] = None,
) -> websocket.WebSocketApp:
    """订阅用户数据流，返回 WebSocketApp 实例。"""
    ws_url = build_user_data_stream_url(listen_key, use_testnet=use_testnet)
    return websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
