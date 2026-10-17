"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const controls = [...document.querySelectorAll("input[data-option], select[data-option]")];
  const chartRadios = [...document.querySelectorAll('input[name="chart"]')];
  const wideScreen = matchMedia("(min-width: 48rem)");
  // Chrome fits a 96-dpi paper box with 10px of native page shadow/margins.
  const previewPageInset = 10;
  const previewToolbarHeight = 56;
  const previewScrollbarWidth = 1;
  let worker;
  let ready = false;
  let hasTree = false;
  let currentTreeChoice = null;
  let fonts = "embedded";
  let root = null;
  let pdfUrl = null;
  let pdfPreview = null;
  let searchSeq = 0;
  let renderSeq = 0;
  let lastRenderSent = 0;
  let renderInFlight = false;
  let openOutstanding = 0;
  const openingFiles = [];
  let fileChoice = 0;
  let heldFile = null;
  let searchTimer = null;
  let pendingSearch = null;
  let pickFirstSeq = null;
  let sampleRootSearch = null;
  let resultRows = [];
  let resultsCurrent = false;
  let searchInFlightSeq = null;
  let activeRootIndex = -1;
  const optionTimers = new Map();
  // The selector stores a cascade ordinal; the numerical input retains its draft.
  let pedigreeGenerationMode = "all";
  let pedigreePresets = [];
  // Root facts have their own currency, independent of searches and PDF renders.
  let treeVersion = 0;
  let metadataSeq = 0;
  let pendingMetadata = null;
  let rootMetadata = null;
  let rootFamily = "";

  function pedigreeGenerations() {
    if (pedigreeGenerationMode === "custom") {
      const value = byId("pedigree-generations").value;
      return value === "" ? null : Number(value);
    }
    if (pedigreeGenerationMode === "all") return null;
    return pedigreePresets[Number(pedigreeGenerationMode)];
  }

  function metadataContext() {
    return {
      treeVersion, rootId: root?.[0],
      adoptiveParents: byId("adoptive-parents").checked,
      largePrint: byId("large-print").checked,
      excludePrivate: byId("exclude-private").checked,
      preserveCase: !byId("preserve-case").checked,
    };
  }

  function matchesMetadataContext(metadata) {
    const context = metadataContext();
    return root && metadata && Object.keys(context).every((key) => metadata[key] === context[key]);
  }

  function updateGenerationChoices() {
    const current = matchesMetadataContext(rootMetadata);
    if (current) {
      const first = rootMetadata.largePrint ? 3 : 4;
      const stride = first - 1;
      const levels = Math.max(1, Math.ceil((rootMetadata.depth - first) / stride) + 1);
      pedigreePresets = Array.from({length: levels}, (_, index) => first + index * stride);
      if (pedigreeGenerationMode !== "all" && pedigreeGenerationMode !== "custom") {
        pedigreeGenerationMode = String(Math.min(Number(pedigreeGenerationMode), levels - 1));
      }
    }
    const choice = byId("pedigree-generation-choice");
    const options = [new Option("All generations", "all"), ...pedigreePresets.map((value, index) => {
      const option = new Option(String(value), String(index));
      // Keep a pending preset's intent selected, but do not offer stale depths.
      option.disabled = !current;
      return option;
    }), new Option("Custom…", "custom")];
    choice.replaceChildren(...options);
    choice.value = pedigreeGenerationMode;
  }

  function showRootFamily() {
    byId("root-family-field").hidden = selectedChart() !== "pedigree" ||
      !matchesMetadataContext(rootMetadata) || rootMetadata.families.length < 2;
  }

  function updateRootFamilyChoices() {
    const current = matchesMetadataContext(rootMetadata);
    const choice = byId("root-family");
    const families = current ? rootMetadata.families : [];
    const options = [new Option(root && !current ? "Loading marriages…" : "First recorded marriage", ""),
      ...families.map((family) => new Option(family.label, family.id))];
    choice.replaceChildren(...options);
    if (current && rootFamily && !families.some((family) => family.id === rootFamily)) rootFamily = "";
    choice.value = current ? rootFamily : "";
    choice.disabled = !current || families.length === 0;
    showRootFamily();
  }

  function invalidateRootMetadata() {
    metadataSeq += 1;
    pendingMetadata = null;
    rootMetadata = null;
    updateGenerationChoices();
    updateRootFamilyChoices();
  }

  function ensureRootMetadata() {
    if (!ready || !root || openOutstanding || matchesMetadataContext(rootMetadata) || pendingMetadata) return;
    pendingMetadata = {type: "root-metadata", seq: metadataSeq, ...metadataContext()};
    worker.postMessage(pendingMetadata);
  }

  function selectedChart() {
    return chartRadios.find((radio) => radio.checked).value;
  }

  function belongsToChart(control, chart) {
    return control.dataset.charts.split(/\s+/).includes(chart);
  }

  function activeControls(chart = selectedChart()) {
    // Collapsed disclosures and hidden ancestors do not determine ownership.
    return controls.filter((control) => belongsToChart(control, chart));
  }

  function showChart() {
    const chart = selectedChart();
    for (const field of document.querySelectorAll(".field[data-charts]")) {
      field.hidden = !belongsToChart(field, chart) ||
        (field.id === "custom-generations-field" && pedigreeGenerationMode !== "custom");
    }
    showRootFamily();
  }

  function validSettings(chart = selectedChart()) {
    const active = activeControls(chart);
    if (chart === "pedigree") {
      const generations = byId("pedigree-generations");
      const empty = generations.value === "" && !generations.validity.badInput;
      const number = generations.valueAsNumber;
      const valid = pedigreeGenerationMode !== "custom" || empty || (!generations.validity.badInput &&
        Number.isFinite(number) && Number.isInteger(number) && number >= 1);
      generations.setCustomValidity(valid ? "" : "Enter a whole number of at least 1, or leave empty.");
      generations.setAttribute("aria-invalid", String(!valid));
      byId("generations-error").hidden = valid;
    }
    return active.every((control) =>
      (control.id === "pedigree-generations" && pedigreeGenerationMode !== "custom") || control.validity.valid);
  }

  function settingsSnapshot(chart) {
    const settings = {};
    for (const control of activeControls(chart)) {
      const key = control.dataset.option;
      if (key === "footer") continue;
      if (key === "generations") {
        settings[key] = chart === "pedigree" ? pedigreeGenerations() : Number(control.value);
      } else if (control.type === "checkbox") {
        settings[key] = ["empty_boxes", "preserve_case"].includes(key) ? !control.checked : control.checked;
      } else if (key === "root_family") {
        settings[key] = rootFamily || null;
      } else if (key === "title") {
        settings[key] = control.value === "" ? null : control.value;
      } else {
        settings[key] = control.value;
      }
    }
    settings.footer = byId("no-footer").checked ? false : (byId("footer").value || null);
    return settings;
  }

  function updateDisabled() {
    byId("root-controls").disabled = !ready || !hasTree;
    byId("option-controls").disabled = !ready;
    byId("footer").disabled = byId("no-footer").checked;
  }

  function showError(target, message, details = "") {
    target.replaceChildren();
    const text = document.createElement("p");
    text.textContent = message;
    target.append(text);
    if (details) {
      const disclosure = document.createElement("details");
      const heading = document.createElement("summary");
      heading.textContent = "Details";
      const trace = document.createElement("pre");
      trace.textContent = details;
      disclosure.append(heading, trace);
      target.append(disclosure);
    }
    target.hidden = false;
  }

  function clearError(target) {
    target.hidden = true;
    target.replaceChildren();
  }

  function updateRendering() {
    const rendering = renderInFlight && Boolean(root);
    const preview = pdfUrl && navigator.pdfViewerEnabled && wideScreen.matches;
    byId("rendering-overlay").hidden = !rendering;
    byId("render-status").hidden = !rendering || Boolean(preview);
    byId("pdf-section").setAttribute("aria-busy", String(rendering));
    byId("root-prompt").hidden = !hasTree || Boolean(root || pdfUrl);
  }

  function updatePreview() {
    const preview = Boolean(pdfUrl && navigator.pdfViewerEnabled && wideScreen.matches);
    byId("preview").hidden = !preview;
    byId("open-pdf").hidden = preview;
    const frame = byId("pdf-frame");
    if (preview) {
      // Unhide before measuring. Geometry belongs to this accepted PDF reply,
      // including a fan reply accepted after switching to invalid pedigree fields.
      const width = frame.clientWidth;
      if (width > 0 && pdfPreview) {
        // Show one paper page; the native viewer navigates the remaining pages.
        const paperWidth = pdfPreview.width * 96 / 72;
        const paperHeight = pdfPreview.height * 96 / 72;
        const fitZoom = (width - previewScrollbarWidth) / (paperWidth + previewPageInset);
        const borderHeight = frame.offsetHeight - frame.clientHeight;
        const height = Math.ceil((paperHeight + previewPageInset) * fitZoom +
          previewToolbarHeight + borderHeight);
        frame.style.height = `${height}px`;
        const displayUrl = `${pdfUrl}#view=FitH&navpanes=0`;
        // Width changes resize the frame without reloading the native viewer.
        if (frame.getAttribute("src") !== displayUrl) frame.src = displayUrl;
      }
    } else {
      frame.removeAttribute("src");
    }
    updateRendering();
  }

  function clearPdf() {
    byId("pdf-frame").removeAttribute("src");
    byId("download-pdf").removeAttribute("href");
    byId("download-pdf").removeAttribute("download");
    byId("open-pdf").removeAttribute("href");
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    pdfUrl = null;
    pdfPreview = null;
    byId("pdf-frame").style.removeProperty("height");
    byId("pdf-summary").textContent = "";
    byId("pdf-section").hidden = true;
    updatePreview();
  }

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} bytes`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function showPdf(reply) {
    // Revoke first so there is never more than one live PDF URL.
    clearPdf();
    const blob = new Blob([reply.pdf], {type: "application/pdf"});
    pdfUrl = URL.createObjectURL(blob);
    pdfPreview = reply.preview;
    byId("download-pdf").href = pdfUrl;
    byId("download-pdf").download = reply.filename;
    byId("open-pdf").href = pdfUrl;
    const fontNote = fonts === "base14" ? " · Built-in fonts used" : "";
    byId("pdf-summary").textContent = `${reply.summary} · ${humanSize(blob.size)}${fontNote}`;
    byId("pdf-section").hidden = false;
    updatePreview();
  }

  function maybeRender() {
    ensureRootMetadata();
    if (!ready || renderInFlight || openOutstanding || !root) return;
    const chart = selectedChart();
    if (chart === "pedigree" && pedigreeGenerationMode !== "all" &&
        pedigreeGenerationMode !== "custom" && !matchesMetadataContext(rootMetadata)) return;
    if (!validSettings(chart) || renderSeq <= lastRenderSent) return;
    // Capture all fields together from current controls, never from an earlier edit.
    const request = {
      type: "render", seq: renderSeq, rootId: root[0], chart,
      settings: settingsSnapshot(chart),
    };
    lastRenderSent = request.seq;
    renderInFlight = true;
    clearError(byId("request-error"));
    updateRendering();
    worker.postMessage(request);
  }

  function setActiveRoot(index) {
    activeRootIndex = index;
    const buttons = [...byId("results").querySelectorAll("button")];
    for (const [position, button] of buttons.entries()) {
      button.setAttribute("aria-selected", String(position === index));
    }
    const active = buttons[index];
    if (active && !byId("root-choices").hidden) {
      byId("search").setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({block: "nearest"});
    } else {
      byId("search").removeAttribute("aria-activedescendant");
    }
  }

  function invalidateRootQuery() {
    clearTimeout(searchTimer);
    searchTimer = null;
    pendingSearch = null;
    pickFirstSeq = null;
    sampleRootSearch = null;
    searchInFlightSeq = null;
    searchSeq += 1;
    resultsCurrent = false;
    resultRows = [];
    setActiveRoot(-1);
    byId("results").replaceChildren();
    byId("result-summary").textContent = "";
  }

  function updateRootAction() {
    byId("root-action").setAttribute("aria-label", root ? "Clear selected person" : "Open person list");
    byId("root-clear-icon").toggleAttribute("hidden", !root);
    byId("root-list-icon").toggleAttribute("hidden", Boolean(root));
  }

  function setRootChoicesOpen(open) {
    byId("root-choices").hidden = !open;
    byId("search").setAttribute("aria-expanded", String(open));
    if (!open) {
      setActiveRoot(-1);
      // Dismissal cancels a pending manual Enter, never the sample's I1 intent.
      pickFirstSeq = null;
      if (pendingSearch) pendingSearch.pickFirst = false;
      if (root && byId("search").value !== root[1]) {
        byId("search").value = root[1];
        // The restored field and future suggestions must describe the same query.
        invalidateRootQuery();
      }
    }
  }

  function pickRoot(row) {
    if (root?.[0] !== row[0]) rootFamily = "";
    root = [...row];
    invalidateRootMetadata();
    const queryChanged = byId("search").value !== root[1];
    byId("search").value = root[1];
    byId("root-summary").textContent = `Root: ${root[0]}, ${root[1]}`;
    updateRootAction();
    setRootChoicesOpen(false);
    if (queryChanged) {
      // The committed name replaces the query; its old rows cannot be reused.
      invalidateRootQuery();
    }
    renderSeq += 1;
    updateRendering();
    maybeRender();
  }

  function clearRoot() {
    root = null;
    rootFamily = "";
    invalidateRootMetadata();
    // Explicit clearing ends the opened sample's automatic selection intent.
    if (currentTreeChoice) currentTreeChoice = {...currentTreeChoice, rootId: null};
    // Keep queued file opens, but a newer clear supersedes their root intent.
    for (const choice of openingFiles) choice.rootId = null;
    byId("search").value = "";
    byId("root-summary").textContent = "Choose a root person.";
    setRootChoicesOpen(false);
    invalidateRootQuery();
    updateRootAction();
    clearError(byId("request-error"));
    clearPdf();
    // Keep the existing render barrier; a late reply has no selected recipient.
    byId("search").focus();
    setRootChoicesOpen(false);
  }

  function showResults(reply) {
    setActiveRoot(-1);
    byId("results").replaceChildren();
    const rows = reply.rows.slice(0, 200);
    resultRows = rows;
    resultsCurrent = true;
    searchInFlightSeq = null;
    byId("result-summary").textContent = reply.total > rows.length
      ? `${rows.length} of ${reply.total} shown`
      : `${reply.total} ${reply.total === 1 ? "match" : "matches"}`;
    for (const [position, row] of rows.entries()) {
      const item = document.createElement("li");
      item.setAttribute("role", "presentation");
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.id = `root-option-${reply.seq}-${position}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", "false");
      button.dataset.recordId = row[0];
      for (const [index, className] of [[1, "person-name"], [0, "record-id"], [2, "years"]]) {
        const part = document.createElement("span");
        part.className = className;
        part.textContent = row[index];
        button.append(part);
      }
      // Options stay outside the Tab sequence and preserve input DOM focus.
      button.addEventListener("pointerdown", (event) => {
        if (event.button === 0) event.preventDefault();
      });
      button.addEventListener("pointermove", () => {
        if (resultsCurrent && !openOutstanding) setActiveRoot(position);
      });
      button.addEventListener("click", () => {
        if (resultsCurrent && !openOutstanding) pickRoot(row);
      });
      item.append(button);
      byId("results").append(item);
    }
    const sampleRow = !root && sampleRootSearch?.seq === reply.seq
      ? rows.find((row) => row[0] === sampleRootSearch.rootId) : null;
    if (rows.length && pickFirstSeq === reply.seq) {
      pickRoot(rows[0]);
    } else if (sampleRow) {
      pickRoot(sampleRow);
    }
    pickFirstSeq = null;
    sampleRootSearch = null;
  }

  function sendPendingSearch() {
    clearTimeout(searchTimer);
    searchTimer = null;
    if (!ready || !hasTree || openOutstanding || !pendingSearch) return;
    const seq = pendingSearch.seq;
    pickFirstSeq = pendingSearch.pickFirst ? seq : null;
    sampleRootSearch = pendingSearch.rootId ? {seq, rootId: pendingSearch.rootId} : null;
    pendingSearch = null;
    searchInFlightSeq = seq;
    worker.postMessage({
      type: "search", seq, text: byId("search").value,
      excludePrivate: byId("exclude-private").checked,
      standins: byId("event-standins").checked,
    });
  }

  function scheduleSearch(immediate = false, pickFirst = false) {
    clearTimeout(searchTimer);
    searchSeq += 1;
    resultsCurrent = false;
    resultRows = [];
    setActiveRoot(-1);
    byId("results").replaceChildren();
    byId("result-summary").textContent = "Searching…";
    // Only the successfully opened file owns automatic sample selection. This
    // survives option/search refreshes without leaking to a replacement file.
    const rootId = !root ? currentTreeChoice?.rootId : null;
    pendingSearch = {seq: searchSeq, pickFirst, rootId};
    if (immediate) sendPendingSearch();
    else searchTimer = setTimeout(sendPendingSearch, 150);
  }

  function sendOpen(choice, bytes) {
    clearTimeout(searchTimer);
    searchTimer = null;
    pendingSearch = null;
    pickFirstSeq = null;
    sampleRootSearch = null;
    searchInFlightSeq = null;
    setRootChoicesOpen(false);
    searchSeq += 1;
    renderSeq += 1;
    invalidateRootMetadata();
    openOutstanding += 1;
    openingFiles.push(choice);
    clearError(byId("open-error"));
    worker.postMessage({type: "open", bytes}, [bytes]);
  }

  async function readChoice(choice) {
    try {
      const bytes = choice.file ? await choice.file.arrayBuffer() : choice.bytes;
      // Choosing is ordered before reading: a slow earlier read cannot win.
      if (choice.id !== fileChoice) return;
      sendOpen(choice, bytes);
    } catch (error) {
      if (choice.id === fileChoice) {
        showError(byId("open-error"), `Unable to read ${choice.name}: ${error.message || error}`);
      }
    }
  }

  function chooseFile(file) {
    if (!file) return;
    const choice = {id: ++fileChoice, name: file.name, file};
    if (ready) void readChoice(choice);
    else heldFile = choice;
  }

  function optionChanged(control) {
    if (!belongsToChart(control, selectedChart())) return;
    if (control.id === "root-family") rootFamily = control.value;
    if (["large-print", "adoptive-parents", "exclude-private", "preserve-case"].includes(control.id)) {
      invalidateRootMetadata();
      ensureRootMetadata();
    }
    if (control.dataset.option === "footer") updateDisabled();
    if (control.dataset.option === "exclude_private" || control.dataset.option === "event_standins") {
      scheduleSearch(true);
    }
    if (validSettings()) {
      renderSeq += 1;
      maybeRender();
    }
  }

  function initFailed(step, host, message) {
    const hint = step === "Installing Kincade" && host === "this site" && message.startsWith("Download failed:")
      ? " Reload the page. If the download still fails, report this URL to the site owner."
      : "";
    byId("status").classList.remove("visually-hidden");
    byId("status").textContent = `${step} failed (${host}): ${message}${hint}`;
    byId("retry").hidden = false;
  }

  function receive({data: reply}) {
    switch (reply.type) {
      case "status":
        byId("status").classList.remove("visually-hidden");
        byId("status").textContent = reply.text;
        break;
      case "ready":
        ready = true;
        fonts = reply.fonts;
        byId("status").textContent = "Ready";
        byId("status").classList.add("visually-hidden");
        byId("version").textContent = `Version ${reply.kincade || manifest.kincade}`;
        updateDisabled();
        if (heldFile) {
          const choice = heldFile;
          heldFile = null;
          void readChoice(choice);
        }
        break;
      case "failed":
        initFailed(reply.step, reply.host, reply.message);
        break;
      case "opened": {
        const choice = openingFiles.shift();
        openOutstanding -= 1;
        hasTree = true;
        currentTreeChoice = choice;
        byId("sample").hidden = choice.source === "sample";
        byId("file-summary").textContent = `${choice.name}: ${reply.count} people`;
        root = null;
        rootFamily = "";
        treeVersion += 1;
        invalidateRootMetadata();
        updateRootAction();
        setRootChoicesOpen(false);
        byId("search").value = "";
        byId("results").replaceChildren();
        byId("result-summary").textContent = "";
        byId("root-summary").textContent = "Choose a root person.";
        clearPdf();
        clearError(byId("open-error"));
        clearError(byId("request-error"));
        updateDisabled();
        scheduleSearch(true);
        break;
      }
      case "results":
        if (reply.seq === searchSeq) {
          clearError(byId("request-error"));
          showResults(reply);
        }
        break;
      case "root-metadata":
        if (reply.seq === pendingMetadata?.seq && !openOutstanding && matchesMetadataContext(reply)) {
          rootMetadata = reply;
          pendingMetadata = null;
          updateGenerationChoices();
          updateRootFamilyChoices();
          maybeRender();
        }
        break;
      case "rendered":
        renderInFlight = false;
        // A current reply still applies across an invalid chart switch, but an
        // explicitly cleared selection has no recipient for its old PDF.
        if (root && reply.seq === renderSeq) {
          clearError(byId("request-error"));
          showPdf(reply);
        }
        maybeRender();
        updateRendering();
        break;
      case "error":
        if (reply.request === "open") {
          openingFiles.shift();
          openOutstanding -= 1;
          showError(byId("open-error"), reply.message, reply.details);
          if (!openOutstanding) {
            if (!root && currentTreeChoice?.rootId && !pendingSearch) {
              scheduleSearch(true);
            } else {
              sendPendingSearch();
            }
          }
          maybeRender();
        } else if (reply.request === "search") {
          if (reply.seq === searchSeq) {
            searchInFlightSeq = null;
            byId("result-summary").textContent = "Search unavailable.";
            showError(byId("request-error"), reply.message, reply.details);
          }
        } else if (reply.request === "root-metadata") {
          if (root && reply.seq === pendingMetadata?.seq) {
            showError(byId("request-error"), reply.message, reply.details);
          }
        } else if (reply.request === "render") {
          renderInFlight = false;
          if (root && reply.seq === renderSeq) showError(byId("request-error"), reply.message, reply.details);
          maybeRender();
          updateRendering();
        }
        break;
    }
  }

  byId("retry").addEventListener("click", () => location.reload());
  byId("drop-zone").addEventListener("click", (event) => {
    if (event.target !== byId("file")) byId("file").click();
  });
  byId("file").addEventListener("change", (event) => {
    chooseFile(event.target.files[0]);
    event.target.value = "";
  });
  byId("drop-zone").addEventListener("dragover", (event) => {
    event.preventDefault();
    byId("drop-zone").classList.add("dragging");
  });
  byId("drop-zone").addEventListener("dragleave", () => byId("drop-zone").classList.remove("dragging"));
  byId("drop-zone").addEventListener("drop", (event) => {
    event.preventDefault();
    byId("drop-zone").classList.remove("dragging");
    chooseFile(event.dataTransfer.files[0]);
  });
  byId("sample").addEventListener("click", () => {
    const choice = {
      id: ++fileChoice, name: manifest.sample.name, rootId: "I1", source: "sample",
      bytes: new TextEncoder().encode(manifest.sample.text).buffer,
    };
    if (ready) void readChoice(choice);
    else heldFile = choice;
  });
  function ensureRootResults() {
    if (!resultsCurrent && !pendingSearch && searchInFlightSeq !== searchSeq) {
      scheduleSearch();
    }
  }

  function openRootChoices() {
    setRootChoicesOpen(true);
    ensureRootResults();
    if (root && byId("search").value === root[1]) byId("search").select();
  }

  byId("root-action").addEventListener("click", () => {
    if (root) {
      clearRoot();
    } else {
      byId("search").focus();
      openRootChoices();
    }
  });
  byId("search").addEventListener("focus", openRootChoices);
  byId("search").addEventListener("click", openRootChoices);
  byId("search").addEventListener("input", () => {
    setRootChoicesOpen(true);
    scheduleSearch();
  });
  byId("root-controls").addEventListener("focusout", (event) => {
    if (!byId("root-controls").contains(event.relatedTarget)) setRootChoicesOpen(false);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!byId("root-controls").contains(event.target)) setRootChoicesOpen(false);
  });
  byId("search").addEventListener("keydown", (event) => {
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape" || event.key === "Tab") {
      if (event.key === "Escape") event.preventDefault();
      setRootChoicesOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setRootChoicesOpen(true);
      ensureRootResults();
      if (resultsCurrent && !openOutstanding && resultRows.length) {
        const last = resultRows.length - 1;
        const index = activeRootIndex < 0
          ? (event.key === "ArrowDown" ? 0 : last)
          : Math.max(0, Math.min(last, activeRootIndex + (event.key === "ArrowDown" ? 1 : -1)));
        setActiveRoot(index);
      }
      return;
    }
    if (event.key !== "Enter") return;
    event.preventDefault();
    // Enter on an unchanged, closed selection retains that committed person.
    if (root && byId("root-choices").hidden && byId("search").value === root[1]) return;
    if (pendingSearch) {
      pendingSearch.pickFirst = true;
      sendPendingSearch();
    } else if (searchInFlightSeq === searchSeq) {
      // The current reply is already on its way; never pick an older row.
      pickFirstSeq = searchSeq;
    } else if (resultsCurrent && !openOutstanding) {
      const row = resultRows[activeRootIndex < 0 ? 0 : activeRootIndex];
      if (row) pickRoot(row);
    } else {
      scheduleSearch(true, true);
    }
  });
  byId("pedigree-generation-choice").addEventListener("change", () => {
    const wasValid = validSettings("pedigree");
    const previous = pedigreeGenerations();
    pedigreeGenerationMode = byId("pedigree-generation-choice").value;
    showChart();
    if (pedigreeGenerationMode === "custom") {
      byId("more-options").open = true;
      byId("pedigree-generations").focus();
    }
    if (validSettings("pedigree") && (!wasValid || previous !== pedigreeGenerations())) {
      renderSeq += 1;
      maybeRender();
    }
  });
  for (const radio of chartRadios) {
    radio.addEventListener("change", () => {
      showChart();
      if (validSettings()) {
        renderSeq += 1;
        maybeRender();
      }
    });
  }
  for (const control of controls) {
    if (control.type === "text") {
      control.addEventListener("input", () => {
        clearTimeout(optionTimers.get(control));
        optionTimers.set(control, setTimeout(() => {
          optionTimers.delete(control);
          optionChanged(control);
        }, 400));
      });
    } else {
      control.addEventListener(control.type === "number" ? "input" : "change", () => {
        if (control.id === "no-footer") {
          clearTimeout(optionTimers.get(byId("footer")));
          optionTimers.delete(byId("footer"));
        }
        optionChanged(control);
      });
    }
  }
  let observedPreviewWidth = 0;
  const previewObserver = new ResizeObserver(([entry]) => {
    const width = entry.contentRect.width;
    // Ignore hidden containers and height-only changes caused by sizing the frame.
    if (width > 0 && width !== observedPreviewWidth) {
      observedPreviewWidth = width;
      updatePreview();
    }
  });
  previewObserver.observe(byId("preview"));
  wideScreen.addEventListener("change", updatePreview);
  window.addEventListener("pagehide", (event) => {
    // A cached page keeps its PDF available when the reader returns with Back.
    if (!event.persisted && pdfUrl) URL.revokeObjectURL(pdfUrl);
  });
  byId("footer").placeholder = `Created ${new Date().toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric",
  })} using Kincade`;
  showChart();
  updateDisabled();
  let manifest;
  try {
    manifest = JSON.parse(byId("manifest").textContent);
    byId("version").textContent = `Version ${manifest.kincade}`;
    const workerUrl = URL.createObjectURL(new Blob([byId("worker").textContent], {type: "text/javascript"}));
    try {
      worker = new Worker(workerUrl, {type: "module"});
    } finally {
      URL.revokeObjectURL(workerUrl);
    }
    worker.addEventListener("message", receive);
    worker.addEventListener("error", (event) => initFailed("Starting Kincade", "browser", event.message));
    // Static hosts can serve /kincade without redirecting to /kincade/.
    // Resolve assets from that directory, also supporting / and /index.html.
    const directoryPath = location.pathname.endsWith("/index.html")
      ? location.pathname.slice(0, -"index.html".length)
      : location.pathname.replace(/\/?$/, "/");
    const siteDirectory = new URL(directoryPath, location.origin);
    worker.postMessage({
      type: "init", manifest, glue: byId("glue").textContent,
      wheelUrl: new URL(manifest.wheel.name, siteDirectory).href,
    });
  } catch (error) {
    initFailed("Starting Kincade", "browser", error.message || String(error));
  }
})();
