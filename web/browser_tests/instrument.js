// Only the acceptance harness installs this. Every request still runs in the real worker.
(() => {
  if (window.acceptance) return;
  const NativeWorker = Worker;
  const a = window.acceptance = {sent: [], replies: [], held: [], gates: {}, pdfs: [], violations: []};
  const createObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = blob => {
    const url = createObjectURL(blob);
    if (blob.type === 'application/pdf') a.pdfs.push({url, size: blob.size});
    return url;
  };
  document.addEventListener('securitypolicyviolation', e => a.violations.push(e.violatedDirective));
  a.hold = type => { a.gates[type] = true; };
  a.release = type => {
    a.gates[type] = false;
    const held = a.held.filter(x => x.event.data.type === type);
    a.held = a.held.filter(x => x.event.data.type !== type);
    for (const item of held) item.deliver();
  };
  window.Worker = class extends NativeWorker {
    postMessage(data, ...rest) {
      a.sent.push(JSON.parse(JSON.stringify({...data, bytes: undefined, glue: undefined})));
      return super.postMessage(data, ...rest);
    }
    addEventListener(type, callback, ...rest) {
      if (type !== "message") return super.addEventListener(type, callback, ...rest);
      return super.addEventListener(type, event => {
        const data = event.data;
        a.replies.push({...data, pdf: undefined});
        const deliver = () => callback.call(this, event);
        if (a.gates[data.type]) a.held.push({event, deliver});
        else deliver();
      }, ...rest);
    }
  };
})();
