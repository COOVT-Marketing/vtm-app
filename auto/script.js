const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbwZo2WecH8AbJ2rx6-YM7nVzO6D7l7Qn8tMmYQdVMopnIyuCy3SkfZibVS5ibHFtces-w/exec';

const COMPANY_MAP = {
  'CAMPAIGN_A': 'SecureDrive Insurance',
  'CAMPAIGN_B': 'Vocal Tech Marketing',
  'DEFAULT': ''
};

const US_STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"];

const ALIASES = {
  agentName: ['fullname','agentName','agent_name','agent','user'],
  phone: ['phone','phone_number','phonenumber','phone_code'],
  first: ['first','first_name','fname'],
  last: ['last','last_name','lname'],
  age: ['age'],
  state: ['state'],
  zip: ['zip','postal','postal_code','zipcode'],
  dob: ['dob','birthdate','d_o_b'],
  company: ['company','vendor'],
  campaign: ['campaign','campaign_id'],
  did: ['did','did_id','inbound_number'],
  comments: ['comments','notes','comment'],
};

function getParam(name) {
  const params = new URLSearchParams(window.location.search);
  for (const k of (ALIASES[name] || [name])) {
    const v = params.get(k);
    if (v && v.trim()) return v.trim();
  }
  return '';
}

function isLiveCall() {
  const params = new URLSearchParams(window.location.search);
  return ['phone','phone_number','phonenumber','first','first_name','last','last_name','campaign']
    .some(p => params.get(p));
}

function normalizePhone(raw) {
  if (!raw) return '';
  return String(raw).replace(/\D/g, '').slice(-10);
}

/* ---------- Boot ---------- */
function boot() {
  if (!isLiveCall()) {
    renderNoCall();
    return;
  }
  renderPage();
  const phone = normalizePhone(getParam('phone'));
  if (phone && phone.length === 10) {
    runComplianceCheck(phone);
  } else {
    showStatusBanner('warning', 'No valid phone number detected in URL. Manual check required.');
  }
}

/* ---------- Compliance Check ---------- */
async function runComplianceCheck(phone) {
  showStatusBanner('loading', 'Running DNC / Duplicate / BLA checks…');

  try {
    const res = await fetch(APPS_SCRIPT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify({
        action: 'checkCompliance',
        phone: phone
      })
    });

    const data = await res.json();

    if (!data.success) {
      showStatusBanner('error', data.message || data.reason || 'Compliance check failed');
      return;
    }

    if (data.blocked) {
      const reason = data.reason || 'Restricted';
      showStatusBanner('blocked', `Do Not Transfer — ${reason}`);
      // Keep the Fill Form button hidden
      const btn = document.getElementById('fillFormBtn');
      if (btn) btn.classList.add('hidden');
    } else {
      showStatusBanner('clean', 'Lead verified — Clean (Internal DNC, Duplicate & BLA clear)');
      const btn = document.getElementById('fillFormBtn');
      if (btn) btn.classList.remove('hidden');
    }
  } catch (err) {
    console.error(err);
    showStatusBanner('error', 'Network error during compliance check. Do not proceed without manual verification.');
  }
}

/* ---------- UI Helpers ---------- */
function showStatusBanner(type, message) {
  const banner = document.getElementById('statusBanner');
  if (!banner) return;

  banner.className = 'status-banner ' + type;
  banner.innerHTML = `
    <div class="status-icon">
      ${type === 'clean' ? '<i class="ti ti-circle-check"></i>' :
        type === 'blocked' ? '<i class="ti ti-ban"></i>' :
        type === 'loading' ? '<i class="ti ti-loader"></i>' :
        '<i class="ti ti-alert-triangle"></i>'}
    </div>
    <div class="status-text">${message}</div>
  `;
  banner.style.display = 'flex';
}

function showSaleForm() {
  const form = document.getElementById('saleFormSection');
  const btn = document.getElementById('fillFormBtn');
  if (form) form.classList.remove('hidden');
  if (btn) btn.classList.add('hidden');
}

