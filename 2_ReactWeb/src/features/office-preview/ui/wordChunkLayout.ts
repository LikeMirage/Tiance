import type { WordChunk } from "../../file-preview/model/filePreview";

// Only one bounded DOCX render may run at a time, including across editor tabs.
let rendering: Promise<unknown> = Promise.resolve();
export function scheduleWordRender<T>(signal: AbortSignal, work: () => Promise<T>): Promise<T> {
  const next = rendering.catch(() => {}).then(() => { signal.throwIfAborted(); return work(); });
  rendering = next.catch(() => {});
  return next;
}

async function yieldLayout(signal: AbortSignal) {
  await new Promise<void>(resolve => setTimeout(resolve, 0));
  signal.throwIfAborted();
}

export function annotateWordChunk(host: HTMLElement, chunk: WordChunk, prefix: string,
  numberings: Array<{ id: string; level: number; start: number }> = []) {
  let previous: Record<string, string> | undefined;
  let previousLength = 0;
  for (const paragraph of host.querySelectorAll<HTMLElement>("section > article p")) {
    const marker = paragraph.querySelector<HTMLElement>('span[id^="tiance_preview_p_"]');
    const location = marker ? chunk.locations[marker.id.slice("tiance_preview_p_".length)] : undefined;
    if (location) {
      paragraph.dataset.wordPosition = JSON.stringify(location);
      paragraph.dataset.wordOffset = "0";
      if (location.numbering) {
        const { id, level, preceding } = location.numbering;
        const start = numberings.find(item => String(item.id) === id && String(item.level) === level)?.start ?? 1;
        paragraph.style.counterSet = `${prefix}-num-${id}-${level} ${preceding + start - 1}`;
      }
    } else if (previous) {
      // docx-preview splits paragraphs at explicit page breaks.
      paragraph.dataset.wordPosition = previous.wordPosition;
      paragraph.dataset.wordOffset = String(Number(previous.wordOffset ?? 0) + previousLength);
    }
    previous = { ...paragraph.dataset } as Record<string, string>;
    previousLength = paragraph.textContent?.length ?? 0;
    marker?.remove();
  }
}

/** Paginate a bounded chunk using measured layout. No whole-document DOM exists. */
export async function paginateWordChunk(host: HTMLElement, prefix: string, signal: AbortSignal) {
  const wrapper = host.querySelector<HTMLElement>(`.${prefix}-wrapper`);
  if (!wrapper) throw new Error("Word 内容未生成。");
  wrapper.classList.add("office-docx-wrapper");
  await Promise.all(Array.from(host.querySelectorAll("img"), img => img.decode().catch(() => {})));
  signal.throwIfAborted();
  for (const original of Array.from(wrapper.querySelectorAll<HTMLElement>(`:scope > section.${prefix}`))) {
    original.classList.add("office-docx");
    const articles = Array.from(original.querySelectorAll<HTMLElement>(":scope > article"));
    const style = getComputedStyle(original);
    const pageHeight = Number.parseFloat(style.minHeight) || 1122;
    const padding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
    const header = original.querySelector<HTMLElement>(":scope > header");
    const footer = original.querySelector<HTMLElement>(":scope > footer");
    const notes = Array.from(original.children).filter(e => !articles.includes(e as HTMLElement) && e !== header && e !== footer);
    const available = Math.max(100, pageHeight - padding - (header?.offsetHeight ?? 0) - (footer?.offsetHeight ?? 0)
      - notes.reduce((height, e) => height + (e as HTMLElement).offsetHeight, 0));
    let page: HTMLElement;
    let article: HTMLElement;
    const nextPage = (sourceArticle: HTMLElement) => {
      page = original.cloneNode(false) as HTMLElement;
      page.dataset.previewPage = "true";
      if (header) page.append(header.cloneNode(true));
      article = sourceArticle.cloneNode(false) as HTMLElement;
      page.append(article);
      if (footer) page.append(footer.cloneNode(true));
      original.before(page);
    };
    for (const sourceArticle of articles) {
      nextPage(sourceArticle);
      for (const child of Array.from(sourceArticle.children) as HTMLElement[]) {
        signal.throwIfAborted();
        if (child.tagName === "TABLE") {
          const table = child as HTMLTableElement;
          const groups: HTMLTableRowElement[][] = [];
          let through = -1;
          for (const [index, row] of Array.from(table.rows).entries()) {
            if (index > through) groups.push([]);
            groups.at(-1)!.push(row);
            through = Math.max(through, index, ...Array.from(row.cells, cell => index + cell.rowSpan - 1));
          }
          const shell = () => {
            const result = table.cloneNode(false) as HTMLTableElement;
            for (const col of table.querySelectorAll(":scope > colgroup")) result.append(col.cloneNode(true));
            return result;
          };
          let fragment = shell();
          article!.append(fragment);
          for (const rows of groups) {
            for (const row of rows) fragment.append(row);
            if (article!.offsetHeight > available && (fragment.rows.length > rows.length || article!.children.length > 1)) {
              for (const row of rows) row.remove();
              if (!fragment.rows.length) fragment.remove();
              nextPage(sourceArticle);
              fragment = shell();
              article!.append(fragment);
              for (const row of rows) fragment.append(row);
            }
            await yieldLayout(signal);
          }
        } else {
          article!.append(child);
          if (article!.offsetHeight > available && article!.children.length > 1) {
            child.remove();
            nextPage(sourceArticle);
            article!.append(child);
          }
        }
        // Indivisible oversized content remains visible instead of being clipped.
        await yieldLayout(signal);
      }
    }
    for (const note of notes) page!.insertBefore(note, page!.querySelector(":scope > footer"));
    original.remove();
  }
}
