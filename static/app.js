/* FiveQThoughts Frontend Application */

const state = {
  cards: [],
  allSummaries: [],
  totalCount: 0,
  cardCount: 5,
  signature: "",
  autoSync: true,
  instantDelete: false,
  confirmingDeleteId: null,
  lightboxImage: null,
  // Config & i18n
  version: "1.2.0",
  hasApiKey: false,
  maskedKey: "",
  languagePref: "auto", // "auto" | "de" | "en"
  activeLang: "en", // "de" | "en"
  i18n: {},
  // Editor state (Create or Edit)
  editingThoughtId: null, // null = create mode, string = edit mode
  existingFiles: [], // [{id, name, proxyUrl, byteLength}]
  deletedFileIds: [], // string[]
  stagedAttachments: [], // [{name, contentType, dataUrl, byteLength}]
};

const els = {
  versionBadge: document.getElementById("versionBadge"),
  statusSubtitle: document.getElementById("statusSubtitle"),
  newThoughtBtn: document.getElementById("newThoughtBtn"),
  autoSyncLabel: document.getElementById("autoSyncLabel"),
  autoSyncToggle: document.getElementById("autoSyncToggle"),
  autoSyncText: document.getElementById("autoSyncText"),
  syncDot: document.getElementById("syncDot"),
  instantDeleteLabel: document.getElementById("instantDeleteLabel"),
  instantDeleteToggle: document.getElementById("instantDeleteToggle"),
  instantDeleteText: document.getElementById("instantDeleteText"),
  refreshBtn: document.getElementById("refreshBtn"),
  langSelect: document.getElementById("langSelect"),
  settingsBtn: document.getElementById("settingsBtn"),
  errorBanner: document.getElementById("errorBanner"),
  cardsGrid: document.getElementById("cardsGrid"),
  // Editor modal
  editorModal: document.getElementById("editorModal"),
  editorModalTitle: document.getElementById("editorModalTitle"),
  closeEditorBtn: document.getElementById("closeEditorBtn"),
  cancelEditorBtn: document.getElementById("cancelEditorBtn"),
  editorForm: document.getElementById("editorForm"),
  editorNoteLabel: document.getElementById("editorNoteLabel"),
  editorNoteHint: document.getElementById("editorNoteHint"),
  editorMarkdown: document.getElementById("editorMarkdown"),
  editorLinksLabel: document.getElementById("editorLinksLabel"),
  editorLinks: document.getElementById("editorLinks"),
  pasteClipboardImgBtn: document.getElementById("pasteClipboardImgBtn"),
  chooseFileText: document.getElementById("chooseFileText"),
  editorFileInput: document.getElementById("editorFileInput"),
  pasteInlineLabelWrap: document.getElementById("pasteInlineLabelWrap"),
  pasteInlineToggle: document.getElementById("pasteInlineToggle"),
  pasteInlineText: document.getElementById("pasteInlineText"),
  editorAttachmentsWrap: document.getElementById("editorAttachmentsWrap"),
  saveEditorBtn: document.getElementById("saveEditorBtn"),
  // Settings modal
  settingsModal: document.getElementById("settingsModal"),
  settingsTitle: document.getElementById("settingsTitle"),
  closeSettingsBtn: document.getElementById("closeSettingsBtn"),
  cancelSettingsBtn: document.getElementById("cancelSettingsBtn"),
  saveSettingsBtn: document.getElementById("saveSettingsBtn"),
  settingsForm: document.getElementById("settingsForm"),
  settingsUrlLabel: document.getElementById("settingsUrlLabel"),
  settingsUrlHint: document.getElementById("settingsUrlHint"),
  baseUrlInput: document.getElementById("baseUrlInput"),
  settingsKeyLabel: document.getElementById("settingsKeyLabel"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  settingsCountLabel: document.getElementById("settingsCountLabel"),
  cardCountInput: document.getElementById("cardCountInput"),
  settingsLangLabel: document.getElementById("settingsLangLabel"),
  settingsLangSelect: document.getElementById("settingsLangSelect"),
  settingsLangAutoOpt: document.getElementById("settingsLangAutoOpt"),
  currentKeyHint: document.getElementById("currentKeyHint"),
  // Lightbox
  lightboxModal: document.getElementById("lightboxModal"),
  lightboxTitle: document.getElementById("lightboxTitle"),
  lightboxImg: document.getElementById("lightboxImg"),
  lightboxCopyBtn: document.getElementById("lightboxCopyBtn"),
  closeLightboxBtn: document.getElementById("closeLightboxBtn"),
  toast: document.getElementById("toast"),
};

let toastTimer = null;
let pollIntervalId = null;

/* --- i18n Engine --- */

function detectSystemLanguage() {
  const navLangs = navigator.languages?.length ? navigator.languages : [navigator.language || "en"];
  for (const raw of navLangs) {
    const code = String(raw || "").toLowerCase().slice(0, 2);
    if (code === "de") return "de";
    if (code === "en") return "en";
  }
  return "en";
}

function resolveLanguage(pref) {
  if (pref === "de" || pref === "en") return pref;
  return detectSystemLanguage();
}

function t(keyPath, vars = {}) {
  const parts = keyPath.split(".");
  let val = state.i18n;
  for (const p of parts) {
    val = val?.[p];
  }
  if (typeof val !== "string") return keyPath;
  return val.replace(/\{(\w+)\}/g, (_, k) => (vars[k] !== undefined ? vars[k] : `{${k}}`));
}

async function loadTranslations(langPref) {
  state.languagePref = langPref || "auto";
  const resolved = resolveLanguage(state.languagePref);
  state.activeLang = resolved;

  try {
    const resp = await fetch(`/i18n/${resolved}.json`);
    if (resp.ok) {
      state.i18n = await resp.json();
    }
  } catch (err) {
    console.warn("Could not load i18n JSON:", err);
  }

  document.documentElement.lang = state.activeLang;
  if (els.langSelect) {
    els.langSelect.value = state.activeLang;
  }
  if (els.settingsLangSelect) {
    els.settingsLangSelect.value = state.languagePref;
  }
  applyStaticTranslations();
}

function applyStaticTranslations() {
  // Topbar
  els.newThoughtBtn.textContent = t("topbar.newBtn");
  els.newThoughtBtn.title = t("topbar.newBtnTitle");
  els.autoSyncText.textContent = t("topbar.liveSync");
  els.autoSyncLabel.title = t("topbar.liveSyncTitle");
  els.instantDeleteText.textContent = t("topbar.instantDelete");
  els.instantDeleteLabel.title = t("topbar.instantDeleteTitle");
  els.refreshBtn.textContent = t("topbar.refreshBtn");
  els.refreshBtn.title = t("topbar.refreshBtnTitle");
  els.settingsBtn.textContent = t("topbar.settingsBtn");
  els.settingsBtn.title = t("topbar.settingsBtnTitle");
  if (els.langSelect) {
    els.langSelect.title = t("topbar.languageTitle");
  }

  // Editor modal
  els.editorModalTitle.textContent = state.editingThoughtId
    ? t("editor.titleEdit")
    : t("editor.titleCreate");
  els.closeEditorBtn.setAttribute("aria-label", t("editor.closeAria"));
  els.editorNoteLabel.textContent = t("editor.noteLabel");
  els.editorNoteHint.innerHTML = t("editor.noteHintHtml");
  els.editorMarkdown.placeholder = t("editor.notePlaceholder");
  els.editorLinksLabel.innerHTML = t("editor.linksLabelHtml");
  els.editorLinks.placeholder = t("editor.linksPlaceholder");
  els.pasteClipboardImgBtn.textContent = t("editor.pasteClipboardBtn");
  els.chooseFileText.textContent = t("editor.chooseFileBtn");
  els.pasteInlineText.textContent = t("editor.pasteInlineLabel");
  els.pasteInlineLabelWrap.title = t("editor.pasteInlineTitle");
  els.cancelEditorBtn.textContent = t("editor.cancelBtn");
  els.saveEditorBtn.textContent = t("editor.saveBtn");

  // Settings modal
  els.settingsTitle.textContent = t("settings.title");
  els.closeSettingsBtn.setAttribute("aria-label", t("editor.closeAria"));
  els.settingsUrlLabel.textContent = t("settings.serverUrlLabel");
  els.settingsUrlHint.innerHTML = t("settings.serverUrlHintHtml");
  els.settingsKeyLabel.textContent = t("settings.apiKeyLabel");
  els.apiKeyInput.placeholder = t("settings.apiKeyPlaceholder");
  els.settingsCountLabel.textContent = t("settings.cardCountLabel");
  els.settingsLangLabel.textContent = t("settings.languageLabel");
  els.settingsLangAutoOpt.textContent = t("settings.languageAuto");
  els.cancelSettingsBtn.textContent = t("settings.cancelBtn");
  els.saveSettingsBtn.textContent = t("settings.saveBtn");
  updateKeyHintText();

  // Lightbox
  els.lightboxCopyBtn.textContent = t("lightbox.copyBtn");
  els.closeLightboxBtn.textContent = t("lightbox.closeBtn");

  if (state.cards.length > 0 || state.totalCount > 0) {
    updateSubtitle();
    renderCards();
  }
}

function updateKeyHintText() {
  if (state.hasApiKey) {
    els.currentKeyHint.innerHTML = t("settings.activeKeyHintHtml", {
      maskedKey: escapeHtml(state.maskedKey),
    });
  } else {
    els.currentKeyHint.innerHTML = t("settings.noKeyHintHtml");
  }
}

function showToast(msg, isError = false) {
  els.toast.textContent = msg;
  els.toast.style.borderColor = isError ? "#ef4444" : "#10b981";
  els.toast.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.toast.classList.add("hidden");
  }, 2600);
}