/* ---------- Render ---------- */
function renderNoCall() {
  document.getElementById('app').innerHTML = `
    <div class="no-call-screen">
      <div class="no-call-icon"><i class="ti ti-phone-off"></i></div>
      <h2>No webform found</h2>
    </div>`;
}

function renderPage() {
  const phone = getParam('phone');
  const campaignParam = getParam('campaign');
  const urlCompany = getParam('company');
  const detectedCompany = urlCompany || COMPANY_MAP[campaignParam] || COMPANY_MAP['DEFAULT'];
  const stateOptions = US_STATES.map(s => `<option>${s}</option>`).join('');

  document.getElementById('app').innerHTML = `
    <div class="vtm-card">
      <div class="vtm-header">
        <div class="vtm-logo"><i class="ti ti-headset"></i></div>
        <div class="vtm-header-txt">
          <h1>Sale Form</h1>
          <p>Vocal Tech Marketing · Auto</p>
        </div>
        <div class="live-badge"><div class="live-dot"></div>Live call</div>
      </div>

      <!-- STATUS BANNER -->
      <div id="statusBanner" class="status-banner loading" style="display:none;"></div>

      <div class="sale-form-inner">
        <!-- Single Toggle Button -->
        <button id="fillFormBtn" class="btn-fill-form hidden" onclick="showSaleForm()">
          <i class="ti ti-forms"></i> Fill the Sale Form
        </button>

        <!-- HIDDEN SALE FORM -->
        <div id="saleFormSection" class="hidden">
          <input type="hidden" id="campaign" />
          <input type="hidden" id="company" value="${detectedCompany}" />
          <input type="hidden" id="zip" />
          <input type="hidden" id="dob" />

          <div class="section-label">Agent Information</div>
          <div class="field-grid full">
            <div class="field-group">
              <label for="agentName">Agent Name</label>
              <div class="input-wrap"><i class="ti ti-id"></i>
                <input type="text" id="agentName" placeholder="Agent Name / ID" />
              </div>
            </div>
          </div>
          <div class="field-grid full">
            <div class="field-group">
              <label for="did">DID</label>
              <div class="input-wrap"><i class="ti ti-hash"></i>
                <input type="text" id="did" placeholder="e.g. D1" />
              </div>
            </div>
          </div>

          <div class="section-label">Customer Information</div>
          <div class="field-grid">
            <div class="field-group">
              <label for="firstName">First name</label>
              <div class="input-wrap"><i class="ti ti-user"></i>
                <input type="text" id="firstName" placeholder="First name" />
              </div>
            </div>
            <div class="field-group">
              <label for="lastName">Last name</label>
              <div class="input-wrap"><i class="ti ti-user"></i>
                <input type="text" id="lastName" placeholder="Last name" />
              </div>
            </div>
          </div>
          <div class="field-grid">
            <div class="field-group">
              <label for="phone">Phone number</label>
              <div class="input-wrap"><i class="ti ti-phone"></i>
                <input type="tel" id="phone" placeholder="10-digit number" />
              </div>
            </div>
            <div class="field-group">
              <label for="state">State</label>
              <div class="input-wrap"><i class="ti ti-map-pin"></i>
                <select id="state"><option value="">Select state</option>${stateOptions}</select>
              </div>
            </div>
          </div>
          <div class="field-grid full">
            <div class="field-group">
              <label for="age">Age</label>
              <div class="input-wrap"><i class="ti ti-calendar-event"></i>
                <input type="number" id="age" placeholder="Age" min="0" max="120" />
              </div>
            </div>
          </div>

          <div class="section-label">Agent Notes</div>
          <div class="field-group" style="margin-bottom:0">
            <label for="comments">Comments</label>
            <div class="textarea-wrap"><i class="ti ti-notes"></i>
              <textarea id="comments" placeholder="Comments…"></textarea>
            </div>
          </div>

          <div class="btn-row">
            <button class="btn-secondary" onclick="clearSaleForm()">
              <i class="ti ti-refresh"></i> Clear
            </button>
            <button class="btn-primary" id="submitBtn" onclick="submitSaleForm()">
              <i class="ti ti-device-floppy"></i> Submit Sale
            </button>
          </div>

          <div class="success-toast" id="successToast">
            <i class="ti ti-circle-check"></i> Sale submitted successfully!
          </div>
          <div class="error-toast" id="errorToast">
            <i class="ti ti-alert-circle"></i> Submission failed. Check your connection and try again.
          </div>
        </div>
      </div>
    </div>`;

  // Auto-fill
  autoFill('agentName', getParam('agentName'));
  autoFill('phone', phone);
  autoFill('firstName', getParam('first'));
  autoFill('lastName', getParam('last'));
  autoFill('age', getParam('age'));
  autoFill('zip', getParam('zip'));
  autoFill('dob', getParam('dob'));
  autoFill('campaign', campaignParam);
  autoFill('did', getParam('did'));
  autoFill('comments', getParam('comments'));
  setStateByValue(getParam('state'));
}

