(() => {
  const form = document.querySelector('#report-form');
  const fileInput = document.querySelector('#context-doc');
  const dropZone = document.querySelector('#drop-zone');
  const prompt = document.querySelector('#drop-prompt');
  const loaded = document.querySelector('#file-loaded');
  const fileName = document.querySelector('#file-name');
  const fileSize = document.querySelector('#file-size');
  const removeFile = document.querySelector('#remove-file');
  const generateButton = document.querySelector('#generate-btn');
  const progress = document.querySelector('#progress-view');
  const progressFill = document.querySelector('#progress-fill');
  const progressPercent = document.querySelector('#progress-percent');
  const progressDetail = document.querySelector('#progress-detail');
  const result = document.querySelector('#result-view');
  const resultDetail = document.querySelector('#result-detail');
  const download = document.querySelector('#download-link');
  const error = document.querySelector('#error-view');
  const newReport = document.querySelector('#new-report');
  let selectedFile = null;
  let timer = null;

  const allowed = new Set(['pdf', 'csv', 'txt', 'text', 'md']);
  const maxBytes = 50 * 1024 * 1024;
  const fileNoise = new Set(['q1','q2','q3','q4','fy','fy24','fy25','fy26','fy27','fy28','pdf','csv','txt','equity','report','geojit','quarter','result','results','update','earnings','financial','financials','statement','statements','annual','investor','presentation','transcript','filing','document','untitled']);
  const nameAliases = { ltts: ['ltts','lnt'], lnt: ['ltts','lnt'], pocl: ['pocl','pondy'], pondy: ['pocl','pondy'] };

  function nameTokens(text) {
    const normalized = String(text || '')
      .replace(/\bL\s*&\s*T\b/gi, 'LTTS')
      .replace(/\bL\s+and\s+T\b/gi, 'LTTS');
    return (normalized.toLowerCase().match(/[a-z0-9]+/g) || [])
      .filter((t) => t.length >= 3 && !fileNoise.has(t));
  }
  function expandTokens(tokens) {
    const out = new Set(tokens);
    tokens.forEach((t) => (nameAliases[t] || []).forEach((alias) => out.add(alias)));
    return out;
  }
  function companyFileMismatch(companyName, filename) {
    const stem = String(filename || '').replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    const fileTokens = expandTokens(nameTokens(stem));
    const coverTokens = expandTokens(nameTokens(companyName));
    if (!fileTokens.size || !coverTokens.size) return '';
    for (const token of fileTokens) if (coverTokens.has(token)) return '';
    return `Company name "${companyName}" does not match the uploaded file "${filename}". Enter the company name that matches the document (for example, if the file is JSW Energy Q2FY26.pdf, enter JSW Energy).`;
  }
  function detailText(payload, status) {
    const detail = payload && payload.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item.msg || item).filter(Boolean).join(' ');
    }
    return `The report could not be generated (${status}).`;
  }

  function showError(message) { error.textContent = message; error.hidden = false; }
  function clearError() { error.hidden = true; error.textContent = ''; }
  function chooseFile() { fileInput.click(); }
  function formatSize(bytes) { return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(2)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`; }
  function setFile(file) {
    clearError();
    const ext = file.name.split('.').pop().toLowerCase();
    if (!allowed.has(ext)) return showError('Unsupported file type. Please upload a PDF, CSV, TXT, or MD file.');
    if (file.size === 0) return showError('The selected file is empty.');
    if (file.size > maxBytes) return showError('The selected file is larger than the 50 MB limit.');
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatSize(file.size);
    prompt.hidden = true;
    loaded.hidden = false;
  }
  function reset() {
    clearInterval(timer); selectedFile = null; fileInput.value = '';
    prompt.hidden = false; loaded.hidden = true; progress.hidden = true; result.hidden = true;
    form.hidden = false; generateButton.disabled = false; progressFill.style.width = '0%';
  }
  function startProgress() {
    form.hidden = true; result.hidden = true; progress.hidden = false; generateButton.disabled = true;
    let value = 7;
    const messages = ['Reading and validating the source document…', 'Extracting financial tables and sector metrics…', 'Checking source values and units…', 'Building and rendering the report…'];
    let messageIndex = 0;
    timer = setInterval(() => { value = Math.min(94, value + 1); if (value % 20 === 0) messageIndex = Math.min(messages.length - 1, messageIndex + 1); progressFill.style.width = `${value}%`; progressPercent.textContent = `${value}%`; progressDetail.textContent = messages[messageIndex]; }, 700);
  }
  function finishProgress() { clearInterval(timer); progressFill.style.width = '100%'; progressPercent.textContent = '100%'; progressDetail.textContent = 'Verified PDF is ready.'; }

  dropZone.addEventListener('click', (event) => { if (event.target !== removeFile) chooseFile(); });
  dropZone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseFile(); } });
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });
  ['dragenter', 'dragover'].forEach(type => dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.add('drag-over'); }));
  ['dragleave', 'drop'].forEach(type => dropZone.addEventListener(type, event => { event.preventDefault(); dropZone.classList.remove('drag-over'); }));
  dropZone.addEventListener('drop', event => { if (event.dataTransfer.files[0]) setFile(event.dataTransfer.files[0]); });
  removeFile.addEventListener('click', event => { event.stopPropagation(); reset(); });
  newReport.addEventListener('click', reset);

  form.addEventListener('submit', async event => {
    event.preventDefault(); clearError();
    if (!selectedFile) return showError('Please choose a PDF, CSV, TXT, or MD file first.');
    const companyName = document.querySelector('#company-name').value.trim();
    if (companyName.length < 2) return showError('Please enter the company name.');
    const mismatch = companyFileMismatch(companyName, selectedFile.name);
    if (mismatch) {
      showError(mismatch);
      window.alert(mismatch);
      return;
    }
    const data = new FormData(); data.append('file', selectedFile); data.append('company_name', companyName);
    startProgress();
    try {
      const response = await fetch('/generate-report', { method: 'POST', body: data });
      let payload = {}; try { payload = await response.json(); } catch (_) {}
      if (!response.ok) {
        const reference = payload.request_id ? ` Reference: ${payload.request_id}` : '';
        throw new Error(`${detailText(payload, response.status)}${reference}`);
      }
      finishProgress();
      setTimeout(() => { progress.hidden = true; result.hidden = false; const filename = payload.pdf_filename || 'Equity_Research_Report.pdf'; download.href = `/download/${encodeURIComponent(filename)}`; download.download = filename; resultDetail.textContent = `${payload.message || 'The report passed the final source and layout checks.'}`; }, 350);
    } catch (err) {
      clearInterval(timer);
      progress.hidden = true;
      form.hidden = false;
      generateButton.disabled = false;
      const message = err.message || 'Something went wrong. Please try again.';
      showError(message);
      if (/does not match/i.test(message)) window.alert(message);
    }
  });
})();
