/* Trading Mind Care - Frontend Logic */

// Theme
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'light' ? '' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    document.getElementById('theme-btn').textContent = next === 'light' ? '☀️' : '🌙';
}
(function() {
    const saved = localStorage.getItem('theme');
    if (saved) { document.documentElement.setAttribute('data-theme', saved); document.getElementById('theme-btn').textContent = saved === 'light' ? '☀️' : '🌙'; }
})();

// Tab switching
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        const tab = btn.dataset.tab;
        if (tab === 'plans') loadPlans();
        else if (tab === 'review') { document.getElementById('review-date-input').value = new Date().toISOString().slice(0,10); loadReviews(); }
        else if (tab === 'matrix') loadMatrix();
        else if (tab === 'stats') loadStats();
        else if (tab === 'daily') loadDailyReport();
        else if (tab === 'calendar') loadCalendar();
        else if (tab === 'settings') loadSettings();
    });
});

// --- API helpers ---
async function api(url, opts = {}) {
    try {
        const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || `请求失败 (${res.status})`);
        }
        return res.json();
    } catch (e) {
        if (e.message === 'Failed to fetch') throw new Error('网络连接失败，请检查服务是否运行');
        throw e;
    }
}

function toast(msg, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// --- Plans ---
async function generateDailyInsight() {
    const btn = document.getElementById('insight-btn');
    const box = document.getElementById('daily-insight-box');
    btn.disabled = true;
    btn.textContent = '生成中...';
    box.style.display = 'block';
    box.textContent = '';
    try {
        const res = await fetch('/api/insights/daily', { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
                try {
                    const payload = JSON.parse(line.slice(6));
                    if (payload.chunk) box.textContent += payload.chunk;
                    if (payload.error) box.textContent = 'AI 暂不可用: ' + payload.error;
                } catch(e) {}
            }
        }
    } catch (e) { box.textContent = '获取失败: ' + e.message; }
    btn.disabled = false;
    btn.textContent = '🤖 获取今日 AI 建议';
}

async function loadPlans() {
    const today = new Date().toISOString().slice(0, 10);
    const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
    try {
        const [todayPlans, tomorrowPlans, warnings, todayReviews] = await Promise.all([
            api(`/api/plans?trade_date=${today}&plan_type=today`),
            api(`/api/plans?trade_date=${tomorrow}&plan_type=tomorrow`),
            api('/api/plans/warnings'),
            api(`/api/reviews?trade_date=${today}`),
        ]);
        renderPlans('today-plans', todayPlans);
        renderPlans('tomorrow-plans', tomorrowPlans);
        renderWarnings(warnings);
        loadTemplates();
        loadRules();
        // Today status
        const statusEl = document.getElementById('today-status');
        if (todayReviews.length) {
            const pnl = todayReviews.reduce((s, r) => s + (r.pnl || 0), 0);
            const cls = pnl >= 0 ? 'positive' : 'negative';
            statusEl.innerHTML = `📊 今日已复盘 ${todayReviews.length} 次 | 盈亏: <span class="${cls}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}</span>`;
        } else {
            statusEl.textContent = '📊 今日尚未复盘';
        }
    } catch (e) { toast(e.message, 'error'); }
}

function renderPlans(containerId, plans) {
    const el = document.getElementById(containerId);
    if (!plans.length) {
        el.innerHTML = '<div class="empty-state"><div class="icon">📝</div><div class="msg">暂无计划</div><div class="hint">在下方输入框添加你的交易计划</div></div>';
        return;
    }
    el.innerHTML = plans.map(p => `
        <div class="plan-item ${p.done ? 'done' : ''}" id="plan-${p.id}">
            <input type="checkbox" ${p.done ? 'checked' : ''} onchange="togglePlanDone(${p.id})" style="cursor:pointer">
            <span class="content" style="${p.done ? 'text-decoration:line-through;opacity:0.6' : ''}">${esc(p.content)}</span>
            <span class="actions">
                <button onclick="editPlan(${p.id})" title="编辑">✎</button>
                <button onclick="deletePlan(${p.id})" title="删除">✕</button>
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

    // Check keyword warnings before adding
    try {
        const warnings = await api(`/api/plans/warnings?content=${encodeURIComponent(content)}`);
        const matched = warnings.filter(w => w.matched);
        if (matched.length) {
            const msg = matched.map(w => `⚠️ "${w.tag}" (权重${w.weight.toFixed(1)})`).join('\n');
            if (!confirm(`你的计划可能触发以下弱点：\n${msg}\n\n确定继续添加？`)) return;
        }
    } catch (e) {}

    try {
        await api('/api/plans', { method: 'POST', body: JSON.stringify({ plan_type: type, content }) });
        input.value = '';
        loadPlans();
    } catch (e) { toast(e.message, 'error'); }
}

async function togglePlanDone(id) {
    try { await api(`/api/plans/${id}/toggle`, { method: 'PATCH' }); loadPlans(); } catch (e) { toast(e.message, 'error'); }
}

async function copyYesterday() {
    try {
        const res = await api('/api/plans/copy-yesterday', { method: 'POST' });
        toast(`已复制 ${res.copied} 条昨日计划`);
        loadPlans();
    } catch (e) { toast(e.message, 'error'); }
}

async function saveAsTemplate(type) {
    const input = document.getElementById(type + '-input');
    const content = input.value.trim();
    if (!content) { toast('请先输入计划内容', 'error'); return; }
    try {
        await api('/api/plans/templates', { method: 'POST', body: JSON.stringify({ content }) });
        toast('已保存为模板');
        loadTemplates();
    } catch (e) { toast(e.message, 'error'); }
}

async function loadTemplates() {
    try {
        const tpls = await api('/api/plans/templates');
        const el = document.getElementById('templates-list');
        if (!tpls.length) { el.innerHTML = '<span style="color:var(--text-dim);font-size:0.85rem">暂无模板</span>'; return; }
        el.innerHTML = tpls.map(t => `<span class="template-chip" onclick="insertTemplate('${esc(t.content)}')">${esc(t.content)}<button onclick="event.stopPropagation();deleteTemplate(${t.id})" style="background:none;border:none;color:var(--text-dim);cursor:pointer;margin-left:0.3rem;padding:0">✕</button></span>`).join('');
    } catch (e) {}
}

function insertTemplate(content) {
    const input = document.getElementById('today-input');
    input.value = content;
    input.focus();
}

async function deleteTemplate(id) {
    try {
        await api(`/api/plans/templates/${id}`, { method: 'DELETE' });
        loadTemplates();
    } catch (e) { toast(e.message, 'error'); }
}

// --- Trade Rules ---
async function loadRules() {
    try {
        const rules = await api('/api/rules');
        const el = document.getElementById('rules-list');
        if (!rules.length) { el.innerHTML = '<span style="color:var(--text-dim);font-size:0.85rem">暂无规则，添加你的交易纪律</span>'; return; }
        el.innerHTML = rules.map(r => `<div class="plan-item" style="opacity:${r.active ? 1 : 0.5}">
            <input type="checkbox" ${r.active ? 'checked' : ''} onchange="toggleRule(${r.id})" style="cursor:pointer">
            <span class="content"><span style="color:var(--accent);font-size:0.75rem;margin-right:0.3rem">[${esc(r.category)}]</span>${esc(r.rule)}</span>
            <span class="actions"><button onclick="deleteRule(${r.id})" title="删除">✕</button></span>
        </div>`).join('');
    } catch (e) {}
}

async function addRule() {
    const input = document.getElementById('rule-input');
    const rule = input.value.trim();
    if (!rule) return;
    const category = document.getElementById('rule-category').value;
    try {
        await api('/api/rules', { method: 'POST', body: JSON.stringify({ rule, category }) });
        input.value = '';
        loadRules();
        toast('规则已添加');
    } catch (e) { toast(e.message, 'error'); }
}

async function toggleRule(id) {
    try { await api(`/api/rules/${id}/toggle`, { method: 'PATCH' }); loadRules(); } catch (e) { toast(e.message, 'error'); }
}

async function deleteRule(id) {
    if (!confirm('确定删除此规则？')) return;
    try { await api(`/api/rules/${id}`, { method: 'DELETE' }); loadRules(); } catch (e) { toast(e.message, 'error'); }
}

async function editPlan(id) {
    const el = document.querySelector(`#plan-${id} .content`);
    const old = el.textContent;
    const input = document.createElement('textarea');
    input.value = old;
    input.className = 'edit-inline';
    input.rows = 2;
    el.replaceWith(input);
    input.focus();

    async function save() {
        const newVal = input.value.trim();
        if (!newVal || newVal === old) {
            input.replaceWith(el);
            return;
        }
        try {
            await api(`/api/plans/${id}`, { method: 'PUT', body: JSON.stringify({ content: newVal }) });
            loadPlans();
            toast('已更新');
        } catch (e) { toast(e.message, 'error'); input.replaceWith(el); }
    }

    input.addEventListener('blur', save);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.replaceWith(el); }
    });
}

