// Meshcat のポートはサーバーの /api/models から受け取る。
let meshcatPort = 7000;
const meshcatUrl = () => `${location.protocol}//${location.hostname}:${meshcatPort}/`;
const $ = id => document.getElementById(id);
let models = [], current = null, busy = false;

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
      current = m; setBar(`表示中: ${m}`);
      $('view').src = meshcatUrl() + '?t=' + Date.now();
    } else {
      setBar(`表示できません: ${m} — ${j.error} (親の構成から読み込まれる部分ファイルは単体では開けません)`, true);
    }
  } catch (e) { setBar('サーバーに接続できません: ' + e, true); }
  busy = false; render();
}

$('q').oninput = render;
$('frames').onchange = () => { if (current) show(current); };
(async () => {
  const j = await (await fetch('/api/models')).json();
  models = j.models; current = j.current; meshcatPort = j.meshcatPort; render();
  if (current) { setBar(`表示中: ${current}`); $('view').src = meshcatUrl(); }
  else if (j.default) show(j.default);
  else setBar('左の一覧からモデルを選んでください');
})();
