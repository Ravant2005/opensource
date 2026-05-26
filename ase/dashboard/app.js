const state = {
  currentJobId: null,
  logs: [],
  analyzeResult: null,
  activeView: 'dashboard',
};

// UI Elements
const repoUrlInput = document.getElementById('repoUrl');
const analyzeBtn = document.getElementById('analyzeBtn');
const logStream = document.getElementById('logStream');
const resultsArea = document.getElementById('resultsArea');
const dashboardView = document.getElementById('view-dashboard');
const summaryText = document.getElementById('summaryText');
const fixesList = document.getElementById('fixesList');
const featuresList = document.getElementById('featuresList');
const orgIntelCard = document.getElementById('org-intel-card');
const currentTaskText = document.getElementById('current-task-text');

// Stats
const statVulns = document.getElementById('stat-vulns');
const statFeats = document.getElementById('stat-feats');

// Navigation
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const view = link.dataset.view;
    switchView(view);
  });
});

function switchView(view) {
  state.activeView = view;
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
  document.querySelector(`[data-view="${view}"]`).classList.add('active');

  // Hide all sections in main content
  dashboardView.classList.add('hidden');
  resultsArea.classList.add('hidden');

  if (view === 'dashboard') {
    dashboardView.classList.remove('hidden');
  } else {
    resultsArea.classList.remove('hidden');
    // Scroll to specific section
    const target = document.getElementById(`${view}-section`);
    if (target) target.scrollIntoView({ behavior: 'smooth' });
  }
}

analyzeBtn.addEventListener('click', startMagic);

async function startMagic() {
  const url = repoUrlInput.value.trim();
  if (!url) return;

  // Reset UI
  state.logs = [];
  logStream.innerHTML = '';
  resultsArea.classList.add('hidden');
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = 'Agent Working...';
  currentTaskText.textContent = 'Initializing Agent...';

  try {
    const res = await fetch('/api/v1/analyze-repo/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: url, dry_run: true })
    });
    const data = await res.json();
    state.currentJobId = data.job_id;
    addLog('INFO', `Mission assigned: ${url}. Job ID: ${state.currentJobId}`);
    pollJob();
  } catch (err) {
    addLog('ERROR', 'Failed to initialize mission.');
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = 'Start Magic';
  }
}

async function pollJob() {
  try {
    const res = await fetch(`/api/v1/analyze-repo/jobs/${state.currentJobId}`);
    const data = await res.json();

    if (data.logs && data.logs.length > state.logs.length) {
      const newLogs = data.logs.slice(state.logs.length);
      newLogs.forEach(l => addLog(l.level, l.message));
      state.logs = data.logs;
    }

    currentTaskText.textContent = `Current Phase: ${data.status.toUpperCase()} (${data.progress}%)`;

    if (data.status === 'completed') {
      state.analyzeResult = data.result;
      renderResults(data.result);
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = 'Start Magic';
      currentTaskText.textContent = 'Mission Accomplished.';
      addLog('SUCCESS', 'All phases completed. View results below.');
      setTimeout(() => switchView('fixes'), 1000);
      return;
    }

    if (data.status === 'failed') {
      addLog('ERROR', `Mission failed: ${data.error}`);
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = 'Start Magic';
      currentTaskText.textContent = 'Mission Aborted.';
      return;
    }

    setTimeout(pollJob, 1500);
  } catch (err) {
    setTimeout(pollJob, 5000);
  }
}

function addLog(level, message) {
  const entry = document.createElement('div');
  entry.className = 'log-entry animate-in';
  const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  entry.innerHTML = `
    <span class="log-ts">${ts}</span>
    <span class="log-msg ${level.toLowerCase()}">${message}</span>
  `;
  logStream.appendChild(entry);
  logStream.scrollTop = logStream.scrollHeight;
}