async function deletePlan(id) {
    if (!confirm('确定删除？')) return;
    try {
        await api(`/api/plans/${id}`, { method: 'DELETE' });
        loadPlans();
    } catch (e) { toast(e.message, 'error'); }
}

// --- Reviews ---
let reviewPage = 0;
const PAGE_SIZE = 10;
let selectedMood = null;

function selectMood(val) {
    selectedMood = val;
    document.querySelectorAll('.mood-btn').forEach(b => {
        b.classList.toggle('selected', parseInt(b.dataset.mood) === val);
    });
}

async function submitReview() {
    const btn = document.getElementById('submit-review');
    const emotion = document.getElementById('emotion-input').value.trim();
    if (!emotion) { toast('请填写交易倾诉', 'error'); return; }

    const pnlVal = document.getElementById('pnl-input').value;
    const pnl = pnlVal ? parseFloat(pnlVal) : null;
    const trade_date = document.getElementById('review-date-input').value || null;
    const mood = selectedMood;

    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner"></span>AI 正在分析你的交易...';

    const box = document.getElementById('critique-result');
    box.textContent = '';
    box.className = 'critique-box';
    box.style.display = 'block';

    try {
        const resp = await fetch('/api/reviews/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pnl, emotion_log: emotion, trade_date, mood }),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const data = line.slice(6);
                if (data === '[DONE]') break;
                try {
                    const msg = JSON.parse(data);
                    if (msg.chunk) box.textContent += msg.chunk;
                    else if (msg.error) {
                        box.textContent = 'AI 暂不可用：' + msg.error + '\n复盘已保存。';
                        box.className = 'critique-box warning-mode';
                    }
                } catch (e) {}
            }
        }

        document.getElementById('emotion-input').value = '';
        document.getElementById('pnl-input').value = '';
        selectedMood = null;
        document.querySelectorAll('.mood-btn').forEach(b => b.classList.remove('selected'));
        localStorage.removeItem('review_draft');
        loadReviews();
    } catch (e) {
        box.textContent = 'AI 暂不可用，复盘已保存。请在设置中配置 LLM。';
        box.className = 'critique-box warning-mode';
        // Fallback: submit without streaming
        try {
            await api('/api/reviews', { method: 'POST', body: JSON.stringify({ pnl, emotion_log: emotion, trade_date, mood }) });
            loadReviews();
        } catch (e2) { toast(e2.message, 'error'); }
    } finally {
        btn.disabled = false;
        btn.innerHTML = '提交复盘 — 接受拷打';
    }
}

