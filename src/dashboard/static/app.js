// ─── State ───
let ws = null;
let equityChart = null;
let currentTab = 'orders';
let chartPeriod = '24h';
let lastData = null;
let selectedPair = '__all__';
let knownPairs = new Set();

// ─── Formatting ───
const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtUsd = (n) => '$' + fmt(n);
const fmtPnl = (n) => (n >= 0 ? '+' : '') + '$' + fmt(n);

function pnlColor(n) {
    if (n > 0) return 'var(--green)';
    if (n < 0) return 'var(--red)';
    return 'var(--text-secondary)';
}

// ─── Pair Selector ───
function selectPair(pair) {
    selectedPair = pair;
    if (lastData) updateAll(lastData);
}

function updatePairSelector(pairs) {
    const sel = document.getElementById('pair-selector');
    const symbols = Object.keys(pairs || {});
    // Only update if new pairs appear
    let changed = false;
    for (const s of symbols) {
        if (!knownPairs.has(s)) { changed = true; knownPairs.add(s); }
    }
    if (!changed) return;

    sel.innerHTML = '<option value="__all__">All Pairs</option>';
    for (const s of symbols) {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s;
        if (s === selectedPair) opt.selected = true;
        sel.appendChild(opt);
    }
}

// ─── WebSocket ───
function connectWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/live`);

    ws.onopen = () => console.log('WS connected');

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        lastData = data;
        updateAll(data);
    };

    ws.onclose = () => {
        console.log('WS disconnected, reconnecting...');
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => ws.close();
}

// ─── Update Functions ───
function updateAll(d) {
    updatePairSelector(d.pairs);
    updateStatus(d.status);
    updateRiskAlert(d.risk_halted);

    if (selectedPair === '__all__') {
        updateAllPairsView(d);
    } else {
        updateSinglePairView(d, selectedPair);
    }
}

function updateAllPairsView(d) {
    // Show aggregate stats
    document.getElementById('current-price').textContent = '--';
    document.getElementById('total-equity').textContent = fmtUsd(d.total_equity || 0);

    if (d.pool) {
        document.getElementById('available-usd').textContent = fmtUsd(d.pool.available_usd || 0);
        const securedEl = document.getElementById('secured-profits');
        securedEl.textContent = fmtPnl(d.pool.secured_profits || 0);
        securedEl.style.color = pnlColor(d.pool.secured_profits || 0);
        document.getElementById('total-fees').textContent = fmtUsd(d.pool.total_fees || 0);
        document.getElementById('trade-count').textContent = d.pool.total_trade_count || 0;
    }

    // Aggregate P&L across all pairs
    let totalRpnl = 0, totalUpnl = 0;
    if (d.pairs) {
        for (const p of Object.values(d.pairs)) {
            totalRpnl += p.realized_pnl || 0;
            totalUpnl += p.unrealized_pnl || 0;
        }
    }
    const rpnlEl = document.getElementById('realized-pnl');
    rpnlEl.textContent = fmtPnl(totalRpnl);
    rpnlEl.style.color = pnlColor(totalRpnl);
    const upnlEl = document.getElementById('unrealized-pnl');
    upnlEl.textContent = fmtPnl(totalUpnl);
    upnlEl.style.color = pnlColor(totalUpnl);

    document.getElementById('open-orders').textContent = d.open_order_count || 0;

    // Show all grid levels
    updateGrid(d.grid_levels, 0);

    // Position panel: aggregate
    updatePosition(d.position);

    // Trailing / config
    document.getElementById('trailing-badge').style.display = 'none';
    document.getElementById('trailing-shifts').style.display = 'none';
}

function updateSinglePairView(d, sym) {
    const pair = d.pairs ? d.pairs[sym] : null;
    if (!pair) return;

    document.getElementById('current-price').textContent = pair.current_price > 0 ? fmtUsd(pair.current_price) : '$--';
    document.getElementById('total-equity').textContent = fmtUsd(d.total_equity || 0);

    if (d.pool) {
        document.getElementById('available-usd').textContent = fmtUsd(d.pool.available_usd || 0);
        const securedEl = document.getElementById('secured-profits');
        securedEl.textContent = fmtPnl(d.pool.secured_profits || 0);
        securedEl.style.color = pnlColor(d.pool.secured_profits || 0);
        document.getElementById('total-fees').textContent = fmtUsd(d.pool.total_fees || 0);
        document.getElementById('trade-count').textContent = pair.trade_count || 0;
    }

    const rpnlEl = document.getElementById('realized-pnl');
    rpnlEl.textContent = fmtPnl(pair.realized_pnl || 0);
    rpnlEl.style.color = pnlColor(pair.realized_pnl || 0);
    const upnlEl = document.getElementById('unrealized-pnl');
    upnlEl.textContent = fmtPnl(pair.unrealized_pnl || 0);
    upnlEl.style.color = pnlColor(pair.unrealized_pnl || 0);

    document.getElementById('open-orders').textContent = d.open_order_count || 0;

    // Grid levels for this pair
    updateGrid(pair.grid_levels || [], pair.current_price);

    // Position
    updatePosition({
        base_balance: pair.base_balance || 0,
        quote_balance: d.pool ? d.pool.available_usd : 0,
        avg_entry_price: pair.avg_entry_price || 0,
        realized_pnl: pair.realized_pnl || 0,
        unrealized_pnl: pair.unrealized_pnl || 0,
    });

    // Trailing
    updateTrailing(pair.trailing, pair.grid_config);
    updateConfigPlaceholders(pair.grid_config);
}

function updateStatus(status) {
    const pill = document.getElementById('status-pill');
    const text = document.getElementById('status-text');
    pill.className = 'status-pill status-' + status;
    text.textContent = status.toUpperCase();

    document.getElementById('btn-start').style.display =
        ['idle', 'stopped', 'error'].includes(status) ? '' : 'none';
    document.getElementById('btn-stop').style.display =
        ['running', 'starting'].includes(status) ? '' : 'none';
}

function updateGrid(levels, currentPrice) {
    const container = document.getElementById('grid-levels');
    const countEl = document.getElementById('grid-count');

    if (!levels || levels.length === 0) {
        container.innerHTML = '<div class="empty-state">Lab is cold. Start cooking to see the formula.</div>';
        countEl.textContent = '0 levels';
        return;
    }

    countEl.textContent = levels.length + ' levels';
    const sorted = [...levels].sort((a, b) => b.price - a.price);

    let html = '';
    let priceMarkerInserted = false;

    for (let i = 0; i < sorted.length; i++) {
        const l = sorted[i];
        const next = sorted[i + 1];

        if (!priceMarkerInserted && currentPrice > 0) {
            if (next && l.price >= currentPrice && next.price < currentPrice) {
                html += `<div class="current-price-label">&#9654; Current: ${fmtUsd(currentPrice)}</div>`;
                priceMarkerInserted = true;
            }
        }

        html += `
            <div class="grid-level ${l.side}">
                <span class="index">${l.index}</span>
                <span class="side-tag">${l.side}</span>
                <span class="price">${fmtUsd(l.price)}</span>
                <span class="status-tag ${l.status}">${l.status.replace('_', ' ')}</span>
            </div>`;
    }

    if (!priceMarkerInserted && currentPrice > 0) {
        html += `<div class="current-price-label">&#9654; Current: ${fmtUsd(currentPrice)}</div>`;
    }

    container.innerHTML = html;
}

