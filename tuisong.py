#用来推送企业微信或者其他什么推送的消息
from __future__ import annotations

import json
import logging
from typing import Optional
from urllib.request import Request, urlopen


DEFAULT_WEBHOOK_URL = (
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=43874765-eb79-481d-84ce-3773b1e879d7"
)


def push_wechat(message: str, webhook_url: Optional[str] = None) -> bool:
    """推送企业微信机器人消息。

    Args:
        message: 需要发送到企业微信群的文本内容。
        webhook_url: 自定义的机器人 webhook 地址，不传则使用默认配置。

    Returns:
        True 表示推送成功；False 表示推送失败（包含网络或接口错误）。
    """
    logger = logging.getLogger("WeChatPush")
    url = webhook_url or DEFAULT_WEBHOOK_URL
    payload = {
        "msgtype": "text",
        "text": {"content": message},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            logger.debug("企业微信推送响应原文: %s", body)
            result = json.loads(body)
            errcode = result.get("errcode")
            errmsg = result.get("errmsg")
            if errcode == 0:
                logger.info("企业微信推送成功: %s", errmsg)
                return True
            logger.warning("企业微信推送失败，错误码: %s，错误信息: %s", errcode, errmsg)
            return False
    except Exception as exc:
        logger.warning("企业微信推送失败，异常信息: %s", exc)
        return False