function showError(msg) {
  if (!msg) {
    els.errorBanner.classList.add("hidden");
    els.errorBanner.textContent = "";
    return;
  }
  els.errorBanner.textContent = msg;
  els.errorBanner.classList.remove("hidden");
}

function formatDate(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  if (isNaN(d.getTime())) return isoStr;
  const now = new Date();
  const diffSec = Math.round((now - d) / 1000);
  let rel = "";
  if (diffSec >= 0 && diffSec < 60) rel = t("time.justNow");
  else if (diffSec >= 60 && diffSec < 3600)
    rel = t("time.minutesAgo", { n: Math.floor(diffSec / 60) });
  else if (diffSec >= 3600 && diffSec < 86400)
    rel = t("time.hoursAgo", { n: Math.floor(diffSec / 3600) });
  else if (diffSec >= 86400 && diffSec < 86400 * 7)
    rel = t("time.daysAgo", { n: Math.floor(diffSec / 86400) });

  const locale = state.i18n?.meta?.dateLocale || (state.activeLang === "de" ? "de-DE" : "en-US");
  const abs = d.toLocaleString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return rel ? `${rel} (${abs})` : abs;
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function shortDevice(deviceName) {
  if (!deviceName) return "";
  return deviceName
    .replace("TheBrain on Apple ", "")
    .replace(/\s*\|.*$/, "")
    .trim();
}

function getCleanNoteText(card) {
  const md = (card.markdown || "").trim();
  return md.replace(/!\[[^\]]*\]\([^)]+\)/g, "").trim();
}

