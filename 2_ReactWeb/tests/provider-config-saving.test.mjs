import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import ts from "typescript";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const rootDir = fileURLToPath(new URL("../", import.meta.url));

function moduleLoader(mocks) {
  const cache = new Map();
  function load(relative) {
    const file = path.resolve(rootDir, relative);
    if (cache.has(file)) return cache.get(file);
    const js = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: {
        module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    const module = { exports: {} };
    vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file })(
      (name) => name in mocks ? mocks[name] : name.startsWith(".")
        ? load(path.resolve(path.dirname(file), `${name}.ts`)) : require(name),
      module, module.exports,
    );
    cache.set(file, module.exports);
    return module.exports;
  }
  return load;
}

const protocol = "openai_compatible";
const url = "https://initial.invalid/v1/chat/completions";
const provider = {
  provider_id: "test-provider", display_name: "Test", protocol_family: protocol,
  api_base_url: url, generation_urls: { [protocol]: url },
  preset_generation_urls: { [protocol]: url },
  generation_auth_schemes: { [protocol]: "bearer_token" }, auth_scheme: "bearer_token",
  model_discovery_url: "https://initial.invalid/v1/models",
  preset_model_discovery_url: "https://initial.invalid/v1/models",
  model_discovery_strategy: "openai_models", model_discovery_auth_scheme: "bearer_token",
};
const initial = {
  ...provider, api_keys: [], enabled: false, reasoning_replay_mode: "never",
  prompt_cache_retention_seconds: 300, updated_at: "t0",
};

