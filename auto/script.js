const APPS_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbwZo2WecH8AbJ2rx6-YM7nVzO6D7l7Qn8tMmYQdVMopnIyuCy3SkfZibVS5ibHFtces-w/exec';

const COMPANY_MAP = {
  'CAMPAIGN_A': 'SecureDrive Insurance',
  'CAMPAIGN_B': 'Vocal Tech Marketing',
  'DEFAULT': ''
};

const US_STATES = ["AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"];

function getParam(name) {
  const params = new URLSearchParams(window.location.search);
  const aliases = {
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
    comments: ['comments','notes','comment']
  };
  const keys = aliases[name] || [name];
  for (const k of keys) {
    const v = params.get(k);
    if (v && v.trim()) return v.trim();
  }
  return '';
}

function normalizePhone(raw) {
  if (!raw) return '';
  return String(raw).replace(/\D/g, '').slice(-10);
}

function boot() {
  const phone = getParam('phone');
  if (!phone && !getParam('first') && !getParam('campaign')) {
    document.getElementById('app').innerHTML = `
      <div class="no-call-screen">
        <div class="no-call-icon"><i class="ti ti-phone-off"></i></div>
        <h2>No webform found</h2>
      </div>`;
    return;
  }
  renderPage();
}

function showStatusBanner(type, message) {
  const banner = document.getElementById('statusBanner');
  if (!banner) return;

  banner.className = 'status-banner ' + type;

  let icon = 'ti ti-alert-triangle';
  if (type === 'clean') icon = 'ti ti-circle-check';
  if (type === 'blocked') icon = 'ti ti-ban';
  if (type === 'loading') icon = 'ti ti-loader';

  banner.innerHTML = `
    <div class="status-icon"><i class="${icon}"></i></div>
    <div class="status-text">${message}</div>
  `;
  banner.style.display = 'flex';
}

function showSaleForm() {
  document.getElementById('saleFormSection').classList.remove('hidden');
  document.getElementById('fillFormBtn').classList.add('hidden');
}

function showDetailedResponse(data) {
  const container = document.getElementById('detailedResponse');
  if (!container) return;

  const isClean = !data.blocked;
  const title = isClean ? 'Lead Verified — Clean' : `DNC List Warning (${data.reason || 'Restricted'})`;
  const raw = data.raw || {};

  container.innerHTML = `
    <div class="detail-card ${isClean ? 'clean' : 'blocked'}">
      <div class="detail-header ${isClean ? 'clean-title' : 'blocked-title'}">
        <i class="ti ${isClean ? 'ti-circle-check' : 'ti-alert-triangle'}"></i>
        <span>${title}</span>
      </div>
      <div class="detail-body">
        <div class="detail-row">
          <span class="label">PHONE</span>
          <span class="value">${data.phone || raw.phone || '-'}</span>
        </div>
        <div class="detail-row">
          <span class="label">STATUS</span>
          <span class="value">${raw.status || (isClean ? 'success' : 'blacklisted')}</span>
        </div>
        <div class="detail-row">
          <span class="label">MESSAGE</span>
          <span class="value">${raw.message || data.reason || '-'}</span>
        </div>
        <div class="detail-row">
          <span class="label">CODE</span>
          <span class="value">${raw.code || data.blaCode || 'none'}</span>
        </div>
        <div class="detail-row">
          <span class="label">SID</span>
          <span class="value">${raw.sid || '-'}</span>
        </div>
        <div class="detail-row">
          <span class="label">WIRELESS</span>
          <span class="value">${raw.wireless !== undefined ? raw.wireless : '-'}</span>
        </div>
        <div class="detail-row">
          <span class="label">RESULTS</span>
          <span class="value">${raw.results !== undefined ? raw.results : '-'}</span>
        </div>
        <div class="detail-row">
          <span class="label">SCRUBS</span>
          <span class="value">${raw.scrubs !== undefined ? String(raw.scrubs) : '-'}</span>
        </div>
      </div>
    </div>
  `;
  container.style.display = 'block';
}

async function runComplianceCheck(phone) {
  showStatusBanner('loading', 'Please wait… Searching…');

  // Collect extra fields from URL (Vicidial)
  const extraData = {
    action: 'checkCompliance',
    phone: phone,
    firstName: getParam('first') || getParam('first_name') || '',
    lastName: getParam('last') || getParam('last_name') || '',
    city: getParam('city') || '',
    state: getParam('state') || '',
    zip: getParam('zip') || getParam('postal') || ''
  };

  try {
    const res = await fetch(APPS_SCRIPT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(extraData)
    });

    const text = await res.text();
    console.log('Raw response:', text);

    let data;
    try {
      data = JSON.parse(text);
    } catch (e) {
      showStatusBanner('error', 'Server error – please try again');
      document.getElementById('fillFormBtn').classList.remove('hidden');
      return;
    }

    // Hide loading banner
    document.getElementById('statusBanner').style.display = 'none';

    // Show detailed response card
    showDetailedResponse(data);

    if (data.blocked) {
      document.getElementById('fillFormBtn').classList.add('hidden');
    } else {
      document.getElementById('fillFormBtn').classList.remove('hidden');
    }

  } catch (err) {
    console.error(err);
    showStatusBanner('error', 'Network error during check. Proceed with caution.');
    document.getElementById('fillFormBtn').classList.remove('hidden');
  }
}

