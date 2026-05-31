/* Trading Mind Care - Frontend Logic */

// Tab switching
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        // Load data for active tab
        const tab = btn.dataset.tab;
        if (tab === 'plans') loadPlans();
        else if (tab === 'review') loadReviews();
        else if (tab === 'matrix') loadMatrix();
        else if (tab === 'settings') loadSettings();
    });
});

// --- API helpers ---
async function api(url, opts = {}) {
    const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    });
    return res.json();
}

// --- Plans ---
async function loadPlans() {
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

    const [todayPlans, tomorrowPlans, warnings] = await Promise.all([
        api(`/api/plans?trade_date=${today}&plan_type=today`),
        api(`/api/plans?trade_date=${tomorrow}&plan_type=tomorrow`),
        api('/api/plans/warnings'),
    ]);

    renderPlans('today-plans', todayPlans);
    renderPlans('tomorrow-plans', tomorrowPlans);
    renderWarnings(warnings);
}

function renderPlans(containerId, plans) {
    const el = document.getElementById(containerId);
    if (!plans.length) {
        el.innerHTML = '<p style="color:var(--text-dim);font-size:0.85rem">暂无计划</p>';
        return;
    }
    el.innerHTML = plans.map(p => `
        <div class="plan-item">
            <span class="content">${esc(p.content)}</span>
            <span class="actions">
                <button onclick="deletePlan(${p.id})">✕</button>
            </span>
        </div>
    `).join('');
}

function renderWarnings(warnings) {
    const el = document.getElementById('warnings-bar');
    if (!warnings.length) { el.innerHTML = ''; return; }
    el.innerHTML = warnings.map(w =>
        `<div class="warning-item">⚠️ 高频弱点：<strong>${esc(w.tag)}</strong>（权重 ${w.weight.toFixed(1)}）— 今日请特别注意！</div>`
    ).join('');
}

async function addPlan(type) {
    const input = document.getElementById(type + '-input');
    const content = input.value.trim();
    if (!content) return;
    await api('/api/plans', { method: 'POST', body: JSON.stringify({ plan_type: type, content }) });
    input.value = '';
    loadPlans();
}

async function deletePlan(id) {
    await api(`/api/plans/${id}`, { method: 'DELETE' });
    loadPlans();
}

// --- Reviews ---
async function submitReview() {
    const btn = document.getElementById('submit-review');
    const emotion = document.getElementById('emotion-input').value.trim();
    if (!emotion) { alert('请填写交易倾诉'); return; }

    const pnlVal = document.getElementById('pnl-input').value;
    const pnl = pnlVal ? parseFloat(pnlVal) : null;

    btn.disabled = true;
    btn.textContent = '正在分析...';

    try {
        const result = await api('/api/reviews', {
            method: 'POST',
            body: JSON.stringify({ pnl, emotion_log: emotion }),
        });

        const box = document.getElementById('critique-result');
        if (result.ai_critique) {
            box.textContent = result.ai_critique;
            box.style.display = 'block';
        } else {
            box.textContent = 'AI 暂不可用，复盘已保存。请在设置中配置 LLM。';
            box.style.display = 'block';
            box.style.borderColor = 'var(--warning)';
        }

        document.getElementById('emotion-input').value = '';
        document.getElementById('pnl-input').value = '';
        loadReviews();
    } finally {
        btn.disabled = false;
        btn.textContent = '提交复盘 — 接受拷打';
    }
}

async function loadReviews() {
    const reviews = await api('/api/reviews?limit=10');
    const el = document.getElementById('review-history');
    if (!reviews.length) {
        el.innerHTML = '<p style="color:var(--text-dim)">暂无复盘记录</p>';
        return;
    }
    el.innerHTML = reviews.map(r => {
        const pnlClass = r.pnl > 0 ? 'pnl-pos' : r.pnl < 0 ? 'pnl-neg' : '';
        const pnlText = r.pnl !== null ? `<span class="${pnlClass}">${r.pnl > 0 ? '+' : ''}${r.pnl}</span>` : '';
        return `<div class="review-history-item">
            <div class="date">${r.trade_date} ${pnlText}</div>
            <div>${esc(r.emotion_log).slice(0, 100)}${r.emotion_log.length > 100 ? '...' : ''}</div>
        </div>`;
    }).join('');
}

// --- Matrix ---
async function loadMatrix() {
    const vulns = await api('/api/vulnerabilities');
    const tbody = document.querySelector('#matrix-table tbody');
    if (!vulns.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-dim)">暂无数据，完成复盘后系统会自动提取弱点</td></tr>';
        return;
    }
    tbody.innerHTML = vulns.map(v => `<tr>
        <td><strong>${esc(v.tag)}</strong></td>
        <td>${v.weight.toFixed(2)}</td>
        <td>${v.hit_count}</td>
        <td>${v.last_hit_at || '-'}</td>
        <td><button onclick="deleteVuln(${v.id})" class="secondary" style="padding:0.2rem 0.5rem;margin:0">删除</button></td>
    </tr>`).join('');
}

async function deleteVuln(id) {
    await api(`/api/vulnerabilities/${id}`, { method: 'DELETE' });
    loadMatrix();
}

// --- Settings ---
async function loadSettings() {
    const cfg = await api('/api/settings');
    document.getElementById('cfg-base-url').value = cfg.base_url || '';
    document.getElementById('cfg-api-key').value = cfg.api_key || '';
    document.getElementById('cfg-model-name').value = cfg.model_name || '';
    document.getElementById('cfg-feishu-webhook').value = cfg.feishu_webhook || '';
    document.getElementById('cfg-notify-time').value = cfg.notify_time || '08:30';
}

async function saveLLM() {
    await api('/api/settings/llm', {
        method: 'POST',
        body: JSON.stringify({
            base_url: document.getElementById('cfg-base-url').value,
            api_key: document.getElementById('cfg-api-key').value,
            model_name: document.getElementById('cfg-model-name').value,
        }),
    });
    showResult('llm-test-result', '✅ 已保存', true);
}

async function testLLM() {
    const el = document.getElementById('llm-test-result');
    el.textContent = '测试中...';
    const result = await api('/api/settings/test-llm', {
        method: 'POST',
        body: JSON.stringify({
            base_url: document.getElementById('cfg-base-url').value,
            api_key: document.getElementById('cfg-api-key').value,
            model_name: document.getElementById('cfg-model-name').value,
        }),
    });
    if (result.success) {
        showResult('llm-test-result', `✅ 连接成功 | 模型: ${result.model} | 延迟: ${result.ttft_ms}ms`, true);
    } else {
        showResult('llm-test-result', `❌ 失败: ${result.error}`, false);
    }
}

async function saveFeishu() {
    await api('/api/settings/feishu', {
        method: 'POST',
        body: JSON.stringify({
            feishu_webhook: document.getElementById('cfg-feishu-webhook').value,
            notify_time: document.getElementById('cfg-notify-time').value,
        }),
    });
    showResult('feishu-test-result', '✅ 已保存', true);
}

async function testFeishu() {
    const el = document.getElementById('feishu-test-result');
    el.textContent = '发送中...';
    const result = await api('/api/notifications/test-feishu', { method: 'POST' });
    if (result.success) {
        showResult('feishu-test-result', '✅ 发送成功，请检查飞书', true);
    } else {
        showResult('feishu-test-result', `❌ ${result.error}`, false);
    }
}

function showResult(id, msg, success) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.style.background = success ? 'rgba(76,175,80,0.15)' : 'rgba(233,69,96,0.15)';
}

// --- Utils ---
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// Initial load
loadPlans();