function autoFill(id, value) {
  const el = document.getElementById(id);
  if (!el || !value) return;
  el.value = value;
  if (el.type !== 'hidden') el.classList.add('auto-filled');
}

function setStateByValue(value) {
  if (!value) return;
  const sel = document.getElementById('state');
  if (!sel) return;
  for (const opt of sel.options) {
    if (opt.value.toLowerCase() === value.toLowerCase() || opt.text.toLowerCase() === value.toLowerCase()) {
      sel.value = opt.value;
      sel.classList.add('auto-filled');
      break;
    }
  }
}

function clearSaleForm() {
  ['agentName','firstName','lastName','phone','age','state','zip','dob','company','campaign','did','comments']
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.value = '';
        el.classList.remove('auto-filled');
      }
    });
  document.getElementById('successToast').style.display = 'none';
  document.getElementById('errorToast').style.display = 'none';
}

async function submitSaleForm() {
  const btn = document.getElementById('submitBtn');
  const successToast = document.getElementById('successToast');
  const errorToast = document.getElementById('errorToast');

  successToast.style.display = 'none';
  errorToast.style.display = 'none';
  btn.innerHTML = '<i class="ti ti-loader"></i> Submitting…';
  btn.disabled = true;

  const payload = {
    submissionType: 'AUTO_SALE_FORM',
    agentName: document.getElementById('agentName').value,
    phone: document.getElementById('phone').value,
    firstName: document.getElementById('firstName').value,
    lastName: document.getElementById('lastName').value,
    age: document.getElementById('age').value,
    state: document.getElementById('state').value,
    zip: document.getElementById('zip').value,
    dob: document.getElementById('dob').value,
    company: document.getElementById('company').value,
    campaign: document.getElementById('campaign').value,
    did: document.getElementById('did').value,
    comments: document.getElementById('comments').value,
  };

  try {
    const res = await fetch(APPS_SCRIPT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.status === 'success' || data.success) {
      window.history.replaceState({}, '', window.location.pathname);
      const modalHtml = `
        <div class="modal-overlay show" id="successModal">
          <div class="modal-box">
            <div class="modal-icon"><i class="ti ti-circle-check"></i></div>
            <h2 class="modal-title">Sale Submitted</h2>
            <p class="modal-sub">Successfully recorded.</p>
            <button class="modal-close" onclick="closeSaleAndExit()">Okay</button>
          </div>
        </div>`;
      document.body.insertAdjacentHTML('beforeend', modalHtml);
    } else {
      throw new Error(data.message || 'Submission failed');
    }
  } catch (err) {
    btn.innerHTML = '<i class="ti ti-device-floppy"></i> Submit Sale';
    btn.disabled = false;
    errorToast.style.display = 'flex';
  }
}

function closeSaleAndExit() {
  const modal = document.getElementById('successModal');
  if (modal) modal.remove();
  renderNoCall();
}

boot();
