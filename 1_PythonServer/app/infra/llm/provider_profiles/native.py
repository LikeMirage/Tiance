from dataclasses import dataclass, replace

from app.domain.llm.provider_catalog import ProviderCatalogEntry
from app.domain.llm.runtime_capabilities import LlmRuntimeCapabilities
from app.infra.llm.provider_profiles.base import GenericOpenAICompatibleProfile


@dataclass(frozen=True, slots=True)
class NativeChatProfile(GenericOpenAICompatibleProfile):
    """Keep declared sampling capabilities within what the native adapter sends."""

    sampling_parameters: tuple[str, ...] = ("temperature", "top_p")

    def resolve_capabilities(
        self,
        provider_template: ProviderCatalogEntry,
        model_id: str | None,
    ) -> LlmRuntimeCapabilities:
        capabilities = GenericOpenAICompatibleProfile.resolve_capabilities(
            self, provider_template, model_id,
        )
        sampling = capabilities.sampling
        parameters = tuple(
            name for name in sampling.parameters if name in self.sampling_parameters
        )
        return replace(
            capabilities,
            sampling=replace(sampling, supported=sampling.supported and bool(parameters), parameters=parameters),
        )
