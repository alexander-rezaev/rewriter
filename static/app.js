const form = document.querySelector("#rewrite-form");
const source = document.querySelector("#source-text");

function parseDocument(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const parts = [];
  let index = 0;
  while (index < lines.length) {
    if (lines[index] === "§§TABLE") {
      const rows = [];
      index += 1;
      while (index < lines.length && lines[index] !== "§§ENDTABLE") {
        rows.push(lines[index].split("\t"));
        index += 1;
      }
      if (lines[index] === "§§ENDTABLE") index += 1;
      if (rows.length) parts.push({ table: true, rows });
      continue;
    }
    parts.push({ table: false, text: lines[index] });
    index += 1;
  }
  return parts;
}

function cleanCell(value) {
  return String(value || "")
    .replace(/\u200b/g, "")
    .replace(/\t/g, " ")
    .replace(/\r\n?/g, "\n")
    .replace(/\n/g, "\u2028");
}

function formatTable(rows) {
  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  if (!width) return "";
  const body = rows
    .map((row) => {
      const cells = row.map(cleanCell);
      while (cells.length < width) cells.push("");
      return cells.slice(0, width).join("\t");
    })
    .join("\n");
  return `§§TABLE\n${body}\n§§ENDTABLE`;
}

function fillCell(cell, value) {
  const parts = String(value || "").split("\u2028");
  parts.forEach((part, index) => {
    if (index) cell.append(document.createElement("br"));
    if (part) cell.append(document.createTextNode(part));
  });
  if (!cell.childNodes.length) cell.append(document.createElement("br"));
}

function buildTable(rows) {
  const table = document.createElement("table");
  table.className = "sheet";
  rows.forEach((row) => {
    const line = document.createElement("tr");
    row.forEach((value) => {
      const cell = document.createElement("td");
      fillCell(cell, value);
      line.append(cell);
    });
    table.append(line);
  });
  return table;
}

function cellPlain(cell) {
  let raw = "";
  const appendBreak = () => {
    if (raw && !raw.endsWith("\u2028")) raw += "\u2028";
  };
  cell.childNodes.forEach((child) => {
    if (child.nodeType === 3) {
      raw += child.textContent.replace(/\u200b/g, "");
      return;
    }
    if (child.nodeType !== 1) return;
    if (child.tagName === "BR") {
      raw += "\u2028";
      return;
    }
    if (child.tagName === "P" || child.tagName === "DIV") {
      appendBreak();
      raw += child.textContent.replace(/\u200b/g, "").replace(/\n/g, "\u2028");
      return;
    }
    if (child.tagName === "TABLE") {
      appendBreak();
      raw += [...child.rows]
        .map((row) => [...row.cells].map((item) => cellPlain(item).replace(/\u2028/g, " ")).join(" | "))
        .join("\u2028");
    }
  });
  const cleaned = raw.replace(/\t/g, " ").replace(/\u200b/g, "");
  if (!cleaned.replace(/\u2028/g, "").trim()) return "";
  return cleaned;
}

function tableToBlock(table) {
  const rows = [...table.rows].map((row) => [...row.cells].map((cell) => cellPlain(cell)));
  return formatTable(rows);
}

function blockText(node) {
  if (!node || node.nodeType !== 1) return "";
  if (node.tagName === "TABLE") return tableToBlock(node);
  if (node.tagName === "P") return node.textContent.replace(/\u200b/g, "");
  return "";
}

function sourceText() {
  const blocks = [...source.children].filter((node) => node.tagName === "P" || node.tagName === "TABLE");
  if (!blocks.length) return (source.textContent || "").replace(/\u200b/g, "").replace(/\n$/, "");
  return blocks
    .map((block) => blockText(block))
    .join("\n")
    .replace(/\n$/, "");
}

function setSourceText(value) {
  source.replaceChildren();
  parseDocument(value).forEach((part) => {
    if (part.table) {
      source.append(buildTable(part.rows));
      return;
    }
    const paragraph = document.createElement("p");
    paragraph.className = part.text ? "para" : "para para-empty";
    if (part.text) paragraph.textContent = part.text;
    else paragraph.append(document.createElement("br"));
    source.append(paragraph);
  });
  source.dataset.empty = sourceText().trim() ? "false" : "true";
}

