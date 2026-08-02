export type BufferedChatSocketEvent<T> = {
  contentUnits: number;
  value: T;
};

export class ChatSocketEventBuffer<T> {
  private bufferedContentUnits = 0;
  private bufferedEventCount = 0;
  private readonly pending: BufferedChatSocketEvent<T>[] = [];

  constructor(
    private readonly maxEvents: number,
    private readonly maxContentUnits: number,
  ) {}

  tryPush(value: T): boolean {
    const contentUnits = estimateBufferedContentUnits(value);
    const exceedsCount = this.bufferedEventCount >= this.maxEvents;
    const exceedsContent = (
      this.bufferedContentUnits + contentUnits > this.maxContentUnits
    );
    if (exceedsCount || (exceedsContent && this.bufferedEventCount > 0)) {
      return false;
    }
    this.pending.push({ contentUnits, value });
    this.bufferedEventCount += 1;
    this.bufferedContentUnits += contentUnits;
    return true;
  }

  take(): BufferedChatSocketEvent<T> | undefined {
    return this.pending.shift();
  }

  release(item: BufferedChatSocketEvent<T>) {
    this.bufferedEventCount = Math.max(0, this.bufferedEventCount - 1);
    this.bufferedContentUnits = Math.max(
      0,
      this.bufferedContentUnits - item.contentUnits,
    );
  }

  clear() {
    this.pending.length = 0;
    this.bufferedEventCount = 0;
    this.bufferedContentUnits = 0;
  }

  get pendingCount() {
    return this.pending.length;
  }
}

function estimateBufferedContentUnits(value: unknown): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === "string") return value.length;
  if (typeof value === "number" || typeof value === "boolean") return 8;
  if (Array.isArray(value)) {
    return value.reduce<number>(
      (total, item) => total + estimateBufferedContentUnits(item),
      0,
    );
  }
  if (typeof value === "object") {
    return Object.entries(value).reduce(
      (total, [key, item]) => (
        total + key.length + estimateBufferedContentUnits(item)
      ),
      0,
    );
  }
  return 0;
}