function getCopyableText(card) {
  const md = (card.markdown || "").trim();
  const links = (card.links || []).map((l) => (l.title ? `${l.title}: ${l.url}` : l.url)).join("\n");
  if (md && links && !md.includes(card.links[0].url)) {
    return `${md}\n\n${links}`;
  }
  if (md) return md;
  if (links) return links;
  return card.title || "";
}

async function copyTextAction(card, buttonEl) {
  const text = getCopyableText(card);
  if (!text) {
    showToast(t("toasts.noTextToCopy"), true);
    return;
  }

  const origLabel = buttonEl ? buttonEl.innerHTML : "";
  try {
    const resp = await fetch("/api/clipboard/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) {
      await navigator.clipboard.writeText(text);
    }
    if (buttonEl) {
      buttonEl.classList.add("btn-success");
      buttonEl.innerHTML = t("toasts.textCopiedBtn");
      setTimeout(() => {
        buttonEl.classList.remove("btn-success");
        buttonEl.innerHTML = origLabel;
      }, 1500);
    }
    showToast(t("toasts.textCopied"));
  } catch (err) {
    try {
      await navigator.clipboard.writeText(text);
      showToast(t("toasts.textCopied"));
    } catch (_) {
      showToast(t("toasts.copyFailed", { error: err.message }), true);
    }
  }
}

async function copyImageAction(thoughtId, imgItem, buttonEl) {
  if (!imgItem) return;
  const origLabel = buttonEl ? buttonEl.innerHTML : "";
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.innerHTML = t("toasts.copyingBtn");
  }

  try {
    const resp = await fetch("/api/clipboard/image", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thoughtId: thoughtId,
        sourceKind: imgItem.sourceKind,
        fileId: imgItem.id,
        fileName: imgItem.fileName || imgItem.name || "image.png",
        url: imgItem.rawSrc || imgItem.proxyUrl || "",
      }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.classList.add("btn-success");
      buttonEl.innerHTML = t("toasts.imageCopiedBtn");
      setTimeout(() => {
        buttonEl.classList.remove("btn-success");
        buttonEl.innerHTML = origLabel;
      }, 1600);
    }
    showToast(t("toasts.imageCopied", { name: imgItem.name || t("cards.imageDefaultName") }));
  } catch (err) {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.innerHTML = origLabel;
    }
    showToast(t("toasts.imageCopyFailed", { error: err.message }), true);
  }
}