function placeCaretAtEnd() {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(source);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

function paragraphsAreReady() {
  const nodes = [...source.childNodes];
  return nodes.length > 0 && nodes.every((node) => node.nodeType === 1 && node.tagName === "P");
}

const INDENT_RE = /^[ \t\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]+/;
const BLOCK_TAGS = new Set(["P", "DIV", "LI", "H1", "H2", "H3", "H4", "H5", "H6", "BLOCKQUOTE", "TR", "PRE"]);
let composing = false;

function stripLineIndent(line) {
  return String(line || "").replace(/\u200b/g, "").replace(/\u00a0/g, " ").replace(INDENT_RE, "");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function indentedHtml(text) {
  return String(text || "")
    .split("\n")
    .map((line) =>
      line
        ? `<p style="margin:0;padding:0;text-indent:1.5em;text-align:justify">${escapeHtml(line)}</p>`
        : '<p style="margin:0;padding:0;text-indent:0"><br></p>',
    )
    .join("");
}

function tableHtml(rows) {
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell).replace(/\u2028/g, "<br>")}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="sheet">${body}</table>`;
}

function documentHtml(text) {
  return parseDocument(text)
    .map((part) => {
      if (part.table) return tableHtml(part.rows);
      if (!part.text) return '<p style="margin:0;padding:0;text-indent:0"><br></p>';
      return `<p style="margin:0;padding:0;text-indent:1.5em;text-align:justify">${escapeHtml(part.text)}</p>`;
    })
    .join("");
}

function readBlocks(root, point) {
  const lines = [];
  let index = 0;
  let found = !point;

  function pushLine(raw, pointAt) {
    const normalized = stripLineIndent(raw);
    const indent = raw.replace(/\u200b/g, "").replace(/\u00a0/g, " ").length - normalized.length;
    if (!found && pointAt != null) {
      index += Math.max(0, Math.min(normalized.length, pointAt - indent));
      found = true;
    } else if (!found) {
      index += normalized.length;
    }
    lines.push(normalized);
  }

  function addRaw(raw, pointAt, hasMore) {
    const parts = raw.split("\n");
    let cursor = 0;
    parts.forEach((part, partIndex) => {
      const localPoint =
        pointAt != null && pointAt >= cursor && pointAt <= cursor + part.length ? pointAt - cursor : null;
      pushLine(part, localPoint);
      cursor += part.length + 1;
      if (!found && (partIndex < parts.length - 1 || hasMore)) index += 1;
    });
  }

  function inlineRaw(el) {
    let raw = "";
    let pointAt = null;
    const append = (node) => {
      if (node.nodeType === 3) {
        const value = node.textContent.replace(/\u200b/g, "");
        if (point && node === point.node) pointAt = raw.length + Math.min(point.offset, value.length);
        raw += value;
        return;
      }
      if (node.nodeType !== 1 || BLOCK_TAGS.has(node.tagName)) return;
      if (node.tagName === "BR") {
        if (point && node === point.node) pointAt = raw.length;
        raw += "\n";
        return;
      }
      const kids = [...node.childNodes];
      kids.forEach((child, childIndex) => {
        if (point && point.node === node && point.offset === childIndex && pointAt == null) pointAt = raw.length;
        append(child);
      });
      if (point && point.node === node && point.offset >= kids.length && pointAt == null) pointAt = raw.length;
    };
    const kids = [...el.childNodes];
    kids.forEach((child, childIndex) => {
      if (point && point.node === el && point.offset === childIndex && pointAt == null) pointAt = raw.length;
      append(child);
    });
    if (point && point.node === el && point.offset >= kids.length && pointAt == null) pointAt = raw.length;
    return { raw, pointAt };
  }

  const children = [...root.childNodes].filter((node) => {
    if (node.nodeType === 3) return node.textContent.replace(/\u200b/g, "").trim() !== "";
    return node.nodeType === 1;
  });
  const hasBlock = children.some((node) => node.nodeType === 1 && BLOCK_TAGS.has(node.tagName));
  if (!hasBlock) {
    const { raw, pointAt } = inlineRaw(root);
    addRaw(raw, pointAt, false);
  } else {
    const blocks = children.filter((node) => node.nodeType !== 1 || BLOCK_TAGS.has(node.tagName));
    blocks.forEach((child, childIndex) => {
      const hasMore = childIndex < blocks.length - 1;
      if (child.nodeType === 3) {
        const value = child.textContent.replace(/\u200b/g, "");
        const pointAt = point && child === point.node ? Math.min(point.offset, value.length) : null;
        addRaw(value, pointAt, hasMore);
        return;
      }
      const { raw, pointAt } = inlineRaw(child);
      addRaw(raw, pointAt, hasMore);
    });
  }
  return { lines, index: found ? index : lines.join("\n").length };
}

function collectLines(root) {
  return readBlocks(root, null).lines;
}

function sourceDocument() {
  return sourceText();
}

function pointIndex(node, offset) {
  if (!node) return sourceText().length;
  const children = [...source.children];
  let index = 0;
  for (let i = 0; i < children.length; i += 1) {
    const child = children[i];
    const serialized = blockText(child);
    const gap = i < children.length - 1 ? 1 : 0;
    if (child === node || child.contains(node)) {
      if (child.tagName === "TABLE") return index + serialized.length;
      const local = offsetWithin(child, node, offset);
      return index + Math.min(serialized.length, local);
    }
    index += serialized.length + gap;
  }
  return index;
}

function offsetWithin(root, node, offset) {
  if (node === root) return offset;
  let count = 0;
  const walk = (current) => {
    for (const child of current.childNodes) {
      if (child === node) {
        count += node.nodeType === 3 ? offset : 0;
        return true;
      }
      if (child.nodeType === 3) count += child.textContent.length;
      else if (walk(child)) return true;
    }
    return false;
  };
  walk(root);
  return count;
}

function isCanonical() {
  const nodes = [...source.childNodes].filter((node) => node.nodeType !== 3 || node.textContent.trim());
  if (!nodes.length) return false;
  return nodes.every((node) => {
    if (node.nodeType !== 1) return false;
    if (node.tagName === "TABLE") return node.classList.contains("sheet");
    if (node.tagName !== "P") return false;
    if (node.getAttribute("style")) return false;
    if (node.className !== "para" && node.className !== "para para-empty") return false;
    const kids = [...node.childNodes];
    if (kids.length === 1 && kids[0].nodeType === 1 && kids[0].tagName === "BR") return true;
    if (kids.some((kid) => kid.nodeType !== 3)) return false;
    const text = kids.map((kid) => kid.textContent).join("");
    return !text.includes("\n") && !text.includes("\u00a0") && !INDENT_RE.test(text);
  });
}

function placeCaret(index) {
  const selection = window.getSelection();
  if (!selection) return;
  let remaining = Math.max(0, index);
  const children = [...source.children];
  const place = (container, offset) => {
    const range = document.createRange();
    range.setStart(container, offset);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  };
  for (let i = 0; i < children.length; i += 1) {
    const child = children[i];
    const serialized = blockText(child);
    const gap = i < children.length - 1 ? 1 : 0;
    if (child.tagName === "P") {
      const textNode = [...child.childNodes].find((node) => node.nodeType === 3);
      const length = textNode ? textNode.textContent.length : 0;
      if (remaining <= length || i === children.length - 1) {
        if (textNode) place(textNode, Math.min(remaining, length));
        else place(child, 0);
        return;
      }
    } else if (remaining <= serialized.length) {
      place(source, [...source.childNodes].indexOf(child) + 1);
      return;
    }
    remaining -= serialized.length + gap;
  }
  placeCaretAtEnd();
}

function caretPoint() {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  if (!source.contains(range.startContainer)) return null;
  return { node: range.startContainer, offset: range.startOffset, endNode: range.endContainer, endOffset: range.endOffset };
}

function normalizeSource(keepCaret) {
  if (composing || isCanonical()) {
    source.dataset.empty = sourceText().trim() ? "false" : "true";
    return;
  }
  const point = keepCaret ? caretPoint() : null;
  const start = point ? pointIndex(point.node, point.offset) : null;
  const end = point ? pointIndex(point.endNode, point.endOffset) : null;
  setSourceText(sourceDocument());
  if (start == null) return;
  placeCaret(start);
  if (end != null && end !== start) {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const anchor = selection.getRangeAt(0).startContainer;
    const anchorOffset = selection.getRangeAt(0).startOffset;
    placeCaret(end);
    const focus = selection.getRangeAt(0).startContainer;
    const focusOffset = selection.getRangeAt(0).startOffset;
    selection.setBaseAndExtent(anchor, anchorOffset, focus, focusOffset);
  }
}

function selectionPlain(root) {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || selection.isCollapsed) return null;
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
  const box = document.createElement("div");
  box.append(selection.getRangeAt(0).cloneContents());
  return fragmentToText(box);
}

function writeClipboardData(clipboard, text) {
  const plain = String(text || "").replace(/\n$/, "");
  clipboard.setData("text/plain", plain);
  clipboard.setData("text/html", documentHtml(plain));
}

function copyRich(text) {
  const plain = String(text || "").replace(/\n$/, "");
  if (!plain) return Promise.resolve();
  if (navigator.clipboard && window.isSecureContext && window.ClipboardItem) {
    return navigator.clipboard.write([
      new ClipboardItem({
        "text/plain": new Blob([plain], { type: "text/plain" }),
        "text/html": new Blob([documentHtml(plain)], { type: "text/html" }),
      }),
    ]);
  }
  return new Promise((resolve, reject) => {
    const holder = document.createElement("div");
    holder.contentEditable = "true";
    holder.style.position = "fixed";
    holder.style.left = "-9999px";
    holder.innerHTML = documentHtml(plain);
    document.body.append(holder);
    const range = document.createRange();
    range.selectNodeContents(holder);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    const copied = document.execCommand("copy");
    holder.remove();
    if (copied) resolve();
    else reject(new Error("Не удалось скопировать текст."));
  });
}

function endsSentence(line) {
  return /[.!?…]["»”')\]]*$/.test(line);
}

function isListItem(line) {
  return /^(?:[-*•–—]|\d+[.)])\s+\S/.test(line);
}

function mapOutsideTables(text, transform) {
  const parts = parseDocument(text);
  if (!parts.some((part) => part.table)) return transform(text);
  const chunks = [];
  let prose = [];
  const flush = () => {
    if (!prose.length) return;
    chunks.push(transform(prose.join("\n")));
    prose = [];
  };
  parts.forEach((part) => {
    if (part.table) {
      flush();
      chunks.push(formatTable(part.rows));
      return;
    }
    prose.push(part.text);
  });
  flush();
  return chunks.join("\n").replace(/\n{3,}/g, "\n\n");
}

function tableColumnCount(line) {
  if (!String(line).includes("\t")) return 0;
  const cells = String(line).split("\t");
  // A tab at the start of a Word line is an indent. A row needs text in two cells.
  if (cells.filter((cell) => cell.trim()).length < 2) return 0;
  return cells.length;
}

function promoteTabTables(text) {
  return mapOutsideTables(text, (chunk) => {
    const lines = String(chunk || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let index = 0;
    while (index < lines.length) {
      const columns = tableColumnCount(lines[index]);
      if (!columns) {
        out.push(lines[index]);
        index += 1;
        continue;
      }
      let end = index + 1;
      while (end < lines.length && tableColumnCount(lines[end]) === columns) end += 1;
      if (end - index >= 2 || columns >= 3) {
        out.push(formatTable(lines.slice(index, end).map((line) => line.split("\t"))));
        index = end;
        continue;
      }
      out.push(lines[index]);
      index += 1;
    }
    return out.join("\n");
  });
}

function prepareIncoming(text) {
  return unwrapWrappedLines(promoteTabTables(text));
}

function fragmentToText(root) {
  const lines = [];
  const pushText = (raw) => {
    String(raw || "")
      .replace(/\u200b/g, "")
      .split("\n")
      .forEach((line) => lines.push(stripLineIndent(line)));
  };
  const visit = (node) => {
    if (node.nodeType === 3) {
      if (node.textContent.replace(/\u200b/g, "").trim()) pushText(node.textContent);
      return;
    }
    if (node.nodeType !== 1) return;
    if (node.tagName === "TABLE") {
      const block = tableToBlock(node);
      if (block) lines.push(block);
      return;
    }
    if (node.querySelector && node.querySelector("table")) {
      node.childNodes.forEach(visit);
      return;
    }
    if (BLOCK_TAGS.has(node.tagName)) {
      pushText(node.textContent || "");
      return;
    }
    node.childNodes.forEach(visit);
  };
  root.childNodes.forEach(visit);
  return lines.join("\n");
}

function insideCell(node) {
  let current = node && node.nodeType === 3 ? node.parentElement : node;
  while (current && current !== source) {
    if (current.tagName === "TD" || current.tagName === "TH") return current;
    current = current.parentElement;
  }
  return null;
}

function unwrapWrappedLines(text) {
  return mapOutsideTables(text, unwrapChunk);
}

function unwrapChunk(text) {
  const lines = String(text || "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map(stripLineIndent);
  const content = lines.filter(Boolean);
  if (content.length < 4) return lines.join("\n");
  const lengths = content.map((line) => line.length).sort((a, b) => a - b);
  const median = lengths[Math.floor((lengths.length - 1) / 2)];
  const wrapped = content.some((line) => !endsSentence(line) && !isListItem(line));
  if (!wrapped || median >= 90) return lines.join("\n");
  const merged = [];
  let buffer = "";
  const flush = () => {
    if (buffer) merged.push(buffer);
    buffer = "";
  };
  lines.forEach((line) => {
    if (!line) {
      flush();
      merged.push("");
      return;
    }
    if (!buffer) {
      buffer = line;
      return;
    }
    if (isListItem(line) || isListItem(buffer)) {
      flush();
      buffer = line;
      return;
    }
    const leftover = buffer.length < Math.max(48, median * 0.85);
    const continuesLower = /^[a-zа-яё«"(]/.test(line);
    if (continuesLower || leftover || !endsSentence(buffer)) {
      if (/[-\u00ad]$/.test(buffer)) buffer = `${buffer.replace(/\u00ad$/, "")}${line}`;
      else buffer = `${buffer} ${line}`;
      return;
    }
    flush();
    buffer = line;
  });
  flush();
  return merged.join("\n").replace(/\n{3,}/g, "\n\n").replace(/^\n+|\n+$/g, "");
}

function insertPlain(text) {
  const point = caretPoint();
  const current = sourceDocument();
  const start = point ? pointIndex(point.node, point.offset) : current.length;
  const end = point ? pointIndex(point.endNode, point.endOffset) : current.length;
  const from = Math.min(start, end);
  const to = Math.max(start, end);
  const incoming = prepareIncoming(text);
  const next = `${current.slice(0, from)}${incoming}${current.slice(to)}`.replace(/\n{3,}/g, "\n\n");
  setSourceText(next.replace(/\n$/, ""));
  placeCaret(from + incoming.length);
  source.dataset.empty = sourceText().trim() ? "false" : "true";
}
const result = document.querySelector("#result");
const resultTitle = document.querySelector("#result-title");
const resultLegend = document.querySelector("#result-legend");
const errorBox = document.querySelector("#form-error");
const submitBtn = document.querySelector("#rewrite-btn");
const copyBtn = document.querySelector("#copy-btn");
const charCount = document.querySelector("#char-count");
const styleBlock = document.querySelector("#style-block");
const modeInput = document.querySelector("#mode-input");
const modeButtons = document.querySelectorAll(".mode-btn");
const modelSelect = document.querySelector("#model-select");
const modelField = document.querySelector("#model-field");
const modelUnlock = document.querySelector("#model-unlock");
const wordBtn = document.querySelector("#word-btn");
const wordFile = document.querySelector("#word-file");
const progress = document.querySelector("#progress");
const progressBar = document.querySelector("#progress-bar");
const progressLabel = document.querySelector("#progress-label");
const modelHint = document.querySelector("#model-hint");
const stopBtn = document.querySelector("#stop-btn");
const termsLink = document.querySelector("#terms-link");
const ideasLink = document.querySelector("#ideas-link");
const rewriteCount = document.querySelector("#rewrite-count");
const appLike = document.querySelector("#app-like");
const appLikeHeart = document.querySelector("#app-like-heart");
const appLikeCount = document.querySelector("#app-like-count");
const appLikeHint = document.querySelector("#app-like-hint");
const APP_LIKE_KEY = "rewriter-app-liked";
const elapsed = document.querySelector("#elapsed");
const queueNote = document.querySelector("#queue-note");
const resultStats = document.querySelector("#result-stats");
const statsSpacer = document.querySelector("#stats-spacer");
const MODEL_KEY = "rewriter-model";
const MODEL_ACCESS_KEY = "rewriter-model-access";
const SOURCE_KEY = "rewriter-source";
const RESULT_KEY = "rewriter-result";
const RESULT_KINDS = new Set(["change", "spelling", "punctuation", "grammar", "uncertain"]);
let requestController = null;
let timerId = null;
let timerStarted = 0;

function readStorage(storage, key) {
  try {
    return storage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeStorage(storage, key, value) {
  try {
    storage.setItem(key, value);
  } catch {
    /* приватный режим браузера может запретить хранилище */
  }
}

function modelAccessKey() {
  return readStorage(window.sessionStorage, MODEL_ACCESS_KEY);
}

function newRequestId() {
  const time = Date.now().toString(36);
  const rand = Math.random().toString(36).slice(2, 10);
  return `r${time}${rand}`;
}

const MODE = {
  rewrite: {
    button: "Переписать",
    pending: "Переписываю…",
    title: "Переписанный текст",
    placeholder: "Здесь появится переписанный текст.",
    working: "Модель переписывает текст…",
    empty: "Введите текст для переписывания.",
    legend:
      '<span class="legend-item"><span class="legend-swatch hl-change"></span>изменённые фрагменты</span>',
  },
  proofread: {
    button: "Проверить",
    pending: "Проверяю…",
    title: "Орфография и грамматика",
    placeholder: "Здесь появится текст с исправленной орфографией и пунктуацией.",
    working: "Проверяю орфографию и пунктуацию…",
    empty: "Введите текст для проверки.",
    legend:
      '<span class="legend-item"><span class="legend-swatch hl-spelling"></span>орфография</span>' +
      '<span class="legend-item"><span class="legend-swatch hl-punctuation"></span>пунктуация, в том числе убранная запятая</span>' +
      '<span class="legend-item"><span class="legend-swatch hl-uncertain"></span>неуверенно</span>',
  },
  grammar: {
    button: "Проверить",
    pending: "Проверяю…",
    title: "Падежи и согласование",
    placeholder: "Здесь появится текст с исправленными падежами и согласованием.",
    working: "Проверяю падежи и согласование…",
    empty: "Введите текст для проверки.",
    legend:
      '<span class="legend-item"><span class="legend-swatch hl-spelling"></span>орфография</span>' +
      '<span class="legend-item"><span class="legend-swatch hl-grammar"></span>падеж / согласование</span>' +
      '<span class="legend-item"><span class="legend-swatch hl-punctuation"></span>пунктуация, в том числе убранная запятая</span>',
  },
};

function currentMode() {
  const value = modeInput.value;
  return MODE[value] ? value : "rewrite";
}

const BORODINO = [
  "— Скажи-ка, дядя, ведь не даром",
  "Москва, спалённая пожаром,",
  "Французу отдана?",
  "Ведь были ж схватки боевые,",
  "Да, говорят, ещё какие!",
  "Недаром помнит вся Россия",
  "Про день Бородина!",
].join("\n");

let militaryStyle = false;

function selectedStyle() {
  const input = form.querySelector('input[name="style"]:checked');
  if (militaryStyle && input && input.value === "simple") return "military";
  return input ? input.value : "";
}

function setMilitary(on) {
  militaryStyle = on;
  const label = document.querySelector("#style-simple-label");
  if (label) label.textContent = on ? "Военный" : "Простой";
}

function lockNav(link, busy) {
  if (!link) return;
  link.classList.toggle("is-disabled", busy);
  link.tabIndex = busy ? -1 : 0;
  if (busy) link.setAttribute("aria-disabled", "true");
  else link.removeAttribute("aria-disabled");
}

function setError(message) {
  if (!message) {
    errorBox.hidden = true;
    errorBox.textContent = "";
    return;
  }
  errorBox.hidden = false;
  errorBox.textContent = message;
}

function updateCount() {
  const count = sourceText().length;
  charCount.textContent = `${count} ${pluralize(count, "знак", "знака", "знаков")}`;
}

function pluralize(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function errorMessage(payload, fallback) {
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item).join(" ");
  return fallback;
}

function formatSize(bytes) {
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) {
    const rounded = gb >= 10 ? gb.toFixed(0) : gb.toFixed(1);
    return `${rounded.replace(".0", "")} ГБ`;
  }
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} МБ`;
}

