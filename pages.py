"""Local Upload Server - the web pages shown on the phone.

PAGE is the shared shell. LOGIN_BODY and UPLOAD_BODY fill its __BODY__ slot,
and __APP__ becomes the app name. Nothing here depends on the rest of the tool.
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__APP__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --bg:#f4f4f9; --card:#fff; --text:#1c1c1e; --muted:#6b6b76; --accent:#007bff; --line:#dcdce4; --ok:#1a9c4a; --err:#d92d20; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#121216; --card:#1e1e24; --text:#f2f2f5; --muted:#9a9aa6; --line:#33333d; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding:16px; font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
         background:var(--bg); color:var(--text); }
  .card { max-width:560px; margin:24px auto; background:var(--card); padding:22px; border-radius:14px;
          box-shadow:0 4px 14px rgba(0,0,0,.12); }
  h1 { font-size:1.3rem; margin:0 0 4px; }
  p.sub { margin:0 0 16px; color:var(--muted); font-size:.9rem; }
  .drop { border:2px dashed var(--line); border-radius:12px; padding:34px 12px; text-align:center;
          cursor:pointer; transition:.15s; }
  .drop.over { border-color:var(--accent); background:rgba(0,123,255,.08); }
  .drop strong { display:block; font-size:1.1rem; margin-bottom:4px; }
  .drop span { color:var(--muted); font-size:.85rem; }
  button, .btn { padding:13px 22px; font-size:1rem; background:var(--accent); color:#fff; border:0;
                 border-radius:8px; cursor:pointer; }
  input[type=password], input[type=text] { width:100%; padding:13px; font-size:1.2rem; text-align:center;
        border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); margin-bottom:12px; }
  .err { color:var(--err); margin-top:12px; text-align:center; }
  .item { margin-top:12px; font-size:.9rem; }
  .row { display:flex; justify-content:space-between; gap:10px; }
  .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .status { color:var(--muted); white-space:nowrap; }
  .status.ok { color:var(--ok); } .status.bad { color:var(--err); }
  .bar { height:6px; background:var(--line); border-radius:3px; margin-top:5px; overflow:hidden; }
  .bar > div { height:100%; width:0; background:var(--accent); transition:width .1s; }
  [hidden] { display:none !important; }
  .pending { margin-top:16px; padding:14px; border:1px solid var(--line); border-radius:12px; }
  .phead { display:flex; justify-content:space-between; font-size:.9rem; margin-bottom:8px; }
  .phead span { color:var(--muted); }
  .pitem { display:flex; align-items:center; gap:10px; padding:6px 0; font-size:.9rem; border-top:1px solid var(--line); }
  .pitem .name { flex:1; }
  .pitem .sz { color:var(--muted); white-space:nowrap; }
  .pitem .x { background:none; color:var(--muted); padding:0 8px; font-size:1.3rem; line-height:1; }
  .actions { display:flex; gap:10px; margin-top:12px; }
  .actions button { flex:1; }
  button.secondary { background:transparent; color:var(--text); border:1px solid var(--line); }
  .note { margin-top:18px; color:var(--muted); font-size:.8rem; text-align:center; }
</style>
</head>
<body>
<div class="card">
__BODY__
</div>
</body>
</html>"""

LOGIN_BODY = """<h1>Enter passcode</h1>
<p class="sub">This transfer page is protected.</p>
<form method="post" action="/login">
  <input type="password" name="passcode" inputmode="__MODE__" maxlength="__MAXLEN__" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" autofocus placeholder="Passcode">
  <button type="submit" style="width:100%">Unlock</button>
</form>
__ERROR__"""

