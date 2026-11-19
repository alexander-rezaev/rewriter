(function (global) {
  const LETTER_RE = /[0-9A-Za-zА-Яа-яЁё]/;

  function tokenize(text) {
    return text.match(/\s+|\S+/g) || [];
  }

  function opcodes(a, b) {
    const n = a.length;
    const m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i -= 1) {
      for (let j = m - 1; j >= 0; j -= 1) {
        dp[i][j] =
          a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const ops = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) {
        const i0 = i;
        const j0 = j;
        while (i < n && j < m && a[i] === b[j]) {
          i += 1;
          j += 1;
        }
        ops.push(["equal", i0, i, j0, j]);
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        const i0 = i;
        while (i < n && (j >= m || (a[i] !== b[j] && dp[i + 1][j] >= dp[i][j + 1]))) {
          i += 1;
        }
        ops.push(["delete", i0, i, j, j]);
      } else {
        const j0 = j;
        while (j < m && (i >= n || (a[i] !== b[j] && dp[i + 1][j] < dp[i][j + 1]))) {
          j += 1;
        }
        ops.push(["insert", i, i, j0, j]);
      }
    }
    if (i < n) ops.push(["delete", i, n, j, j]);
    if (j < m) ops.push(["insert", i, i, j, m]);
    return ops;
  }

  function merge(segments) {
    const out = [];
    segments.forEach((seg) => {
      if (!seg.text) return;
      if (out.length && out[out.length - 1].kind === seg.kind) {
        out[out.length - 1].text += seg.text;
      } else {
        out.push({ text: seg.text, kind: seg.kind });
      }
    });
    return out;
  }

  function highlightRewrite(source, result) {
    const src = tokenize(source);
    const dst = tokenize(result);
    const segments = [];
    opcodes(src, dst).forEach(([tag, , , j1, j2]) => {
      const chunk = dst.slice(j1, j2).join("");
      if (!chunk) return;
      if (tag === "equal") segments.push({ text: chunk, kind: null });
      else segments.push({ text: chunk, kind: chunk.trim() ? "change" : null });
    });
    return merge(segments);
  }

  function isLetter(ch) {
    return LETTER_RE.test(ch || "");
  }

  function commaWasRemoved(oldText, newText) {
    const oldValue = oldText || "";
    const newValue = newText || "";
    if ((oldValue.match(/,/g) || []).length <= (newValue.match(/,/g) || []).length) return false;
    const letters = (value) => [...value].filter(isLetter).join("");
    return letters(oldValue) === letters(newValue);
  }

  function markRemovedComma(kinds, result, index) {
    if (!result.length) return;
    let cursor = index - 1;
    while (cursor >= 0 && /\s/.test(result[cursor])) {
      if (kinds[cursor] == null) kinds[cursor] = "punctuation";
      cursor -= 1;
    }
    cursor = index;
    while (cursor < result.length && /\s/.test(result[cursor])) {
      if (kinds[cursor] == null) kinds[cursor] = "punctuation";
      cursor += 1;
    }
  }

  function proofreadKind(oldText, newText, source, result, i1, j1, j2) {
    if (commaWasRemoved(oldText, newText)) return "punctuation";
    const glue = /^[\s\-–—]+$/;
    if (glue.test(newText || "") || glue.test(oldText || "")) {
      if (isLetter(result[j1 - 1]) && isLetter(result[j2])) return "spelling";
      if (isLetter(source[i1 - 1]) && isLetter(source[i1 + (oldText || "").length])) return "spelling";
    }
    const sample = (oldText || "") + (newText || "");
    if (![...sample].some(isLetter)) return "punctuation";
    const oldLetters = [...(oldText || "")].filter(isLetter).join("");
    const newLetters = [...(newText || "")].filter(isLetter).join("");
    if (oldLetters !== newLetters) return "spelling";
    const rest = [...(oldText || "") + (newText || "")].filter((ch) => !isLetter(ch)).join("");
    if (/^[\s\-–—]*$/.test(rest)) return "spelling";
    return "punctuation";
  }

  function charOpcodes(a, b) {
    return opcodes([...a], [...b]);
  }

  function expandSpelling(result, segments) {
    const kinds = [];
    segments.forEach((seg) => {
      for (let k = 0; k < seg.text.length; k += 1) kinds.push(seg.kind);
    });
    if (kinds.length !== result.length) return segments;
    let i = 0;
    while (i < result.length) {
      if (kinds[i] === "spelling") {
        let start = i;
        while (start > 0 && isLetter(result[start - 1])) start -= 1;
        let end = i + 1;
        while (end < result.length && isLetter(result[end])) end += 1;
        for (let j = start; j < end; j += 1) kinds[j] = "spelling";
        i = end;
      } else {
        i += 1;
      }
    }
    const rebuilt = [];
    let start = 0;
    for (let idx = 1; idx <= result.length; idx += 1) {
      if (idx === result.length || kinds[idx] !== kinds[start]) {
        rebuilt.push({ text: result.slice(start, idx), kind: kinds[start] });
        start = idx;
      }
    }
    return merge(rebuilt);
  }

  function highlightProofread(source, result) {
    const a = [...source];
    const b = [...result];
    const kinds = b.map(() => null);
    charOpcodes(source, result).forEach(([tag, i1, i2, j1, j2]) => {
      if (tag === "equal") return;
      const oldText = a.slice(i1, i2).join("");
      const chunk = b.slice(j1, j2).join("");
      if (chunk) {
        const kind = proofreadKind(oldText, chunk, source, result, i1, j1, j2);
        for (let index = j1; index < j2; index += 1) kinds[index] = kind;
      }
      if (commaWasRemoved(oldText, chunk)) markRemovedComma(kinds, b, j1);
    });
    const segments = [];
    let start = 0;
    for (let index = 1; index <= b.length; index += 1) {
      if (index === b.length || kinds[index] !== kinds[start]) {
        segments.push({ text: b.slice(start, index).join(""), kind: kinds[start] });
        start = index;
      }
    }
    return expandSpelling(result, merge(segments));
  }

  function escapeHtml(value) {
    return value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function segmentHtml(segment) {
    const raw = String(segment.text || "");
    const text = escapeHtml(raw);
    if (!segment.kind) return text;
    const gap = segment.kind === "punctuation" && !raw.trim();
    const cls = gap ? "hl-punctuation hl-gap" : escapeHtml(segment.kind);
    const markClass = gap ? cls : `hl-${cls}`;
    return `<mark class="${markClass}">${text}</mark>`;
  }

  function splitParagraphs(segments) {
    const paragraphs = [];
    let current = [];
    const push = () => {
      paragraphs.push(current);
      current = [];
    };
    (segments || []).forEach((segment) => {
      const parts = String(segment.text || "").split("\n");
      parts.forEach((part, index) => {
        if (part) current.push({ text: part, kind: segment.kind });
        if (index < parts.length - 1) push();
      });
    });
    if (current.length || !paragraphs.length) paragraphs.push(current);
    return paragraphs;
  }

  function stripLineIndent(line) {
    return String(line || "").replace(/\u00a0/g, " ").replace(/^[ \t\u1680\u2000-\u200a\u202f\u205f\u3000]+/, "");
  }

  function renderSegments(segments) {
    return splitParagraphs(segments)
      .map((paragraph) => {
        let atStart = true;
        const html = paragraph
          .map((segment) => {
            let text = String(segment.text || "").replace(/\u00a0/g, " ");
            if (atStart) {
              const stripped = stripLineIndent(text);
              if (!stripped) return "";
              text = stripped;
              atStart = false;
            }
            return segmentHtml({ text, kind: segment.kind });
          })
          .join("");
        if (!html) return '<p class="para para-empty"><br></p>';
        return `<p class="para">${html}</p>`;
      })
      .join("");
  }

  global.RewriterHighlight = {
    highlightRewrite,
    highlightProofread,
    renderSegments,
  };
})(window);