function showWordButton(open) {
  if (!wordBtn) return;
  wordBtn.hidden = !open;
}

function showModelField(open) {
  modelField.hidden = !open;
  modelField.classList.toggle("is-open", open);
}

function selectedModel() {
  return modelSelect.value || "";
}

function setBusy(busy) {
  form.classList.toggle("is-busy", busy);
  source.contentEditable = busy ? "false" : "true";
  source.classList.toggle("is-locked", busy);
  source.setAttribute("aria-disabled", busy ? "true" : "false");
  submitBtn.disabled = busy;
  stopBtn.hidden = !busy;
  modelSelect.disabled = busy || !modelField.classList.contains("is-open") || modelSelect.options.length === 0;
  if (modelUnlock) modelUnlock.disabled = busy;
  if (wordBtn) wordBtn.disabled = busy;
  if (wordFile) wordFile.disabled = busy;
  lockNav(termsLink, busy);
  lockNav(ideasLink, busy);
  modeButtons.forEach((button) => {
    button.disabled = busy;
  });
  form.querySelectorAll('input[name="style"]').forEach((input) => {
    input.disabled = busy;
  });
  form.querySelectorAll(".style-card").forEach((card) => {
    card.classList.toggle("is-disabled", busy);
  });
}

async function loadModels() {
  const accessKey = modelAccessKey();
  if (!accessKey) return;
  modelHint.textContent = "";
  showModelField(false);
  modelSelect.replaceChildren();
  const loading = document.createElement("option");
  loading.value = "";
  loading.textContent = "Загружаю модели…";
  modelSelect.append(loading);
  modelSelect.disabled = true;
  try {
    const response = await fetch("/api/models", { headers: { "X-Model-Key": accessKey } });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 403) {
      try {
        window.sessionStorage.removeItem(MODEL_ACCESS_KEY);
      } catch {
        /* хранилище недоступно */
      }
      showModelField(false);
      showWordButton(false);
      if (modelUnlock) modelUnlock.hidden = false;
      modelHint.textContent = "Ключ не подошёл.";
      return;
    }
    showWordButton(true);
    const names = (Array.isArray(payload.models) ? payload.models : [])
      .map((item) => (typeof item === "string" ? { name: item, size: 0 } : item))
      .filter((item) => item && item.name);
    modelSelect.replaceChildren();
    if (!names.length) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "Нет доступных моделей";
      modelSelect.append(empty);
      modelHint.textContent = payload.warning || "Ollama не вернула ни одной модели.";
      return;
    }
    showModelField(true);
    if (modelUnlock) modelUnlock.hidden = true;
    const saved = readStorage(window.localStorage, MODEL_KEY);
    const available = names.map((item) => item.name);
    names.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.size ? `${item.name} · ${formatSize(item.size)}` : item.name;
      modelSelect.append(option);
    });
    const preferred = available.includes(saved) ? saved : payload.default;
    if (available.includes(preferred)) modelSelect.value = preferred;
    modelHint.textContent = payload.warning || "";
  } catch {
    showModelField(false);
    showWordButton(false);
    if (modelUnlock) modelUnlock.hidden = false;
    modelHint.textContent = "Не удалось загрузить список моделей.";
  } finally {
    if (!form.classList.contains("is-busy") && modelField.classList.contains("is-open")) {
      modelSelect.disabled = false;
    }
  }
}