UPLOAD_BODY = """<h1>__APP__ <small style="font-weight:400;color:var(--muted);font-size:.7em">by Mattias</small></h1>
<p class="sub">Saved to: __DIR__</p>
<div class="drop" id="drop">
  <strong>Tap to choose files</strong>
  <span>or drag &amp; drop them here</span>
</div>
<div class="pending" id="pending" hidden>
  <div class="phead"><strong id="pcount"></strong><span id="ptotal"></span></div>
  <div id="plist"></div>
  <div class="actions">
    <button id="go">Upload</button>
    <button id="clear" class="secondary">Clear</button>
  </div>
</div>
<div id="list"></div>
<p class="note">Keep your screen on while large files upload.</p>
<script>
const drop = document.getElementById('drop');
const list = document.getElementById('list');
const panel = document.getElementById('pending');
const plist = document.getElementById('plist');
const pcount = document.getElementById('pcount');
const ptotal = document.getElementById('ptotal');
const go = document.getElementById('go');
const clearBtn = document.getElementById('clear');
const pending = [];
const queue = [];
let running = false;

// A fresh <input> per selection: never reset an input that still has files queued,
// because some mobile browsers then lose access to the not-yet-uploaded files.
drop.onclick = () => {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.multiple = true;
  inp.onchange = () => add(Array.from(inp.files));
  inp.click();
};
['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => add(ev.dataTransfer.files));

function size(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
  if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}

// Step 1: selected files wait here until you confirm.
function add(files) {
  for (const f of files) {
    const dup = pending.some(p => p.name === f.name && p.size === f.size && p.lastModified === f.lastModified);
    if (!dup) pending.push(f);
  }
  renderPending();
}

function renderPending() {
  plist.textContent = '';
  pending.forEach((f, i) => {
    const row = document.createElement('div'); row.className = 'pitem';
    const name = document.createElement('span'); name.className = 'name'; name.textContent = f.name;
    const sz = document.createElement('span'); sz.className = 'sz'; sz.textContent = size(f.size);
    const x = document.createElement('button'); x.className = 'x'; x.textContent = '\u00d7'; x.title = 'Remove';
    x.onclick = () => { pending.splice(i, 1); renderPending(); };
    row.append(name, sz, x); plist.appendChild(row);
  });
  const n = pending.length;
  pcount.textContent = n + (n === 1 ? ' file selected' : ' files selected');
  ptotal.textContent = size(pending.reduce((sum, f) => sum + f.size, 0));
  go.textContent = 'Upload ' + n + (n === 1 ? ' file' : ' files');
  panel.hidden = n === 0;
}

go.onclick = () => { const files = pending.splice(0); renderPending(); enqueue(files); };
clearBtn.onclick = () => { pending.length = 0; renderPending(); };

// Step 2: confirmed files are uploaded one after another.
function enqueue(files) {
  for (const f of files) {
    const el = document.createElement('div');
    el.className = 'item';
    const row = document.createElement('div'); row.className = 'row';
    const name = document.createElement('span'); name.className = 'name'; name.textContent = f.name;
    const status = document.createElement('span'); status.className = 'status'; status.textContent = 'Waiting (' + size(f.size) + ')';
    const bar = document.createElement('div'); bar.className = 'bar';
    const fill = document.createElement('div'); bar.appendChild(fill);
    row.append(name, status); el.append(row, bar); list.prepend(el);
    queue.push({ f, status, fill });
  }
  if (!running) next();
}

function next() {
  const job = queue.shift();
  if (!job) { running = false; return; }
  running = true;
  const { f, status, fill } = job;
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload');
  xhr.setRequestHeader('X-Filename', encodeURIComponent(f.name));
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round(e.loaded / e.total * 100);
    fill.style.width = p + '%';
    status.textContent = p + '%';
  };
  xhr.onload = () => {
    if (xhr.status === 200) {
      fill.style.width = '100%';
      status.textContent = 'Done'; status.className = 'status ok';
    } else if (xhr.status === 401) {
      location.reload(); return;
    } else {
      status.textContent = xhr.responseText || 'Failed'; status.className = 'status bad';
    }
    next();
  };
  const fail = msg => { status.textContent = msg; status.className = 'status bad'; next(); };
  xhr.onerror = () => fail('Failed - could not read/send file');
  xhr.onabort = () => fail('Aborted');
  xhr.ontimeout = () => fail('Timed out');
  try { xhr.send(f); } catch (e) { fail('Failed: ' + e.message); }
}
</script>"""


def _wrap(app_name, body):
    return PAGE.replace("__BODY__", body).replace("__APP__", app_name).encode("utf-8")


def render_login(app_name, error="", numeric=False, max_len=12):
    """The passcode page. `numeric` shows a number keypad on phones."""
    err = f'<div class="err">{error}</div>' if error else ""
    body = (LOGIN_BODY.replace("__MODE__", "numeric" if numeric else "text")
            .replace("__MAXLEN__", str(max_len)).replace("__ERROR__", err))
    return _wrap(app_name, body)


def render_upload(app_name, save_dir):
    """The upload page, showing where files will be saved."""
    safe_dir = save_dir.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _wrap(app_name, UPLOAD_BODY.replace("__DIR__", safe_dir))
