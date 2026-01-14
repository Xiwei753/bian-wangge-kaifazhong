#系统代理程序：通过开关控制是否启用代理，默认端口 7890
from __future__ import annotations

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


def _read_gsettings(key: str) -> str | None:
    if shutil.which("gsettings") is None:
        return None
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.system.proxy", key],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.stdout:
        return result.stdout.strip().strip("'")
    return None


def _read_gsettings_proxy(scheme: str) -> tuple[str | None, int | None]:
    if shutil.which("gsettings") is None:
        return None, None
    try:
        host_result = subprocess.run(
            ["gsettings", "get", f"org.gnome.system.proxy.{scheme}", "host"],
            check=False,
            capture_output=True,
            text=True,
        )
        port_result = subprocess.run(
            ["gsettings", "get", f"org.gnome.system.proxy.{scheme}", "port"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None, None
    host = host_result.stdout.strip().strip("'") if host_result.stdout else None
    port = None
    if port_result.stdout:
        try:
            port = int(port_result.stdout.strip())
        except ValueError:
            port = None
    return host, port


def read_system_proxy() -> ProxyConfig:
    """读取系统代理配置，优先使用 GNOME 配置。"""
    mode = _read_gsettings("mode")
    if mode and mode != "none":
        host, port = _read_gsettings_proxy("http")
        if host and port:
            return ProxyConfig(enabled=True, host=host, port=port)
    return ProxyConfig()


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
    config = read_system_proxy()
    apply_proxy(config)


if __name__ == "__main__":
    main()