async function loadReviews(query) {
    try {
        let url = `/api/reviews?limit=${PAGE_SIZE}&offset=${reviewPage * PAGE_SIZE}`;
        if (query) url += `&q=${encodeURIComponent(query)}`;
        const reviews = await api(url);
        const el = document.getElementById('review-history');
        if (!reviews.length && reviewPage === 0) {
            el.innerHTML = '<div class="empty-state"><div class="icon">🔥</div><div class="msg">暂无复盘记录</div><div class="hint">提交你的第一次复盘，接受 AI 拷打</div></div>';
            document.getElementById('review-pagination').innerHTML = '';
            return;
        }
        el.innerHTML = reviews.map(r => {
            const pnlClass = r.pnl > 0 ? 'pnl-pos' : r.pnl < 0 ? 'pnl-neg' : '';
            const pnlText = r.pnl !== null ? `<span class="${pnlClass}">${r.pnl > 0 ? '+' : ''}${r.pnl}</span>` : '';
            return `<div class="review-history-item" onclick="toggleReviewDetail(this, ${r.id})">
                <div class="meta"><span class="date">${r.trade_date}</span>${pnlText}</div>
                <div class="summary">${esc(r.emotion_log).slice(0, 80)}${r.emotion_log.length > 80 ? '...' : ''}</div>
                <div class="critique-expand" id="review-detail-${r.id}"></div>
            </div>`;
        }).join('');

        const pag = document.getElementById('review-pagination');
        let html = '';
        if (reviewPage > 0) html += `<button class="secondary" onclick="reviewPage--;loadReviews()" style="margin:0 0.3rem">← 上一页</button>`;
        if (reviews.length === PAGE_SIZE) html += `<button class="secondary" onclick="reviewPage++;loadReviews()" style="margin:0 0.3rem">下一页 →</button>`;
        pag.innerHTML = html;
    } catch (e) { toast(e.message, 'error'); }
}

function searchReviews() {
    const q = document.getElementById('review-search').value.trim();
    reviewPage = 0;
    loadReviews(q);
}

async function toggleReviewDetail(el, id) {
    if (el.classList.contains('expanded')) {
        el.classList.remove('expanded');
        return;
    }
    el.classList.add('expanded');
    const detail = document.getElementById(`review-detail-${id}`);
    if (detail.dataset.loaded) return;

    try {
        const r = await api(`/api/reviews/${id}`);
        let html = '';
        if (r.plans && r.plans.length) {
            html += `<div class="detail-section"><strong>📋 当日计划：</strong><ul>${r.plans.map(p => `<li>${esc(p.content)}</li>`).join('')}</ul></div>`;
        }
        html += `<div class="detail-section"><strong>💬 倾诉全文：</strong><p>${esc(r.emotion_log)}</p></div>`;
        if (r.ai_critique) {
            html += `<div class="detail-section"><strong>🔥 AI 拷打：</strong><p>${esc(r.ai_critique)}</p></div>`;
        }
        if (r.mood) {
            const moods = ['', '😫', '😟', '😐', '🙂', '😄'];
            html += `<div class="detail-section"><strong>情绪：</strong> ${moods[r.mood]} (${r.mood}/5)</div>`;
        }
        html += `<div style="margin-top:0.5rem"><button class="secondary" onclick="deleteReview(${id})" style="margin:0;padding:0.2rem 0.6rem;font-size:0.8rem;color:var(--danger)">🗑️ 删除此复盘</button></div>`;
        detail.innerHTML = html;
        detail.dataset.loaded = '1';
    } catch (e) { detail.innerHTML = '<em>加载失败</em>'; }
}

async function exportReviews() {
    try {
        const data = await api('/api/reviews?limit=9999');
        downloadJSON(data, 'reviews.json');
        toast('导出成功');
    } catch (e) { toast(e.message, 'error'); }
}

