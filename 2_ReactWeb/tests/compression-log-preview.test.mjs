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
const { parseCompressionLog } = await vite.ssrLoadModule(
  "/src/features/compression-log-preview/model/compressionLogParser.ts",
);

after(async () => {
  await vite.close();
});

test("压缩记录解析器不在前端静默截断记录", () => {
  const recordCount = 305;
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
  assert.equal(retainedRecords.length, recordCount);
  assert.equal(retainedRecords[0].record.lineNumber, 1);
  assert.equal(
    retainedRecords.at(-1).record.compressionId,
    `compression-${recordCount}`,
  );
});