async function deleteThoughtAction(thoughtId) {
  const cardEl = document.querySelector(`.thought-card[data-id="${thoughtId}"]`);
  if (cardEl) {
    cardEl.classList.add("removing");
  }

  try {
    const resp = await fetch(`/api/thoughts/${encodeURIComponent(thoughtId)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }

    state.cards = state.cards.filter((c) => c.id !== thoughtId);
    state.allSummaries = state.allSummaries.filter((s) => s.id !== thoughtId);
    state.totalCount = Math.max(0, state.totalCount - 1);
    state.confirmingDeleteId = null;

    const displayedIds = new Set(state.cards.map((c) => c.id));
    const nextCandidate = state.allSummaries.find((s) => !displayedIds.has(s.id));

    if (nextCandidate && state.cards.length < state.cardCount) {
      try {
        const nextResp = await fetch(`/api/thoughts/${encodeURIComponent(nextCandidate.id)}`);
        if (nextResp.ok) {
          const nextDto = await nextResp.json();
          state.cards.push(nextDto);
        }
      } catch (_) {
        await loadThoughts(false);
        return;
      }
    }

    renderCards();
    updateSubtitle();
    showToast(t("toasts.thoughtDeletedAndLoaded"));
  } catch (err) {
    if (cardEl) {
      cardEl.classList.remove("removing");
    }
    showToast(t("toasts.deleteFailed", { error: err.message }), true);
  }
}

/* --- Create & Edit Quick Thought Modal --- */

function formatLinksForTextarea(links) {
  if (!links || !links.length) return "";
  return links
    .map((l) => {
      if (l.title && l.title !== l.url) {
        return `${l.title} | ${l.url}`;
      }
      return l.url;
    })
    .join("\n");
}

function parseLinksFromTextarea(raw) {
  const lines = (raw || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const result = [];
  for (const line of lines) {
    if (line.includes("|")) {
      const [titlePart, urlPart] = line.split("|", 2).map((s) => s.trim());
      if (urlPart) {
        result.push({ title: titlePart || null, url: urlPart });
      }
    } else {
      result.push({ title: null, url: line });
    }
  }
  return result;
}

function openCreateModal() {
  state.editingThoughtId = null;
  state.existingFiles = [];
  state.deletedFileIds = [];
  state.stagedAttachments = [];

  els.editorModalTitle.textContent = t("editor.titleCreate");
  els.editorMarkdown.value = "";
  els.editorLinks.value = "";
  renderEditorAttachments();
  els.editorModal.classList.remove("hidden");
  setTimeout(() => els.editorMarkdown.focus(), 50);
}

function openEditModal(card) {
  state.editingThoughtId = card.id;
  state.existingFiles = [...(card.attachedImages || []), ...(card.otherFiles || [])];
  state.deletedFileIds = [];
  state.stagedAttachments = [];

  els.editorModalTitle.textContent = t("editor.titleEdit");
  els.editorMarkdown.value = card.markdown || "";
  els.editorLinks.value = formatLinksForTextarea(card.links || []);
  renderEditorAttachments();
  els.editorModal.classList.remove("hidden");
  setTimeout(() => els.editorMarkdown.focus(), 50);
}

function closeEditorModal() {
  els.editorModal.classList.add("hidden");
  state.editingThoughtId = null;
}

function renderEditorAttachments() {
  const remainingExisting = state.existingFiles.filter(
    (f) => !state.deletedFileIds.includes(f.id)
  );
  const total = remainingExisting.length + state.stagedAttachments.length;

  if (total === 0) {
    els.editorAttachmentsWrap.classList.add("hidden");
    els.editorAttachmentsWrap.innerHTML = "";
    return;
  }

  els.editorAttachmentsWrap.classList.remove("hidden");
  els.editorAttachmentsWrap.innerHTML = "";

  remainingExisting.forEach((f) => {
    const item = document.createElement("div");
    item.className = "editor-att-item";
    const isImg = f.origin === "attachment";
    item.innerHTML = `
      ${isImg ? `<img src="${escapeAttr(f.proxyUrl)}" alt="${escapeAttr(f.name)}" />` : ""}
      <div class="editor-att-meta">
        <span class="editor-att-name" title="${escapeAttr(f.name)}">${escapeHtml(f.name)}</span>
        <button type="button" class="editor-att-remove" title="${escapeAttr(t("editor.removeAttachmentTitle"))}">✕</button>
      </div>
    `;
    item.querySelector(".editor-att-remove").addEventListener("click", () => {
      state.deletedFileIds.push(f.id);
      renderEditorAttachments();
    });
    els.editorAttachmentsWrap.appendChild(item);
  });

  state.stagedAttachments.forEach((att, idx) => {
    const item = document.createElement("div");
    item.className = "editor-att-item";
    const isImg = (att.contentType || "").startsWith("image/");
    item.innerHTML = `
      ${isImg ? `<img src="${escapeAttr(att.dataUrl)}" alt="${escapeAttr(att.name)}" />` : ""}
      <div class="editor-att-meta">
        <span class="editor-att-name" title="${escapeAttr(att.name)}">🆕 ${escapeHtml(att.name)}</span>
        <button type="button" class="editor-att-remove" title="${escapeAttr(t("editor.removeStagedTitle"))}">✕</button>
      </div>
    `;
    item.querySelector(".editor-att-remove").addEventListener("click", () => {
      state.stagedAttachments.splice(idx, 1);
      renderEditorAttachments();
    });
    els.editorAttachmentsWrap.appendChild(item);
  });
}

function addImageToEditor({ name, contentType, dataUrl, byteLength }) {
  if (els.pasteInlineToggle.checked) {
    // Insert as inline markdown data URI at cursor position
    const ta = els.editorMarkdown;
    const mdImg = `\n![${name || t("cards.imageDefaultName")}](${dataUrl})\n`;
    const start = ta.selectionStart ?? ta.value.length;
    const end = ta.selectionEnd ?? ta.value.length;
    ta.value = ta.value.slice(0, start) + mdImg + ta.value.slice(end);
    showToast(t("toasts.inlineImageInserted"));
  } else {
    state.stagedAttachments.push({
      name: name || `Clipboard-${Date.now()}.png`,
      contentType: contentType || "image/png",
      dataUrl,
      byteLength: byteLength || 0,
    });
    renderEditorAttachments();
    showToast(t("toasts.attachmentAdded", { name }));
  }
}

async function fetchImageFromOsClipboard() {
  els.pasteClipboardImgBtn.disabled = true;
  const orig = els.pasteClipboardImgBtn.innerHTML;
  els.pasteClipboardImgBtn.innerHTML = t("editor.readingClipboardBtn");
  try {
    const resp = await fetch("/api/clipboard/image");
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || t("toasts.noImageInClipboard"));
    }
    addImageToEditor({
      name: data.name,
      contentType: data.contentType,
      dataUrl: data.dataUrl,
      byteLength: data.byteLength,
    });
  } catch (err) {
    showToast(err.message, true);
  } finally {
    els.pasteClipboardImgBtn.disabled = false;
    els.pasteClipboardImgBtn.innerHTML = orig;
  }
}

function handleFileInputList(fileList) {
  Array.from(fileList || []).forEach((file) => {
    const reader = new FileReader();
    reader.onload = () => {
      addImageToEditor({
        name: file.name || `Clipboard-${Date.now()}.png`,
        contentType: file.type || "application/octet-stream",
        dataUrl: reader.result,
        byteLength: file.size || 0,
      });
    };
    reader.readAsDataURL(file);
  });
}

async function saveEditorSubmit(e) {
  if (e) e.preventDefault();
  const markdown = els.editorMarkdown.value;
  const links = parseLinksFromTextarea(els.editorLinks.value);

  els.saveEditorBtn.disabled = true;
  const origText = els.saveEditorBtn.textContent;
  els.saveEditorBtn.textContent = t("editor.savingBtn");

  try {
    if (state.editingThoughtId) {
      const resp = await fetch(`/api/thoughts/${encodeURIComponent(state.editingThoughtId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          markdown,
          links,
          newAttachments: state.stagedAttachments,
          deleteFileIds: state.deletedFileIds,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || `HTTP ${resp.status}`);
      }
      closeEditorModal();
      showToast(t("toasts.thoughtUpdated"));
      await loadThoughts(false);
    } else {
      if (!markdown.trim() && links.length === 0 && state.stagedAttachments.length === 0) {
        throw new Error(t("toasts.emptyThoughtError"));
      }
      const resp = await fetch("/api/thoughts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          markdown,
          links,
          attachments: state.stagedAttachments,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.error || `HTTP ${resp.status}`);
      }
      closeEditorModal();
      showToast(t("toasts.thoughtCreated"));
      await loadThoughts(false);
    }
  } catch (err) {
    showToast(t("toasts.saveError", { error: err.message }), true);
  } finally {
    els.saveEditorBtn.disabled = false;
    els.saveEditorBtn.textContent = origText;
  }
}

