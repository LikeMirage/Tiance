"""Use the same model catalog and partial session update as the desktop picker."""
from app.core.errors import BadRequestError
from app.services.llm.model_catalog import get_llm_model_catalog_service
from app.services.project import get_project_conversation_service
from .context import resolve_target


def available_models():
    return get_llm_model_catalog_service().list_models(enabled_only=True, kind='chat')


def select_model(target, provider_id, model_id):
    resolve_target(target)
    model = next((m for m in available_models()
                  if m.provider_id == provider_id and m.model_id == model_id), None)
    if model is None:
        raise BadRequestError('该模型已移除或供应商已停用，请重新选择模型。')
    # A partial update deliberately preserves the role prompt, reasoning setting,
    # tool permissions, draft and every other conversation setting.
    get_project_conversation_service().update_session(
        target['project_id'], target['session_id'],
        provider_id=provider_id, should_update_provider=True,
        model_id=model_id, should_update_model=True,
    )
    return model
