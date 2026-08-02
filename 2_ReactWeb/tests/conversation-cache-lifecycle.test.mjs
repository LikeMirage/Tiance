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
const { ConversationDraftProtectionStore } = await vite.ssrLoadModule(
  "/src/features/ai-panel/model/conversationDraftProtectionStore.ts",
);

after(async () => {
  await vite.close();
});

test("草稿保存后仍保护在途旧读取，读取结束后释放副本", () => {
  const store = new ConversationDraftProtectionStore();
  store.rememberPendingDraft("project-1", "session-1", "最新草稿");
  const request = store.snapshotRequest("project-1");
  store.clearPendingDraft("project-1", "session-1", "最新草稿");

  const protectedStates = store.mergeProtectedDrafts(
    "project-1",
    { "session-1": sessionState("旧草稿") },
    request,
  );
  assert.equal(protectedStates["session-1"].draft, "最新草稿");

  store.releaseRequest("project-1", request);
  const laterRequest = store.snapshotRequest("project-1");
  const releasedStates = store.mergeProtectedDrafts(
    "project-1",
    { "session-1": sessionState("后端草稿") },
    laterRequest,
  );
  assert.equal(releasedStates["session-1"].draft, "后端草稿");
  store.releaseRequest("project-1", laterRequest);
});

test("保存旧版本完成时不会清掉随后输入的新草稿", () => {
  const store = new ConversationDraftProtectionStore();
  store.rememberPendingDraft("project-1", "session-1", "版本一");
  const request = store.snapshotRequest("project-1");
  store.rememberPendingDraft("project-1", "session-1", "版本二");
  store.clearPendingDraft("project-1", "session-1", "版本一");

  const merged = store.mergeProtectedDrafts(
    "project-1",
    { "session-1": sessionState("版本一") },
    request,
  );
  assert.equal(merged["session-1"].draft, "版本二");
  store.releaseRequest("project-1", request);
});

function sessionState(draft) {
  return {
    draft,
    references: { files: [], images: [] },
    runtime_status: "idle",
    updated_at: "now",
  };
}