async function deleteReview(id) {
    if (!confirm('确定删除此复盘记录？此操作不可恢复。')) return;
    try {
        await api(`/api/reviews/${id}`, { method: 'DELETE' });
        toast('已删除');
        loadReviews();
    } catch (e) { toast(e.message, 'error'); }
}

// --- Matrix ---
async function loadMatrix() {
    try {
        const vulns = await api('/api/vulnerabilities');
        const tbody = document.querySelector('#matrix-table tbody');
        const chart = document.getElementById('matrix-chart');

        if (!vulns.length) {
            tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="icon">📊</div><div class="msg">暂无数据</div><div class="hint">完成复盘后系统会自动提取弱点，或手动添加</div></div></td></tr>';
            chart.innerHTML = '';
            return;
        }

        const maxW = Math.max(...vulns.map(v => v.weight));
        chart.innerHTML = '<div style="margin-bottom:1.5rem">' + vulns.slice(0, 8).map(v => {
            const pct = Math.max(5, (v.weight / maxW) * 100);
            return `<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem">
                <span style="min-width:6rem;font-size:0.8rem;text-align:right;color:var(--text-dim)">${esc(v.tag)}</span>
                <div style="flex:1;background:var(--surface);border-radius:3px;height:8px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:3px;transition:width 0.3s"></div>
                </div>
                <span style="font-size:0.8rem;font-family:var(--font-mono);min-width:2.5rem">${v.weight.toFixed(1)}</span>
            </div>`;
        }).join('') + '</div>';

        tbody.innerHTML = vulns.map(v => {
            const pct = Math.max(5, (v.weight / maxW) * 100);
            return `<tr>
                <td><strong>${esc(v.tag)}</strong><br><small style="color:var(--text-dim)">${esc(v.description || '')}</small></td>
                <td><div class="weight-bar-container"><div class="weight-bar" style="width:${pct}px"></div><span class="weight-value">${v.weight.toFixed(2)}</span></div></td>
                <td>${v.hit_count}</td>
                <td>${v.last_hit_at || '-'}</td>
                <td style="white-space:nowrap">
                    <button onclick="editVuln(${v.id}, '${esc(v.tag)}', ${v.weight}, '${esc(v.description || '')}')" class="secondary" style="padding:0.2rem 0.5rem;margin:0 0.2rem 0 0;font-size:0.8rem">编辑</button>
                    <button onclick="resetVuln(${v.id})" class="secondary" style="padding:0.2rem 0.5rem;margin:0 0.2rem 0 0;font-size:0.8rem">重置</button>
                    <button onclick="mergeVuln(${v.id}, '${esc(v.tag)}')" class="secondary" style="padding:0.2rem 0.5rem;margin:0 0.2rem 0 0;font-size:0.8rem">合并</button>
                    <button onclick="deleteVuln(${v.id})" class="secondary" style="padding:0.2rem 0.5rem;margin:0;font-size:0.8rem">删除</button>
                </td>
            </tr>`;
        }).join('');
    } catch (e) { toast(e.message, 'error'); }
}

async function addVuln() {
    const tag = document.getElementById('vuln-tag-input').value.trim();
    if (!tag) { toast('请输入弱点标签', 'error'); return; }
    const weight = parseFloat(document.getElementById('vuln-weight-input').value) || 1.0;
    const desc = document.getElementById('vuln-desc-input').value.trim();
    try {
        await api('/api/vulnerabilities', { method: 'POST', body: JSON.stringify({ tag, weight, description: desc }) });
        document.getElementById('vuln-tag-input').value = '';
        document.getElementById('vuln-weight-input').value = '1.0';
        document.getElementById('vuln-desc-input').value = '';
        loadMatrix();
        toast('已添加');
    } catch (e) { toast(e.message, 'error'); }
}

async function editVuln(id, tag, weight, desc) {
    const newTag = prompt('弱点标签：', tag);
    if (newTag === null) return;
    const newWeight = prompt('权重：', weight);
    if (newWeight === null) return;
    const newDesc = prompt('描述：', desc);
    if (newDesc === null) return;
    try {
        await api(`/api/vulnerabilities/${id}`, { method: 'PUT', body: JSON.stringify({ tag: newTag.trim(), weight: parseFloat(newWeight), description: newDesc.trim() }) });
        loadMatrix();
        toast('已更新');
    } catch (e) { toast(e.message, 'error'); }
}

async function deleteVuln(id) {
    if (!confirm('确定删除？')) return;
    try {
        await api(`/api/vulnerabilities/${id}`, { method: 'DELETE' });
        loadMatrix();
    } catch (e) { toast(e.message, 'error'); }
}

async function resetVuln(id) {
    if (!confirm('确定重置此弱点权重为 1.0？')) return;
    try {
        await api(`/api/vulnerabilities/${id}/reset`, { method: 'POST' });
        loadMatrix();
        toast('已重置');
    } catch (e) { toast(e.message, 'error'); }
}

