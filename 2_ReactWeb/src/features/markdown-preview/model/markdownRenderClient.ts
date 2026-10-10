import type { MarkdownRenderDocument } from "./markdownRenderDocument";

type WorkerPort = Pick<Worker, "postMessage" | "terminate" | "onmessage" | "onerror" | "onmessageerror">;
type Subscriber = { resolve: (document: MarkdownRenderDocument) => void; reject: (error: Error) => void };
type Job = { id: number; content: string; subscribers: Set<Subscriber> };

export function createMarkdownRenderClient(createWorker: () => WorkerPort, maxCachedChars = 16_000_000) {
  let nextId = 0;
  let worker: WorkerPort | null = null;
  let active: Job | null = null;
  let cachedChars = 0;
  const cache = new Map<string, MarkdownRenderDocument>();
  const jobs = new Map<string, Job>();
  const queue: Job[] = [];
  const disposeWorker = () => { worker?.terminate(); worker = null; };
  const getCached = (content: string) => {
    const document = cache.get(content);
    if (document) { cache.delete(content); cache.set(content, document); }
    return document;
  };
  const remember = (content: string, document: MarkdownRenderDocument) => {
    if (document.cacheWeight > maxCachedChars) return;
    cache.set(content, document);
    cachedChars += document.cacheWeight;
    while (cachedChars > maxCachedChars || cache.size > 128) {
      const oldest = cache.entries().next().value!;
      cache.delete(oldest[0]);
      cachedChars -= oldest[1].cacheWeight;
    }
  };
  const complete = (job: Job, document?: MarkdownRenderDocument, error?: Error) => {
    jobs.delete(job.content);
    if (document) remember(job.content, document);
    job.subscribers.forEach((subscriber) => document ? subscriber.resolve(document) : subscriber.reject(error!));
  };
  const pump = () => {
    if (active || !queue.length) return;
    active = queue.shift()!;
    const fail = (message: string) => {
      const job = active;
      active = null;
      disposeWorker();
      if (job) complete(job, undefined, new Error(message));
      queueMicrotask(pump);
    };
    try {
      if (!worker) {
        const current = createWorker();
        worker = current;
        current.onmessage = (event: MessageEvent<{ id: number; document?: MarkdownRenderDocument; error?: string }>) => {
          if (worker !== current || !active || active.id !== event.data.id) return;
          const job = active;
          active = null;
          complete(job, event.data.document, new Error(event.data.error || "内容渲染失败"));
          pump();
        };
        current.onerror = (event) => {
          if (worker !== current) return;
          console.error("Markdown worker failed:", event.message, event.filename, event.lineno, event.colno);
          fail("内容加载失败，请重试。");
        };
        current.onmessageerror = () => { if (worker === current) fail("内容加载结果无法读取，请重试。"); };
      }
      worker.postMessage({ id: active.id, content: active.content });
    } catch (error) {
      fail(error instanceof Error ? error.message : "无法启动内容加载。");
    }
  };
  return {
    getCached,
    request(content: string) {
      const cached = getCached(content);
      if (cached) return { promise: Promise.resolve(cached), cancel() {} };
      let job = jobs.get(content);
      if (!job) {
        job = { id: ++nextId, content, subscribers: new Set() };
        jobs.set(content, job);
        queue.push(job);
      }
      const currentJob = job;
      let subscriber: Subscriber;
      const promise = new Promise<MarkdownRenderDocument>((resolve, reject) => {
        subscriber = { resolve, reject };
        currentJob.subscribers.add(subscriber);
      });
      pump();
      return {
        promise,
        cancel() {
          if (jobs.get(content) !== currentJob || !currentJob.subscribers.delete(subscriber!)) return;
          subscriber!.reject(new DOMException("Content view closed", "AbortError"));
          if (currentJob.subscribers.size) return;
          // React may unmount and reattach the same preview in one commit. Allow
          // that commit to finish before killing the worker and losing its parse.
          // Superseded work with no subscriber is still aborted on the next task.
          queueMicrotask(() => {
            if (jobs.get(content) !== currentJob || currentJob.subscribers.size) return;
            jobs.delete(content);
            if (active === currentJob) { active = null; disposeWorker(); }
            else { const index = queue.indexOf(currentJob); if (index >= 0) queue.splice(index, 1); }
            pump();
          });
        },
      };
    },
  };
}

const client = createMarkdownRenderClient(() => new Worker(
  new URL("./markdownRender.worker.ts", import.meta.url), { type: "module" },
));
export const getCachedMarkdownRender = (content: string) => client.getCached(content);
export const requestMarkdownRender = (content: string) => client.request(content);
