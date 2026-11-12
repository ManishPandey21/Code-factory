'use strict';
let cursor = 0;
let tickets = [];
let history = [];
const el = id => document.getElementById(id);
function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value == null ? '—' : String(value);
  if (className) node.className = className;
  return node;
}
function render() {
  const query = el('filter').value.toLowerCase();
  const rows = tickets.filter(t => `${t.id} ${t.title} ${t.state}`.toLowerCase().includes(query));
  el('count').textContent = `${rows.length} / ${tickets.length}`;
  el('tickets').replaceChildren(...rows.map(t => {
    const row = document.createElement('tr');
    const identity = document.createElement('td');
    identity.append(text('strong', t.id), text('small', t.title));
    row.append(identity, text('td', t.state, 'state'), text('td', t.head ? t.head.slice(0, 12) : 'Pending', 'mono'),
      text('td', `${t.risk || 'Not configured'}${t.human_required ? (t.human_reviewer ? ` · Approved by ${t.human_reviewer}` : ' · Human required') : ''}`),
      text('td', `${t.attempts} / ${t.maximum_attempts ?? '?'}`), text('td', t.hold_reason ? `HELD: ${t.hold_reason}` : t.error || '—'));
    return row;
  }));
  if (!rows.length) {
    const row = document.createElement('tr');
    const cell = text('td', tickets.length ? 'No matching tickets.' : 'No tickets yet. Add a ticket with the factory CLI.');
    cell.colSpan = 6; row.append(cell); el('tickets').append(row);
  }
  el('events').replaceChildren(...history.slice().reverse().map(e => {
    const item = document.createElement('li');
    item.append(text('time', new Date(e.at * 1000).toLocaleTimeString()),
      text('strong', `${e.ticket} · ${e.state}`), text('span', `#${e.sequence} ${e.action}${e.reason || e.error ? ' · ' + (e.reason || e.error) : ''}`));
    return item;
  }));
  el('cursor').textContent = `Cursor ${cursor}`;
}
async function poll() {
  let delay = 2000;
  try {
    const response = await fetch(`/api/snapshot?after=${cursor}&limit=100`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    tickets = data.tickets;
    history = history.concat(data.events).slice(-1000);
    cursor = data.cursor;
    el('connection').textContent = `Live · ${data.coordinator_locked ? 'Coordinator active' : 'Coordinator idle'} · Updated ${new Date().toLocaleTimeString()}`;
    el('connection').className = 'connected';
    render();
    if (data.has_more) delay = 100;
  } catch (error) {
    el('connection').textContent = `Disconnected · ${error.message} · Retrying; showing last received data`;
    el('connection').className = 'disconnected';
  }
  window.setTimeout(poll, delay);
}
el('filter').addEventListener('input', render);
poll();