async function mergeVuln(sourceId, sourceTag) {
    const targetTag = prompt(`将"${sourceTag}"合并到哪个弱点？输入目标弱点的标签名：`);
    if (!targetTag) return;
    // Find target by tag
    try {
        const vulns = await api('/api/vulnerabilities');
        const target = vulns.find(v => v.tag === targetTag.trim());
        if (!target) { toast('未找到目标弱点', 'error'); return; }
        if (target.id === sourceId) { toast('不能合并到自身', 'error'); return; }
        await api(`/api/vulnerabilities/merge?source_id=${sourceId}&target_id=${target.id}`, { method: 'POST' });
        loadMatrix();
        toast(`已合并到"${targetTag}"`);
    } catch (e) { toast(e.message, 'error'); }
}

async function exportMatrix() {
    try {
        const data = await api('/api/vulnerabilities');
        downloadJSON(data, 'vulnerability_matrix.json');
        toast('导出成功');
    } catch (e) { toast(e.message, 'error'); }
}

// --- Stats ---
async function loadStats() {
    try {
        const data = await api('/api/stats');
        const el = document.getElementById('stats-content');
        const pnlClass = data.total_pnl >= 0 ? 'positive' : 'negative';
        const weekClass = data.week_pnl >= 0 ? 'positive' : 'negative';
        const monthClass = data.month_pnl >= 0 ? 'positive' : 'negative';

        let html = `
            <div class="stats-grid">
                <div class="stat-card"><div class="value">${data.review_count}</div><div class="label">总复盘次数</div></div>
                <div class="stat-card"><div class="value ${pnlClass}">${data.total_pnl >= 0 ? '+' : ''}${data.total_pnl.toFixed(1)}</div><div class="label">累计盈亏</div></div>
                <div class="stat-card"><div class="value ${weekClass}">${data.week_pnl >= 0 ? '+' : ''}${data.week_pnl.toFixed(1)}</div><div class="label">本周盈亏</div></div>
                <div class="stat-card"><div class="value ${monthClass}">${data.month_pnl >= 0 ? '+' : ''}${data.month_pnl.toFixed(1)}</div><div class="label">本月盈亏</div></div>
                <div class="stat-card"><div class="value ${data.last_month_pnl >= 0 ? 'positive' : 'negative'}">${data.last_month_pnl >= 0 ? '+' : ''}${data.last_month_pnl.toFixed(1)}</div><div class="label">上月盈亏</div></div>
                <div class="stat-card"><div class="value">${data.week_reviews}</div><div class="label">本周复盘</div></div>
                <div class="stat-card"><div class="value">${data.streak_days}🔥</div><div class="label">连续复盘天数</div></div>
                <div class="stat-card"><div class="value">${data.win_rate}%</div><div class="label">胜率</div></div>
                <div class="stat-card"><div class="value">${data.max_loss_streak}</div><div class="label">最大连亏天数</div></div>
                <div class="stat-card"><div class="value">${data.profit_factor}</div><div class="label">盈亏比</div></div>
                <div class="stat-card"><div class="value positive">+${data.avg_win}</div><div class="label">平均盈利</div></div>
                <div class="stat-card"><div class="value negative">${data.avg_loss}</div><div class="label">平均亏损</div></div>
                <div class="stat-card"><div class="value">${data.plan_rate}%</div><div class="label">计划执行率</div></div>
                <div class="stat-card"><div class="value negative">-${data.max_drawdown}</div><div class="label">最大回撤</div></div>
                <div class="stat-card"><div class="value ${data.current_drawdown > 0 ? 'negative' : ''}">${data.current_drawdown > 0 ? '-' + data.current_drawdown : '0'}</div><div class="label">当前回撤</div></div>
            </div>`;

        // PnL trend bar chart
        if (data.pnl_trend && data.pnl_trend.length) {
            const maxAbs = Math.max(...data.pnl_trend.map(d => Math.abs(d.daily_pnl || 0)), 1);
            html += `<h3 style="margin:1.5rem 0 0.8rem">近 14 日盈亏趋势</h3>
            <div class="pnl-trend">
                ${data.pnl_trend.map(d => {
                    const v = d.daily_pnl || 0;
                    const h = Math.max(4, Math.abs(v) / maxAbs * 40);
                    const color = v >= 0 ? 'var(--success)' : 'var(--danger)';
                    const dir = v >= 0 ? 'bottom' : 'top';
                    return `<div class="trend-bar-wrap" title="${d.trade_date}: ${v > 0 ? '+' : ''}${v.toFixed(1)}">
                        <div class="trend-bar" style="height:${h}px;background:${color};align-self:${v >= 0 ? 'flex-end' : 'flex-start'}"></div>
                        <span class="trend-date">${d.trade_date.slice(5)}</span>
                    </div>`;
                }).join('')}
            </div>`;
        }

        // Top weaknesses by hit_count
        if (data.top_weaknesses.length) {
            html += `<h3 style="margin:1.5rem 0 0.8rem">高频弱点 Top 5（按触发次数）</h3>`;
            html += data.top_weaknesses.map(w => {
                const pct = Math.max(8, (w.hit_count / (data.top_weaknesses[0]?.hit_count || 1)) * 100);
                return `<div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem">
                    <span style="min-width:7rem;font-size:0.85rem">${esc(w.tag)}</span>
                    <div style="flex:1;background:var(--surface);border-radius:3px;height:10px;overflow:hidden">
                        <div style="width:${pct}%;height:100%;background:var(--accent);border-radius:3px"></div>
                    </div>
                    <span style="font-size:0.8rem;color:var(--text-dim)">${w.hit_count}次</span>
                </div>`;
            }).join('');
        }

        // Mood-PnL correlation
        if (data.mood_pnl_corr && data.mood_pnl_corr.length) {
            const moods = ['', '😫', '😟', '😐', '🙂', '😄'];
            html += `<h3 style="margin:1.5rem 0 0.8rem">情绪-盈亏关联</h3>`;
            html += `<div style="display:flex;gap:1rem;flex-wrap:wrap">`;
            html += data.mood_pnl_corr.map(m => {
                const avgPnl = m.avg_pnl || 0;
                const cls = avgPnl >= 0 ? 'positive' : 'negative';
                return `<div class="stat-card" style="min-width:80px"><div class="value">${moods[m.mood] || m.mood}</div><div class="label">平均盈亏</div><div class="${cls}" style="font-family:var(--font-mono);font-size:0.85rem;margin-top:0.2rem">${avgPnl >= 0 ? '+' : ''}${avgPnl.toFixed(1)}</div><div style="font-size:0.7rem;color:var(--text-dim)">${m.cnt}次</div></div>`;
            }).join('');
            html += `</div>`;
        }

        if (!data.top_weaknesses.length && !data.mood_pnl_corr?.length) {
            html += '<div class="empty-state"><div class="icon">📈</div><div class="msg">暂无统计数据</div></div>';
        }

        el.innerHTML = html;
    } catch (e) { toast(e.message, 'error'); }
}