/* --- Lightbox --- */

function openLightbox(thoughtId, imgItem) {
  state.lightboxImage = { thoughtId, imgItem };
  els.lightboxTitle.textContent = imgItem.name || imgItem.fileName || t("cards.imageDefaultName");
  els.lightboxImg.src = imgItem.proxyUrl;
  els.lightboxModal.classList.remove("hidden");
}

function closeLightbox() {
  els.lightboxModal.classList.add("hidden");
  els.lightboxImg.src = "";
  state.lightboxImage = null;
}

function updateSubtitle() {
  els.statusSubtitle.textContent = t("topbar.subtitleCount", {
    shown: state.cards.length,
    total: state.totalCount,
  });
}

function renderCards() {
  els.cardsGrid.innerHTML = "";

  if (!state.cards.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = t("cards.emptyState");
    els.cardsGrid.appendChild(empty);
    return;
  }

  state.cards.forEach((card, idx) => {
    const cardEl = document.createElement("article");
    cardEl.className = "thought-card";
    cardEl.dataset.id = card.id;

    const cleanNote = getCleanNoteText(card);
    const allImages = card.allImages || [];
    const links = card.links || [];
    const otherFiles = card.otherFiles || [];
    const displayTitle =
      card.title ||
      (cleanNote ? cleanNote.slice(0, 55) : allImages[0]?.name || t("cards.untitled"));

    // Header
    const headerEl = document.createElement("div");
    headerEl.className = "card-header";
    const timeStr = formatDate(card.capturedAt || card.createdAt || card.modifiedAt);
    const devStr = shortDevice(card.deviceName);

    headerEl.innerHTML = `
      <div class="card-title-group">
        <div class="card-meta-top">
          <span class="card-index">#${idx + 1}</span>
          <span class="card-time">${escapeHtml(timeStr)}</span>
          ${devStr ? `<span class="card-device" title="${escapeHtml(card.deviceName || "")}">${escapeHtml(devStr)}</span>` : ""}
        </div>
        <h3 class="card-title">${escapeHtml(displayTitle)}</h3>
      </div>
    `;
    cardEl.appendChild(headerEl);

    // Body
    const bodyEl = document.createElement("div");
    bodyEl.className = "card-body";

    // Links
    if (links.length > 0) {
      const linksWrap = document.createElement("div");
      linksWrap.className = "card-links";
      links.forEach((lnk) => {
        const chip = document.createElement("div");
        chip.className = "link-chip";
        chip.innerHTML = `
          <span>🔗</span>
          <a href="${escapeAttr(lnk.url)}" target="_blank" rel="noopener noreferrer" title="${escapeAttr(lnk.url)}">
            ${escapeHtml(lnk.title || lnk.url)}
          </a>
        `;
        linksWrap.appendChild(chip);
      });
      bodyEl.appendChild(linksWrap);
    }

    // Note Text
    if (cleanNote) {
      const noteEl = document.createElement("div");
      noteEl.className = "note-content";
      noteEl.textContent = cleanNote;
      bodyEl.appendChild(noteEl);
    } else if (allImages.length === 0 && links.length === 0) {
      const emptyNote = document.createElement("div");
      emptyNote.className = "note-empty";
      emptyNote.textContent = t("cards.noNoteText");
      bodyEl.appendChild(emptyNote);
    }

    // Images (Inline + Attached)
    if (allImages.length > 0) {
      const imgsWrap = document.createElement("div");
      imgsWrap.className = "images-section";

      allImages.forEach((imgItem) => {
        const imgCard = document.createElement("div");
        imgCard.className = "image-card";

        const isInline = imgItem.origin === "inline";
        const badgeText = isInline ? t("cards.badgeInline") : t("cards.badgeAttachment");
        const sizeInfo = imgItem.byteLength ? ` · ${formatBytes(imgItem.byteLength)}` : "";

        const imgHeader = document.createElement("div");
        imgHeader.className = "image-card-header";
        imgHeader.innerHTML = `
          <span class="image-badge ${isInline ? "inline" : ""}">${escapeHtml(badgeText)}</span>
          <span class="image-name" title="${escapeAttr(imgItem.name || "")}">${escapeHtml(imgItem.name || t("cards.imageDefaultName"))}${escapeHtml(sizeInfo)}</span>
        `;

        const copyImgMiniBtn = document.createElement("button");
        copyImgMiniBtn.type = "button";
        copyImgMiniBtn.className = "btn btn-secondary btn-sm";
        copyImgMiniBtn.innerHTML = t("cards.copyImageBtn");
        copyImgMiniBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          copyImageAction(card.id, imgItem, copyImgMiniBtn);
        });
        imgHeader.appendChild(copyImgMiniBtn);

        const previewWrap = document.createElement("div");
        previewWrap.className = "image-preview-wrap";
        previewWrap.title = t("cards.clickToEnlarge");
        const imgEl = document.createElement("img");
        imgEl.src = imgItem.proxyUrl;
        imgEl.alt = imgItem.name || t("cards.imageDefaultName");
        imgEl.loading = "lazy";
        previewWrap.appendChild(imgEl);
        previewWrap.addEventListener("click", () => openLightbox(card.id, imgItem));

        imgCard.appendChild(imgHeader);
        imgCard.appendChild(previewWrap);
        imgsWrap.appendChild(imgCard);
      });

      bodyEl.appendChild(imgsWrap);
    }

    // Non-image files
    if (otherFiles.length > 0) {
      const filesWrap = document.createElement("div");
      filesWrap.className = "other-files";
      otherFiles.forEach((f) => {
        const a = document.createElement("a");
        a.className = "file-chip";
        a.href = f.proxyUrl;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = `📎 ${f.name} (${formatBytes(f.byteLength)})`;
        filesWrap.appendChild(a);
      });
      bodyEl.appendChild(filesWrap);
    }

    cardEl.appendChild(bodyEl);

    // Card Footer Actions
    const footerEl = document.createElement("div");
    footerEl.className = "card-footer";

    const leftActions = document.createElement("div");
    leftActions.className = "card-footer-left";

    // Copy Text Button
    const copyTextBtn = document.createElement("button");
    copyTextBtn.type = "button";
    copyTextBtn.className = "btn btn-secondary btn-sm";
    copyTextBtn.innerHTML = t("cards.copyTextBtn");
    copyTextBtn.title = t("cards.copyTextTitle");
    copyTextBtn.addEventListener("click", () => copyTextAction(card, copyTextBtn));
    leftActions.appendChild(copyTextBtn);

    // Primary Copy Image Button in Footer if the card has at least one image
    if (allImages.length > 0) {
      const copyImgFooterBtn = document.createElement("button");
      copyImgFooterBtn.type = "button";
      copyImgFooterBtn.className = "btn btn-secondary btn-sm";
      copyImgFooterBtn.innerHTML =
        allImages.length === 1
          ? t("cards.copyImageFooterSingle")
          : t("cards.copyImageFooterMulti", { count: allImages.length });
      copyImgFooterBtn.title = t("cards.copyImageFooterTitle");
      copyImgFooterBtn.addEventListener("click", () =>
        copyImageAction(card.id, allImages[0], copyImgFooterBtn)
      );
      leftActions.appendChild(copyImgFooterBtn);
    }

    // Edit Button
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-secondary btn-sm";
    editBtn.innerHTML = t("cards.editBtn");
    editBtn.title = t("cards.editBtnTitle");
    editBtn.addEventListener("click", () => openEditModal(card));
    leftActions.appendChild(editBtn);

    const rightActions = document.createElement("div");
    rightActions.className = "card-footer-right";

    if (state.confirmingDeleteId === card.id) {
      const confirmGroup = document.createElement("div");
      confirmGroup.className = "confirm-group";

      const lbl = document.createElement("span");
      lbl.className = "confirm-label";
      lbl.textContent = t("cards.deleteConfirmQuestion");

      const yesBtn = document.createElement("button");
      yesBtn.type = "button";
      yesBtn.className = "btn btn-danger btn-sm";
      yesBtn.textContent = t("cards.deleteConfirmYes");
      yesBtn.addEventListener("click", () => deleteThoughtAction(card.id));

      const noBtn = document.createElement("button");
      noBtn.type = "button";
      noBtn.className = "btn btn-ghost btn-sm";
      noBtn.textContent = t("cards.deleteConfirmNo");
      noBtn.addEventListener("click", () => {
        state.confirmingDeleteId = null;
        renderCards();
      });

      confirmGroup.appendChild(lbl);
      confirmGroup.appendChild(yesBtn);
      confirmGroup.appendChild(noBtn);
      rightActions.appendChild(confirmGroup);
    } else {
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn btn-danger btn-sm";
      delBtn.innerHTML = t("cards.deleteBtn");
      delBtn.addEventListener("click", () => {
        if (state.instantDelete) {
          deleteThoughtAction(card.id);
        } else {
          state.confirmingDeleteId = card.id;
          renderCards();
        }
      });
      rightActions.appendChild(delBtn);
    }

    footerEl.appendChild(leftActions);
    footerEl.appendChild(rightActions);
    cardEl.appendChild(footerEl);

    els.cardsGrid.appendChild(cardEl);
  });
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(str) {
  return escapeHtml(str);
}

