# 日志配置模块
# 设置全局日志级别，并压制 httpx 库的详细日志

import logging

_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def configure_logging(log_level: str) -> None:
    """配置全局日志级别和格式，降低 httpx 的日志噪音"""

    level = _LOG_LEVELS.get(log_level.strip().upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
