const input = document.getElementById('q');
const nameInput = document.getElementById('name');
const resultsEl = document.getElementById('results');
const statusEl = document.getElementById('status');

// Remember the name for this visitor so they don't retype it on every request.
nameInput.value = sessionStorage.getItem('requesterName') || '';
nameInput.addEventListener('input', () => {
  sessionStorage.setItem('requesterName', nameInput.value);
});

let debounceTimer = null;

input.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  const query = input.value.trim();
  if (!query) {
    resultsEl.innerHTML = '';
    return;
  }
  debounceTimer = setTimeout(() => runSearch(query), 350);
});

async function runSearch(query) {
  const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
  const tracks = await res.json();
  renderResults(tracks);
}

function renderResults(tracks) {
  resultsEl.innerHTML = '';
  for (const t of tracks) {
    const li = document.createElement('li');
    li.className = 'track';
    li.innerHTML = `
      ${t.album_art ? `<img class="track__art" src="${t.album_art}" alt="" />` : '<div class="track__art"></div>'}
      <div class="track__meta">
        <div class="track__name">${escapeHtml(t.name)}</div>
        <div class="track__artist">${escapeHtml(t.artist)}</div>
      </div>
      <button class="track__button">İste</button>
    `;
    li.querySelector('button').addEventListener('click', (e) => requestTrack(t, e.target));
    resultsEl.appendChild(li);
  }
}

async function requestTrack(track, button) {
  const requesterName = nameInput.value.trim();
  if (!requesterName) {
    setStatus('Önce adını yaz.', 'error');
    nameInput.focus();
    return;
  }

  button.disabled = true;
  button.textContent = '...';
  setStatus('', '');

  try {
    const res = await fetch('/api/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: track.id,
        name: track.name,
        artist: track.artist,
        requester_name: requesterName,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      button.textContent = 'Eklendi';
      setStatus(`"${track.name}" listeye eklendi.`, 'ok');
    } else {
      button.disabled = false;
      button.textContent = 'İste';
      setStatus(data.error || 'Bir şeyler ters gitti.', 'error');
    }
  } catch (err) {
    button.disabled = false;
    button.textContent = 'İste';
    setStatus('Bağlantı hatası, tekrar dene.', 'error');
  }
}

function setStatus(message, kind) {
  statusEl.textContent = message;
  statusEl.className = 'status' + (kind ? ' ' + kind : '');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