async function loadConfig() {
  const resp = await fetch("/api/config");
  if (!resp.ok) return;
  const cfg = await resp.json();
  if (cfg.version && els.versionBadge) {
    state.version = cfg.version;
    els.versionBadge.textContent = `v${cfg.version}`;
    document.title = `FiveQThoughts v${cfg.version} – TheBrain Quick Thoughts`;
  }
  state.cardCount = cfg.cardCount || 5;
  state.hasApiKey = Boolean(cfg.hasApiKey);
  state.maskedKey = cfg.maskedKey || "";
  els.baseUrlInput.value = cfg.baseUrl || "http://localhost:11524";
  els.cardCountInput.value = state.cardCount;

  const savedLang = localStorage.getItem("fiveq_lang");
  const pref = cfg.language && cfg.language !== "auto" ? cfg.language : savedLang || "auto";
  await loadTranslations(pref);
}

async function switchLanguage(newLangPref) {
  localStorage.setItem("fiveq_lang", newLangPref);
  await loadTranslations(newLangPref);
  try {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: newLangPref,
        languageOnly: true,
      }),
    });
  } catch (_) {
    // Non-fatal if backend save fails
  }
}

async function loadThoughts(showLoadingStatus = true) {
  els.refreshBtn.disabled = true;
  if (showLoadingStatus) {
    els.statusSubtitle.textContent = t("topbar.loading");
  }
  showError("");

  try {
    const resp = await fetch(`/api/thoughts?limit=${state.cardCount}`);
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }

    state.cards = data.cards || [];
    state.allSummaries = data.allSummaries || [];
    state.totalCount = data.totalCount || state.cards.length;
    state.signature = data.signature || "";
    state.confirmingDeleteId = null;

    renderCards();
    updateSubtitle();
  } catch (err) {
    showError(err.message);
    els.statusSubtitle.textContent = t("topbar.connectionError");
    if (String(err.message).includes("API Key") || String(err.message).includes("401")) {
      els.settingsModal.classList.remove("hidden");
    }
  } finally {
    els.refreshBtn.disabled = false;
  }
}

