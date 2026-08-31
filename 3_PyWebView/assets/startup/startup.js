const startup = __TIANCE_STARTUP_STATE__;
const startupConfig = __TIANCE_STARTUP_CONFIG__;
let startupAttempt = 0;

startStartup();

function setTitlebarVisible(visible) {
  document.body.dataset.titlebarVisible = visible ? "true" : "false";
}

function setPageState(state) {
  document.getElementById("loader")?.setAttribute("data-state", state);
  if (state === "error") {
    setTitlebarVisible(true);
  }
}

function setText(id, text) {
  const element = document.getElementById(id);
  if (element) element.textContent = text;
}

function waitForShellApi() {
  if (window.pywebview?.api) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let didResolve = false;
    const finish = () => {
      if (didResolve) return;
      didResolve = true;
      resolve();
    };
    window.addEventListener("pywebviewready", finish, { once: true });
    document.addEventListener("pywebviewready", finish, { once: true });
    window.setTimeout(finish, 1000);
  });
}

async function revealWindow() {
  await waitForShellApi();
  const callReveal = async () => {
    try {
      await window.pywebview?.api?.reveal_window?.();
    } catch (_error) {}
  };
  await callReveal();
}

async function ensureBackendRunning() {
  await waitForShellApi();
  const ensureBackend = window.pywebview?.api?.ensure_backend_running;
  if (typeof ensureBackend !== "function") {
    return { ok: true };
  }

  try {
    return await ensureBackend();
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

async function canReach(url, timeoutMs = startupConfig.defaultTimeoutMs) {
  const shellUrlCheck = window.pywebview?.api?.check_url_available;
  if (typeof shellUrlCheck === "function") {
    try {
      return await shellUrlCheck(url, timeoutMs);
    } catch (_error) {
      return false;
    }
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    await fetch(url, {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      signal: controller.signal,
    });
    return true;
  } catch (_error) {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function haveSameOrigin(firstUrl, secondUrl) {
  try {
    return new URL(firstUrl).origin === new URL(secondUrl).origin;
  } catch (_error) {
    return false;
  }
}

async function canReachDevFrontend() {
  if (haveSameOrigin(startup.devUrl, startup.apiUrl)) {
    return false;
  }

  try {
    const viteClientUrl = new URL("/@vite/client", startup.devUrl);
    return await canReach(viteClientUrl.toString(), startupConfig.devTimeoutMs);
  } catch (_error) {
    return false;
  }
}

function withBootState(url, statusText) {
  try {
    const nextUrl = new URL(url, window.location.href);
    const bootState = new URLSearchParams();
    bootState.set("tianceApiBaseUrl", startup.apiUrl);
    bootState.set("tianceBootTheme", JSON.stringify(startup.bootTheme));
    bootState.set("tianceBootStatus", statusText);
    nextUrl.hash = bootState.toString();
    return nextUrl.toString();
  } catch (_error) {
    return url;
  }
}

function getRetryDelay() {
  return startupAttempt <= startupConfig.fastRetryAttempts
    ? startupConfig.fastRetryDelayMs
    : startupConfig.retryDelayMs;
}

async function runStartupCheck() {
  startupAttempt += 1;
  setPageState("loading");
  setText("summary", startupAttempt === 1 ? "正在启动后端服务" : "正在等待后端服务");
  const backendResult = await ensureBackendRunning();
  if (!backendResult?.ok) {
    setPageState("error");
    setText("summary", "启动失败");
    const backendError =
      typeof backendResult?.error === "string" ? backendResult.error.trim() : "";
    setText(
      "hint",
      backendError
        ? `后端服务启动失败：${backendError}`
        : "后端服务启动失败，请重试。",
    );
    return;
  }

  setText("summary", "正在等待后端服务");
  if (!(await canReach(startup.gatewayHealthUrl, startupConfig.apiTimeoutMs))) {
    if (startupAttempt >= startupConfig.maxAttempts) {
      setPageState("error");
      setText("summary", "启动失败");
      setText("hint", "后端服务长时间未就绪，请关闭后重新启动。");
      return;
    }
    window.setTimeout(runStartupCheck, getRetryDelay());
    return;
  }

  setText("summary", "后端已就绪，正在检测前端开发服务");
  if (await canReachDevFrontend()) {
    setText("summary", "正在进入开发服务");
    window.location.replace(withBootState(startup.devUrl, "正在加载开发服务界面"));
    return;
  }

  setText("summary", "正在检查本地页面");
  if (!startup.distExists) {
    setPageState("error");
    setText("summary", "启动未完成");
    setText("hint", "请先启动前端开发服务，或构建本地页面后重试。");
    return;
  }

  setText("summary", "正在进入本地页面");
  if (await canReach(startup.appUrl, startupConfig.appTimeoutMs)) {
    setText("summary", "正在打开应用");
    window.location.replace(withBootState(startup.appUrl, "正在加载本地界面"));
    return;
  }

  if (startupAttempt >= startupConfig.maxAttempts) {
    setPageState("error");
    setText("summary", "启动失败");
    setText("hint", "本地页面服务长时间不可用，请关闭后重新启动。");
    return;
  }
  window.setTimeout(runStartupCheck, getRetryDelay());
}

async function startStartup() {
  await revealWindow();
  window.setTimeout(runStartupCheck, startupConfig.initialDelayMs);
}

document.getElementById("open-target")?.addEventListener("click", () => {
  startupAttempt = 0;
  setTitlebarVisible(false);
  runStartupCheck();
});

document.getElementById("reload-page")?.addEventListener("click", () => {
  window.location.reload();
});

document.getElementById("minimize-window")?.addEventListener("click", async () => {
  try {
    await window.pywebview?.api?.minimize_window?.();
  } catch (_error) {}
});

document.getElementById("close-window")?.addEventListener("click", async () => {
  try {
    await window.pywebview?.api?.close_window?.();
  } catch (_error) {
    window.close();
  }
});
