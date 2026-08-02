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
  MAX_PREVIEW_LINES,
  parseCompressionLog,
} = await vite.ssrLoadModule(
  "/src/features/compression-log-preview/model/compressionLogParser.ts",
);

after(async () => {
  await vite.close();
});

test("压缩记录超过预览上限时保留最新结果", () => {
  const recordCount = MAX_PREVIEW_LINES + 5;
  const content = Array.from({ length: recordCount }, (_, index) => JSON.stringify({
    compression_id: `compression-${index + 1}`,
    status: "completed",
    source_message_count: index + 1,
    result: {
      items: [{ content: `摘要 ${index + 1}`, keywords: [] }],
      handoff: "",
    },
  })).join("\n");

  const result = parseCompressionLog(content);
  const retainedRecords = result.parsedLines.filter((line) => line.kind === "record");

  assert.equal(result.totalLineCount, recordCount);
  assert.equal(result.truncatedLineCount, 5);
  assert.equal(retainedRecords.length, MAX_PREVIEW_LINES);
  assert.equal(retainedRecords[0].record.lineNumber, 6);
  assert.equal(
    retainedRecords.at(-1).record.compressionId,
    `compression-${recordCount}`,
  );
});
