#这个文件是所有binance sdk语法的集合。所有涉及到和交易所交互的东西都从这里走，其他文件获取数据行情之类的要从这里获取
#下单和撤单也是别的文件算出来后决定要不要，然后给这个文件发送一个决定
# 这个文件是所有 binance connector 语法的集合。
# 所有涉及到和交易所交互的东西都从这里走，其他文件获取数据行情之类的要从这里获取。
#url和apikey都写在这里
#需要一个实盘的地址，和api，一个测试的地址和api
#都写到这里。peizhi里面就只写其他的参数

from typing import Any, Dict, List, Optional
from binance.error import ClientError
from binance.um_futures import UMFutures


def _call(api_func, *args, **kwargs) -> Dict[str, Any]:
    """统一捕获 Binance connector 的异常，便于上层统一处理。"""
    try:
        data = api_func(*args, **kwargs)
        return {"ok": True, "data": data}
    except ClientError as exc:
        return {
            "ok": False,
            "status_code": exc.status_code,
            "error": exc.error_message,
            "data": getattr(exc, "error_data", None),
        }


def create_um_client(
    api_key: str,
    api_secret: str,
    base_url: Optional[str] = None,
    timeout: int = 10,
) -> UMFutures:
    """创建 USDT-M 合约客户端。"""
    return UMFutures(key=api_key, secret=api_secret, base_url=base_url, timeout=timeout)


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


# ===================== 账户/仓位相关 =====================
def get_account_balance(client: UMFutures) -> Dict[str, Any]:
    return _call(client.balance)


def get_position_risk(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    return _call(client.position_risk, symbol=symbol)


def change_leverage(client: UMFutures, symbol: str, leverage: int) -> Dict[str, Any]:
    return _call(client.change_leverage, symbol=symbol, leverage=leverage)


def change_margin_type(client: UMFutures, symbol: str, margin_type: str) -> Dict[str, Any]:
    # margin_type: "ISOLATED" or "CROSSED"
    return _call(client.change_margin_type, symbol=symbol, marginType=margin_type)


def change_position_mode(client: UMFutures, dual_side: bool) -> Dict[str, Any]:
    # dual_side=True 表示双向持仓模式
    return _call(client.change_position_mode, dualSidePosition="true" if dual_side else "false")


# ===================== 下单/撤单 =====================
def new_order(
    client: UMFutures,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    reduce_only: Optional[bool] = None,
    position_side: Optional[str] = None,
    client_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
    }
    if price is not None:
        params["price"] = price
    if time_in_force is not None:
        params["timeInForce"] = time_in_force
    if reduce_only is not None:
        params["reduceOnly"] = reduce_only
    if position_side is not None:
        params["positionSide"] = position_side
    if client_order_id is not None:
        params["newClientOrderId"] = client_order_id
    return _call(client.new_order, **params)


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


def get_open_orders(client: UMFutures, symbol: Optional[str] = None) -> Dict[str, Any]:
    return _call(client.get_open_orders, symbol=symbol)


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
    return _call(client.get_order, **params)


def get_income_history(
    client: UMFutures, symbol: Optional[str] = None, limit: int = 100
) -> Dict[str, Any]:
    return _call(client.get_income_history, symbol=symbol, limit=limit)