async function postJson(url, body, signal) {
  const headers = { "Content-Type": "application/json" };
  const accessKey = modelAccessKey();
  if (accessKey) headers["X-Model-Key"] = accessKey;
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(payload, "Не удалось обработать текст."));
  }
  return payload;
}

function runsOf(parts) {
  const groups = [];
  let prose = [];
  const flush = () => {
    if (!prose.length) return;
    groups.push({ table: false, text: prose.join("\n") });
    prose = [];
  };
  parts.forEach((part) => {
    if (part.table) {
      flush();
      groups.push(part);
      return;
    }
    prose.push(part.text);
  });
  flush();
  return groups;
}

function renderDocument(mode, sourceValue, output) {
  const sourceRuns = runsOf(parseDocument(sourceValue));
  const outputRuns = runsOf(parseDocument(output));
  const paired =
    sourceRuns.length === outputRuns.length &&
    sourceRuns.every((part, index) => Boolean(part.table) === Boolean(outputRuns[index].table));
  const segments = [];
  const html = outputRuns
    .map((part, index) => {
      if (part.table) return tableHtml(part.rows);
      const original = paired && !sourceRuns[index].table ? sourceRuns[index].text : "";
      const resolved = highlightSegments(mode, original.trim(), part.text);
      segments.push(...resolved);
      return window.RewriterHighlight
        ? window.RewriterHighlight.renderSegments(resolved)
        : escapeHtml(part.text);
    })
    .join("");
  return { html, segments };
}

