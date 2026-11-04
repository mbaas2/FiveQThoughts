/* FiveQThoughts Frontend Application */

const state = {
  cards: [],
  allSummaries: [],
  totalCount: 0,
  cardCount: 5,
  instantDelete: false,
  confirmingDeleteId: null,
  lightboxImage: null,
};

const els = {
  statusSubtitle: document.getElementById("statusSubtitle"),
  instantDeleteToggle: document.getElementById("instantDeleteToggle"),
  refreshBtn: document.getElementById("refreshBtn"),
  settingsBtn: document.getElementById("settingsBtn"),
  errorBanner: document.getElementById("errorBanner"),
  cardsGrid: document.getElementById("cardsGrid"),
  settingsModal: document.getElementById("settingsModal"),
  closeSettingsBtn: document.getElementById("closeSettingsBtn"),
  cancelSettingsBtn: document.getElementById("cancelSettingsBtn"),
  settingsForm: document.getElementById("settingsForm"),
  baseUrlInput: document.getElementById("baseUrlInput"),
  apiKeyInput: document.getElementById("apiKeyInput"),
  cardCountInput: document.getElementById("cardCountInput"),
  currentKeyHint: document.getElementById("currentKeyHint"),
  lightboxModal: document.getElementById("lightboxModal"),
  lightboxTitle: document.getElementById("lightboxTitle"),
  lightboxImg: document.getElementById("lightboxImg"),
  lightboxCopyBtn: document.getElementById("lightboxCopyBtn"),
  closeLightboxBtn: document.getElementById("closeLightboxBtn"),
  toast: document.getElementById("toast"),
};

let toastTimer = null;

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
  if (diffSec >= 0 && diffSec < 60) rel = "gerade eben";
  else if (diffSec >= 60 && diffSec < 3600) rel = `vor ${Math.floor(diffSec / 60)} Min.`;
  else if (diffSec >= 3600 && diffSec < 86400) rel = `vor ${Math.floor(diffSec / 3600)} Std.`;
  else if (diffSec >= 86400 && diffSec < 86400 * 7) rel = `vor ${Math.floor(diffSec / 86400)} Tg.`;

  const abs = d.toLocaleString("de-DE", {
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
  // Remove inline markdown image syntax for clean text display if desired, or keep text around it
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
    showToast("Kein Text zum Kopieren vorhanden.", true);
    return;
  }

  const origLabel = buttonEl ? buttonEl.innerHTML : "";
  try {
    // Primary: Native OS clipboard via backend (works reliably across macOS & Windows)
    const resp = await fetch("/api/clipboard/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) {
      // Fallback: browser clipboard API
      await navigator.clipboard.writeText(text);
    }
    if (buttonEl) {
      buttonEl.classList.add("btn-success");
      buttonEl.innerHTML = "✓ Text kopiert";
      setTimeout(() => {
        buttonEl.classList.remove("btn-success");
        buttonEl.innerHTML = origLabel;
      }, 1500);
    }
    showToast("Text in die Zwischenablage kopiert!");
  } catch (err) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Text in die Zwischenablage kopiert!");
    } catch (e2) {
      showToast(`Kopieren fehlgeschlagen: ${err.message}`, true);
    }
  }
}

async function copyImageAction(thoughtId, imgItem, buttonEl) {
  if (!imgItem) return;
  const origLabel = buttonEl ? buttonEl.innerHTML : "";
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.innerHTML = "⏳ Kopiere…";
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
      buttonEl.innerHTML = "✓ Grafik kopiert";
      setTimeout(() => {
        buttonEl.classList.remove("btn-success");
        buttonEl.innerHTML = origLabel;
      }, 1600);
    }
    showToast(`Grafik "${imgItem.name || "Bild"}" in die Zwischenablage kopiert!`);
  } catch (err) {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.innerHTML = origLabel;
    }
    showToast(`Grafik-Kopieren fehlgeschlagen: ${err.message}`, true);
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

    // Remove from local state
    state.cards = state.cards.filter((c) => c.id !== thoughtId);
    state.allSummaries = state.allSummaries.filter((s) => s.id !== thoughtId);
    state.totalCount = Math.max(0, state.totalCount - 1);
    state.confirmingDeleteId = null;

    // Check if there is a next thought in allSummaries not currently displayed in state.cards
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
        // Fallback full reload if single fetch fails
        await loadThoughts();
        return;
      }
    }

    renderCards();
    updateSubtitle();
    showToast("Quick Thought gelöscht & nächster geladen.");
  } catch (err) {
    if (cardEl) {
      cardEl.classList.remove("removing");
    }
    showToast(`Löschen fehlgeschlagen: ${err.message}`, true);
  }
}

function openLightbox(thoughtId, imgItem) {
  state.lightboxImage = { thoughtId, imgItem };
  els.lightboxTitle.textContent = imgItem.name || imgItem.fileName || "Grafik";
  els.lightboxImg.src = imgItem.proxyUrl;
  els.lightboxModal.classList.remove("hidden");
}

function closeLightbox() {
  els.lightboxModal.classList.add("hidden");
  els.lightboxImg.src = "";
  state.lightboxImage = null;
}

function updateSubtitle() {
  els.statusSubtitle.textContent = `${state.cards.length} von ${state.totalCount} Quick Thoughts angezeigt (neueste zuerst)`;
}

