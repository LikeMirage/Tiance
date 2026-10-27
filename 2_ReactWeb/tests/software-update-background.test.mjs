import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "vite";

const vite = await createServer({ server: { middlewareMode: true }, appType: "custom", logLevel: "error" });
const { createSoftwareUpdateStore } = await vite.ssrLoadModule("/src/features/software-update/model/softwareUpdateStore.ts");
after(() => vite.close());

const release = { currentVersion: "0.3.31", latestVersion: "0.3.32", updateAvailable: true, sourceCheckout: false };
const staged = { version: "0.3.32", stagePath: "C:/Temp/update", packageSize: 20 };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test("closing and unsubscribing during slow download preserves the job and requires explicit restart", async () => {
  const pending = deferred();
  let downloads = 0, installs = 0;
  const store = createSoftwareUpdateStore({
    check: async () => release, checkOnStartup: async () => release,
    download: () => { downloads++; return pending.promise; },
    install: async (value) => { assert.equal(value, staged); installs++; },
  });
  const unsubscribe = store.subscribe(() => {});
  await store.checkOnStartup();
  assert.equal(store.getSnapshot().prompt, "offer");
  const operation = store.install();
  store.dismiss();
  unsubscribe();
  assert.equal(store.getSnapshot().state, "downloading");
  assert.equal(store.getSnapshot().prompt, null);
  await store.install(); // A second entry point must not start another download.
  await store.check();
  assert.equal(downloads, 1);
  pending.resolve(staged);
  await operation;
  assert.equal(store.getSnapshot().state, "ready");
  assert.equal(store.getSnapshot().prompt, "restart");
  assert.equal(installs, 0);
  store.dismiss(); // Later preserves the staged package.
  await store.install();
  assert.equal(downloads, 1);
  assert.equal(store.getSnapshot().prompt, "restart");
  await Promise.all([store.restart(), store.restart()]);
  assert.equal(installs, 1);
});

test("failed download can be retried and failed restart keeps the checked package", async () => {
  let downloads = 0, installs = 0;
  const store = createSoftwareUpdateStore({
    check: async () => release, checkOnStartup: async () => release,
    download: async () => { if (++downloads === 1) throw new Error("offline"); return staged; },
    install: async () => { if (++installs === 1) throw new Error("exit failed"); },
  });
  await store.check();
  await store.install();
  assert.equal(store.getSnapshot().error, "offline");
  assert.equal(store.getSnapshot().state, "idle");
  await store.install();
  await store.restart();
  assert.equal(store.getSnapshot().state, "ready");
  assert.equal(store.getSnapshot().download, staged);
  assert.equal(store.getSnapshot().error, "exit failed");
  await store.restart();
  assert.equal(downloads, 2);
  assert.equal(installs, 2);
});

test("startup checks are single flight and source checkouts cannot install", async () => {
  const pending = deferred();
  let checks = 0, downloads = 0;
  const store = createSoftwareUpdateStore({
    check: async () => release,
    checkOnStartup: () => { checks++; return pending.promise; },
    download: async () => { downloads++; return staged; }, install: async () => {},
  });
  const operation = store.checkOnStartup();
  await store.checkOnStartup();
  pending.resolve({ ...release, sourceCheckout: true });
  await operation;
  await store.install();
  assert.equal(checks, 1);
  assert.equal(downloads, 0);
  assert.equal(store.getSnapshot().prompt, null);
});
