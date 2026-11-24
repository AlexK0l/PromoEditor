"""Safe diagnostics for paid OpenAI image request connection failures.

Persist only known exception class names and stage/timing metadata. SDK
exception strings may contain untrusted URLs, headers, prompts or customer
content and must never be included in public task status or recovery ZIP.
"""
from __future__ import annotations

import time

_KNOWN_NETWORK_TYPES = {
    "APIConnectionError", "APITimeoutError",
    "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
    "TimeoutError", "TimeoutException",
    "ConnectError", "ReadError", "WriteError",
    "RemoteProtocolError", "ProtocolError",
    "ProxyError", "SSLError", "SSLCertVerificationError",
    "CertificateError", "gaierror", "NameResolutionError",
    "ConnectionResetError", "ConnectionAbortedError",
    "ConnectionRefusedError", "BrokenPipeError",
}
_DESCRIPTIONS = {
    "dns": "VPS не смог разрешить адрес API OpenAI (DNS).",
    "tls": "Не удалось установить защищённое TLS-соединение с API.",
    "proxy": "Промежуточный прокси не смог передать запрос OpenAI.",
    "connect_timeout": "Истекло время установления соединения с API.",
    "read_timeout": "Соединение установлено, но ожидание ответа API превысило тайм-аут.",
    "write_timeout": "Истекло время отправки изображений в API.",
    "timeout": "Истекло время ожидания ответа OpenAI.",
    "connection_reset": "Соединение с API оборвалось во время передачи данных.",
    "connect_error": "Не удалось подключиться к API OpenAI.",
    "transport": "Сетевая передача запроса OpenAI завершилась ошибкой.",
}


class OpenAIImageConnectionFailure(RuntimeError):
    """User-safe wrapper around SDK transport errors, with JSON metadata."""

    def __init__(self, report: dict):
        self.report = report
        self.public_reason = str(report["explanation"])
        super().__init__(self.public_reason)


def _safe_type_chain(exc: BaseException) -> list[str]:
    names = []
    seen = set()
    current = exc
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        name = type(current).__name__
        names.append(name if name in _KNOWN_NETWORK_TYPES else "Other")
        current = current.__cause__ or current.__context__
    return names


def connection_report(
    exc: BaseException, *, format_name: str, started_at: float,
) -> dict | None:
    """Return a small, serializable SAFE report, or None for non-network errors."""
    if type(exc).__name__ not in ("APIConnectionError", "APITimeoutError"):
        return None
    types = _safe_type_chain(exc)
    seen = set(types)
    if "gaierror" in seen or "NameResolutionError" in seen:
        code = "dns"
    elif "SSLError" in seen or "SSLCertVerificationError" in seen or "CertificateError" in seen:
        code = "tls"
    elif "ProxyError" in seen:
        code = "proxy"
    elif "ConnectTimeout" in seen:
        code = "connect_timeout"
    elif "ReadTimeout" in seen:
        code = "read_timeout"
    elif "WriteTimeout" in seen:
        code = "write_timeout"
    elif "APITimeoutError" in seen or "TimeoutError" in seen or "TimeoutException" in seen:
        code = "timeout"
    elif any(n in seen for n in (
        "RemoteProtocolError", "ProtocolError", "ReadError", "WriteError",
        "ConnectionResetError", "ConnectionAbortedError", "BrokenPipeError",
    )):
        code = "connection_reset"
    elif any(n in seen for n in ("ConnectError", "ConnectionRefusedError")):
        code = "connect_error"
    else:
        code = "transport"

    elapsed = max(0.0, min(9999.0, time.monotonic() - started_at))
    return {
        "phase": "paid_artwork_images_edit",
        "format": format_name if format_name in ("4x3", "9x16", "rebrand") else "unknown",
        "reason_code": code,
        "sdk_exception": types[0],
        "cause_classes": types[1:],
        "elapsed_seconds": round(elapsed, 1),
        "explanation": _DESCRIPTIONS[code],
        "billing_uncertain": True,
        "automatic_retry": False,
        "instruction": (
            "Сохранённые ранее этапы не повторены. "
            "Убедитесь в доступности API с VPS; перед повторным платным "
            "запуском проверьте остаток квоты и кэш. "
            "Если запрос дошёл до OpenAI, его стоимость может быть учтена."
        ),
    }


def edit_paid_image_once(api, format_name: str, **options):
    """One paid Images attempt, bounded timeout and redacted transport errors."""
    import os
    try:
        timeout = int(os.getenv("PROMO_OPENAI_ART_TIMEOUT_SECONDS", "480"))
    except (TypeError, ValueError):
        timeout = 480
    started = time.monotonic()
    try:
        return api.images.edit(timeout=max(180, min(600, timeout)), **options)
    except Exception as exc:
        report = connection_report(exc, format_name=format_name, started_at=started)
        if report is None:
            raise
        raise OpenAIImageConnectionFailure(report) from exc