function updatePosition(pos) {
    if (!pos) return;

    document.getElementById('base-balance').textContent = (pos.base_balance || 0).toFixed(8);
    document.getElementById('quote-balance').textContent = fmtUsd(pos.quote_balance || 0);

    const avgEntry = document.getElementById('avg-entry');
    avgEntry.textContent = pos.avg_entry_price > 0 ? fmtUsd(pos.avg_entry_price) : '--';

    const netPnl = (pos.realized_pnl || 0) + (pos.unrealized_pnl || 0);
    const netEl = document.getElementById('net-pnl');
    netEl.textContent = fmtPnl(netPnl);
    netEl.style.color = pnlColor(netPnl);
}

function updateRiskAlert(halted) {
    const el = document.getElementById('risk-alert');
    el.classList.toggle('visible', !!halted);
}

function updateTrailing(trailing, config) {
    const badge = document.getElementById('trailing-badge');
    const shifts = document.getElementById('trailing-shifts');
    if (trailing && trailing.enabled) {
        badge.style.display = '';
        if (trailing.shift_count > 0) {
            shifts.style.display = '';
            shifts.textContent = trailing.shift_count + ' shift' + (trailing.shift_count !== 1 ? 's' : '');
        }
        if (config) {
            const rangeEl = document.getElementById('grid-count');
            rangeEl.textContent = fmtUsd(config.lower_price) + ' - ' + fmtUsd(config.upper_price);
        }
    } else {
        badge.style.display = 'none';
        shifts.style.display = 'none';
    }
}