function renderPage() {
  const phone = getParam('phone');
  const campaignParam = getParam('campaign');
  const urlCompany = getParam('company');
  const detectedCompany = urlCompany || COMPANY_MAP[campaignParam] || '';
  const stateOptions = US_STATES.map(s => `<option value="${s}">${s}</option>`).join('');

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

      <div id="statusBanner" class="status-banner loading" style="display:none;"></div>

      <!-- Detailed API Response Card -->
      <div id="detailedResponse" style="display:none;"></div>

      <div class="sale-form-inner">
        <button id="fillFormBtn" class="btn-fill-form hidden" onclick="showSaleForm()">
          <i class="ti ti-forms"></i> Fill the Sale Form
        </button>

        <div id="saleFormSection" class="hidden">
          <input type="hidden" id="campaign" value="${campaignParam}">
          <input type="hidden" id="company" value="${detectedCompany}">
          <input type="hidden" id="zip">
          <input type="hidden" id="dob">

          <div class="section-label">Agent Information</div>
          <div class="field-grid full">
            <div class="field-group">
              <label>Agent Name</label>
              <div class="input-wrap"><i class="ti ti-id"></i>
                <input type="text" id="agentName" placeholder="Agent Name / ID">
              </div>
            </div>
          </div>
          <div class="field-grid full">
            <div class="field-group">
              <label>DID</label>
              <div class="input-wrap"><i class="ti ti-hash"></i>
                <input type="text" id="did" placeholder="e.g. D1">
              </div>
            </div>
          </div>

          <div class="section-label">Customer Information</div>
          <div class="field-grid">
            <div class="field-group">
              <label>First name</label>
              <div class="input-wrap"><i class="ti ti-user"></i>
                <input type="text" id="firstName" placeholder="First name">
              </div>
            </div>
            <div class="field-group">
              <label>Last name</label>
              <div class="input-wrap"><i class="ti ti-user"></i>
                <input type="text" id="lastName" placeholder="Last name">
              </div>
            </div>
          </div>
          <div class="field-grid">
            <div class="field-group">
              <label>Phone number</label>
              <div class="input-wrap"><i class="ti ti-phone"></i>
                <input type="tel" id="phone" placeholder="10-digit number">
              </div>
            </div>
            <div class="field-group">
              <label>State</label>
              <div class="input-wrap"><i class="ti ti-map-pin"></i>
                <select id="state">
                  <option value="">Select state</option>
                  ${stateOptions}
                </select>
              </div>
            </div>
          </div>
          <div class="field-grid full">
            <div class="field-group">
              <label>Age</label>
              <div class="input-wrap"><i class="ti ti-calendar-event"></i>
                <input type="number" id="age" placeholder="Age" min="0" max="120">
              </div>
            </div>
          </div>

          <div class="section-label">Agent Notes</div>
          <div class="field-group">
            <label>Comments</label>
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
            <i class="ti ti-alert-circle"></i> Submission failed.
          </div>
        </div>
      </div>
    </div>
  `;

  // Auto-fill
  document.getElementById('agentName').value = getParam('agentName') || '';
  document.getElementById('phone').value = phone || '';
  document.getElementById('firstName').value = getParam('first') || '';
  document.getElementById('lastName').value = getParam('last') || '';
  document.getElementById('age').value = getParam('age') || '';
  document.getElementById('did').value = getParam('did') || '';
  document.getElementById('comments').value = getParam('comments') || '';

  const stateVal = getParam('state');
  if (stateVal) {
    const sel = document.getElementById('state');
    for (let i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value.toLowerCase() === stateVal.toLowerCase()) {
        sel.value = sel.options[i].value;
        break;
      }
    }
  }

  // Start compliance check
  const cleanPhone = normalizePhone(phone);
  if (cleanPhone.length === 10) {
    runComplianceCheck(cleanPhone);
  } else {
    showStatusBanner('warning', 'No valid 10-digit phone found');
    document.getElementById('fillFormBtn').classList.remove('hidden');
  }
}

function clearSaleForm() {
  ['agentName','firstName','lastName','phone','age','state','did','comments'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('successToast').style.display = 'none';
  document.getElementById('errorToast').style.display = 'none';
}

async function submitSaleForm() {
  const btn = document.getElementById('submitBtn');
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
    zip: '',
    dob: '',
    company: document.getElementById('company').value,
    campaign: document.getElementById('campaign').value,
    did: document.getElementById('did').value,
    comments: document.getElementById('comments').value
  };

  try {
    const res = await fetch(APPS_SCRIPT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.status === 'success' || data.success) {
      document.body.insertAdjacentHTML('beforeend', `
        <div class="modal-overlay show" id="successModal">
          <div class="modal-box">
            <div class="modal-icon"><i class="ti ti-circle-check"></i></div>
            <h2 class="modal-title">Sale Submitted</h2>
            <p class="modal-sub">Successfully recorded.</p>
            <button class="modal-close" onclick="document.getElementById('successModal').remove(); location.reload();">Okay</button>
          </div>
        </div>
      `);
    } else {
      throw new Error('Failed');
    }
  } catch (err) {
    btn.innerHTML = '<i class="ti ti-device-floppy"></i> Submit Sale';
    btn.disabled = false;
    document.getElementById('errorToast').style.display = 'flex';
  }
}

// Start
boot();
