import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)),
  server: { middlewareMode: true },
});
const {
  filterLlmModelProviderGroups,
  groupLlmModelsByProvider,
  modelMatchesLlmModelSearch,
} = await vite.ssrLoadModule(
  "/src/features/llm-model-picker/model/llmModelCatalogQuery.ts",
);

after(async () => {
  await vite.close();
});

test("按首次出现顺序分组，并保留供应商内模型顺序", () => {
  const first = model({ modelId: "first", providerId: "provider-a" });
  const second = model({ modelId: "second", providerId: "provider-b" });
  const third = model({ modelId: "third", providerId: "provider-a" });

  const groups = groupLlmModelsByProvider([first, second, third]);

  assert.deepEqual(groups.map((group) => group.providerId), ["provider-a", "provider-b"]);
  assert.deepEqual(groups[0].models, [first, third]);
  assert.deepEqual(groups[1].models, [second]);
});

test("供应商命中时保留该供应商全部模型", () => {
  const groups = groupLlmModelsByProvider([
    model({ modelId: "alpha", providerId: "openai", providerLabel: "OpenAI" }),
    model({ modelId: "beta", providerId: "openai", providerLabel: "OpenAI" }),
    model({ modelId: "gamma", providerId: "other", providerLabel: "Other" }),
  ]);

  const result = filterLlmModelProviderGroups(groups, " OPENAI ");

  assert.deepEqual(result.map((group) => group.providerId), ["openai"]);
  assert.deepEqual(result[0].models.map((item) => item.modelId), ["alpha", "beta"]);
});

test("模型搜索覆盖界面现有的全部字段", () => {
  const target = model({
    capabilityTags: ["reasoning", "tool_calling"],
    familyGroup: "GPT Family",
    modelId: "gpt-5",
    modelLabel: "GPT Five",
    providerId: "provider-a",
    providerLabel: "Provider Alpha",
    source: "custom-source",
  });

  for (const query of [
    "provider-a",
    "provider alpha",
    "gpt-5",
    "gpt five",
    "gpt family",
    "custom-source",
    "tool_calling",
  ]) {
    assert.equal(modelMatchesLlmModelSearch(target, query), true, query);
  }
  assert.equal(modelMatchesLlmModelSearch(target, "unrelated"), false);
});

test("空搜索返回独立数组，避免查询结果意外修改原分组", () => {
  const groups = groupLlmModelsByProvider([model({ modelId: "alpha" })]);
  const result = filterLlmModelProviderGroups(groups, "  ");

  assert.notEqual(result, groups);
  assert.notEqual(result[0], groups[0]);
  assert.notEqual(result[0].models, groups[0].models);
  assert.deepEqual(result, groups);
});

function model(overrides = {}) {
  return {
    capabilityTags: [],
    familyGroup: "",
    modelId: "model",
    modelLabel: "Model",
    providerId: "provider",
    providerLabel: "Provider",
    source: "builtin",
    ...overrides,
  };
}
