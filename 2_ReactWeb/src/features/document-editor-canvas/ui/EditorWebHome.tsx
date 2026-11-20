import { MagnifyingGlass } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";
import { normalizeWebAddress } from "../../../shared/desktop/editorBrowser";
import "./editor-web-page.css";

export function EditorWebHome({ visible, onNavigate }: { visible: boolean; onNavigate: (url: string) => void }) {
  const [error, setError] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const field = event.currentTarget.elements.namedItem("query") as HTMLInputElement;
    const value = field.value.trim();
    if (!value) {
      field.focus();
      return;
    }
    try {
      const host = value.split(/[/?#]/, 1)[0];
      const explicitUrl = /^(?:[a-z][a-z\d+.-]*:\/\/|https?:|file:|data:|javascript:)/i.test(value);
      const looksLikeHost = !/\s/.test(value) && (
        host.includes(".") || /^localhost$/i.test(host) || host.startsWith("[") || /^[\w-]+:\d+$/.test(host)
      );
      const url = explicitUrl || looksLikeHost
        ? normalizeWebAddress(value)
        : `https://cn.bing.com/search?${new URLSearchParams({ q: value })}`;
      setError("");
      onNavigate(url);
    } catch {
      setError("请输入有效的 HTTP 或 HTTPS 网址");
    }
  }

  return <section className="editor-web-home" aria-label="主页">
    <div className="editor-web-home__content">
      <h1 className="editor-web-home__brand" aria-label="Tiance">
        <svg viewBox="206 304 1269 299" aria-hidden="true">
          <use href={`${import.meta.env.BASE_URL}tiance-startup-wordmark.svg#wordmark-art`} />
        </svg>
      </h1>
      <form className="editor-web-home__search" role="search" aria-label="搜索网页" onSubmit={submit}>
        <input name="query" type="text" aria-label="搜索网页或输入网址" placeholder="搜索网页或输入网址"
          autoFocus={visible} autoComplete="off" spellCheck={false} onChange={() => { if (error) setError(""); }} />
        <button type="submit" aria-label="搜索或打开网址" title="搜索或打开网址"><MagnifyingGlass size={20} /></button>
      </form>
      {error && <p className="editor-web-home__error" role="alert">{error}</p>}
    </div>
  </section>;
}