function showPartial(text) {
  if (!text || !result) return;
  holdScroll(() => {
    result.dataset.text = text;
    const rendered = text.includes("§§TABLE")
      ? renderDocument(currentMode(), sourceText(), text)
      : null;
    result.innerHTML = rendered
      ? rendered.html
      : window.RewriterHighlight
        ? window.RewriterHighlight.renderSegments([{ text, kind: null }])
        : escapeHtml(text);
    copyBtn.hidden = false;
  });
}

function queueText(ahead, wait) {
  const count = Number(ahead) || 0;
  if (count < 1) return "";
  const texts = `${count} ${pluralize(count, "текст", "текста", "текстов")}`;
  const seconds = Number(wait) || 0;
  let time = "около 1 мин";
  if (seconds < 45) time = "меньше минуты";
  else if (seconds >= 90) time = `около ${Math.max(2, Math.round(seconds / 60))} мин`;
  return `Перед вами ${texts}. Ожидание ${time}.`;
}

function hideQueue() {
  if (!queueNote) return;
  queueNote.hidden = true;
  queueNote.textContent = "";
}

function showQueue(ahead, wait) {
  const line = queueText(ahead, wait);
  if (!line) {
    hideQueue();
    const placeholder = result.querySelector(".placeholder");
    if (placeholder) placeholder.textContent = MODE[currentMode()].working;
    return;
  }
  if (queueNote) {
    queueNote.hidden = false;
    queueNote.textContent = line;
  }
  if (!result.dataset.text) {
    const placeholder = result.querySelector(".placeholder");
    if (placeholder) placeholder.textContent = line;
  }
}

