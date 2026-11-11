import assert from "node:assert/strict";
import { after, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const vite = await createServer({ appType: "custom", logLevel: "silent",
  root: fileURLToPath(new URL("../", import.meta.url)), server: { middlewareMode: true } });
after(() => vite.close());
const { useMobileDesktopBridge } = await vite.ssrLoadModule("/src/features/mobile-access/model/useMobileDesktopBridge.ts");

test("手机请求读取指定会话配置，重试传输不改变目标或桌面草稿", async () => {
  const previous = globalThis.fetch;
  const calls=[];
  const job={id:"j",project_id:"remote-project",session_id:"remote-session",user_message_id:"mobile_j",content:"hello",references:[]};
  let prepared=0;
  globalThis.fetch=async (url,init) => {
    calls.push(String(url));
    if(String(url).endsWith("/release")) return Response.json({ok:true});
    if(String(url).includes("/poll?")) return Response.json({preparations:prepared<2?[job]:[],events:[]});
    if(String(url).endsWith("/detail")) return Response.json({session:{model_id:"saved-model",provider_id:"saved-provider",reasoning_mode:null,
      settings:{max_output_tokens:8192,upstream_retry_count:3,upstream_retry_interval_seconds:17,tools_enabled:true}}});
    if(String(url).endsWith("/prepare")) {
      prepared++;
      const {payload}=JSON.parse(init.body);
      assert.equal(payload.project_id,"remote-project"); assert.equal(payload.session_id,"remote-session");
      assert.equal(payload.model_id,"saved-model"); assert.equal(payload.upstream_retry_interval_seconds,17);
      assert.equal(payload.messages[0].message_id,"mobile_j");
      assert.deepEqual(payload.client_capabilities,[{name:"test",version:1}]);
      if(prepared===1) throw new Error("temporary disconnect");
      return Response.json({ok:true});
    }
    throw new Error(`Unexpected endpoint: ${url}`);
  };
  const executor={current:null}; const capabilities={current:[{name:"test",version:1}]};
  function Probe(){useMobileDesktopBridge(executor,capabilities);return null;}
  let view;
  try {
    await act(async()=>{view=create(createElement(Probe));});
    await new Promise(resolve=>setTimeout(resolve,1300));
    assert.equal(prepared,2);
    assert.ok(calls.filter(p=>p.endsWith("/detail")).every(p=>p.includes("remote-project/conversations/remote-session")));
    assert.equal(calls.some(p=>p.endsWith("/state") || p.includes("/active")),false);
  } finally {
    await act(async()=>view?.unmount());globalThis.fetch=previous;
  }
});
