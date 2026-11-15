import type { JSX } from "react";

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function safeHref(value: string): string {
  const href = value.trim();
  if (!href || /^(?:javascript|data|vbscript):/i.test(href)) return "#";
  if (/^(?:https?:|mailto:|tel:|\/|#|\?)/i.test(href)) return href;
  return `#${href}`;
}

function renderInline(line: string): string {
  const codeTokens: string[] = [];
  const mathTokens: string[] = [];
  const linkTokens: string[] = [];
  let source = line.replace(/`([^`\n]+)`/g, (_match, code: string) => {
    const index = codeTokens.push(`<code>${escapeHtml(code)}</code>`) - 1;
    return `\u0000CODE${index}\u0000`;
  });
  source = source.replace(/\$([^$\n]+)\$/g, (_match, expression: string) => {
    const index = mathTokens.push(`<span class="math-inline" role="math">${escapeHtml(expression)}</span>`) - 1;
    return `\u0000MATH${index}\u0000`;
  });
  source = escapeHtml(source).replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+["']([^"']*)["'])?\)/g, (_match, label: string, href: string, title?: string) => {
    const titleAttribute = title ? ` title="${escapeHtml(title)}"` : "";
    const index = linkTokens.push(`<a href="${escapeHtml(safeHref(href))}" target="_blank" rel="noopener noreferrer"${titleAttribute}>${label}</a>`) - 1;
    return `\u0000LINK${index}\u0000`;
  });
  source = source
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  return source
    .replace(/\u0000CODE(\d+)\u0000/g, (_match, index: string) => codeTokens[Number(index)] ?? "")
    .replace(/\u0000MATH(\d+)\u0000/g, (_match, index: string) => mathTokens[Number(index)] ?? "")
    .replace(/\u0000LINK(\d+)\u0000/g, (_match, index: string) => linkTokens[Number(index)] ?? "");
}

function leadingSpaces(line: string): number {
  return line.match(/^\s*/)?.[0].length ?? 0;
}

function splitTableRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  let escaped = false;
  for (const char of value) {
    if (char === "|" && !escaped) {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
    escaped = char === "\\" && !escaped;
    if (char !== "\\") escaped = false;
  }
  cells.push(current.trim());
  return cells.map((cell) => cell.replace(/\\\|/g, "|"));
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function tableAlignment(cell: string): string {
  if (cell.startsWith(":") && cell.endsWith(":")) return "center";
  if (cell.endsWith(":")) return "right";
  if (cell.startsWith(":")) return "left";
  return "";
}

function renderTable(lines: string[]): string {
  const header = splitTableRow(lines[0]);
  const separators = splitTableRow(lines[1]);
  const rows = lines.slice(2).map(splitTableRow);
  const cells = (values: string[], tag: "th" | "td") => values.map((value, index) => {
    const align = tableAlignment(separators[index] ?? "");
    const style = align ? ` style="text-align:${align}"` : "";
    return `<${tag}${style}>${renderInline(value)}</${tag}>`;
  }).join("");
  const body = rows.map((row) => {
    const normalized = header.map((_value, index) => row[index] ?? "");
    return `<tr>${cells(normalized, "td")}</tr>`;
  }).join("");
  return `<div class="markdown-table-wrap"><table><thead><tr>${cells(header, "th")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderList(lines: string[], start: number, end: number, indent: number): { html: string; next: number } {
  const first = lines[start].slice(indent);
  const ordered = /^\d+[.)]\s+/.test(first);
  const tag = ordered ? "ol" : "ul";
  const items: string[] = [];
  let index = start;
  while (index < end) {
    const current = lines[index];
    const currentIndent = leadingSpaces(current);
    const match = current.slice(indent).match(/^(?:[-*+]\s+|\d+[.)]\s+)(.*)$/);
    if (currentIndent !== indent || !match || (/^\d+[.)]\s+/.test(current.slice(indent)) !== ordered)) break;
    const itemLines: string[] = [match[1]];
    index += 1;
    while (index < end) {
      const nested = lines[index];
      const nestedIndent = leadingSpaces(nested);
      if (nested.trim() && nestedIndent <= indent) break;
      if (!nested.trim()) {
        itemLines.push("");
        index += 1;
        continue;
      }
      itemLines.push(nested.slice(Math.min(nested.length, indent + 2)));
      index += 1;
    }
    const nestedHtml = itemLines.length > 1 ? renderBlocks(itemLines.slice(1)) : "";
    items.push(`<li>${renderInline(itemLines[0])}${nestedHtml}</li>`);
  }
  return { html: `<${tag}>${items.join("")}</${tag}>`, next: index };
}

function renderBlocks(lines: string[]): string {
  const html: string[] = [];
  let paragraph: string[] = [];
  let index = 0;
  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(renderInline).join("<br />")}</p>`);
      paragraph = [];
    }
  };
  while (index < lines.length) {
    const line = lines[index];
    if (/^\s*```/.test(line)) {
      flushParagraph();
      const language = line.match(/^\s*```([\w-]*)/)?.[1] ?? "";
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      const className = language ? ` class="language-${escapeHtml(language)}"` : "";
      html.push(`<pre><code${className}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^\s*(?:[-*_]\s*){3,}$/.test(line)) {
      flushParagraph(); html.push("<hr />"); index += 1; continue;
    }
    if (line.trim().startsWith("|") && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      flushParagraph();
      const tableLines = [line, lines[index + 1]];
      index += 2;
      while (index < lines.length && lines[index].trim().startsWith("|")) tableLines.push(lines[index++]);
      html.push(renderTable(tableLines));
      continue;
    }
    const mathBlock = line.match(/^\s*\$\$\s*$/);
    if (mathBlock) {
      flushParagraph();
      const formula: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*\$\$\s*$/.test(lines[index])) formula.push(lines[index++]);
      if (index < lines.length) index += 1;
      html.push(`<div class="math-block" role="math">${escapeHtml(formula.join("\n"))}</div>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      const quoteLines: string[] = [];
      while (index < lines.length) {
        const match = lines[index].match(/^\s*>\s?(.*)$/);
        if (!match) break;
        quoteLines.push(match[1]); index += 1;
      }
      html.push(`<blockquote>${renderBlocks(quoteLines)}</blockquote>`);
      continue;
    }
    if (/^\s*(?:[-*+]\s+|\d+[.)]\s+)/.test(line)) {
      flushParagraph();
      const indent = leadingSpaces(line);
      const list = renderList(lines, index, lines.length, indent);
      html.push(list.html); index = list.next; continue;
    }
    if (!line.trim()) {
      flushParagraph(); index += 1; continue;
    }
    paragraph.push(line.trim());
    index += 1;
  }
  flushParagraph();
  return html.join("\n");
}

export default function MarkdownRenderer({ content, className = "" }: { content: string; className?: string }): JSX.Element {
  const lines = String(content ?? "").split(/\r?\n/);
  return <article className={`markdown-body ${className}`.trim()} dangerouslySetInnerHTML={{ __html: renderBlocks(lines) }} />;
}
