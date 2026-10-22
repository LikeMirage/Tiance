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

const modelPath = "src/features/provider-model-management/model/";
async function mountDraft(t, initialModels = []) {
  const requests = [], saves = [];
  const load = moduleLoader({
    "../../../shared/i18n": { useI18n: () => ({ t: key => key }) },
    "../../../services/llm/inferProviderModelMetadata": {
      inferProviderModelMetadata: (id, input) => new Promise((resolve, reject) => {
        requests.push({ id, input, reject, finish: tags => resolve({
          provider_id: id, model_id: input.model_id, display_name: input.display_name,
          family_group: input.family_group || "new-family", capability_tags: tags,
        }) });
      }),
    },
    "../../../services/llm/saveProviderCustomModel": {
      saveProviderCustomModel: async (id, input) => {
        saves.push({ id, input });
        return { ...input, provider_id: id };
      },
    },
    "../../../entities/llm-provider/model/modelCatalogEvents": { emitLlmModelCatalogChanged: () => {} },
    "../../../entities/llm-usage/model/usageRefreshEvents": { emitLlmUsageChanged: () => {} },
  });
  const { useCustomModelDraft } = load(modelPath + "useCustomModelDraft.ts");
  let current, error, renderer;
  function Harness({ id }) {
    const providerRef = React.useRef(id);
    providerRef.current = id;
    const [models, setModels] = React.useState(initialModels);
    const [lastError, setError] = React.useState(null);
    error = lastError;
    current = useCustomModelDraft({
      addedCustomModels: models, selectedProviderId: id, selectedProviderIdRef: providerRef,
      setAddedCustomModels: setModels, setCustomModelError: setError,
      selectCustomMode: () => {}, selectAddedMode: () => {},
    });
    return null;
  }
  await act(async () => { renderer = create(React.createElement(Harness, { id: "provider-a" })); });
  t.after(async () => { await act(async () => renderer.unmount()); });
  return { get current() { return current; }, get error() { return error; }, requests, saves,
    select: async id => act(async () => renderer.update(React.createElement(Harness, { id }))),
    change: async (field, value) => act(async () => current.updateCustomModelDraft(field, value)),
    infer: async () => { await act(async () => { void current.inferCustomModelCapabilities(); }); },
  };
}

// Responses are deliberately delayed to exercise user edits while inference is in flight.
test("late inference respects a manual removal and manual addition", async t => {
  const e = await mountDraft(t);
  await e.change("modelId", "deepseek-flash");
  await e.infer();
  await act(async () => e.requests[0].finish(["reasoning", "vision"]));
  await e.infer();
  await act(async () => {
    e.current.toggleCustomModelCapability("vision");
    e.current.toggleCustomModelCapability("tts");
  });
  await act(async () => e.requests[1].finish(["vision", "function_calling"]));
  assert.deepEqual(e.current.customModelDraft.capabilityTags, ["function_calling", "tts"]);
});

test("an older model's response cannot replace the latest draft", async t => {
  const e = await mountDraft(t);
  await e.change("modelId", "old-model");
  await e.infer();
  await e.change("modelId", "new-model");
  await e.infer();
  await act(async () => e.requests[1].finish(["tts"]));
  await act(async () => e.requests[0].finish(["vision"]));
  assert.deepEqual(e.current.customModelDraft.capabilityTags, ["tts"]);
});

test("clear and provider switch discard pending inference", async t => {
  const e = await mountDraft(t);
  await e.change("modelId", "old-model");
  await e.infer();
  await act(async () => e.current.clearCustomModelDraft());
  await act(async () => e.requests[0].finish(["vision"]));
  assert.deepEqual(e.current.customModelDraft.capabilityTags, []);
  await e.change("modelId", "another-model");
  await e.infer();
  await e.select("provider-b");
  await act(async () => e.requests[1].finish(["vision"]));
  assert.deepEqual(e.current.customModelDraft.capabilityTags, []);
  await e.select("provider-a");
  assert.deepEqual(e.current.customModelDraft.capabilityTags, []);
});

test("saving a new model waits for inference and persists the user's removal and inferred family", async t => {
  const e = await mountDraft(t);
  await e.change("modelId", "new-model");
  await e.infer();
  await act(async () => e.requests[0].finish(["vision", "reasoning"]));
  await act(async () => e.current.toggleCustomModelCapability("vision"));
  let saving;
  await act(async () => { saving = e.current.saveCustomModelDraft(); });
  assert.equal(e.saves.length, 0);
  await act(async () => { e.requests[1].finish(["vision", "reasoning"]); await saving; });
  assert.deepEqual(e.saves[0].input.capability_tags, ["reasoning"]);
  assert.equal(e.saves[0].input.family_group, "new-family");
});

test("editing an existing model never reinfers labels even when its name changes", async t => {
  const existing = { modelId: "deepseek-flash", displayName: "Old", familyGroup: "family",
    capabilityTags: [], note: "", priceCurrency: "CNY", inputPricePerMillion: null,
    cacheHitPricePerMillion: null, outputPricePerMillion: null };
  const e = await mountDraft(t, [existing]);
  await act(async () => e.current.startEditingCustomModel(existing.modelId));
  await e.change("displayName", "New vision name");
  await e.infer();
  await act(async () => e.current.saveCustomModelDraft());
  assert.equal(e.requests.length, 0);
  assert.deepEqual(e.saves[0].input.capability_tags, []);
});

test("inference failure does not block saving manual labels", async t => {
  const e = await mountDraft(t);
  await e.change("modelId", "model");
  await act(async () => e.current.toggleCustomModelCapability("vision"));
  let saving;
  await act(async () => { saving = e.current.saveCustomModelDraft(); });
  await act(async () => { e.requests[0].reject(new Error("offline")); await saving; });
  assert.equal(e.saves.length, 1);
  assert.deepEqual(e.saves[0].input.capability_tags, ["vision"]);
});
