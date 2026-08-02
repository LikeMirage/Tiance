import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveCollapseBottomViewportOffset,
  resolveCollapseScrollAdjustment,
} from "../src/features/ai-panel/model/useAssistantProcessAutoCollapse.ts";

test("折叠区域起点位于当前视口下方时不改变阅读位置", () => {
  assert.equal(
    resolveCollapseBottomViewportOffset({
      regionBottom: 900,
      regionTop: 700,
      viewportBottom: 600,
      viewportTop: 100,
    }),
    null,
  );
});

test("用户已经看到折叠区域下方时保持区域底部的视口位置", () => {
  assert.equal(
    resolveCollapseBottomViewportOffset({
      regionBottom: 320,
      regionTop: -400,
      viewportBottom: 600,
      viewportTop: 100,
    }),
    220,
  );
  assert.equal(resolveCollapseScrollAdjustment(-280, 220), -500);
});

test("用户位于即将收起的长处理过程内部时让后续内容接到视口顶部", () => {
  assert.equal(
    resolveCollapseBottomViewportOffset({
      regionBottom: 1200,
      regionTop: -600,
      viewportBottom: 600,
      viewportTop: 100,
    }),
    8,
  );
  assert.equal(resolveCollapseScrollAdjustment(-550, 8), -558);
});

test("浏览器已经完成相同锚定时不重复补偿", () => {
  assert.equal(resolveCollapseScrollAdjustment(220, 220), 0);
});