// --- Daily Report ---
async function loadDailyReport() {
    const dateInput = document.getElementById('daily-date-input');
    if (!dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
    const d = dateInput.value;
    try {
        const data = await api(`/api/daily-report?trade_date=${d}`);
        const el = document.getElementById('daily-content');
        const pnlClass = data.total_pnl >= 0 ? 'pnl-pos' : 'pnl-neg';
        let html = `<div style="margin-bottom:1rem;font-size:0.9rem;color:var(--text-dim)">日期：<strong style="color:var(--text)">${d}</strong> | 总盈亏：<span class="${pnlClass}" style="font-weight:600">${data.total_pnl >= 0 ? '+' : ''}${data.total_pnl.toFixed(1)}</span></div>`;

        html += '<h3 style="margin:1rem 0 0.5rem">📋 计划</h3>';
        if (data.plans.length) {
            html += '<ul>' + data.plans.map(p => `<li>${esc(p.content)} <small style="color:var(--text-dim)">(${p.plan_type})</small></li>`).join('') + '</ul>';
        } else {
            html += '<p style="color:var(--text-dim)">当日无计划</p>';
        }

        html += '<h3 style="margin:1rem 0 0.5rem">🔥 复盘</h3>';
        if (data.reviews.length) {
            data.reviews.forEach(r => {
                html += `<div style="background:var(--surface);padding:0.8rem 1rem;border-radius:var(--radius);margin-bottom:0.5rem">`;
                if (r.pnl !== null) html += `<div style="margin-bottom:0.3rem"><strong>盈亏：</strong><span class="${r.pnl >= 0 ? 'pnl-pos' : 'pnl-neg'}">${r.pnl >= 0 ? '+' : ''}${r.pnl}</span></div>`;
                html += `<div style="margin-bottom:0.5rem"><strong>倾诉：</strong>${esc(r.emotion_log)}</div>`;
                if (r.ai_critique) html += `<div style="border-top:1px solid var(--surface2);padding-top:0.5rem;color:var(--accent)"><strong>AI 拷打：</strong>${esc(r.ai_critique)}</div>`;
                html += '</div>';
            });
        } else {
            html += '<p style="color:var(--text-dim)">当日无复盘</p>';
        }

        el.innerHTML = html;
    } catch (e) { toast(e.message, 'error'); }

    // Load journal for this date
    loadJournal();
}

async function loadJournal() {
    const d = document.getElementById('daily-date-input').value;
    try {
        const entries = await api(`/api/journal?trade_date=${d}`);
        const el = document.getElementById('journal-entries');
        if (!entries.length) { el.innerHTML = '<span style="color:var(--text-dim);font-size:0.85rem">当日无日记</span>'; return; }
        el.innerHTML = entries.map(e => `<div class="plan-item">
            <span class="content" style="white-space:pre-wrap;font-size:0.85rem">${esc(e.content)}</span>
            <span class="actions"><button onclick="deleteJournal(${e.id})" title="删除">✕</button></span>
        </div>`).join('');
    } catch (e) {}
}

async function saveJournal() {
    const input = document.getElementById('journal-input');
    const content = input.value.trim();
    if (!content) { toast('请输入日记内容', 'error'); return; }
    const trade_date = document.getElementById('daily-date-input').value;
    try {
        await api('/api/journal', { method: 'POST', body: JSON.stringify({ content, trade_date }) });
        input.value = '';
        loadJournal();
        toast('日记已保存');
    } catch (e) { toast(e.message, 'error'); }
}

async function deleteJournal(id) {
    if (!confirm('确定删除？')) return;
    try { await api(`/api/journal/${id}`, { method: 'DELETE' }); loadJournal(); } catch (e) { toast(e.message, 'error'); }
}

// --- Settings ---
async function loadSettings() {
    try {
        const cfg = await api('/api/settings');
        document.getElementById('cfg-base-url').value = cfg.base_url || '';
        document.getElementById('cfg-api-key').value = cfg.api_key || '';
        document.getElementById('cfg-model-name').value = cfg.model_name || '';
        document.getElementById('cfg-feishu-webhook').value = cfg.feishu_webhook || '';
        document.getElementById('cfg-notify-time').value = cfg.notify_time || '08:30';
        document.getElementById('cfg-intensity').value = cfg.critique_intensity || '3';
    } catch (e) { toast(e.message, 'error'); }
}

async function saveLLM() {
    try {
        await api('/api/settings/llm', {
            method: 'POST',
            body: JSON.stringify({
                base_url: document.getElementById('cfg-base-url').value,
                api_key: document.getElementById('cfg-api-key').value,
                model_name: document.getElementById('cfg-model-name').value,
            }),
        });
        showResult('llm-test-result', '✅ 已保存', true);
    } catch (e) { showResult('llm-test-result', `❌ ${e.message}`, false); }
}

async function testLLM() {
    const el = document.getElementById('llm-test-result');
    el.textContent = '测试中...';
    try {
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
    } catch (e) { showResult('llm-test-result', `❌ ${e.message}`, false); }
}

async function saveFeishu() {
    try {
        await api('/api/settings/feishu', {
            method: 'POST',
            body: JSON.stringify({
                feishu_webhook: document.getElementById('cfg-feishu-webhook').value,
                notify_time: document.getElementById('cfg-notify-time').value,
            }),
        });
        showResult('feishu-test-result', '✅ 已保存', true);
    } catch (e) { showResult('feishu-test-result', `❌ ${e.message}`, false); }
}

async function testFeishu() {
    const el = document.getElementById('feishu-test-result');
    el.textContent = '发送中...';
    try {
        const result = await api('/api/notifications/test-feishu', { method: 'POST' });
        if (result.success) showResult('feishu-test-result', '✅ 发送成功，请检查飞书', true);
        else showResult('feishu-test-result', `❌ ${result.error}`, false);
    } catch (e) { showResult('feishu-test-result', `❌ ${e.message}`, false); }
}

function showResult(id, msg, success) {
    const el = document.getElementById(id);
    el.textContent = msg;
    el.style.background = success ? 'rgba(76,175,80,0.15)' : 'rgba(233,69,96,0.15)';
}

async function saveIntensity() {
    const val = document.getElementById('cfg-intensity').value;
    try {
        await api('/api/settings/llm-extra', { method: 'POST', body: JSON.stringify({ critique_intensity: val }) });
        toast('已保存');
    } catch (e) { toast(e.message, 'error'); }
}

async function exportData(type, format) {
    window.open(`/api/data/export/${type}?format=${format}`);
}

async function importReviews() {
    const file = document.getElementById('import-file').files[0];
    if (!file) { toast('请选择文件', 'error'); return; }
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch('/api/data/import/reviews', { method: 'POST', body: formData });
        const result = await res.json();
        document.getElementById('import-result').textContent = result.error || `成功导入 ${result.imported} 条记录`;
    } catch (e) { toast(e.message, 'error'); }
}

