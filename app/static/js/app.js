/**
 * Main Frontend SPA Controller
 */
const App = {
  state: {
    currentTab: 'dashboard',
    customers: [],
    cheques: [],
    holders: [],
    stats: {},
    searchQuery: '',
    selectedCustomer: null,
    colorFilter: 'all',
    charts: {}
  },

  async init() {
    await this.fetchHolders();
    await this.loadStats();
    await this.loadCustomers();
    await this.loadCheques();
    this.setupEventListeners();
    this.renderView();
    if (window.lucide) lucide.createIcons();
  },

  // ─────────────────────────────────────────────────────────────
  // 📡 API Helper Calls
  // ─────────────────────────────────────────────────────────────
  async fetchHolders() {
    try {
      const res = await fetch('/api/holders');
      const data = await res.json();
      this.state.holders = data.holders || [];
      this.populateHolderDropdowns();
    } catch (e) {
      console.error('Error fetching holders:', e);
    }
  },

  async loadStats() {
    try {
      const res = await fetch('/api/stats');
      this.state.stats = await res.json();
      this.renderDashboardStats();
      this.renderCharts();
    } catch (e) {
      console.error('Error loading stats:', e);
    }
  },

  async loadCustomers() {
    try {
      const q = encodeURIComponent(this.state.searchQuery || '');
      const color = encodeURIComponent(this.state.colorFilter || 'all');
      const res = await fetch(`/api/customers?q=${q}&color=${color}&limit=200`);
      const data = await res.json();
      this.state.customers = data.customers || [];
      this.renderCustomersTable();
    } catch (e) {
      console.error('Error loading customers:', e);
    }
  },

  async loadCheques() {
    try {
      const q = encodeURIComponent(this.state.searchQuery || '');
      const res = await fetch(`/api/cheques?q=${q}&limit=300`);
      const data = await res.json();
      this.state.cheques = data.cheques || [];
      this.renderChequesTable();
    } catch (e) {
      console.error('Error loading cheques:', e);
    }
  },

  async viewCustomerProfile(customerId) {
    try {
      const res = await fetch(`/api/customers/${customerId}`);
      const data = await res.json();
      this.state.selectedCustomer = data;
      this.renderCustomerProfileModal(data);
    } catch (e) {
      this.showToast('خطا در بارگذاری پروفایل مشتری', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 🎨 View & UI Rendering
  // ─────────────────────────────────────────────────────────────
  switchTab(tabName) {
    this.state.currentTab = tabName;
    
    // Update nav buttons
    document.querySelectorAll('.nav-link').forEach(btn => {
      if (btn.dataset.tab === tabName) {
        btn.classList.add('bg-blue-600', 'text-white', 'shadow-md');
        btn.classList.remove('text-slate-400', 'hover:bg-slate-800');
      } else {
        btn.classList.remove('bg-blue-600', 'text-white', 'shadow-md');
        btn.classList.add('text-slate-400', 'hover:bg-slate-800');
      }
    });

    // Toggle views
    document.querySelectorAll('.tab-view').forEach(view => {
      view.classList.toggle('hidden', view.id !== `view-${tabName}`);
    });

    if (tabName === 'dashboard') {
      this.loadStats();
    } else if (tabName === 'customers') {
      this.loadCustomers();
    } else if (tabName === 'cheques') {
      this.loadCheques();
    } else if (tabName === 'scheduler') {
      this.loadSchedulerStatus();
    }

    if (window.lucide) lucide.createIcons();
  },

  renderDashboardStats() {
    const s = this.state.stats;
    document.getElementById('stat-total-customers').innerText = (s.total_customers || 0).toLocaleString('fa-IR');
    document.getElementById('stat-total-cheques').innerText = (s.total_cheques || 0).toLocaleString('fa-IR');
    document.getElementById('stat-total-amount').innerText = this.formatMoney(s.total_amount || 0);
    
    document.getElementById('stat-in-transit-amount').innerText = this.formatMoney(s.in_transit_amount || 0);
    document.getElementById('stat-cleared-amount').innerText = this.formatMoney(s.cleared_amount || 0);
    document.getElementById('stat-bounced-amount').innerText = this.formatMoney(s.bounced_amount || 0);
  },

  renderCharts() {
    const s = this.state.stats;
    if (!s || !s.credit_colors) return;

    // Credit Color Doughnut Chart
    const ctxColor = document.getElementById('chart-credit-colors');
    if (ctxColor) {
      if (this.state.charts.colorChart) this.state.charts.colorChart.destroy();
      
      const labels = Object.keys(s.credit_colors);
      const data = Object.values(s.credit_colors);
      const colorMap = {
        'سفید': '#10b981',
        'زرد': '#eab308',
        'نارنجی': '#f97316',
        'قهوه ای': '#854d0e',
        'قهوه‌ای': '#854d0e',
        'قرمز': '#ef4444',
        'نامشخص': '#94a3b8'
      };
      const bgColors = labels.map(l => colorMap[l] || '#3b82f6');

      this.state.charts.colorChart = new Chart(ctxColor, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: data,
            backgroundColor: bgColors,
            borderWidth: 2,
            borderColor: 'transparent'
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: {
                font: { family: 'Vazirmatn', size: 12 },
                color: document.documentElement.getAttribute('data-theme') === 'dark' ? '#cbd5e1' : '#475569'
              }
            }
          }
        }
      });
    }
  },

  renderCustomersTable() {
    const container = document.getElementById('customers-table-body');
    if (!container) return;

    if (this.state.customers.length === 0) {
      container.innerHTML = `
        <tr>
          <td colspan="7" class="text-center py-12 text-slate-400">
            <i data-lucide="users" class="w-12 h-12 mx-auto mb-3 opacity-40"></i>
            هیچ مشتری با مشخصات جستجو شده یافت نشد.
          </td>
        </tr>`;
      if (window.lucide) lucide.createIcons();
      return;
    }

    container.innerHTML = this.state.customers.map((c, idx) => `
      <tr class="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
        <td class="py-4 px-4 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
        <td class="py-4 px-4 font-semibold text-slate-100 flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold">
            ${c.full_name.charAt(0)}
          </div>
          <div>
            <div>${c.full_name}</div>
            ${c.original_name_alias ? `<div class="text-xs text-slate-400">نام صندوق: ${c.original_name_alias}</div>` : ''}
          </div>
        </td>
        <td class="py-4 px-4 text-sm font-mono text-slate-300">${c.national_id || '---'}</td>
        <td class="py-4 px-4 text-center">
          ${this.renderCreditBadge(c.credit_color)}
        </td>
        <td class="py-4 px-4 text-center font-mono font-bold text-blue-400">
          ${(c.cheque_count || 0).toLocaleString('fa-IR')} فقره
        </td>
        <td class="py-4 px-4 text-left font-mono font-bold text-emerald-400">
          ${this.formatMoney(c.total_cheque_amount || 0)} <span class="text-xs text-slate-400 font-normal">ریال</span>
        </td>
        <td class="py-4 px-4 text-center">
          <div class="flex items-center justify-center gap-2">
            <button onclick="App.viewCustomerProfile(${c.id})" class="p-2 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded-lg transition" title="مشاهده پروفایل">
              <i data-lucide="eye" class="w-4 h-4"></i>
            </button>
            <button onclick="App.openEditCustomerModal(${c.id})" class="p-2 bg-amber-600/20 hover:bg-amber-600 text-amber-400 hover:text-white rounded-lg transition" title="ویرایش">
              <i data-lucide="edit-3" class="w-4 h-4"></i>
            </button>
            <button onclick="App.deleteCustomer(${c.id})" class="p-2 bg-rose-600/20 hover:bg-rose-600 text-rose-400 hover:text-white rounded-lg transition" title="حذف">
              <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
          </div>
        </td>
      </tr>
    `).join('');

    if (window.lucide) lucide.createIcons();
  },

  renderChequesTable() {
    const container = document.getElementById('cheques-table-body');
    if (!container) return;

    if (this.state.cheques.length === 0) {
      container.innerHTML = `
        <tr>
          <td colspan="8" class="text-center py-12 text-slate-400">
            <i data-lucide="file-text" class="w-12 h-12 mx-auto mb-3 opacity-40"></i>
            هیچ چکی یافت نشد.
          </td>
        </tr>`;
      if (window.lucide) lucide.createIcons();
      return;
    }

    container.innerHTML = this.state.cheques.map((ch, idx) => `
      <tr class="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
        <td class="py-4 px-3 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
        <td class="py-4 px-3 font-mono text-blue-400 font-bold">${ch.sayadi_id}</td>
        <td class="py-4 px-3 font-medium text-slate-200">${ch.customer_name || '---'}</td>
        <td class="py-4 px-3 font-mono text-slate-300">${ch.cheque_number || '---'}</td>
        <td class="py-4 px-3 font-mono font-bold text-emerald-400">${this.formatMoney(ch.amount || 0)}</td>
        <td class="py-4 px-3 font-mono text-sm text-slate-300">${ch.cheque_date || '---'}</td>
        <td class="py-4 px-3 text-sm text-slate-300">${ch.bank_name || '---'}</td>
        <td class="py-4 px-3 text-center">
          <div class="flex items-center justify-center gap-2">
            <button onclick="App.openPasargadModalForCheque('${ch.sayadi_id}', ${ch.customer_id || 'null'})" class="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white text-xs rounded-lg flex items-center gap-1 shadow-sm transition">
              <i data-lucide="shield-check" class="w-3.5 h-3.5"></i>
              استعلام پاسارگاد
            </button>
            <button onclick="App.openEditChequeModal(${ch.id})" class="p-1.5 bg-amber-600/20 hover:bg-amber-600 text-amber-400 hover:text-white rounded-lg transition">
              <i data-lucide="edit" class="w-3.5 h-3.5"></i>
            </button>
            <button onclick="App.deleteCheque(${ch.id})" class="p-1.5 bg-rose-600/20 hover:bg-rose-600 text-rose-400 hover:text-white rounded-lg transition">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </td>
      </tr>
    `).join('');

    if (window.lucide) lucide.createIcons();
  },

  renderCustomerProfileModal(data) {
    const c = data.customer;
    const s = data.summary;
    const cheques = data.cheques;
    const inquiries = data.inquiries;

    const modal = document.getElementById('customer-profile-modal');
    const content = document.getElementById('customer-profile-content');

    content.innerHTML = `
      <div class="p-6 border-b border-slate-700/60 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-4">
          <div class="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white text-2xl font-black shadow-lg">
            ${c.full_name.charAt(0)}
          </div>
          <div>
            <div class="flex items-center gap-3">
              <h2 class="text-2xl font-bold text-slate-100">${c.full_name}</h2>
              ${this.renderCreditBadge(c.credit_color)}
            </div>
            <div class="text-sm text-slate-400 mt-1 flex items-center gap-4">
              <span>کدملی: <strong class="font-mono text-slate-200">${c.national_id || 'ثبت نشده'}</strong></span>
              <span>تلفن: <strong class="font-mono text-slate-200">${c.phone || 'ثبت نشده'}</strong></span>
              ${c.original_name_alias ? `<span>نام در صندوق: <strong class="text-slate-200">${c.original_name_alias}</strong></span>` : ''}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button onclick="App.openAddChequeModal(${c.id})" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-semibold flex items-center gap-2 shadow-lg transition">
            <i data-lucide="plus-circle" class="w-4 h-4"></i>
            ثبت چک جدید برای این مشتری
          </button>
          <button onclick="App.closeCustomerProfile()" class="p-2 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white rounded-xl transition">
            <i data-lucide="x" class="w-5 h-5"></i>
          </button>
        </div>
      </div>

      <!-- Financial Metrics Cards -->
      <div class="p-6 grid grid-cols-1 md:grid-cols-4 gap-4 bg-slate-900/40">
        <div class="glass-card p-4 border border-blue-500/20 bg-blue-500/5">
          <div class="text-xs text-blue-400 font-semibold mb-1">مجموع ارزش چک‌ها</div>
          <div class="text-xl font-bold font-mono text-slate-100">${this.formatMoney(s.total_amount)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
          <div class="text-xs text-slate-400 mt-1">${(s.cheque_count).toLocaleString('fa-IR')} فقره چک</div>
        </div>

        <div class="glass-card p-4 border border-sky-500/20 bg-sky-500/5">
          <div class="text-xs text-sky-400 font-semibold mb-1">چک‌های در راه (پاسارگاد)</div>
          <div class="text-xl font-bold font-mono text-sky-300">${this.formatMoney(s.total_in_transit)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
        </div>

        <div class="glass-card p-4 border border-emerald-500/20 bg-emerald-500/5">
          <div class="text-xs text-emerald-400 font-semibold mb-1">چک‌های رفع سوءاثر شده</div>
          <div class="text-xl font-bold font-mono text-emerald-300">${this.formatMoney(s.total_cleared)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
        </div>

        <div class="glass-card p-4 border border-rose-500/20 bg-rose-500/5">
          <div class="text-xs text-rose-400 font-semibold mb-1">چک‌های برگشتی (پاسارگاد)</div>
          <div class="text-xl font-bold font-mono text-rose-300">${this.formatMoney(s.total_bounced)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
        </div>
      </div>

      <!-- Customer Cheques List -->
      <div class="p-6">
        <h3 class="text-lg font-bold text-slate-200 mb-4 flex items-center gap-2">
          <i data-lucide="file-check" class="w-5 h-5 text-blue-400"></i>
          فهرست چک‌های صیادی این مشتری
        </h3>

        <div class="overflow-x-auto rounded-xl border border-slate-700/60">
          <table class="w-full text-right text-sm">
            <thead class="bg-slate-800/80 text-slate-400 text-xs">
              <tr>
                <th class="py-3 px-4">شناسه صیادی</th>
                <th class="py-3 px-4">شماره سریال</th>
                <th class="py-3 px-4">مبلغ (ریال)</th>
                <th class="py-3 px-4">تاریخ سررسید</th>
                <th class="py-3 px-4">بانک</th>
                <th class="py-3 px-4">دارنده چک (هولدر)</th>
                <th class="py-3 px-4 text-center">وضعیت پاسارگاد</th>
                <th class="py-3 px-4 text-center">عملیات</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              ${cheques.map(ch => `
                <tr class="hover:bg-slate-800/30 transition">
                  <td class="py-3 px-4 font-mono font-bold text-blue-400">${ch.sayadi_id}</td>
                  <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_number || '---'}</td>
                  <td class="py-3 px-4 font-mono font-bold text-emerald-400">${this.formatMoney(ch.amount)}</td>
                  <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_date || '---'}</td>
                  <td class="py-3 px-4 text-slate-300">${ch.bank_name || '---'}</td>
                  <td class="py-3 px-4 text-xs font-semibold text-slate-200">${ch.holder_name || 'انتخاب نشده'}</td>
                  <td class="py-3 px-4 text-center">
                    ${ch.last_bounced > 0 
                      ? `<span class="px-2 py-1 bg-rose-500/20 text-rose-400 rounded-md text-xs font-bold font-mono">برگشتی: ${this.formatMoney(ch.last_bounced)}</span>`
                      : `<span class="px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded-md text-xs font-bold font-mono">فاقد برگشتی</span>`}
                  </td>
                  <td class="py-3 px-4 text-center">
                    <div class="flex items-center justify-center gap-2">
                      <button onclick="App.openPasargadModalForCheque('${ch.sayadi_id}', ${c.id})" class="px-2.5 py-1 bg-sky-600 hover:bg-sky-500 text-white text-xs rounded-lg flex items-center gap-1 transition">
                        <i data-lucide="refresh-cw" class="w-3 h-3"></i>
                        استعلام
                      </button>
                      <button onclick="App.openEditChequeModal(${ch.id})" class="p-1 text-amber-400 hover:bg-slate-700 rounded">
                        <i data-lucide="edit" class="w-3.5 h-3.5"></i>
                      </button>
                      <button onclick="App.deleteCheque(${ch.id})" class="p-1 text-rose-400 hover:bg-slate-700 rounded">
                        <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                      </button>
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    modal.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closeCustomerProfile() {
    document.getElementById('customer-profile-modal').classList.add('hidden');
  },

  renderCreditBadge(color) {
    const c = (color || 'نامشخص').trim();
    if (c === 'سفید') return `<span class="px-2.5 py-1 rounded-full text-xs font-bold badge-credit-white">سفید (خوش‌حساب)</span>`;
    if (c === 'زرد') return `<span class="px-2.5 py-1 rounded-full text-xs font-bold badge-credit-yellow">زرد (کم‌ریسک)</span>`;
    if (c === 'نارنجی') return `<span class="px-2.5 py-1 rounded-full text-xs font-bold badge-credit-orange">نارنجی (ریسک متوسط)</span>`;
    if (c === 'قهوه ای' || c === 'قهوه‌ای') return `<span class="px-2.5 py-1 rounded-full text-xs font-bold badge-credit-brown">قهوه‌ای (ریسک بالا)</span>`;
    if (c === 'قرمز') return `<span class="px-2.5 py-1 rounded-full text-xs font-bold badge-credit-red">قرمز (بدحساب)</span>`;
    return `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-700 text-slate-300">نامشخص</span>`;
  },

  formatMoney(num) {
    if (!num) return '۰';
    return Number(num).toLocaleString('fa-IR');
  },

  populateHolderDropdowns() {
    const optionsHtml = this.state.holders.map(h => `
      <option value="${h.id}">${h.full_name} (${h.national_id}) - ${h.relationship || ''}</option>
    `).join('');

    const holderSelects = document.querySelectorAll('.holder-select-dropdown');
    holderSelects.forEach(s => {
      s.innerHTML = optionsHtml;
    });
  },

  // ─────────────────────────────────────────────────────────────
  // 🏦 Pasargad Bank Live Inquiry Modal & Action
  // ─────────────────────────────────────────────────────────────
  openPasargadModalForCheque(sayadiId, customerId) {
    document.getElementById('pasargad-sayadi-input').value = sayadiId || '';
    document.getElementById('pasargad-customer-id-hidden').value = customerId || '';
    document.getElementById('pasargad-result-card').classList.add('hidden');
    document.getElementById('pasargad-inquiry-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closePasargadModal() {
    document.getElementById('pasargad-inquiry-modal').classList.add('hidden');
  },

  async submitPasargadInquiry() {
    const sayadiId = document.getElementById('pasargad-sayadi-input').value.trim();
    const holderId = parseInt(document.getElementById('pasargad-holder-select').value);
    const customerId = parseInt(document.getElementById('pasargad-customer-id-hidden').value) || null;

    if (!sayadiId || sayadiId.length !== 16) {
      this.showToast('لطفا شناسه صیادی ۱۶ رقمی را به درستی وارد کنید.', 'error');
      return;
    }

    const btn = document.getElementById('btn-submit-pasargad');
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> در حال ارتباط با سرور بانک پاسارگاد...`;
    if (window.lucide) lucide.createIcons();

    try {
      const res = await fetch('/api/inquiries/pasargad', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sayadi_id: sayadiId,
          holder_id: holderId,
          customer_id: customerId
        })
      });

      const result = await res.json();
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      if (window.lucide) lucide.createIcons();

      if (res.ok && result.status === 'success') {
        this.showToast('استعلام با موفقیت از بانک پاسارگاد دریافت شد.', 'success');
        
        // Show result box
        const resultCard = document.getElementById('pasargad-result-card');
        resultCard.classList.remove('hidden');
        
        document.getElementById('res-in-transit').innerText = this.formatMoney(result.in_transit_amount) + ' ریال';
        document.getElementById('res-cleared').innerText = this.formatMoney(result.cleared_amount) + ' ریال';
        document.getElementById('res-bounced').innerText = this.formatMoney(result.bounced_amount) + ' ریال';
        document.getElementById('res-holder-name').innerText = result.holder_name;

        // Reload data
        await this.loadStats();
        if (this.state.selectedCustomer) {
          await this.viewCustomerProfile(this.state.selectedCustomer.customer.id);
        }
      } else {
        this.showToast(result.detail || 'خطا در دریافت استعلام از بانک پاسارگاد', 'error');
      }
    } catch (e) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      this.showToast('خطا در اتصال به سرور', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // ✏️ Customer CRUD Handlers
  // ─────────────────────────────────────────────────────────────
  openAddCustomerModal() {
    document.getElementById('customer-form-id').value = '';
    document.getElementById('customer-form-name').value = '';
    document.getElementById('customer-form-national-id').value = '';
    document.getElementById('customer-form-phone').value = '';
    document.getElementById('customer-form-address').value = '';
    document.getElementById('customer-form-notes').value = '';
    document.getElementById('customer-modal-title').innerText = 'ثبت مشتری جدید';
    document.getElementById('customer-modal').classList.remove('hidden');
  },

  openEditCustomerModal(customerId) {
    const cust = this.state.customers.find(c => c.id === customerId);
    if (!cust) return;

    document.getElementById('customer-form-id').value = cust.id;
    document.getElementById('customer-form-name').value = cust.full_name || '';
    document.getElementById('customer-form-national-id').value = cust.national_id || '';
    document.getElementById('customer-form-phone').value = cust.phone || '';
    document.getElementById('customer-form-address').value = cust.address || '';
    document.getElementById('customer-form-notes').value = cust.notes || '';
    document.getElementById('customer-modal-title').innerText = 'ویرایش اطلاعات مشتری';
    document.getElementById('customer-modal').classList.remove('hidden');
  },

  closeCustomerModal() {
    document.getElementById('customer-modal').classList.add('hidden');
  },

  async saveCustomerForm() {
    const id = document.getElementById('customer-form-id').value;
    const full_name = document.getElementById('customer-form-name').value.trim();
    const national_id = document.getElementById('customer-form-national-id').value.trim();
    const phone = document.getElementById('customer-form-phone').value.trim();
    const address = document.getElementById('customer-form-address').value.trim();
    const notes = document.getElementById('customer-form-notes').value.trim();

    if (!full_name) {
      this.showToast('نام مشتری الزامی است.', 'error');
      return;
    }

    const payload = { full_name, national_id, phone, address, notes };

    try {
      let res;
      if (id) {
        res = await fetch(`/api/customers/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch('/api/customers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (res.ok) {
        this.showToast('اطلاعات مشتری با موفقیت ذخیره شد.', 'success');
        this.closeCustomerModal();
        await this.loadCustomers();
        await this.loadStats();
      } else {
        const err = await res.json();
        this.showToast(err.detail || 'خطا در ذخیره سازی', 'error');
      }
    } catch (e) {
      this.showToast('خطا در اتصال به سرور', 'error');
    }
  },

  async deleteCustomer(customerId) {
    if (!confirm('آیا از حذف این مشتری اطمینان دارید؟ چک‌های متصل به این مشتری بدون انتساب باقی خواهند ماند.')) {
      return;
    }

    try {
      const res = await fetch(`/api/customers/${customerId}`, { method: 'DELETE' });
      if (res.ok) {
        this.showToast('مشتری با موفقیت حذف شد.', 'success');
        await this.loadCustomers();
        await this.loadStats();
        if (this.state.selectedCustomer && this.state.selectedCustomer.customer.id === customerId) {
          this.closeCustomerProfile();
        }
      }
    } catch (e) {
      this.showToast('خطا در حذف مشتری', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 📑 Cheque CRUD Handlers
  // ─────────────────────────────────────────────────────────────
  openAddChequeModal(customerId = null) {
    document.getElementById('cheque-form-id').value = '';
    document.getElementById('cheque-form-sayadi').value = '';
    document.getElementById('cheque-form-number').value = '';
    document.getElementById('cheque-form-amount').value = '';
    document.getElementById('cheque-form-date').value = '';
    document.getElementById('cheque-form-bank').value = '';
    document.getElementById('cheque-form-notes').value = '';

    // Populate customer dropdown
    const custSelect = document.getElementById('cheque-form-customer-select');
    custSelect.innerHTML = this.state.customers.map(c => `
      <option value="${c.id}" ${customerId && c.id === customerId ? 'selected' : ''}>${c.full_name}</option>
    `).join('');

    document.getElementById('cheque-modal-title').innerText = 'ثبت چک صیادی جدید';
    document.getElementById('cheque-modal').classList.remove('hidden');
  },

  openEditChequeModal(chequeId) {
    const ch = this.state.cheques.find(c => c.id === chequeId);
    if (!ch) return;

    document.getElementById('cheque-form-id').value = ch.id;
    document.getElementById('cheque-form-sayadi').value = ch.sayadi_id || '';
    document.getElementById('cheque-form-number').value = ch.cheque_number || '';
    document.getElementById('cheque-form-amount').value = ch.amount || '';
    document.getElementById('cheque-form-date').value = ch.cheque_date || '';
    document.getElementById('cheque-form-bank').value = ch.bank_name || '';
    document.getElementById('cheque-form-notes').value = ch.notes || '';

    const custSelect = document.getElementById('cheque-form-customer-select');
    custSelect.innerHTML = this.state.customers.map(c => `
      <option value="${c.id}" ${c.id === ch.customer_id ? 'selected' : ''}>${c.full_name}</option>
    `).join('');

    document.getElementById('cheque-modal-title').innerText = 'ویرایش چک صیادی';
    document.getElementById('cheque-modal').classList.remove('hidden');
  },

  closeChequeModal() {
    document.getElementById('cheque-modal').classList.add('hidden');
  },

  async saveChequeForm() {
    const id = document.getElementById('cheque-form-id').value;
    const customer_id = parseInt(document.getElementById('cheque-form-customer-select').value);
    const sayadi_id = document.getElementById('cheque-form-sayadi').value.trim();
    const cheque_number = document.getElementById('cheque-form-number').value.trim();
    const amount = parseFloat(document.getElementById('cheque-form-amount').value) || 0;
    const cheque_date = document.getElementById('cheque-form-date').value.trim();
    const bank_name = document.getElementById('cheque-form-bank').value.trim();
    const holder_id = parseInt(document.getElementById('cheque-form-holder-select').value) || null;
    const notes = document.getElementById('cheque-form-notes').value.trim();

    if (!sayadi_id || sayadi_id.length !== 16) {
      this.showToast('شناسه صیادی باید دقیقاً ۱۶ رقم باشد.', 'error');
      return;
    }

    const payload = { customer_id, sayadi_id, cheque_number, amount, cheque_date, bank_name, holder_id, notes };

    try {
      let res;
      if (id) {
        res = await fetch(`/api/cheques/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch('/api/cheques', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
      }

      if (res.ok) {
        this.showToast('اطلاعات چک با موفقیت ذخیره گردید.', 'success');
        this.closeChequeModal();
        await this.loadCheques();
        await this.loadStats();
        if (this.state.selectedCustomer) {
          await this.viewCustomerProfile(this.state.selectedCustomer.customer.id);
        }
      } else {
        const err = await res.json();
        this.showToast(err.detail || 'خطا در ذخیره‌سازی چک', 'error');
      }
    } catch (e) {
      this.showToast('خطا در اتصال به سرور', 'error');
    }
  },

  async deleteCheque(chequeId) {
    if (!confirm('آیا از حذف این چک اطمینان دارید؟')) return;

    try {
      const res = await fetch(`/api/cheques/${chequeId}`, { method: 'DELETE' });
      if (res.ok) {
        this.showToast('چک با موفقیت حذف گردید.', 'success');
        await this.loadCheques();
        await this.loadStats();
        if (this.state.selectedCustomer) {
          await this.viewCustomerProfile(this.state.selectedCustomer.customer.id);
        }
      }
    } catch (e) {
      this.showToast('خطا در حذف چک', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // ⏰ Daily Scheduler Handlers
  // ─────────────────────────────────────────────────────────────
  async loadSchedulerStatus() {
    try {
      const res = await fetch('/api/scheduler/status');
      const data = await res.json();
      
      document.getElementById('sched-status-badge').innerText = data.current_status === 'running' ? 'در حال اجرا' : 'فعال و آماده';
      document.getElementById('sched-last-run').innerText = data.last_run || 'هنوز اجرا نشده است';
      
      const logContainer = document.getElementById('scheduler-logs-body');
      if (logContainer) {
        logContainer.innerHTML = (data.recent_logs || []).map(l => `
          <tr class="border-b border-slate-700/40 hover:bg-slate-800/30">
            <td class="py-3 px-4 font-mono text-xs text-slate-400">${l.run_time}</td>
            <td class="py-3 px-4 font-semibold text-slate-200">${l.task_name}</td>
            <td class="py-3 px-4">
              <span class="px-2 py-0.5 rounded text-xs font-bold ${l.status === 'success' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}">
                ${l.status === 'success' ? 'موفق' : l.status}
              </span>
            </td>
            <td class="py-3 px-4 text-xs text-slate-300 font-mono">${l.details}</td>
          </tr>
        `).join('');
      }
    } catch (e) {
      console.error('Error loading scheduler status:', e);
    }
  },

  async triggerSchedulerNow() {
    if (!confirm('آیا می‌خواهید استعلام دسته‌ای تمام چک‌ها از بانک پاسارگاد همین الان در پس‌زمینه آغاز شود؟')) {
      return;
    }

    try {
      const res = await fetch('/api/scheduler/run-now', { method: 'POST' });
      const data = await res.json();
      this.showToast(data.message || 'عملیات آغاز شد', 'success');
      await this.loadSchedulerStatus();
    } catch (e) {
      this.showToast('خطا در اجرای زمان‌بند', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 🔔 Toast Notifications
  // ─────────────────────────────────────────────────────────────
  showToast(message, type = 'info') {
    const toast = document.createElement('div');
    const bg = type === 'success' ? 'bg-emerald-600' : (type === 'error' ? 'bg-rose-600' : 'bg-blue-600');
    toast.className = `fixed bottom-6 left-6 z-50 px-5 py-3.5 rounded-2xl text-white font-medium shadow-2xl flex items-center gap-3 animate-fade-in ${bg}`;
    toast.innerHTML = `
      <i data-lucide="${type === 'success' ? 'check-circle' : (type === 'error' ? 'alert-circle' : 'info')}" class="w-5 h-5"></i>
      <span>${message}</span>
    `;
    document.body.appendChild(toast);
    if (window.lucide) lucide.createIcons();

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  },

  setupEventListeners() {
    // Search bar live listener
    const searchInput = document.getElementById('global-search-input');
    if (searchInput) {
      let debounceTimer;
      searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          this.state.searchQuery = e.target.value;
          this.loadCustomers();
          this.loadCheques();
        }, 300);
      });
    }

    // Color filter listener
    const colorSelect = document.getElementById('credit-color-filter');
    if (colorSelect) {
      colorSelect.addEventListener('change', (e) => {
        this.state.colorFilter = e.target.value;
        this.loadCustomers();
      });
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
