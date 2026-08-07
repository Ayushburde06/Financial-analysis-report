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
    const data = new FormData(); data.append('file', selectedFile); data.append('company_name', document.querySelector('#company-name').value.trim());
    startProgress();
    try {
      const response = await fetch('/generate-report', { method: 'POST', body: data });
      let payload = {}; try { payload = await response.json(); } catch (_) {}
      if (!response.ok) {
        const reference = payload.request_id ? ` Reference: ${payload.request_id}` : '';
        throw new Error(`${payload.detail || `The report could not be generated (${response.status}).`}${reference}`);
      }
      finishProgress();
      setTimeout(() => { progress.hidden = true; result.hidden = false; const filename = payload.pdf_filename || 'Equity_Research_Report.pdf'; download.href = `/download/${encodeURIComponent(filename)}`; download.download = filename; resultDetail.textContent = `${payload.message || 'The report passed the final source and layout checks.'}`; }, 350);
    } catch (err) { clearInterval(timer); progress.hidden = true; form.hidden = false; generateButton.disabled = false; showError(err.message || 'Something went wrong. Please try again.'); }
  });
})();
