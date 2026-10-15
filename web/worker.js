"use strict";

let pyodide = null;
let dispatchPython = null;
let queue = Promise.resolve();
let step = "Loading Pyodide";
let host = "jsDelivr";

function status(text, source) {
  step = text;
  host = source;
  self.postMessage({type: "status", text});
}

async function fetchBytes(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Download failed: HTTP ${response.status}`);
  }
  return new Uint8Array(await response.arrayBuffer());
}

function sha256(bytes) {
  // Python's digest path also works when the page is served over plain HTTP.
  pyodide.globals.set("_web_digest_bytes", bytes);
  try {
    return pyodide.runPython(`
import hashlib
hashlib.sha256(_web_digest_bytes.to_bytes()).hexdigest()
`);
  } finally {
    pyodide.globals.delete("_web_digest_bytes");
  }
}

async function install(requirement) {
  pyodide.globals.set("_web_requirement", requirement);
  try {
    await pyodide.runPythonAsync(`
import micropip
await micropip.install(_web_requirement)
`);
  } finally {
    pyodide.globals.delete("_web_requirement");
  }
}

async function initialize({manifest, glue, wheelUrl}) {
  status("Loading Pyodide", "jsDelivr");
  const {loadPyodide} = await import(`${manifest.pyodide.base}pyodide.mjs`);
  pyodide = await loadPyodide({indexURL: manifest.pyodide.base});

  status("Loading micropip", "jsDelivr");
  await pyodide.loadPackage("micropip");

  status("Installing reportlab", "PyPI (reportlab), jsDelivr (Pillow, charset-normalizer)");
  await install(manifest.reportlab);

  status("Installing Kincade", "this site");
  const wheel = await fetchBytes(`${wheelUrl}?v=${manifest.wheel.sha256.slice(0, 12)}`);
  const wheelPath = `/tmp/${manifest.wheel.name}`;
  pyodide.FS.writeFile(wheelPath, wheel);
  if (sha256(wheel) !== manifest.wheel.sha256) {
    throw new Error(
      "The HTML and Kincade wheel may be from different cached builds. Reload the page to download matching files."
    );
  }
  await install(`emfs:${wheelPath}`);

  status("Loading fonts", "jsDelivr");
  pyodide.FS.mkdirTree("/fonts");
  for (const font of manifest.fonts) {
    try {
      const bytes = await fetchBytes(font.url);
      if (sha256(bytes) === font.sha256) {
        pyodide.FS.writeFile(`/fonts/${font.name}`, bytes);
      }
    } catch {
      // Each unavailable font is independent; the Session chooses fallback faces.
    }
  }

  status("Starting Kincade", "—");
  pyodide.runPython(glue);
  pyodide.runPython(`
import json
import traceback

_web_session = Session()
_web_tree_version = 0

def _web_dispatch(request_json, data):
    global _web_tree_version
    request = json.loads(request_json)
    operation = request["type"]
    try:
        if operation == "open":
            count = _web_session.open(data.to_bytes())
            _web_tree_version += 1
            return {"type": "opened", "count": count}
        if operation == "search":
            total, rows = _web_session.search(
                request["text"], request["excludePrivate"], request["standins"]
            )
            return {
                "type": "results", "seq": request["seq"],
                "total": total, "rows": rows,
            }
        if operation == "root-metadata":
            if request["treeVersion"] != _web_tree_version:
                raise ValueError("The family tree has changed")
            depth = _web_session.pedigree_depth(
                request["rootId"], request["adoptiveParents"], request["largePrint"]
            )
            families = _web_session.root_families(
                request["rootId"], request["excludePrivate"], request["preserveCase"]
            )
            return {
                "type": "root-metadata", "seq": request["seq"],
                "treeVersion": _web_tree_version, "rootId": request["rootId"],
                "adoptiveParents": request["adoptiveParents"],
                "largePrint": request["largePrint"], "depth": depth,
                "excludePrivate": request["excludePrivate"],
                "preserveCase": request["preserveCase"], "families": families,
            }
        if operation == "render":
            pdf, filename, summary = _web_session.render(
                request["rootId"], request["chart"], request["settings"]
            )
            return {
                "type": "rendered", "seq": request["seq"],
                "pdf": pdf, "filename": filename, "summary": summary,
                "preview": _web_session.preview,
            }
        raise ValueError(f"Unknown request {operation!r}")
    except Exception as error:
        reply = {
            "type": "error", "request": operation,
            "message": str(error) if isinstance(error, ValueError)
                else f"Unable to {operation} the family tree.",
            "details": "" if isinstance(error, ValueError) else traceback.format_exc(),
        }
        if operation in ("search", "render", "root-metadata"):
            reply["seq"] = request["seq"]
        return reply
`);
  const fonts = pyodide.runPython('_web_session.load_fonts("/fonts")');
  dispatchPython = pyodide.globals.get("_web_dispatch");
  self.postMessage({type: "ready", fonts, kincade: manifest.kincade});
}

async function dispatch(request) {
  if (request.type === "init") {
    await initialize(request);
    return;
  }
  if (!dispatchPython) {
    throw new Error("Kincade is not ready. Reload the page and try again.");
  }

  // JSON preserves plain settings (including null and booleans) as a Python dict.
  // The buffer is passed separately as a JsProxy, then converted to Python bytes.
  const metadata = JSON.stringify({...request, bytes: undefined});
  const bytes = request.type === "open" ? new Uint8Array(request.bytes) : null;
  const result = dispatchPython(metadata, bytes);
  let reply;
  try {
    reply = result.toJs({dict_converter: Object.fromEntries});
  } finally {
    result.destroy();
  }
  if (reply.type === "rendered") {
    const pdfBytes = reply.pdf;
    // The Python bytes conversion owns a JS buffer; transfer exactly the PDF span.
    reply.pdf = pdfBytes.byteOffset === 0 && pdfBytes.byteLength === pdfBytes.buffer.byteLength
      ? pdfBytes.buffer
      : pdfBytes.slice().buffer;
    self.postMessage(reply, [reply.pdf]);
  } else {
    self.postMessage(reply);
  }
}

function failed(request, error) {
  if (request.type === "init") {
    self.postMessage({type: "failed", step, host, message: String(error.message || error)});
    return;
  }
  const reply = {
    type: "error", request: request.type,
    message: String(error.message || error), details: String(error.stack || ""),
  };
  if (request.type === "search" || request.type === "render" || request.type === "root-metadata") {
    reply.seq = request.seq;
  }
  self.postMessage(reply);
}

self.onmessage = ({data}) => {
  // Capture each structured-cloned request before waiting; never read mutable UI state.
  // Catch on every link so a rejected request cannot poison later queued messages.
  queue = queue.then(() => dispatch(data)).catch((error) => failed(data, error));
};