async function pollForUpdates() {
  if (!state.autoSync) return;
  // Don't interrupt user if a modal or delete confirmation is active
  if (
    !els.editorModal.classList.contains("hidden") ||
    !els.settingsModal.classList.contains("hidden") ||
    state.confirmingDeleteId
  ) {
    return;
  }

  try {
    const resp = await fetch(`/api/thoughts/poll?limit=${state.cardCount}`);
    if (!resp.ok) return;
    const data = await resp.json();
    if (state.signature && data.signature && data.signature !== state.signature) {
      await loadThoughts(false);
      showToast(t("toasts.autoSynced"));
    }
  } catch (_) {
    // Silent background poll error
  }
}

function startPolling() {
  clearInterval(pollIntervalId);
  pollIntervalId = setInterval(pollForUpdates, 5000);
}

// Event Listeners
els.newThoughtBtn.addEventListener("click", openCreateModal);
els.closeEditorBtn.addEventListener("click", closeEditorModal);
els.cancelEditorBtn.addEventListener("click", closeEditorModal);
els.editorForm.addEventListener("submit", saveEditorSubmit);

els.pasteClipboardImgBtn.addEventListener("click", fetchImageFromOsClipboard);
els.editorFileInput.addEventListener("change", (e) => {
  handleFileInputList(e.target.files);
  e.target.value = "";
});