function updateConfigPlaceholders(config) {
    if (!config) return;
    document.getElementById('cfg-lower').placeholder = config.lower_price;
    document.getElementById('cfg-upper').placeholder = config.upper_price;
    document.getElementById('cfg-levels').placeholder = config.num_levels;
    document.getElementById('cfg-size').placeholder = config.order_size_usd || 100;
}

// ─── Orders ───
async function fetchOrders() {
    let url = '/api/orders?limit=50';
    if (currentTab === 'orders') url = '/api/orders?status=open&limit=50';
    else if (currentTab === 'filled') url = '/api/orders?status=filled&limit=50';

    try {
        const res = await fetch(url);
        const data = await res.json();
        renderOrders(data.orders);
    } catch (e) {
        console.error('Failed to fetch orders:', e);
    }
}

function renderOrders(orders) {
    const tbody = document.getElementById('orders-body');
    if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No product on the street</td></tr>';
        return;
    }
    tbody.innerHTML = orders.map(o => `
        <tr>
            <td style="color:var(--text-muted)">${o.symbol || ''}</td>
            <td class="${o.side}">${o.side.toUpperCase()}</td>
            <td>${fmtUsd(o.price)}</td>
            <td>${Number(o.amount).toFixed(8)}</td>
            <td>${o.status}</td>
            <td style="color:var(--text-muted)">${formatTime(o.created_at)}</td>
        </tr>
    `).join('');
}

function formatTime(ts) {
    if (!ts) return '';
    try {
        const d = new Date(ts);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
        return ts;
    }
}

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab-bar .tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + tab).classList.add('active');
    fetchOrders();
}

// ─── Equity Chart ───
async function fetchEquityCurve() {
    try {
        const res = await fetch(`/api/pnl?period=${chartPeriod}`);
        const data = await res.json();
        renderChart(data.snapshots);
    } catch (e) {
        console.error('Failed to fetch equity curve:', e);
    }
}

function renderChart(snapshots) {
    if (!snapshots || snapshots.length === 0) return;

    const labels = snapshots.map(s => {
        try {
            return new Date(s.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch { return ''; }
    });
    const values = snapshots.map(s => s.total_equity_usd);

    const ctx = document.getElementById('equity-chart').getContext('2d');
    if (equityChart) equityChart.destroy();

    const gradient = ctx.createLinearGradient(0, 0, 0, 280);
    gradient.addColorStop(0, 'rgba(0, 200, 83, 0.2)');
    gradient.addColorStop(1, 'rgba(0, 200, 83, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: values,
                borderColor: '#00c853',
                backgroundColor: gradient,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: '#00e676',
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(26, 38, 19, 0.8)', drawBorder: false },
                    ticks: { color: '#5a7843', font: { size: 10, family: 'JetBrains Mono' }, maxTicksLimit: 8 },
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(26, 38, 19, 0.8)', drawBorder: false },
                    ticks: {
                        color: '#5a7843',
                        font: { size: 10, family: 'JetBrains Mono' },
                        callback: (v) => '$' + v.toLocaleString(),
                    },
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#121a0e',
                    borderColor: '#2a3d1e',
                    borderWidth: 1,
                    titleColor: '#5a7843',
                    bodyColor: '#00e676',
                    titleFont: { size: 11, family: 'JetBrains Mono' },
                    bodyFont: { size: 13, weight: 'bold', family: 'JetBrains Mono' },
                    padding: 10,
                    callbacks: {
                        label: (ctx) => '$' + fmt(ctx.parsed.y),
                    }
                }
            }
        }
    });
}

function setChartPeriod(period) {
    chartPeriod = period;
    document.querySelectorAll('.chart-panel .tab').forEach(t => {
        t.classList.toggle('active', t.textContent === period.toUpperCase());
    });
    fetchEquityCurve();
}

// ─── Bot Actions ───
async function botAction(action) {
    try {
        const res = await fetch(`/api/bot/${action}`, { method: 'POST' });
        const data = await res.json();
        showToast(data.status ? `${data.status === 'running' ? 'Yeah, science!' : data.status.toUpperCase()}` : 'Done.', 'success');
        fetchOrders();
    } catch (e) {
        showToast('Action failed: ' + e.message, 'error');
    }
}

