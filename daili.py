#系统代理程序：通过开关控制是否启用代理，默认端口 7890
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ProxyConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7890

    @property
    def http_proxy(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def https_proxy(self) -> str:
        return f"http://{self.host}:{self.port}"


def _run_gsettings(args: list[str]) -> None:
    if shutil.which("gsettings") is None:
        return
    try:
        subprocess.run(["gsettings", *args], check=False)
    except OSError:
        return


def apply_proxy(config: ProxyConfig) -> None:
    """启用或关闭系统代理（尽量兼容 GNOME），同时打印 shell 环境变量指令。"""
    if config.enabled:
        _run_gsettings(["set", "org.gnome.system.proxy", "mode", "manual"])
        _run_gsettings(["set", "org.gnome.system.proxy.http", "host", config.host])
        _run_gsettings(["set", "org.gnome.system.proxy.http", "port", str(config.port)])
        _run_gsettings(["set", "org.gnome.system.proxy.https", "host", config.host])
        _run_gsettings(["set", "org.gnome.system.proxy.https", "port", str(config.port)])
        print(f"export http_proxy={config.http_proxy}")
        print(f"export https_proxy={config.https_proxy}")
        print(f"export HTTP_PROXY={config.http_proxy}")
        print(f"export HTTPS_PROXY={config.https_proxy}")
    else:
        _run_gsettings(["set", "org.gnome.system.proxy", "mode", "none"])
        print("unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY")


def main() -> None:
    config = ProxyConfig()
    apply_proxy(config)


if __name__ == "__main__":
    main()