async function checkDataHealth() {
    const el = document.getElementById('health-result');
    el.textContent = '检查中...';
    try {
        const h = await api('/api/data/health');
        let html = `<div style="padding:0.6rem;background:${h.healthy ? 'rgba(76,175,80,0.1)' : 'rgba(233,69,96,0.1)'};border-radius:var(--radius)">`;
        html += `<strong>${h.healthy ? '✅ 数据库健康' : '⚠️ 发现问题'}</strong><br>`;
        html += `完整性: ${h.integrity} | 大小: ${h.db_size_kb}KB<br>`;
        html += `复盘: ${h.review_count}条 | 计划: ${h.plan_count}条 | 弱点: ${h.vuln_count}条`;
        if (h.issues.future_reviews > 0) html += `<br>⚠️ 发现 ${h.issues.future_reviews} 条未来日期的复盘`;
        if (h.issues.duplicate_reviews > 0) html += `<br>⚠️ 发现 ${h.issues.duplicate_reviews} 组重复复盘`;
        html += '</div>';
        el.innerHTML = html;
    } catch (e) { el.textContent = '检查失败: ' + e.message; }
}

// --- Utils ---
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
}

// Keyboard shortcut: Enter to submit in plan inputs
document.querySelectorAll('.plan-input textarea').forEach(ta => {
    ta.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const type = ta.id.replace('-input', '');
            addPlan(type);
        }
    });
});

// Global keyboard shortcuts
document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    const tabs = ['plans', 'review', 'matrix', 'stats', 'daily', 'calendar', 'settings'];
    if (e.key >= '1' && e.key <= '7') {
        e.preventDefault();
        const tab = tabs[parseInt(e.key) - 1];
        document.querySelector(`[data-tab="${tab}"]`).click();
    }
});