// Support pasting images directly via Cmd+V / Ctrl+V inside the Editor Modal
els.editorModal.addEventListener("paste", (e) => {
  const items = e.clipboardData?.items;
  if (!items) return;
  const imageItems = Array.from(items).filter((item) => item.type.startsWith("image/"));
  if (imageItems.length > 0) {
    e.preventDefault();
    imageItems.forEach((item) => {
      const blob = item.getAsFile();
      if (blob) handleFileInputList([blob]);
    });
  }
});

els.editorMarkdown.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    saveEditorSubmit(e);
  }
});

els.autoSyncToggle.addEventListener("change", () => {
  state.autoSync = els.autoSyncToggle.checked;
  els.syncDot.classList.toggle("off", !state.autoSync);
});

els.instantDeleteToggle.addEventListener("change", () => {
  state.instantDelete = els.instantDeleteToggle.checked;
  state.confirmingDeleteId = null;
  renderCards();
});

els.refreshBtn.addEventListener("click", () => loadThoughts(true));

if (els.langSelect) {
  els.langSelect.addEventListener("change", (e) => {
    switchLanguage(e.target.value);
  });
}

els.settingsBtn.addEventListener("click", async () => {
  await loadConfig();
  els.apiKeyInput.value = "";
  els.settingsModal.classList.remove("hidden");
});

els.closeSettingsBtn.addEventListener("click", () => els.settingsModal.classList.add("hidden"));
els.cancelSettingsBtn.addEventListener("click", () => els.settingsModal.classList.add("hidden"));

els.settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const selectedLang = els.settingsLangSelect ? els.settingsLangSelect.value : state.languagePref;
  const payload = {
    baseUrl: els.baseUrlInput.value.trim(),
    apiKey: els.apiKeyInput.value.trim(),
    cardCount: parseInt(els.cardCountInput.value, 10) || 5,
    language: selectedLang,
  };
  try {
    const resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    state.cardCount = data.cardCount || 5;
    localStorage.setItem("fiveq_lang", selectedLang);
    await loadTranslations(selectedLang);
    els.settingsModal.classList.add("hidden");
    showToast(t("toasts.settingsSaved"));
    await loadThoughts(true);
  } catch (err) {
    showToast(t("toasts.genericError", { error: err.message }), true);
  }
});

els.closeLightboxBtn.addEventListener("click", closeLightbox);
els.lightboxModal.addEventListener("click", (e) => {
  if (e.target === els.lightboxModal) closeLightbox();
});
els.lightboxCopyBtn.addEventListener("click", () => {
  if (state.lightboxImage) {
    copyImageAction(
      state.lightboxImage.thoughtId,
      state.lightboxImage.imgItem,
      els.lightboxCopyBtn
    );
  }
});

document.addEventListener("keydown", (e) => {
  const activeTag = document.activeElement?.tagName;
  const inInput = activeTag === "INPUT" || activeTag === "TEXTAREA";

  if (e.key === "Escape") {
    closeLightbox();
    closeEditorModal();
    els.settingsModal.classList.add("hidden");
    if (state.confirmingDeleteId) {
      state.confirmingDeleteId = null;
      renderCards();
    }
  } else if (!inInput && !e.metaKey && !e.ctrlKey) {
    if (e.key === "r" || e.key === "R") {
      loadThoughts(true);
    } else if (e.key === "n" || e.key === "N") {
      e.preventDefault();
      openCreateModal();
    }
  }
});

// Initialize
(async function init() {
  await loadConfig();
  await loadThoughts(true);
  startPolling();
})();