async function reconfigure() {
    const body = {};
    // Use selected pair or first available
    if (selectedPair !== '__all__') {
        body.symbol = selectedPair;
    } else if (knownPairs.size > 0) {
        body.symbol = [...knownPairs][0];
    } else {
        showToast('Select a pair to reconfigure', 'error');
        return;
    }

    const lp = document.getElementById('cfg-lower').value;
    const up = document.getElementById('cfg-upper').value;
    const nl = document.getElementById('cfg-levels').value;
    const sz = document.getElementById('cfg-size').value;
    if (lp) body.lower_price = parseFloat(lp);
    if (up) body.upper_price = parseFloat(up);
    if (nl) body.num_levels = parseInt(nl);
    if (sz) body.order_size_usd = parseFloat(sz);

    if (Object.keys(body).length <= 1) {
        showToast('Enter at least one value to change', 'error');
        return;
    }

    try {
        const res = await fetch('/api/bot/reconfigure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            showToast(`New batch cooking: ${body.symbol}`, 'success');
            ['cfg-lower', 'cfg-upper', 'cfg-levels', 'cfg-size'].forEach(
                id => document.getElementById(id).value = ''
            );
        } else {
            const err = await res.json();
            showToast(err.detail || 'Reconfigure failed', 'error');
        }
    } catch (e) {
        showToast('Reconfigure failed: ' + e.message, 'error');
    }
}

// ─── Toast ───
let toastTimeout = null;
function showToast(msg, type = 'success') {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast visible ' + type;
    if (toastTimeout) clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => el.classList.remove('visible'), 3000);
}

// ─── Futures ───
function fmtPrice(n) {
    if (n >= 1000) return '$' + fmt(n, 0);
    if (n >= 1) return '$' + fmt(n, 3);
    if (n >= 0.01) return '$' + fmt(n, 4);
    return '$' + Number(n).toPrecision(4);
}

async function fetchFutures() {
    try {
        const res = await fetch('/api/futures/status');
        const data = await res.json();
        renderFutures(data);
    } catch (e) {
        // futures endpoint unreachable — hide section
        document.getElementById('futures-section').style.display = 'none';
    }
}

function renderFutures(data) {
    const section = document.getElementById('futures-section');
    if (!data || !data.enabled) {
        section.style.display = 'none';
        return;
    }
    section.style.display = '';

    // Header stats
    const marginPct = ((data.margin_utilization || 0) * 100).toFixed(1) + '%';
    document.getElementById('fut-margin').textContent = marginPct;

    const pill = document.getElementById('fut-status-pill');
    const pillText = document.getElementById('fut-status-text');
    pill.className = 'status-pill status-' + (data.status || 'idle');
    pillText.textContent = (data.status || 'idle').toUpperCase();

    // Pair cards
    const pairs = data.pairs || {};
    const container = document.getElementById('futures-cards');
    container.innerHTML = Object.entries(pairs).map(([sym, p]) => {
        const hasPos = p.open_position_size > 0;
        const posLabel = hasPos
            ? `<div class="fut-position-bar">POS ${p.open_position_size.toFixed(4)} ${sym.split('/')[0]}</div>`
            : '';
        const lockLabel = !p.can_switch
            ? '<span class="fut-locked">⏱ DIR LOCKED</span>'
            : '';
        return `
        <div class="fut-card">
            <div class="fut-card-top">
                <span class="fut-symbol">${sym}</span>
                <span class="fut-dir ${p.direction}">${p.direction.toUpperCase()}</span>
            </div>
            <div class="fut-price">${fmtPrice(p.current_price)}</div>
            <div class="fut-card-stats">
                <div class="fut-mini-stat">
                    <div class="label">Levels</div>
                    <div class="value">${p.levels_placed} active</div>
                </div>
                ${lockLabel ? `<div class="fut-mini-stat">${lockLabel}</div>` : ''}
            </div>
            ${posLabel}
        </div>`;
    }).join('');
}

// ─── Init ───
connectWebSocket();
fetchOrders();
fetchEquityCurve();
fetchFutures();
setInterval(fetchOrders, 10000);
setInterval(fetchEquityCurve, 30000);
setInterval(fetchFutures, 5000);
