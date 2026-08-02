import pytest

from app.domain.llm.discovered_model import DiscoveredModel
from app.services.llm.provider.custom_models import _normalize_capability_tags
from app.services.llm.provider.discovered_model_metadata import enrich_discovered_model


@pytest.mark.parametrize(
    "model_id",
    (
        "gpt-4o",
        "claude-sonnet-4-5",
        "gemini-2.5-pro",
        "qwen2.5-vl-72b-instruct",
        "doubao-seed-2-0-pro-260215",
    ),
)
def test_chat_vision_models_receive_vision_tag(model_id: str):
    model = enrich_discovered_model(_model(model_id))

    assert "vision" in model.capability_tags
    assert "image_generation" not in model.capability_tags
    assert "video_generation" not in model.capability_tags


def test_explicit_image_input_modality_receives_vision_tag():
    model = enrich_discovered_model(
        _model(
            "vendor-multimodal-chat",
            raw_payload={"input_modalities": ["text", "image"]},
        )
    )

    assert "vision" in model.capability_tags


@pytest.mark.parametrize(
    ("model_id", "expected_tag"),
    (
        ("gpt-image-1", "image_generation"),
        ("cogview-4", "image_generation"),
        ("seedance-1-5-pro", "video_generation"),
        ("sora-2", "video_generation"),
    ),
)
def test_generation_models_keep_image_input_and_generation_capabilities(
    model_id: str,
    expected_tag: str,
):
    model = enrich_discovered_model(_model(model_id))

    assert expected_tag in model.capability_tags
    assert "vision" in model.capability_tags
    assert "function_calling" not in model.capability_tags


def test_output_modality_adds_generation_and_image_input_capabilities():
    model = enrich_discovered_model(
        _model(
            "vendor-render-model",
            raw_payload={"output_modalities": ["image"]},
        )
    )

    assert model.capability_tags == ("vision", "image_generation")


def test_saved_capability_tags_are_normalized_for_runtime_lookup():
    assert _normalize_capability_tags((" Vision ", "vision", "REASONING")) == (
        "vision",
        "reasoning",
    )


def _model(
    model_id: str,
    *,
    raw_payload: dict[str, object] | None = None,
) -> DiscoveredModel:
    return DiscoveredModel(
        model_id=model_id,
        display_name=model_id,
        provider_id="provider-1",
        raw_payload=raw_payload,
    )
