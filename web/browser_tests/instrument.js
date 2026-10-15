// Only the acceptance harness installs this. Every request still runs in the real worker.
(() => {
  if (window.acceptance) return;
  const NativeWorker = Worker;
  const initialGates = (new URL(location.href).searchParams.get('acceptanceHold') || '')
    .split(',').filter(Boolean).map(type => [type, true]);
  const a = window.acceptance = {sent: [], replies: [], held: [], gates: Object.fromEntries(initialGates), pdfs: [], violations: [], pageshows: []};
  const createObjectURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = blob => {
    const url = createObjectURL(blob);
    if (blob.type === 'application/pdf') a.pdfs.push({url, size: blob.size});
    return url;
  };
  document.addEventListener('securitypolicyviolation', e => a.violations.push(e.violatedDirective));
  addEventListener('pageshow', e => a.pageshows.push(e.persisted));
  a.hold = type => { a.gates[type] = true; };
  a.releaseOne = (type, seq = null) => {
    const index = a.held.findIndex(x => x.event.data.type === type &&
      (seq === null || x.event.data.seq === seq));
    if (index < 0) throw Error(`No held ${type} reply for sequence ${seq}`);
    const [item] = a.held.splice(index, 1);
    // Keep the gate closed: later replies still wait until explicitly released.
    item.deliver();
  };
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
