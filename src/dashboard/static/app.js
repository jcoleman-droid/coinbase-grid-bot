// ─── State ───
let ws = null;
let equityChart = null;
let currentTab = 'orders';
let chartPeriod = '24h';
let lastData = null;

// ─── Formatting ───
const fmt = (n, d = 2) => Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtUsd = (n) => '$' + fmt(n);
const fmtPnl = (n) => (n >= 0 ? '+' : '') + '$' + fmt(n);

function pnlColor(n) {
    if (n > 0) return 'var(--green)';
    if (n < 0) return 'var(--red)';
    return 'var(--text-secondary)';
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
    updateStatus(d.status);
    updatePrice(d.current_price);
    updateStatBar(d);
    updateGrid(d.grid_levels, d.current_price);
    updatePosition(d.position);
    updateRiskAlert(d.risk_halted);
    updateTrailing(d.trailing, d.grid_config);
    updateSymbol(d.grid_config);
    updateConfigPlaceholders(d.grid_config);
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

function updatePrice(price) {
    document.getElementById('current-price').textContent = price > 0 ? fmtUsd(price) : '$--';
}

function updateStatBar(d) {
    document.getElementById('total-equity').textContent = fmtUsd(d.total_equity || 0);

    if (d.position) {
        const rpnl = d.position.realized_pnl || 0;
        const upnl = d.position.unrealized_pnl || 0;
        const fees = d.position.total_fees || 0;

        const rpnlEl = document.getElementById('realized-pnl');
        rpnlEl.textContent = fmtPnl(rpnl);
        rpnlEl.style.color = pnlColor(rpnl);

        const upnlEl = document.getElementById('unrealized-pnl');
        upnlEl.textContent = fmtPnl(upnl);
        upnlEl.style.color = pnlColor(upnl);

        document.getElementById('total-fees').textContent = fmtUsd(fees);

        const secured = d.position.secured_profits || 0;
        const securedEl = document.getElementById('secured-profits');
        securedEl.textContent = fmtPnl(secured);
        securedEl.style.color = pnlColor(secured);

        document.getElementById('trade-count').textContent = d.position.trade_count || 0;
    }

    document.getElementById('open-orders').textContent = d.open_order_count || 0;
}

function updateGrid(levels, currentPrice) {
    const container = document.getElementById('grid-levels');
    const countEl = document.getElementById('grid-count');

    if (!levels || levels.length === 0) {
        container.innerHTML = '<div class="empty-state">No grid active. Start the bot to see grid levels.</div>';
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

        // Insert current price marker between levels
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

    // If price is below all levels
    if (!priceMarkerInserted && currentPrice > 0) {
        html += `<div class="current-price-label">&#9654; Current: ${fmtUsd(currentPrice)}</div>`;
    }

    container.innerHTML = html;
}

function updatePosition(pos) {
    if (!pos) return;

    document.getElementById('base-balance').textContent = pos.base_balance.toFixed(8);
    document.getElementById('quote-balance').textContent = fmtUsd(pos.quote_balance);

    const avgEntry = document.getElementById('avg-entry');
    avgEntry.textContent = pos.avg_entry_price > 0 ? fmtUsd(pos.avg_entry_price) : '--';

    const netPnl = pos.realized_pnl + pos.unrealized_pnl;
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
        // Update range display in grid panel header
        if (config) {
            const rangeEl = document.getElementById('grid-count');
            rangeEl.textContent = fmtUsd(config.lower_price) + ' - ' + fmtUsd(config.upper_price);
        }
    } else {
        badge.style.display = 'none';
        shifts.style.display = 'none';
    }
}

function updateSymbol(config) {
    if (config && config.symbol) {
        document.getElementById('symbol').textContent = config.symbol;
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
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No orders</td></tr>';
        return;
    }
    tbody.innerHTML = orders.map(o => `
        <tr>
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
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0.25)');
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                data: values,
                borderColor: '#3b82f6',
                backgroundColor: gradient,
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: '#3b82f6',
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
                    grid: { color: 'rgba(30, 41, 59, 0.5)', drawBorder: false },
                    ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 8 },
                },
                y: {
                    display: true,
                    grid: { color: 'rgba(30, 41, 59, 0.5)', drawBorder: false },
                    ticks: {
                        color: '#64748b',
                        font: { size: 10 },
                        callback: (v) => '$' + v.toLocaleString(),
                    },
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1a2233',
                    borderColor: '#2a3a52',
                    borderWidth: 1,
                    titleColor: '#94a3b8',
                    bodyColor: '#e2e8f0',
                    titleFont: { size: 11 },
                    bodyFont: { size: 13, weight: 'bold' },
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
        showToast(data.status ? `Bot: ${data.status}` : 'Action completed', 'success');
        fetchOrders();
    } catch (e) {
        showToast('Action failed: ' + e.message, 'error');
    }
}

async function reconfigure() {
    const body = {};
    const lp = document.getElementById('cfg-lower').value;
    const up = document.getElementById('cfg-upper').value;
    const nl = document.getElementById('cfg-levels').value;
    const sz = document.getElementById('cfg-size').value;
    if (lp) body.lower_price = parseFloat(lp);
    if (up) body.upper_price = parseFloat(up);
    if (nl) body.num_levels = parseInt(nl);
    if (sz) body.order_size_usd = parseFloat(sz);

    if (Object.keys(body).length === 0) {
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
            showToast('Grid reconfigured', 'success');
            // Clear inputs
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

// ─── Init ───
connectWebSocket();
fetchOrders();
fetchEquityCurve();
setInterval(fetchOrders, 10000);
setInterval(fetchEquityCurve, 30000);
