from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).with_name("config.json")


class ConfigError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class AutoParams:
    bias: float
    length_ratio_coefficient: float
    lexical_confidence_coefficient: float
    semantic_margin_coefficient: float


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    model: str
    dimensions: int
    timeout_seconds: int
    attempts: int
    retry_base_delay_seconds: float


@dataclass(frozen=True)
class RetrievalDefaults:
    semantic_k: int
    exact_candidate_cap: int
    keyword_block_cap: int
    keyword_page_cap: int
    hybrid_keyword_weight: float
    auto_params: AutoParams
    consensus_rrf_k: float
    consensus_weights: dict[str, float]


@dataclass(frozen=True)
class ToolConfig:
    provider: ProviderConfig
    retrieval: RetrievalDefaults


def default_config_payload() -> dict[str, Any]:
    return {
        "siliconflow": {
            "base_url": "https://api.siliconflow.cn/v1/embeddings",
            "api_key": "",
            "model": "Qwen/Qwen3-Embedding-8B",
            "dimensions": 4096,
            "timeout_seconds": 90,
            "attempts": 2,
            "retry_base_delay_seconds": 1.0
        },
        "retrieval": {
            "semantic_k": 50,
            "exact_candidate_cap": 2000,
            "keyword_block_cap": 10000,
            "keyword_page_cap": 500,
            "hybrid_keyword_weight": 0.2,
            "auto": {
                "bias": 0.0,
                "length_ratio_coefficient": -1.5,
                "lexical_confidence_coefficient": 1.5,
                "semantic_margin_coefficient": 6.0
            },
            "consensus": {
                "rrf_k": 60.0,
                "weights": {
                    "exact": 2.0,
                    "keyword": 1.0,
                    "vector": 1.0,
                    "hybrid": 0.5,
                    "auto": 0.75
                }
            }
        }
    }


def ensure_config_file_exists() -> None:
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.write_text(
        json.dumps(default_config_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def guidance_details(fields: list[str], message: str) -> dict[str, Any]:
    return {
        "config_path": str(CONFIG_PATH.resolve(strict=False)),
        "fields": fields,
        "message": message,
        "ai_instruction": (
            "请让用户提供缺失的 SiliconFlow 配置并编辑 config_path 指向的 JSON 文件；"
            "不要在最终回复或工具结果中回显 API Key 原文。"
        ),
        "expected_config": default_config_payload(),
    }


def _as_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, result)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_tool_config(*, require_provider: bool = False) -> ToolConfig:
    ensure_config_file_exists()
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        details = guidance_details(["siliconflow", "retrieval"], "请修复配置文件 JSON 格式。")
        details["parse_error"] = str(exc)
        raise ConfigError("CONFIG_INVALID", "工具配置文件不是有效 JSON。", details) from exc
    if not isinstance(payload, dict):
        raise ConfigError(
            "CONFIG_INVALID",
            "工具配置文件根节点必须是 JSON 对象。",
            guidance_details(["siliconflow", "retrieval"], "请按 expected_config 重写配置文件。"),
        )

    siliconflow = payload.get("siliconflow") if isinstance(payload.get("siliconflow"), dict) else {}
    retrieval = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
    auto = retrieval.get("auto") if isinstance(retrieval.get("auto"), dict) else {}
    consensus = retrieval.get("consensus") if isinstance(retrieval.get("consensus"), dict) else {}
    weights_raw = consensus.get("weights") if isinstance(consensus.get("weights"), dict) else {}

    provider = ProviderConfig(
        base_url=str(siliconflow.get("base_url") or "").strip(),
        api_key=str(siliconflow.get("api_key") or "").strip(),
        model=str(siliconflow.get("model") or "").strip(),
        dimensions=_as_int(siliconflow.get("dimensions"), 4096),
        timeout_seconds=_as_int(siliconflow.get("timeout_seconds"), 90),
        attempts=_as_int(siliconflow.get("attempts"), 2),
        retry_base_delay_seconds=max(0.0, _as_float(siliconflow.get("retry_base_delay_seconds"), 1.0)),
    )
    defaults = RetrievalDefaults(
        semantic_k=_as_int(retrieval.get("semantic_k"), 50),
        exact_candidate_cap=_as_int(retrieval.get("exact_candidate_cap"), 2000),
        keyword_block_cap=_as_int(retrieval.get("keyword_block_cap"), 10000),
        keyword_page_cap=_as_int(retrieval.get("keyword_page_cap"), 500),
        hybrid_keyword_weight=min(1.0, max(0.0, _as_float(retrieval.get("hybrid_keyword_weight"), 0.2))),
        auto_params=AutoParams(
            bias=_as_float(auto.get("bias"), 0.0),
            length_ratio_coefficient=_as_float(auto.get("length_ratio_coefficient"), -1.5),
            lexical_confidence_coefficient=_as_float(auto.get("lexical_confidence_coefficient"), 1.5),
            semantic_margin_coefficient=_as_float(auto.get("semantic_margin_coefficient"), 6.0),
        ),
        consensus_rrf_k=max(1.0, _as_float(consensus.get("rrf_k"), 60.0)),
        consensus_weights={
            name: _as_float(weights_raw.get(name), default)
            for name, default in {
                "exact": 2.0,
                "keyword": 1.0,
                "vector": 1.0,
                "hybrid": 0.5,
                "auto": 0.75,
            }.items()
        },
    )

    if require_provider:
        missing: list[str] = []
        if not provider.base_url:
            missing.append("siliconflow.base_url")
        if not provider.api_key:
            missing.append("siliconflow.api_key")
        if not provider.model:
            missing.append("siliconflow.model")
        if provider.dimensions <= 0:
            missing.append("siliconflow.dimensions")
        if missing:
            raise ConfigError(
                "CONFIG_MISSING",
                "向量检索所需的 SiliconFlow 配置不完整。",
                guidance_details(missing, "请补全配置后重试向量相关检索模式。"),
            )

    return ToolConfig(provider=provider, retrieval=defaults)
