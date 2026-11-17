// Meshcat のポートはサーバーの /api/models から受け取る。
let meshcatPort = 7000;
const meshcatUrl = () => `${location.protocol}//${location.hostname}:${meshcatPort}/`;
const $ = id => document.getElementById(id);
let models = [], current = null, busy = false;
let parts = [], isolated = null;

// ---- モデル一覧

function render() {
  const q = $('q').value.trim().toLowerCase();
  const list = $('list'); list.textContent = '';
  let lastGrp = null, n = 0;
  for (const m of models) {
    if (q && !m.toLowerCase().includes(q)) continue;
    n++;
    const i = m.lastIndexOf('/'), grp = i < 0 ? '' : m.slice(0, i), name = m.slice(i + 1);
    if (grp !== lastGrp) {
      const g = document.createElement('div'); g.className = 'grp'; g.textContent = grp || '(root)';
      list.appendChild(g); lastGrp = grp;
    }
    const b = document.createElement('button');
    b.className = 'it' + (m === current ? ' cur' : ''); b.textContent = name; b.title = m;
    b.onclick = () => show(m);
    list.appendChild(b);
  }
  $('count').textContent = `${n} / ${models.length}`;
}

function setBar(text, err) { const b = $('bar'); b.textContent = text; b.className = err ? 'err' : ''; }

async function show(m) {
  if (busy) return;
  busy = true; setBar(`読み込み中: ${m}`);
  try {
    const r = await fetch(`/api/show?m=${encodeURIComponent(m)}&frames=${$('frames').checked ? 1 : 0}`);
    const j = await r.json();
    if (j.ok) {
      current = m; parts = j.parts; isolated = null; setBar(`表示中: ${m}`);
      $('view').src = meshcatUrl() + '?t=' + Date.now();
    } else {
      current = null; parts = []; isolated = null;
      setBar(`表示できません: ${m} — ${j.error} (親の構成から読み込まれる部分ファイルは単体では開けません)`, true);
    }
  } catch (e) { setBar('サーバーに接続できません: ' + e, true); }
  busy = false; render(); renderParts();
}

// ---- 部品と寸法

function cell(tr, text, cls) {
  const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls;
  tr.appendChild(td); return td;
}

function renderParts() {
  const q = $('pq').value.trim().toLowerCase();
  const withCollision = $('pcol').checked;
  const body = $('pbody'); body.textContent = '';
  let n = 0;
  for (const p of parts) {
    if (q && !p.name.toLowerCase().includes(q)) continue;
    const geoms = p.geoms.filter(g => withCollision || g.role === '見た目');
    if (!geoms.length) continue;
    n++;
    const head = document.createElement('tr');
    head.className = 'part' + (p.name === isolated ? ' cur' : '');
    head.title = 'クリックでこの部品だけを表示';
    const td = cell(head, p.name); td.colSpan = 4;
    head.onclick = () => isolate(p.name === isolated ? null : p.name);
    body.appendChild(head);
    for (const g of geoms) {
      const tr = document.createElement('tr');
      cell(tr, g.name, 'gname'); cell(tr, g.role); cell(tr, g.shape); cell(tr, g.text, 'num');
      body.appendChild(tr);
    }
  }
  $('pcount').textContent = parts.length ? `(${n} / ${parts.length} 部品)` : '';
  $('showall').disabled = isolated === null;
}

async function isolate(name) {
  try {
    const r = await fetch('/api/isolate?part=' + encodeURIComponent(name || ''));
    const j = await r.json();
    if (j.ok) isolated = j.isolated;
    else setBar('部品の表示を切り替えられません: ' + j.error, true);
  } catch (e) { setBar('サーバーに接続できません: ' + e, true); }
  renderParts();
}

// ---- 初期化

$('q').oninput = render;
$('pq').oninput = renderParts;
$('pcol').onchange = renderParts;
$('showall').onclick = () => isolate(null);
$('frames').onchange = () => { if (current) show(current); };
(async () => {
  const j = await (await fetch('/api/models')).json();
  models = j.models; current = j.current; meshcatPort = j.meshcatPort;
  parts = j.parts; isolated = j.isolated;
  render(); renderParts();
  if (current) { setBar(`表示中: ${current}`); $('view').src = meshcatUrl(); }
  else if (j.default) show(j.default);
  else setBar('左の一覧からモデルを選んでください');
})();
