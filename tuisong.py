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
    """推送企业微信机器人消息。"""
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
            logger.debug("企业微信推送响应: %s", body)
            return True
    except Exception as exc:
        logger.warning("企业微信推送失败: %s", exc)
        return False