function showProgress(done, total, text) {
  if (text) showPartial(text);
  if (!progress || !total || total < 2) {
    if (progress) progress.hidden = true;
    return;
  }
  progress.hidden = false;
  const value = Math.max(0, Math.min(done, total));
  if (progressBar) progressBar.style.width = `${Math.round((value / total) * 100)}%`;
  if (progressLabel) progressLabel.textContent = `Обработано ${value} из ${total}`;
}

function hideProgress() {
  if (!progress) return;
  progress.hidden = true;
  if (progressBar) progressBar.style.width = "0";
  if (progressLabel) progressLabel.textContent = "";
}

async function postStream(url, body, signal, onProgress) {
  const headers = { "Content-Type": "application/json" };
  const accessKey = modelAccessKey();
  if (accessKey) headers["X-Model-Key"] = accessKey;
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      errorMessage(
        payload,
        `Программа не приняла запрос, код ${response.status}. Если на компьютере включён прокси, закройте окно и снова откройте Rewriter.exe.`,
      ),
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  while (true) {
    const step = await reader.read();
    if (step.done) break;
    buffer += decoder.decode(step.value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    lines.forEach((line) => {
      if (!line.trim()) return;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        throw new Error(
          "Ответ программы оборвался. Если на компьютере включён прокси, закройте окно и снова откройте Rewriter.exe.",
        );
      }
      if (event.type === "queue") showQueue(event.ahead, event.wait);
      if (event.type === "progress" && onProgress) onProgress(event.done, event.total, event.text);
      if (event.type === "error") throw new Error(event.detail || "Не удалось обработать текст.");
      if (event.type === "result") result = event;
    });
  }
  if (!result) throw new Error("Связь с сайтом прервалась. Попробуйте ещё раз.");
  return result;
}

function highlightSegments(mode, original, output) {
  const api = window.RewriterHighlight;
  if (!api) return [{ text: output, kind: null }];
  if (mode === "proofread" || mode === "grammar") {
    return api.highlightProofread(original, output);
  }
  return api.highlightRewrite(original, output);
}

const STAT_LABELS = {
  spelling: "Орфография",
  punctuation: "Пунктуация",
  grammar: "Падеж и согласование",
  uncertain: "Неуверенно",
  change: "Изменено",
};

function renderStats(segments) {
  const counts = {};
  (segments || []).forEach((segment) => {
    if (!segment.kind || !(segment.text || "").trim()) return;
    counts[segment.kind] = (counts[segment.kind] || 0) + 1;
  });
  const parts = Object.keys(STAT_LABELS)
    .filter((kind) => counts[kind])
    .map((kind) => `${STAT_LABELS[kind]}: ${counts[kind]}`);
  resultStats.replaceChildren();
  const visible = Object.keys(STAT_LABELS).filter((kind) => counts[kind]);
  visible.forEach((kind, index) => {
    if (index) resultStats.append(document.createTextNode("   "));
    const item = document.createElement("span");
    item.className = `stat stat-${kind}`;
    item.textContent = `${STAT_LABELS[kind]}: ${counts[kind]}`;
    resultStats.append(item);
  });
  resultStats.hidden = visible.length === 0;
  if (statsSpacer) statsSpacer.hidden = resultStats.hidden;
}

function holdScroll(action) {
  const x = window.scrollX;
  const y = window.scrollY;
  action();
  const restore = () => window.scrollTo(x, y);
  restore();
  window.requestAnimationFrame(restore);
  window.setTimeout(restore, 0);
}

function cleanSegments(segments) {
  if (!Array.isArray(segments)) return [];
  return segments
    .filter((segment) => segment && typeof segment.text === "string")
    .map((segment) => ({
      text: segment.text,
      kind: RESULT_KINDS.has(segment.kind) ? segment.kind : null,
    }));
}

function clearSavedResult() {
  try {
    window.sessionStorage.removeItem(RESULT_KEY);
  } catch {
    /* приватный режим браузера может запретить хранилище */
  }
}

function saveResult(text, mode, segments) {
  writeStorage(
    window.sessionStorage,
    RESULT_KEY,
    JSON.stringify({
      text,
      mode: MODE[mode] ? mode : currentMode(),
      segments: cleanSegments(segments),
      elapsed: elapsed && !elapsed.hidden ? elapsed.textContent : "",
    }),
  );
}

function readSavedResult() {
  const raw = readStorage(window.sessionStorage, RESULT_KEY);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    if (!data || typeof data.text !== "string" || !data.text.trim()) return null;
    return {
      text: data.text,
      mode: MODE[data.mode] ? data.mode : "rewrite",
      segments: cleanSegments(data.segments),
      elapsed: typeof data.elapsed === "string" ? data.elapsed : "",
    };
  } catch {
    return null;
  }
}

function rememberElapsed() {
  const saved = readSavedResult();
  if (!saved || saved.text !== (result.dataset.text || "")) return;
  saved.elapsed = elapsed && !elapsed.hidden ? elapsed.textContent : "";
  writeStorage(window.sessionStorage, RESULT_KEY, JSON.stringify(saved));
}

function setOutput(text, placeholder, mode, segments, options) {
  const keepSaved = Boolean(options && options.keepSaved);
  if (!text) {
    result.dataset.text = "";
    result.innerHTML = `<p class="placeholder">${placeholder}</p>`;
    copyBtn.hidden = true;
    renderStats([]);
    if (!keepSaved) {
      clearSavedResult();
      stopTimer(false);
    }
    return;
  }
  const original = sourceText().trim();
  const mixed = text.includes("§§TABLE") || original.includes("§§TABLE");
  const rendered = mixed ? renderDocument(mode || currentMode(), original, text) : null;
  const resolved = rendered
    ? rendered.segments
    : Array.isArray(segments) && segments.length
      ? segments
      : highlightSegments(mode || currentMode(), original, text);
  result.dataset.text = text;
  result.innerHTML = rendered
    ? rendered.html
    : window.RewriterHighlight
      ? window.RewriterHighlight.renderSegments(resolved)
      : text;
  copyBtn.hidden = false;
  renderStats(resolved);
  saveResult(text, mode || currentMode(), resolved);
}