function renderCards() {
  els.cardsGrid.innerHTML = "";

  if (!state.cards.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Keine Quick Thoughts in der Inbox vorhanden.";
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
      (cleanNote ? cleanNote.slice(0, 55) : allImages[0]?.name || "Ohne Titel");

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
      emptyNote.textContent = "(Kein Notiztext)";
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
        const badgeText = isInline ? "Im Text" : "Anhang";
        const sizeInfo = imgItem.byteLength ? ` · ${formatBytes(imgItem.byteLength)}` : "";

        const imgHeader = document.createElement("div");
        imgHeader.className = "image-card-header";
        imgHeader.innerHTML = `
          <span class="image-badge ${isInline ? "inline" : ""}">${badgeText}</span>
          <span class="image-name" title="${escapeAttr(imgItem.name || "")}">${escapeHtml(imgItem.name || "Grafik")}${escapeHtml(sizeInfo)}</span>
        `;

        const copyImgMiniBtn = document.createElement("button");
        copyImgMiniBtn.type = "button";
        copyImgMiniBtn.className = "btn btn-secondary btn-sm";
        copyImgMiniBtn.innerHTML = "📋 Grafik kopieren";
        copyImgMiniBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          copyImageAction(card.id, imgItem, copyImgMiniBtn);
        });
        imgHeader.appendChild(copyImgMiniBtn);

        const previewWrap = document.createElement("div");
        previewWrap.className = "image-preview-wrap";
        previewWrap.title = "Klicken zum Vergrößern";
        const imgEl = document.createElement("img");
        imgEl.src = imgItem.proxyUrl;
        imgEl.alt = imgItem.name || "Quick Thought Grafik";
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
    copyTextBtn.innerHTML = "📋 Text kopieren";
    copyTextBtn.addEventListener("click", () => copyTextAction(card, copyTextBtn));
    leftActions.appendChild(copyTextBtn);

    // Primary Copy Image Button in Footer if the card has at least one image
    if (allImages.length > 0) {
      const copyImgFooterBtn = document.createElement("button");
      copyImgFooterBtn.type = "button";
      copyImgFooterBtn.className = "btn btn-secondary btn-sm";
      copyImgFooterBtn.innerHTML =
        allImages.length === 1 ? "🖼️ Grafik kopieren" : `🖼️ 1. Grafik kopieren (${allImages.length})`;
      copyImgFooterBtn.addEventListener("click", () =>
        copyImageAction(card.id, allImages[0], copyImgFooterBtn)
      );
      leftActions.appendChild(copyImgFooterBtn);
    }

    const rightActions = document.createElement("div");
    rightActions.className = "card-footer-right";

    if (state.confirmingDeleteId === card.id) {
      const confirmGroup = document.createElement("div");
      confirmGroup.className = "confirm-group";

      const lbl = document.createElement("span");
      lbl.className = "confirm-label";
      lbl.textContent = "Löschen?";

      const yesBtn = document.createElement("button");
      yesBtn.type = "button";
      yesBtn.className = "btn btn-danger btn-sm";
      yesBtn.textContent = "Ja";
      yesBtn.addEventListener("click", () => deleteThoughtAction(card.id));

      const noBtn = document.createElement("button");
      noBtn.type = "button";
      noBtn.className = "btn btn-ghost btn-sm";
      noBtn.textContent = "Nein";
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
      delBtn.innerHTML = "🗑️ Löschen";
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
  state.cardCount = cfg.cardCount || 5;
  els.baseUrlInput.value = cfg.baseUrl || "http://localhost:11524";
  els.cardCountInput.value = state.cardCount;
  if (cfg.hasApiKey) {
    els.currentKeyHint.innerHTML = `Aktiver Key: <code>${escapeHtml(cfg.maskedKey)}</code> (aus <em>Settings &gt; User &gt; Local API</em>)`;
  } else {
    els.currentKeyHint.innerHTML = `Noch kein Key gespeichert. Zu finden in TheBrain 15 unter <strong>Settings &gt; User &gt; Local API</strong>.`;
  }
}

async function loadThoughts() {
  els.refreshBtn.disabled = true;
  els.statusSubtitle.textContent = "Lade Quick Thoughts über TheBrain API…";
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
    state.confirmingDeleteId = null;

    renderCards();
    updateSubtitle();
  } catch (err) {
    showError(err.message);
    els.statusSubtitle.textContent = "Verbindungsfehler";
    if (String(err.message).includes("API Key") || String(err.message).includes("401")) {
      els.settingsModal.classList.remove("hidden");
    }
  } finally {
    els.refreshBtn.disabled = false;
  }
}

// Event Listeners
els.instantDeleteToggle.addEventListener("change", () => {
  state.instantDelete = els.instantDeleteToggle.checked;
  state.confirmingDeleteId = null;
  renderCards();
});

els.refreshBtn.addEventListener("click", () => loadThoughts());

els.settingsBtn.addEventListener("click", async () => {
  await loadConfig();
  els.apiKeyInput.value = "";
  els.settingsModal.classList.remove("hidden");
});

els.closeSettingsBtn.addEventListener("click", () => els.settingsModal.classList.add("hidden"));
els.cancelSettingsBtn.addEventListener("click", () => els.settingsModal.classList.add("hidden"));

els.settingsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    baseUrl: els.baseUrlInput.value.trim(),
    apiKey: els.apiKeyInput.value.trim(),
    cardCount: parseInt(els.cardCountInput.value, 10) || 5,
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
    els.settingsModal.classList.add("hidden");
    showToast("API-Einstellungen gespeichert!");
    await loadThoughts();
  } catch (err) {
    showToast(`Fehler: ${err.message}`, true);
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
  if (e.key === "Escape") {
    closeLightbox();
    els.settingsModal.classList.add("hidden");
    if (state.confirmingDeleteId) {
      state.confirmingDeleteId = null;
      renderCards();
    }
  } else if (
    (e.key === "r" || e.key === "R") &&
    !e.metaKey &&
    !e.ctrlKey &&
    document.activeElement.tagName !== "INPUT"
  ) {
    loadThoughts();
  }
});

// Initialize
(async function init() {
  await loadConfig();
  await loadThoughts();
})();
