const form = document.querySelector("#feedback-form");
const openBtn = document.querySelector("#feedback-open");
const closeBtn = document.querySelector("#feedback-close");
const nameInput = document.querySelector("#feedback-name");
const textInput = document.querySelector("#feedback-text");
const submitBtn = document.querySelector("#feedback-submit");
const errorBox = document.querySelector("#feedback-error");
const list = document.querySelector("#feedback-list");
const empty = document.querySelector("#feedback-empty");
const adminBtn = document.querySelector("#feedback-admin");
const ACCESS_KEY = "rewriter-model-access";
const LIKES_KEY = "rewriter-idea-likes";

let ideas = [];
let admin = false;

function readStorage(key) {
  try {
    return window.sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function writeStorage(key, value) {
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    /* приватный режим может запретить хранилище */
  }
}

function likedIds() {
  try {
    const raw = JSON.parse(window.localStorage.getItem(LIKES_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw : []);
  } catch {
    return new Set();
  }
}

function storeLikes(ids) {
  try {
    window.localStorage.setItem(LIKES_KEY, JSON.stringify([...ids]));
  } catch {
    /* приватный режим может запретить хранилище */
  }
}

function showForm(open) {
  form.hidden = !open;
  openBtn.hidden = open;
  if (open) textInput.focus();
}

function setError(message) {
  errorBox.hidden = !message;
  errorBox.textContent = message || "";
}

function errorMessage(payload, fallback) {
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  return fallback;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru");
}

function render() {
  const liked = likedIds();
  list.replaceChildren();
  empty.hidden = ideas.length > 0;
  ideas.forEach((idea) => {
    const card = document.createElement("article");
    card.className = "idea";

    const head = document.createElement("div");
    head.className = "idea-head";
    const author = document.createElement("strong");
    author.textContent = idea.name || "Аноним";
    const time = document.createElement("span");
    time.className = "hint";
    time.textContent = formatDate(idea.created);
    head.append(author, time);

    const body = document.createElement("p");
    body.className = "idea-text";
    body.textContent = idea.text;

    const actions = document.createElement("div");
    actions.className = "idea-actions";
    const heart = document.createElement("button");
    heart.type = "button";
    heart.className = "heart";
    heart.setAttribute("aria-pressed", liked.has(idea.id) ? "true" : "false");
    heart.textContent = `${liked.has(idea.id) ? "♥" : "♡"} ${idea.likes || 0}`;
    heart.addEventListener("click", () => toggleLike(idea, heart));
    actions.append(heart);
    if (admin) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ghost";
      remove.textContent = "Удалить";
      remove.addEventListener("click", () => removeIdea(idea.id));
      actions.append(remove);
    }

    card.append(head, body, actions);
    list.append(card);
  });
}

async function loadIdeas() {
  const response = await fetch("/api/feedback");
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(errorMessage(payload, "Не удалось загрузить идеи."));
  ideas = payload.ideas || [];
  render();
}

async function toggleLike(idea, button) {
  const liked = likedIds();
  const next = !liked.has(idea.id);
  button.disabled = true;
  try {
    const response = await fetch(`/api/feedback/${encodeURIComponent(idea.id)}/like`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ liked: next }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(payload, "Не удалось отметить идею."));
    if (next) liked.add(idea.id);
    else liked.delete(idea.id);
    storeLikes(liked);
    ideas = ideas.map((item) => (item.id === idea.id ? payload : item));
    render();
  } catch (error) {
    setError(error.message || "Не удалось отметить идею.");
    button.disabled = false;
  }
}

async function removeIdea(id) {
  if (!window.confirm("Удалить эту идею?")) return;
  setError("");
  const response = await fetch(`/api/feedback/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: { "X-Model-Key": readStorage(ACCESS_KEY) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    setError(errorMessage(payload, "Не удалось удалить идею."));
    return;
  }
  ideas = ideas.filter((idea) => idea.id !== id);
  render();
}

async function checkAdmin(key) {
  const response = await fetch("/api/feedback/admin", { headers: { "X-Model-Key": key } });
  if (!response.ok) return false;
  admin = true;
  if (adminBtn) adminBtn.textContent = "Удаление включено";
  render();
  return true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = textInput.value.trim();
  if (!text) {
    setError("Напишите идею.");
    textInput.focus();
    return;
  }
  setError("");
  submitBtn.disabled = true;
  try {
    const response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: nameInput.value.trim(), text }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(payload, "Не удалось отправить идею."));
    ideas = [payload, ...ideas.filter((idea) => idea.id !== payload.id)];
    nameInput.value = "";
    textInput.value = "";
    showForm(false);
    render();
  } catch (error) {
    setError(error.message || "Не удалось отправить идею.");
  } finally {
    submitBtn.disabled = false;
  }
});

openBtn.addEventListener("click", () => {
  setError("");
  showForm(true);
});

closeBtn.addEventListener("click", () => {
  setError("");
  showForm(false);
});

if (adminBtn) {
  adminBtn.addEventListener("click", async () => {
    const key = window.prompt("Ключ администратора");
    if (!key || !key.trim()) return;
    writeStorage(ACCESS_KEY, key.trim());
    const ok = await checkAdmin(key.trim());
    if (!ok) {
      try {
        window.sessionStorage.removeItem(ACCESS_KEY);
      } catch {
        /* ignore */
      }
      setError("Ключ не подошёл.");
    }
  });
}

const savedKey = readStorage(ACCESS_KEY);
if (savedKey) {
  checkAdmin(savedKey).catch(() => {});
}
loadIdeas().catch((error) => setError(error.message || "Не удалось загрузить идеи."));