function formatElapsed(ms) {
  const total = Math.max(0, ms) / 1000;
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  const tenths = Math.floor((total - Math.floor(total)) * 10);
  if (minutes > 0) return `${minutes}:${String(seconds).padStart(2, "0")}`;
  return `${seconds},${tenths} с`;
}

function startTimer() {
  stopTimer(false);
  timerStarted = Date.now();
  elapsed.hidden = false;
  elapsed.textContent = formatElapsed(0);
  timerId = window.setInterval(() => {
    elapsed.textContent = formatElapsed(Date.now() - timerStarted);
  }, 100);
}

function stopTimer(keepValue) {
  if (timerId) {
    window.clearInterval(timerId);
    timerId = null;
  }
  if (!keepValue) {
    elapsed.hidden = true;
    elapsed.textContent = "";
    timerStarted = 0;
    return;
  }
  if (timerStarted) elapsed.textContent = formatElapsed(Date.now() - timerStarted);
}

function applyMode(mode) {
  holdScroll(() => applyModeNow(mode));
}

function applyModeNow(mode) {
  const next = MODE[mode] ? mode : "rewrite";
  const sameMode = modeInput.value === next;
  modeInput.value = next;
  modeButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mode === next);
  });
  const copy = MODE[next];
  styleBlock.hidden = next !== "rewrite";
  if (!submitBtn.disabled) submitBtn.textContent = copy.button;
  resultTitle.textContent = copy.title;
  resultLegend.innerHTML = copy.legend;
  if (!sameMode || !result.dataset.text) {
    setOutput("", copy.placeholder, next);
  }
  setError("");
}

async function copyResult() {
  const text = result.dataset.text || "";
  if (!text) return;
  const lines = collectLines(result);
  const plain = lines.length ? lines.join("\n") : text;
  await copyRich(plain);

  const original = "Копировать";
  copyBtn.textContent = "Скопировано";
  window.setTimeout(() => {
    copyBtn.textContent = original;
  }, 1500);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (requestController) return;
  setError("");

  const mode = currentMode();
  const copy = MODE[mode];
  const text = sourceText().trim();
  if (!text) {
    setError(copy.empty);
    return;
  }
  if (modelField.classList.contains("is-open") && !selectedModel()) {
    setError("Выберите модель.");
    return;
  }

  const previousText = result.dataset.text || "";
  const previousHtml = result.innerHTML;
  const previousCopyHidden = copyBtn.hidden;
  const controller = new AbortController();
  const requestId = newRequestId();
  requestController = controller;
  form.dataset.requestId = requestId;
  submitBtn.textContent = copy.pending;
  holdScroll(() => {
    setBusy(true);
    setOutput("", copy.working, mode, null, { keepSaved: true });
    startTimer();
  });

  const body = { text, request_id: requestId };
  if (modelField.classList.contains("is-open") && selectedModel()) body.model = selectedModel();
  try {
    const payload =
      mode === "rewrite"
        ? await postStream("/api/rewrite", { ...body, style: selectedStyle() }, controller.signal, showProgress)
        : await postStream(
            "/api/proofread",
            { ...body, grammar: mode === "grammar" },
            controller.signal,
            showProgress,
          );
    holdScroll(() => {
      setOutput(payload.result, copy.placeholder, mode, payload.segments);
      if (mode === "rewrite" && Number.isInteger(payload.rewrites)) renderRewriteCount(payload.rewrites);
    });
  } catch (error) {
    const stopped = error.name === "AbortError" || error.message === "Запрос остановлен.";
    holdScroll(() => {
      if (previousText) {
        result.dataset.text = previousText;
        result.innerHTML = previousHtml;
        copyBtn.hidden = previousCopyHidden;
        const saved = readSavedResult();
        if (saved && saved.text === previousText) renderStats(saved.segments);
      } else {
        setOutput("", copy.placeholder, mode);
      }
      setError(stopped ? "Запрос остановлен." : error.message || "Не удалось обработать текст.");
    });
  } finally {
    requestController = null;
    delete form.dataset.requestId;
    holdScroll(() => {
      stopTimer(true);
      rememberElapsed();
      hideQueue();
      setBusy(false);
      hideProgress();
      submitBtn.textContent = MODE[currentMode()].button;
    });
  }
});

stopBtn.addEventListener("click", () => {
  const requestId = form.dataset.requestId;
  if (requestId) {
    fetch("/api/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: requestId }),
      keepalive: true,
    }).catch(() => {});
  }
  if (requestController) requestController.abort();
});

modelSelect.addEventListener("change", () => {
  if (modelSelect.value) writeStorage(window.localStorage, MODEL_KEY, modelSelect.value);
});

if (modelUnlock) {
  modelUnlock.addEventListener("click", () => {
    const key = window.prompt("Ключ для выбора модели");
    if (!key || !key.trim()) return;
    writeStorage(window.sessionStorage, MODEL_ACCESS_KEY, key.trim());
    loadModels();
  });
}

source.addEventListener("beforeinput", (event) => {
  if (source.contentEditable === "false") {
    event.preventDefault();
    return;
  }
  const cell = insideCell(window.getSelection() && window.getSelection().anchorNode);
  if (cell && (event.inputType === "insertParagraph" || event.inputType === "insertLineBreak")) {
    event.preventDefault();
    document.execCommand("insertLineBreak");
  }
});
source.addEventListener("focus", () => {
  try {
    document.execCommand("defaultParagraphSeparator", false, "p");
  } catch {
    /* старые браузеры могут не поддерживать команду */
  }
});
source.addEventListener("compositionstart", () => {
  composing = true;
});
source.addEventListener("compositionend", () => {
  composing = false;
  normalizeSource(true);
  updateCount();
  writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
});
source.addEventListener("paste", (event) => {
  if (source.contentEditable === "false") {
    event.preventDefault();
    return;
  }
  event.preventDefault();
  const html = event.clipboardData ? event.clipboardData.getData("text/html") : "";
  const plain = event.clipboardData ? event.clipboardData.getData("text/plain") : "";
  if (insideCell(window.getSelection() && window.getSelection().anchorNode)) {
    document.execCommand("insertText", false, String(plain || "").replace(/\t/g, " ").replace(/\r?\n/g, " "));
    updateCount();
    writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
    return;
  }
  let incoming = plain;
  if (html && /<(p|div|li|br|h[1-6]|table)\b/i.test(html)) {
    const parsed = new DOMParser().parseFromString(html, "text/html");
    parsed.querySelectorAll("script,style,meta,link").forEach((node) => node.remove());
    incoming = fragmentToText(parsed.body);
  }
  insertPlain(incoming);
  updateCount();
  writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
});
document.addEventListener("copy", (event) => {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount || selection.isCollapsed || !event.clipboardData) return;
  const root = source.contains(selection.anchorNode)
    ? source
    : result.contains(selection.anchorNode)
      ? result
      : null;
  if (!root || (root === result && !(result.dataset.text || "").trim())) return;
  const selected = selectionPlain(root);
  const fallback = root === source ? sourceDocument() : result.dataset.text || fragmentToText(result);
  const text = selected != null ? selected : fallback;
  if (!text.trim()) return;
  event.preventDefault();
  writeClipboardData(event.clipboardData, text);
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => applyMode(button.dataset.mode));
});