// --- Weekly Summary ---
async function generateWeeklySummary() {
    const btn = document.getElementById('weekly-btn');
    const box = document.getElementById('weekly-summary');
    btn.disabled = true;
    btn.textContent = '生成中...';
    box.style.display = 'block';
    box.innerHTML = '';
    try {
        const res = await fetch('/api/weekly/generate', { method: 'POST' });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
                const payload = JSON.parse(line.slice(6));
                if (payload.chunk) box.innerHTML += esc(payload.chunk).replace(/\n/g, '<br>');
                if (payload.error) { box.innerHTML += `<span style="color:var(--danger)">${esc(payload.error)}</span>`; }
            }
        }
    } catch (e) { box.innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`; }
    btn.disabled = false;
    btn.textContent = '生成本周总结';
}

// --- Calendar ---
let calYear = new Date().getFullYear();
let calMonth = new Date().getMonth() + 1;

function calendarPrev() { calMonth--; if (calMonth < 1) { calMonth = 12; calYear--; } loadCalendar(); }
function calendarNext() { calMonth++; if (calMonth > 12) { calMonth = 1; calYear++; } loadCalendar(); }

async function loadCalendar() {
    document.getElementById('calendar-month-label').textContent = `${calYear}年${calMonth}月`;
    try {
        const data = await api(`/api/calendar?year=${calYear}&month=${calMonth}`);
        const grid = document.getElementById('calendar-grid');
        const firstDay = new Date(calYear, calMonth - 1, 1).getDay(); // 0=Sun
        const daysInMonth = new Date(calYear, calMonth, 0).getDate();
        // Monthly summary
        const pnlCls = data.month_pnl >= 0 ? 'positive' : 'negative';
        let html = `<div style="grid-column:1/-1;margin-bottom:0.5rem;font-size:0.85rem;color:var(--text-dim)">交易天数: ${data.trade_days} | 月盈亏: <span class="${pnlCls}">${data.month_pnl >= 0 ? '+' : ''}${data.month_pnl.toFixed(1)}</span></div>`;
        html += '<div class="cal-header">日</div><div class="cal-header">一</div><div class="cal-header">二</div><div class="cal-header">三</div><div class="cal-header">四</div><div class="cal-header">五</div><div class="cal-header">六</div>';
        for (let i = 0; i < firstDay; i++) html += '<div class="cal-cell empty"></div>';
        for (let d = 1; d <= daysInMonth; d++) {
            const key = `${calYear}-${String(calMonth).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
            const info = data.days[key];
            let cls = 'cal-cell';
            let badge = '';
            if (info) {
                if (info.pnl > 0) { cls += ' profit'; badge = `<span class="cal-pnl positive">+${info.pnl.toFixed(0)}</span>`; }
                else if (info.pnl < 0) { cls += ' loss'; badge = `<span class="cal-pnl negative">${info.pnl.toFixed(0)}</span>`; }
                else { cls += ' neutral'; badge = `<span class="cal-pnl">0</span>`; }
            }
            html += `<div class="${cls}" onclick="calendarDayClick('${key}')" style="cursor:${info?'pointer':'default'}"><span class="cal-day">${d}</span>${badge}</div>`;
        }
        grid.innerHTML = html;
    } catch (e) { toast(e.message, 'error'); }
}

function calendarDayClick(dateStr) {
    // Switch to review tab and filter by date
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    document.querySelector('[data-tab="review"]').classList.add('active');
    document.getElementById('tab-review').classList.add('active');
    document.getElementById('review-search').value = '';
    reviewPage = 0;
    api(`/api/reviews?trade_date=${dateStr}`).then(reviews => {
        const el = document.getElementById('review-history');
        if (!reviews.length) { el.innerHTML = `<div class="empty-state"><div class="msg">${dateStr} 无复盘记录</div></div>`; return; }
        el.innerHTML = reviews.map(r => {
            const pnlClass = r.pnl > 0 ? 'pnl-pos' : r.pnl < 0 ? 'pnl-neg' : '';
            const pnlText = r.pnl !== null ? `<span class="${pnlClass}">${r.pnl > 0 ? '+' : ''}${r.pnl}</span>` : '';
            return `<div class="review-history-item" onclick="toggleReviewDetail(this, ${r.id})">
                <div class="meta"><span class="date">${r.trade_date}</span>${pnlText}</div>
                <div class="summary">${esc(r.emotion_log).slice(0, 80)}${r.emotion_log.length > 80 ? '...' : ''}</div>
                <div class="critique-expand" id="review-detail-${r.id}"></div>
            </div>`;
        }).join('');
        document.getElementById('review-pagination').innerHTML = '';
    });
}

// Prevent accidental page leave with unsaved review
window.addEventListener('beforeunload', e => {
    const emotion = document.getElementById('emotion-input').value.trim();
    if (emotion) { e.preventDefault(); e.returnValue = ''; }
});

// Auto-save review draft to localStorage
const emotionInput = document.getElementById('emotion-input');
const savedDraft = localStorage.getItem('review_draft');
if (savedDraft) emotionInput.value = savedDraft;
emotionInput.addEventListener('input', () => localStorage.setItem('review_draft', emotionInput.value));
// Clear draft on successful submit
const origSubmit = submitReview;
// (draft cleared inside submitReview after success via emotion-input.value = '')

// Initial load
loadPlans();