function renderResults(result) {
  resultsArea.classList.remove('hidden');
  const vulnCount = result.findings?.length || 0;
  const featCount = result.assessments?.filter(a => a.type === 'feature_recommendation').length || 0;
  
  statVulns.textContent = vulnCount;
  statFeats.textContent = featCount;
  
  summaryText.textContent = `Agent ${result.repo_slug} completed. Found ${vulnCount} security risks and ${featCount} strategic upgrades.`;

  // Render Org Intel
  if (result.findings) {
    const intel = result.findings.find(f => f.type === 'org_intelligence')?.data;
    if (intel) {
      orgIntelCard.innerHTML = `
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
          <div>
            <h4 style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: 8px;">REPO STRATEGY</h4>
            <p style="font-weight: 600;">${intel.summary?.primary_language} | ${intel.summary?.total_open_issues} Issues</p>
            <p style="font-size: 0.875rem; margin-top: 8px;">${intel.repo_meta?.description || 'No description'}</p>
          </div>
          <div>
            <h4 style="font-size: 0.875rem; color: var(--text-muted); margin-bottom: 8px;">GOVERNANCE</h4>
            <ul style="font-size: 0.875rem; list-style: none; display: flex; flex-wrap: wrap; gap: 8px;">
              ${intel.summary?.has_contributing_guide ? '<li style="background: #ecfdf5; color: #059669; padding: 2px 8px; border-radius: 4px;">CONTRIBUTING</li>' : ''}
              ${intel.summary?.has_security_policy ? '<li style="background: #ecfdf5; color: #059669; padding: 2px 8px; border-radius: 4px;">SECURITY.md</li>' : ''}
              ${intel.summary?.has_roadmap ? '<li style="background: #eff6ff; color: #2563eb; padding: 2px 8px; border-radius: 4px;">ROADMAP</li>' : ''}
            </ul>
          </div>
        </div>
      `;
    }
  }

  // Render Fixes
  fixesList.innerHTML = '';
  const fixTemplate = document.getElementById('fixTemplate');
  (result.patches || []).forEach(patch => {
    const clone = fixTemplate.content.cloneNode(true);
    const finding = patch.finding || {};
    clone.querySelector('#fix-severity').textContent = (finding.severity || 'HIGH').toUpperCase();
    clone.querySelector('#fix-title').textContent = finding.rule_id;
    clone.querySelector('#fix-reasoning').textContent = patch.explanation || finding.message;
    clone.querySelector('#fix-patch').textContent = patch.patch || 'Analyzing real code changes...';
    
    const prBtn = clone.querySelector('.btn-pr');
    prBtn.addEventListener('click', () => createPR(patch, prBtn));
    
    fixesList.appendChild(clone);
  });

  // Render Features
  featuresList.innerHTML = '';
  const featTemplate = document.getElementById('featTemplate');
  (result.assessments || []).filter(a => a.type === 'feature_recommendation').forEach(feat => {
    const rec = feat.data;
    const clone = featTemplate.content.cloneNode(true);
    clone.querySelector('#feat-impact').textContent = rec.estimated_impact.toUpperCase();
    clone.querySelector('#feat-title').textContent = rec.title;
    clone.querySelector('#feat-desc').textContent = rec.description;
    clone.querySelector('#feat-sketch').textContent = "Proposed Plan:\n" + rec.implementation_sketch;
    
    const prBtn = clone.querySelector('.btn-pr');
    prBtn.addEventListener('click', () => createPR({
      finding: { rule_id: rec.title, file_path: rec.files_to_modify[0] || 'roadmap' },
      patch: '', // Actual feature code would be generated in real flow
      explanation: rec.pr_body
    }, prBtn));
    
    featuresList.appendChild(clone);
  });
}

async function createPR(patch, btn) {
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Submitting...';
  
  try {
    const payload = {
      repo_url: state.analyzeResult.repo_url,
      repo_slug: state.analyzeResult.repo_slug,
      finding: patch.finding,
      patch: patch.patch,
      explanation: patch.explanation || "",
      dry_run: true
    };
    
    const res = await fetch('/api/v1/create-pr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    
    const data = await res.json();
    btn.textContent = '✅ Success';
    btn.style.background = 'var(--success)';
    if (data.pr_url) window.open(data.pr_url, '_blank');
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Retry PR';
  }
}