copyBtn.addEventListener("click", () => {
  copyResult().catch(() => setError("Не удалось скопировать текст."));
});

if (termsLink) {
  termsLink.addEventListener("click", (event) => {
    if (form.classList.contains("is-busy")) event.preventDefault();
  });
}
if (ideasLink) {
  ideasLink.addEventListener("click", (event) => {
    if (form.classList.contains("is-busy")) event.preventDefault();
  });
}

function renderRewriteCount(count) {
  const value = Number.isInteger(count) && count > 0 ? count : 0;
  if (rewriteCount) rewriteCount.textContent = String(value);
}

function appLiked() {
  try {
    return window.localStorage.getItem(APP_LIKE_KEY) === "1";
  } catch {
    return false;
  }
}

function storeAppLiked(liked) {
  try {
    if (liked) window.localStorage.setItem(APP_LIKE_KEY, "1");
    else window.localStorage.removeItem(APP_LIKE_KEY);
  } catch {
    /* приватный режим может запретить хранилище */
  }
}

function renderAppLike(count) {
  const liked = appLiked();
  const value = Number.isInteger(count) && count > 0 ? count : 0;
  if (appLikeHeart) appLikeHeart.textContent = liked ? "♥" : "♡";
  if (appLikeCount) appLikeCount.textContent = String(value);
  if (appLikeHint) appLikeHint.textContent = liked ? "Вам нравится" : "Нажмите, если нравится";
  if (appLike) {
    appLike.setAttribute("aria-pressed", liked ? "true" : "false");
    appLike.setAttribute(
      "aria-label",
      liked ? `Оценка приложения: ${value}. Вам нравится` : `Оценка приложения: ${value}. Нажмите, если нравится`,
    );
  }
}

async function loadStats() {
  const response = await fetch("/api/stats");
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) return;
  renderRewriteCount(payload.rewrites);
  renderAppLike(payload.likes);
}

const simpleInput = form.querySelector('input[name="style"][value="simple"]');
const simpleCard = simpleInput ? simpleInput.closest(".style-card") : null;
if (simpleCard) {
  simpleCard.addEventListener("pointerdown", () => {
    if (form.classList.contains("is-busy")) return;
    simpleCard.dataset.wasChecked = simpleInput.checked ? "1" : "0";
  });
  simpleCard.addEventListener("click", (event) => {
    if (event.target === simpleInput) return;
    if (form.classList.contains("is-busy") || simpleCard.classList.contains("is-disabled")) {
      event.preventDefault();
      return;
    }
    if (simpleCard.dataset.wasChecked !== "1") {
      setMilitary(false);
      return;
    }
    const next = !militaryStyle;
    setMilitary(next);
    if (!next || sourceText().trim()) return;
    setSourceText(BORODINO);
    updateCount();
    writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
  });
}
form.querySelectorAll('input[name="style"]').forEach((input) => {
  input.addEventListener("change", () => {
    if (input.value !== "simple") setMilitary(false);
  });
});

if (appLike) {
  appLike.addEventListener("click", async () => {
    const next = !appLiked();
    appLike.disabled = true;
    try {
      const response = await fetch("/api/stats/like", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ liked: next }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(payload, "Не удалось отметить приложение."));
      storeAppLiked(next);
      renderAppLike(payload.likes);
    } catch (error) {
      setError(error.message || "Не удалось отметить приложение.");
    } finally {
      appLike.disabled = false;
    }
  });
}

if (wordBtn && wordFile) {
  wordBtn.addEventListener("click", () => {
    if (wordBtn.disabled) return;
    wordFile.click();
  });
  wordFile.addEventListener("change", async () => {
    const file = wordFile.files && wordFile.files[0];
    wordFile.value = "";
    if (!file || form.classList.contains("is-busy")) return;
    if (!file.name.toLowerCase().endsWith(".docx")) {
      setError("Нужен файл Word в формате .docx.");
      return;
    }
    setError("");
    wordBtn.disabled = true;
    try {
      const response = await fetch("/api/docx", {
        method: "POST",
        headers: {
          "X-Model-Key": modelAccessKey(),
          "X-Filename": encodeURIComponent(file.name),
          "Content-Type": "application/octet-stream",
        },
        body: file,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(errorMessage(payload, "Не удалось прочитать документ."));
      setSourceText(prepareIncoming(payload.text || ""));
      updateCount();
      writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
    } catch (error) {
      setError(error.message || "Не удалось прочитать документ.");
    } finally {
      wordBtn.disabled = form.classList.contains("is-busy");
    }
  });
}

loadStats();

source.addEventListener("input", () => {
  normalizeSource(true);
  updateCount();
  writeStorage(window.sessionStorage, SOURCE_KEY, sourceText());
});
const savedSource = readStorage(window.sessionStorage, SOURCE_KEY);
setSourceText(savedSource);
updateCount();
const savedResult = readSavedResult();
if (savedResult && sourceText().trim()) {
  applyMode(savedResult.mode);
  setOutput(
    savedResult.text,
    MODE[savedResult.mode].placeholder,
    savedResult.mode,
    savedResult.segments,
  );
  if (savedResult.elapsed) {
    elapsed.hidden = false;
    elapsed.textContent = savedResult.elapsed;
    rememberElapsed();
  }
} else {
  clearSavedResult();
  applyMode("rewrite");
}
if (modelAccessKey()) loadModels();
