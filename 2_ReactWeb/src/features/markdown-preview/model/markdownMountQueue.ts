type Host = {
  requestFrame(callback: () => void): number;
  cancelFrame(id: number): void;
  setTimer(callback: () => void): number;
  clearTimer(id: number): void;
  now(): number;
};

/** Share an 8 ms DOM preparation budget across previews, behind the session curtain.
 * Unlike one fragment per frame, this drains as much work as fits each paint.
 */
export function createMarkdownMountQueue(host: Host) {
  const queue: { run: () => void; cancelled: boolean }[] = [];
  let frame: number | null = null;
  let timer: number | null = null;
  const schedule = () => {
    if (frame !== null || timer !== null || !queue.length) return;
    frame = host.requestFrame(() => {
      frame = null;
      timer = host.setTimer(() => {
        timer = null;
        const end = host.now() + 8;
        while (queue.length) {
          const task = queue.shift()!;
          if (!task.cancelled) task.run();
          if (host.now() >= end) break;
        }
        schedule();
      });
    });
  };
  return (run: () => void) => {
    const task = { run, cancelled: false };
    queue.push(task);
    schedule();
    return () => {
      task.cancelled = true;
      if (queue.some((entry) => !entry.cancelled)) return;
      queue.length = 0;
      if (frame !== null) host.cancelFrame(frame);
      if (timer !== null) host.clearTimer(timer);
      frame = timer = null;
    };
  };
}

export const scheduleMarkdownMount = createMarkdownMountQueue({
  requestFrame: (callback) => window.requestAnimationFrame(callback),
  cancelFrame: (id) => window.cancelAnimationFrame(id),
  setTimer: (callback) => window.setTimeout(callback, 0),
  clearTimer: (id) => window.clearTimeout(id),
  now: () => performance.now(),
});