async function mountEditor(t) {
  const requests = [];
  const record = (kind, providerId, payload) => new Promise((resolve, reject) => {
    requests.push({ kind, providerId, payload, reject, finish: () => resolve(kind === "config"
      ? { ...initial, ...payload, provider_id: providerId, api_keys: [],
        generation_urls: { [protocol]: payload.api_base_url }, updated_at: `t${requests.length}` }
      : { prompt_cache_retention_seconds: payload }) });
  });
  const providers = [provider, { ...provider, provider_id: "other-provider" }];
  const load = moduleLoader({
    "../../../services/llm/getProviderConfigs": {
      getProviderConfigs: async () => ({ items: providers.map(p => ({ ...initial, provider_id: p.provider_id })) }),
    },
    "../../../services/llm/saveProviderConfig": { saveProviderConfig: (id, data) => record("config", id, data) },
    "../../../services/llm/saveProviderPromptCachePolicy": { saveProviderPromptCachePolicy: (id, data) => record("cache", id, data) },
    "../../../entities/llm-usage/model/usageRefreshEvents": { subscribeLlmUsageChanged: () => () => {} },
    "../../../entities/llm-provider/model/modelCatalogEvents": { emitLlmModelCatalogChanged: () => {} },
  });
  const { useProviderConfigState } = load("src/features/provider-config/model/useProviderConfigState.ts");
  let current, renderer;
  function Harness({ id }) { current = useProviderConfigState(providers, id); return null; }
  await act(async () => { renderer = create(React.createElement(Harness, { id: provider.provider_id })); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  return { get current() { return current; }, requests,
    select: async id => act(async () => renderer.update(React.createElement(Harness, { id }))),
  };
}

test("pending save blocks edits and duplicate requests before controls rerender; completion unlocks", async t => {
  const editor = await mountEditor(t);
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://first.invalid/v1/chat/completions"));
  const snapshot = editor.current.selectedDraft;
  const handlers = editor.current;
  let first, duplicate;
  await act(async () => {
    first = handlers.saveSelectedProviderConfig();
    duplicate = handlers.saveSelectedProviderConfig();
    handlers.updateSelectedApiBaseUrl("https://blocked.invalid");
    handlers.updateSelectedModelDiscoveryUrl("https://blocked.invalid/models");
    handlers.updateSelectedApiKey(snapshot.apiKeys[0].id, "fake-key");
    handlers.updateSelectedApiKeyPollWeight(snapshot.apiKeys[0].id, "7");
    handlers.clearSelectedApiKey(snapshot.apiKeys[0].id);
    handlers.addSelectedApiKey();
    handlers.removeSelectedApiKeyIfEmpty(snapshot.apiKeys[0].id);
    handlers.resetSelectedApiBaseUrl();
    handlers.resetSelectedModelDiscoveryUrl();
    handlers.toggleSelectedEnabled();
    handlers.updateSelectedAuthScheme("api_key_query");
    handlers.updateSelectedModelDiscoveryStrategy("gemini_models");
    handlers.updateSelectedModelDiscoveryAuthScheme("api_key_query");
    handlers.updateSelectedReasoningReplayMode("always");
    handlers.updateSelectedPromptCacheRetentionValue("20");
    handlers.updateSelectedPromptCacheRetentionUnit("hours");
  });
  assert.equal(await duplicate, false);
  assert.equal(editor.requests.length, 1);
  assert.equal(editor.current.savingProviderId, provider.provider_id);
  assert.equal(editor.current.selectedDraft, snapshot);
  await act(async () => { editor.requests[0].finish(); assert.equal(await first, true); });
  assert.equal(editor.current.savingProviderId, null);
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://newest.invalid/v1/chat/completions"));
  let second;
  await act(async () => { second = editor.current.saveSelectedProviderConfig(); });
  assert.equal(editor.requests[1].payload.api_base_url, "https://newest.invalid/v1/chat/completions");
  await act(async () => { editor.requests[1].finish(); await second; });
  assert.equal(editor.current.selectedDraft.apiBaseUrl, "https://newest.invalid/v1/chat/completions");
});

test("failed save preserves the draft and unlocks editing and retry", async t => {
  const editor = await mountEditor(t);
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://edited.invalid"));
  let saving;
  await act(async () => { saving = editor.current.saveSelectedProviderConfig(); });
  await act(async () => { editor.requests[0].reject(new Error("simulated save failure")); assert.equal(await saving, false); });
  assert.equal(editor.current.savingProviderId, null);
  assert.equal(editor.current.error, "simulated save failure");
  assert.equal(editor.current.selectedDraft.apiBaseUrl, "https://edited.invalid");
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://retry.invalid"));
  await act(async () => { saving = editor.current.saveSelectedProviderConfig(); });
  await act(async () => { editor.requests[1].finish(); await saving; });
  assert.equal(editor.current.selectedDraft.apiBaseUrl, "https://retry.invalid");
  assert.equal(editor.current.error, null);
});

for (const firstKind of ["config", "cache"]) {
  test(`${firstKind} save excludes the other save path until completion`, async t => {
    const editor = await mountEditor(t);
    let saving, blocked;
    await act(async () => {
      saving = firstKind === "config" ? editor.current.saveSelectedProviderConfig() : editor.current.saveSelectedPromptCachePolicy();
      blocked = firstKind === "config" ? editor.current.saveSelectedPromptCachePolicy() : editor.current.saveSelectedProviderConfig();
    });
    assert.equal(await blocked, false);
    assert.equal(editor.requests.length, 1);
    assert.equal(editor.requests[0].kind, firstKind);
    await act(async () => { editor.requests[0].finish(); await saving; });
    assert.equal(editor.current.savingProviderId, null);
  });
}

test("failed cache save also unlocks the configuration and retains its edited value", async t => {
  const editor = await mountEditor(t);
  await act(async () => editor.current.updateSelectedPromptCacheRetentionValue("15"));
  let saving;
  await act(async () => { saving = editor.current.saveSelectedPromptCachePolicy(); });
  await act(async () => {
    editor.requests[0].reject(new Error("simulated cache failure"));
    assert.equal(await saving, false);
  });
  assert.equal(editor.current.savingProviderId, null);
  assert.equal(editor.current.selectedDraft.promptCacheRetentionValue, "15");
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://after-failure.invalid"));
  assert.equal(editor.current.selectedDraft.apiBaseUrl, "https://after-failure.invalid");
});

test("switching providers during a save keeps the lock and applies the response to its owner", async t => {
  const editor = await mountEditor(t);
  let saving;
  await act(async () => { saving = editor.current.saveSelectedProviderConfig(); });
  await editor.select("other-provider");
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://blocked.invalid"));
  assert.equal(editor.current.selectedDraft.apiBaseUrl, url);
  assert.equal(editor.current.savingProviderId, provider.provider_id);
  await act(async () => { editor.requests[0].finish(); await saving; });
  await act(async () => editor.current.updateSelectedApiBaseUrl("https://other.invalid"));
  assert.equal(editor.current.selectedDraft.apiBaseUrl, "https://other.invalid");
});

test("entering a first key still automatically enables the provider and saves both changes", async t => {
  const editor = await mountEditor(t);
  assert.equal(editor.current.selectedDraft.enabled, false);
  const id = editor.current.selectedDraft.apiKeys[0].id;
  await act(async () => editor.current.updateSelectedApiKey(id, "fake-new-key"));
  assert.equal(editor.current.selectedDraft.enabled, true);
  let saving;
  await act(async () => { saving = editor.current.saveSelectedProviderConfig(); });
  assert.equal(editor.requests[0].payload.enabled, true);
  assert.equal(editor.requests[0].payload.api_keys[0].api_key, "fake-new-key");
  await act(async () => { editor.requests[0].finish(); await saving; });
});

test("key rules preserve manual enable choices while fresh key input still enables", () => {
  const load = moduleLoader({});
  const { resolveEnabledForApiKeys, resolveEnabledAfterApiKeyEdit } = load(
    "src/features/provider-config/model/providerConfigDraftRules.ts",
  );
  const stored = [{ id: "key", value: "", hasStoredApiKey: true }];
  const pending = [{ id: "key", value: "new-key", hasStoredApiKey: false }];
  const manualOff = { enabled: false, hasManualEnabledOverride: true };
  const automatic = { enabled: true, hasManualEnabledOverride: false };
  assert.equal(resolveEnabledForApiKeys(manualOff, stored), false);
  assert.equal(resolveEnabledAfterApiKeyEdit(manualOff, stored), false);
  assert.equal(resolveEnabledAfterApiKeyEdit(manualOff, pending), true);
  assert.equal(resolveEnabledForApiKeys(automatic, []), false);
  assert.equal(resolveEnabledForApiKeys(automatic, stored), true);
  assert.equal(resolveEnabledForApiKeys({ enabled: true, hasManualEnabledOverride: true }, []), true);
});

for (const mode of ["api-key", "generation", "models", "other"]) {
  test(`${mode} controls disable while saving and re-enable afterward`, async t => {
    const load = moduleLoader({
      "../../../shared/i18n": { useI18n: () => ({ t: key => key }) },
      "../../../shared/ui/option-select/OptionSelect": {
        OptionSelect: props => React.createElement("button", { disabled: props.disabled, "aria-label": props.ariaLabel }),
      },
    });
    const { ProviderApiBaseUrlSection, ProviderOtherSettingsSection } = load("src/features/provider-config/ui/ProviderConfigSections.tsx");
    const { mergeProviderDraftAfterSave } = load("src/features/provider-config/model/providerConfigDraftRules.ts");
    const draft = mergeProviderDraftAfterSave(provider, initial);
    const state = { savingProviderId: provider.provider_id, selectedDraft: draft,
      isSelectedApiBaseUrlDirty: true, isSelectedModelDiscoveryUrlDirty: true };
    const Component = mode === "other" ? ProviderOtherSettingsSection : ProviderApiBaseUrlSection;
    const props = { apiKeyInputRefs: { current: new Map() }, providerConfigState: state,
      selectedProviderDraft: draft, providerDisplayName: "Test", isUpdatingProviderProtocol: false,
      protocolFamily: protocol, onUpdateProviderProtocol: () => {} };
    let renderer;
    await act(async () => { renderer = create(React.createElement(Component, props)); });
    t.after(async () => { await act(async () => renderer.unmount()); });
    if (mode === "generation" || mode === "models") {
      await act(async () => renderer.root.findByProps({ id: `provider-api-address-tab-${mode}` }).props.onClick());
    }
    const controls = () => renderer.root.findAll(node => node.type === "input"
      || (node.type === "button" && node.props.role !== "tab"));
    assert.ok(controls().length > 1);
    assert.ok(controls().every(node => node.props.disabled === true));
    await act(async () => renderer.update(React.createElement(Component, { ...props,
      providerConfigState: { ...state, savingProviderId: null } })));
    assert.ok(controls().every(node => node.props.disabled === false));
  });
}
