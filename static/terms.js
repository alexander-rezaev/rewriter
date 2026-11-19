const form = document.querySelector("#term-form");
const termInput = document.querySelector("#term-input");
const termBody = document.querySelector("#term-body");
const termTable = document.querySelector("#term-table");
const termEmpty = document.querySelector("#term-empty");
const errorBox = document.querySelector("#term-error");
const termStatus = document.querySelector("#term-status");
const addBtn = document.querySelector("#term-add-btn");

let editing = null;
let allTerms = [];

function matchesQuery(term, query) {
  return term.toLocaleLowerCase("ru").includes(query.toLocaleLowerCase("ru"));
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

function errorMessage(payload, fallback) {
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item).join(" ");
  return fallback;
}

function renderTerms(terms) {
  allTerms = terms || [];
  updateComposer();
}

function normalizedTerm(value) {
  return value.replace(/\s+/g, " ").trim();
}

function exactTerm(query) {
  const normalized = normalizedTerm(query);
  if (!normalized) return "";
  return allTerms.find((term) => term === normalized) || "";
}

function updateComposer() {
  const query = termInput.value.trim();
  paintTerms(allTerms);
  const exact = exactTerm(query);
  if (!query) {
    termStatus.textContent = "";
    addBtn.disabled = false;
    addBtn.textContent = "Добавить";
    return;
  }
  if (exact) {
    termStatus.textContent = "Такой термин уже есть в словаре.";
    addBtn.disabled = true;
    addBtn.textContent = "Уже есть";
    return;
  }
  const similar = allTerms.some((term) => matchesQuery(term, query));
  termStatus.textContent = similar
    ? "Точного совпадения нет, ниже — похожие термины."
    : "Такого термина нет. Его можно добавить.";
  addBtn.disabled = false;
  addBtn.textContent = "Добавить";
}

function paintTerms(terms) {
  editing = null;
  termBody.replaceChildren();
  const query = termInput.value.trim();
  const exact = exactTerm(query);
  const list = query ? terms.filter((term) => matchesQuery(term, query)) : terms;
  termTable.hidden = list.length === 0;
  termEmpty.hidden = list.length > 0;
  if (!list.length && query && terms.length) {
    termEmpty.hidden = false;
    termEmpty.textContent = "Похожих терминов нет.";
  } else if (!terms.length) {
    termEmpty.textContent = "Пока пусто — добавьте термин, чтобы зафиксировать написание.";
  }
  list.forEach((term, index) => {
    const row = buildRow(term, index + 1);
    if (exact && term === exact) row.classList.add("is-exact");
    termBody.append(row);
  });
}

function buildRow(term, number) {
  const row = document.createElement("tr");
  row.dataset.term = term;

  const num = document.createElement("td");
  num.className = "term-num";
  num.textContent = String(number);

  const value = document.createElement("td");
  value.className = "term-value";
  value.textContent = term;

  const actions = document.createElement("td");
  actions.className = "term-actions";
  const wrap = document.createElement("div");
  wrap.className = "term-action-wrap";

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "ghost term-action";
  editBtn.textContent = "Изменить";
  editBtn.addEventListener("click", () => startEdit(row, term));

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "ghost term-action";
  removeBtn.textContent = "Удалить";
  removeBtn.addEventListener("click", () => removeTerm(term));

  wrap.append(editBtn, removeBtn);
  actions.append(wrap);
  row.append(num, value, actions);
  return row;
}

function startEdit(row, term) {
  if (editing && editing !== term) {
    loadTerms().catch(() => setError("Не удалось обновить таблицу."));
    return;
  }
  editing = term;
  const valueCell = row.querySelector(".term-value");
  const actions = row.querySelector(".term-actions");
  valueCell.replaceChildren();
  actions.replaceChildren();

  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 120;
  input.value = term;
  input.setAttribute("aria-label", "Редактировать термин");
  input.className = "term-edit-input";

  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.className = "ghost term-action";
  saveBtn.textContent = "Сохранить";

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "ghost term-action";
  cancelBtn.textContent = "Отмена";

  const save = () => {
    const next = input.value.trim();
    if (!next) {
      setError("Введите термин.");
      input.focus();
      return;
    }
    updateTerm(term, next);
  };

  saveBtn.addEventListener("click", save);
  cancelBtn.addEventListener("click", () => {
    loadTerms().catch(() => setError("Не удалось обновить таблицу."));
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      save();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      loadTerms().catch(() => setError("Не удалось обновить таблицу."));
    }
  });

  const wrap = document.createElement("div");
  wrap.className = "term-action-wrap";
  wrap.append(saveBtn, cancelBtn);
  valueCell.append(input);
  actions.append(wrap);
  input.focus();
  input.select();
}

async function loadTerms() {
  const response = await fetch("/api/terms");
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(payload, "Не удалось загрузить словарь."));
  }
  renderTerms(payload.terms || []);
}

async function addTerm(term) {
  const response = await fetch("/api/terms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorMessage(payload, "Не удалось добавить термин."));
  }
  renderTerms(payload.terms || []);
}

async function updateTerm(oldTerm, nextTerm) {
  setError("");
  try {
    const response = await fetch("/api/terms", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old: oldTerm, term: nextTerm }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(errorMessage(payload, "Не удалось изменить термин."));
    }
    renderTerms(payload.terms || []);
  } catch (error) {
    setError(error.message || "Не удалось изменить термин.");
  }
}

async function removeTerm(term) {
  setError("");
  try {
    const response = await fetch(`/api/terms?term=${encodeURIComponent(term)}`, {
      method: "DELETE",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(errorMessage(payload, "Не удалось удалить термин."));
    }
    renderTerms(payload.terms || []);
  } catch (error) {
    setError(error.message || "Не удалось удалить термин.");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const term = normalizedTerm(termInput.value);
  if (!term) {
    setError("Введите термин.");
    termInput.focus();
    return;
  }
  if (exactTerm(term)) {
    setError("");
    updateComposer();
    return;
  }
  setError("");
  try {
    await addTerm(term);
    termInput.value = "";
    updateComposer();
    termInput.focus();
  } catch (error) {
    setError(error.message || "Не удалось добавить термин.");
  }
});

termInput.addEventListener("input", () => {
  setError("");
  updateComposer();
});

loadTerms().catch(() => setError("Не удалось загрузить словарь терминов."));
