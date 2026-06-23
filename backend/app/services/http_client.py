from __future__ import annotations

from urllib.request import Request, ProxyHandler, build_opener, urlopen

from app.core.config import settings


def open_http_request(request: Request, timeout: int):
    if settings.model_use_system_proxy:
        return urlopen(request, timeout=timeout)
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)
