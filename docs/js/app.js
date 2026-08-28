/**
 * Client-Side Application Controller for GitHub Pages
 * Runs 100% in the browser with LocalStorage persistence and SheetJS Excel export.
 */
const App = {
  STORAGE_KEY: 'sayad_app_local_data_v2',
  state: {
    currentTab: 'dashboard',
    holders: [],
    customers: [],
    cheques: [],
    inquiries: [],
    searchQuery: '',
    colorFilter: 'all',
    selectedCustomer: null,
    charts: {}
  },

  async init() {
    await this.loadData();
    this.populateHolderDropdowns();
    this.setupEventListeners();
    this.renderCurrentView();
    if (window.lucide) lucide.createIcons();
  },

  // ─────────────────────────────────────────────────────────────
  // 💾 Data Storage & Persistence
  // ─────────────────────────────────────────────────────────────
  async loadData() {
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        this.state.holders = parsed.holders || [];
        this.state.customers = parsed.customers || [];
        this.state.cheques = parsed.cheques || [];
        this.state.inquiries = parsed.inquiries || [];
        return;
      } catch (e) {
        console.error('Error reading localStorage:', e);
      }
    }

    // Fallback: Fetch initial dataset bundled with repo
    try {
      const res = await fetch('data/initial_dataset.json');
      const data = await res.json();
      this.state.holders = data.holders || [];
      this.state.customers = data.customers || [];
      this.state.cheques = data.cheques || [];
      this.state.inquiries = data.inquiries || [];
      this.saveData();
    } catch (e) {
      console.error('Error fetching initial dataset:', e);
    }
  },

  saveData() {
    const payload = {
      holders: this.state.holders,
      customers: this.state.customers,
      cheques: this.state.cheques,
      inquiries: this.state.inquiries
    };
    localStorage.setItem(this.STORAGE_KEY, JSON.stringify(payload));
  },

  resetToDefaultData() {
    if (!confirm('آیا می‌خواهید تمام داده‌ها به حالت اولیه (فایل اکسل اولیه) بازگردند؟ تمام تغییرات محلی ریست خواهد شد.')) {
      return;
    }
    localStorage.removeItem(this.STORAGE_KEY);
    window.location.reload();
  },

  backupDataJSON() {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(localStorage.getItem(this.STORAGE_KEY));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `sayad_backup_${new Date().toISOString().slice(0,10)}.json`);
    dlAnchorElem.click();
    this.showToast('فایل پشتیبان داده‌ها با موفقیت دانلود شد.', 'success');
  },

  restoreDataJSON(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const parsed = JSON.parse(e.target.result);
        if (parsed.customers && parsed.cheques) {
          localStorage.setItem(this.STORAGE_KEY, JSON.stringify(parsed));
          this.showToast('داده‌ها با موفقیت بازیابی شدند.', 'success');
          setTimeout(() => window.location.reload(), 1000);
        } else {
          this.showToast('ساختار فایل پشتیبان نامعتبر است.', 'error');
        }
      } catch (err) {
        this.showToast('خطا در خواندن فایل JSON', 'error');
      }
    };
    reader.readAsText(file);
  },

  // ─────────────────────────────────────────────────────────────
  // 📊 Live Statistics Calculation
  // ─────────────────────────────────────────────────────────────
  getStats() {
    const totalCustomers = this.state.customers.length;
    const totalCheques = this.state.cheques.length;
    const totalAmount = this.state.cheques.reduce((sum, ch) => sum + (parseFloat(ch.amount) || 0), 0);

    const inTransitSum = this.state.inquiries.reduce((sum, i) => sum + (parseFloat(i.in_transit_amount) || 0), 0);
    const clearedSum = this.state.inquiries.reduce((sum, i) => sum + (parseFloat(i.cleared_amount) || 0), 0);
    const bouncedSum = this.state.inquiries.reduce((sum, i) => sum + (parseFloat(i.bounced_amount) || 0), 0);

    // Credit Color counts
    const colors = {};
    this.state.customers.forEach(c => {
      const col = c.credit_color || 'نامشخص';
      colors[col] = (colors[col] || 0) + 1;
    });

    return {
      totalCustomers,
      totalCheques,
      totalAmount,
      inTransitSum,
      clearedSum,
      bouncedSum,
      creditColors: colors
    };
  },

  // ─────────────────────────────────────────────────────────────
  // 🎨 Views & Navigation
  // ─────────────────────────────────────────────────────────────
  switchTab(tabName) {
    this.state.currentTab = tabName;

    document.querySelectorAll('.nav-link').forEach(btn => {
      if (btn.dataset.tab === tabName) {
        btn.classList.add('bg-blue-600', 'text-white', 'shadow-md');
        btn.classList.remove('text-slate-400', 'hover:bg-slate-800');
      } else {
        btn.classList.remove('bg-blue-600', 'text-white', 'shadow-md');
        btn.classList.add('text-slate-400', 'hover:bg-slate-800');
      }
    });

    document.querySelectorAll('.tab-view').forEach(view => {
      view.classList.toggle('hidden', view.id !== `view-${tabName}`);
    });

    this.renderCurrentView();
    if (window.lucide) lucide.createIcons();
  },

  renderCurrentView() {
    if (this.state.currentTab === 'dashboard') {
      this.renderDashboard();
    } else if (this.state.currentTab === 'customers') {
      this.renderCustomersTable();
    } else if (this.state.currentTab === 'cheques') {
      this.renderChequesTable();
    }
  },

  renderDashboard() {
    const s = this.getStats();
    document.getElementById('stat-total-customers').innerText = s.totalCustomers.toLocaleString('fa-IR');
    document.getElementById('stat-total-cheques').innerText = s.totalCheques.toLocaleString('fa-IR');
    document.getElementById('stat-total-amount').innerText = this.formatMoney(s.totalAmount);
    
    document.getElementById('stat-in-transit-amount').innerText = this.formatMoney(s.inTransitSum);
    document.getElementById('stat-cleared-amount').innerText = this.formatMoney(s.clearedSum);
    document.getElementById('stat-bounced-amount').innerText = this.formatMoney(s.bouncedSum);

    this.renderColorChart(s.creditColors);
  },

  renderColorChart(colorCounts) {
    const ctx = document.getElementById('chart-credit-colors');
    if (!ctx) return;

    if (this.state.charts.colorChart) {
      this.state.charts.colorChart.destroy();
    }

    const labels = Object.keys(colorCounts);
    const data = Object.values(colorCounts);
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

    this.state.charts.colorChart = new Chart(ctx, {
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
  },

  // ─────────────────────────────────────────────────────────────
  // 👥 Customers Directory Table
  // ─────────────────────────────────────────────────────────────
  renderCustomersTable() {
    const container = document.getElementById('customers-table-body');
    if (!container) return;

    let list = [...this.state.customers];

    // Search filter
    if (this.state.searchQuery.trim()) {
      const q = this.state.searchQuery.trim().toLowerCase();
      list = list.filter(c => 
        (c.full_name && c.full_name.toLowerCase().includes(q)) ||
        (c.national_id && c.national_id.includes(q)) ||
        (c.phone && c.phone.includes(q)) ||
        (c.original_name_alias && c.original_name_alias.toLowerCase().includes(q))
      );
    }

    // Color filter
    if (this.state.colorFilter !== 'all') {
      list = list.filter(c => (c.credit_color || '').trim() === this.state.colorFilter);
    }

    // Sort by total cheque amount
    list.sort((a, b) => {
      const sumA = this.getCustomerChequesSum(a.id);
      const sumB = this.getCustomerChequesSum(b.id);
      return sumB - sumA;
    });

    if (list.length === 0) {
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

    container.innerHTML = list.map((c, idx) => {
      const cheques = this.getCustomerCheques(c.id);
      const totalSum = cheques.reduce((s, ch) => s + (parseFloat(ch.amount) || 0), 0);

      return `
        <tr class="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
          <td class="py-4 px-4 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
          <td class="py-4 px-4 font-semibold text-slate-100 flex items-center gap-3">
            <div class="w-10 h-10 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold">
              ${c.full_name.charAt(0)}
            </div>
            <div>
              <div>${c.full_name}</div>
              ${c.original_name_alias ? `<div class="text-xs text-slate-400">صندوق: ${c.original_name_alias}</div>` : ''}
            </div>
          </td>
          <td class="py-4 px-4 text-sm font-mono text-slate-300">${c.national_id || '---'}</td>
          <td class="py-4 px-4 text-center">
            ${this.renderCreditBadge(c.credit_color)}
          </td>
          <td class="py-4 px-4 text-center font-mono font-bold text-blue-400">
            ${(cheques.length).toLocaleString('fa-IR')} فقره
          </td>
          <td class="py-4 px-4 text-left font-mono font-bold text-emerald-400">
            ${this.formatMoney(totalSum)} <span class="text-xs text-slate-400 font-normal">ریال</span>
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
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  },

  // ─────────────────────────────────────────────────────────────
  // 📑 Cheques Directory Table
  // ─────────────────────────────────────────────────────────────
  renderChequesTable() {
    const container = document.getElementById('cheques-table-body');
    if (!container) return;

    let list = [...this.state.cheques];

    if (this.state.searchQuery.trim()) {
      const q = this.state.searchQuery.trim().toLowerCase();
      list = list.filter(ch => {
        const cust = this.state.customers.find(c => c.id === ch.customer_id);
        const custName = cust ? cust.full_name.toLowerCase() : '';
        return (
          (ch.sayadi_id && ch.sayadi_id.includes(q)) ||
          (ch.cheque_number && ch.cheque_number.includes(q)) ||
          (ch.bank_name && ch.bank_name.toLowerCase().includes(q)) ||
          custName.includes(q)
        );
      });
    }

    if (list.length === 0) {
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

    container.innerHTML = list.map((ch, idx) => {
      const cust = this.state.customers.find(c => c.id === ch.customer_id);
      return `
        <tr class="border-b border-slate-700/40 hover:bg-slate-800/40 transition">
          <td class="py-4 px-3 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
          <td class="py-4 px-3 font-mono text-blue-400 font-bold">${ch.sayadi_id}</td>
          <td class="py-4 px-3 font-medium text-slate-200">${cust ? cust.full_name : 'نامشخص'}</td>
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
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  },

  // ─────────────────────────────────────────────────────────────
  // 🪟 Customer Profile Modal
  // ─────────────────────────────────────────────────────────────
  viewCustomerProfile(customerId) {
    const c = this.state.customers.find(cust => cust.id === customerId);
    if (!c) return;

    const cheques = this.getCustomerCheques(customerId);
    const totalAmount = cheques.reduce((s, ch) => s + (parseFloat(ch.amount) || 0), 0);

    const inquiries = this.state.inquiries.filter(i => i.customer_id === customerId || cheques.some(ch => ch.sayadi_id === i.sayadi_id));
    const inTransitSum = inquiries.reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
    const clearedSum = inquiries.reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
    const bouncedSum = inquiries.reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);

    this.state.selectedCustomer = c;
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
          <div class="text-xl font-bold font-mono text-slate-100">${this.formatMoney(totalAmount)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
          <div class="text-xs text-slate-400 mt-1">${(cheques.length).toLocaleString('fa-IR')} فقره چک</div>
        </div>

        <div class="glass-card p-4 border border-sky-500/20 bg-sky-500/5">
          <div class="text-xs text-sky-400 font-semibold mb-1">چک‌های در راه (پاسارگاد)</div>
          <div class="text-xl font-bold font-mono text-sky-300">${this.formatMoney(inTransitSum)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
        </div>

        <div class="glass-card p-4 border border-emerald-500/20 bg-emerald-500/5">
          <div class="text-xs text-emerald-400 font-semibold mb-1">چک‌های رفع سوءاثر شده</div>
          <div class="text-xl font-bold font-mono text-emerald-300">${this.formatMoney(clearedSum)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
        </div>

        <div class="glass-card p-4 border border-rose-500/20 bg-rose-500/5">
          <div class="text-xs text-rose-400 font-semibold mb-1">چک‌های برگشتی (پاسارگاد)</div>
          <div class="text-xl font-bold font-mono text-rose-300">${this.formatMoney(bouncedSum)} <span class="text-xs font-normal text-slate-400">ریال</span></div>
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
              ${cheques.map(ch => {
                const holder = this.state.holders.find(h => h.id === ch.holder_id);
                const inq = this.state.inquiries.find(i => i.sayadi_id === ch.sayadi_id);
                const hasBounced = inq && inq.bounced_amount > 0;

                return `
                  <tr class="hover:bg-slate-800/30 transition">
                    <td class="py-3 px-4 font-mono font-bold text-blue-400">${ch.sayadi_id}</td>
                    <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_number || '---'}</td>
                    <td class="py-3 px-4 font-mono font-bold text-emerald-400">${this.formatMoney(ch.amount)}</td>
                    <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_date || '---'}</td>
                    <td class="py-3 px-4 text-slate-300">${ch.bank_name || '---'}</td>
                    <td class="py-3 px-4 text-xs font-semibold text-slate-200">${holder ? holder.full_name : 'انتخاب نشده'}</td>
                    <td class="py-3 px-4 text-center">
                      ${hasBounced 
                        ? `<span class="px-2 py-1 bg-rose-500/20 text-rose-400 rounded-md text-xs font-bold font-mono">برگشتی: ${this.formatMoney(inq.bounced_amount)}</span>`
                        : (inq ? `<span class="px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded-md text-xs font-bold font-mono">فاقد برگشتی</span>` : `<span class="text-xs text-slate-500">استعلام نشده</span>`)}
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
                `;
              }).join('')}
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

  // ─────────────────────────────────────────────────────────────
  // 🏦 Live Pasargad Inquiry Action
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
      this.showToast('لطفاً شناسه صیادی ۱۶ رقمی را به درستی وارد کنید.', 'error');
      return;
    }

    const holder = this.state.holders.find(h => h.id === holderId) || this.state.holders[0];
    const btn = document.getElementById('btn-submit-pasargad');
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> در حال ارتباط با سرور بانک پاسارگاد...`;
    if (window.lucide) lucide.createIcons();

    const targetUrl = `https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus?IdCode=${holder.national_id}&IdType=1&SayadId=${sayadiId}`;

    try {
      // Try direct call or CORS proxy fallback
      let data = null;
      try {
        const directResp = await fetch(targetUrl, {
          headers: { 'Accept': 'application/json, text/plain, */*' }
        });
        if (directResp.ok) {
          data = await directResp.json();
        }
      } catch (corsErr) {
        // CORS fallback via public proxy
        const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(targetUrl)}`;
        const proxyResp = await fetch(proxyUrl);
        const proxyJson = await proxyResp.json();
        data = JSON.parse(proxyJson.contents);
      }

      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      if (window.lucide) lucide.createIcons();

      if (data) {
        const onGoing = parseFloat(data.onGoingAmount || 0);
        const owners = data.ownersInfo || [];
        let totalBounced = 0;
        let totalCleared = 0;
        let bouncedCount = 0;
        let clearedCount = 0;

        owners.forEach(o => {
          const b = parseFloat(o.bouncedAmount || 0);
          const c = parseFloat(o.clearedAmount || 0);
          totalBounced += b;
          totalCleared += c;
          if (b > 0) bouncedCount++;
          if (c > 0) clearedCount++;
        });

        // Record inquiry in local state
        const inquiryRecord = {
          id: Date.now(),
          sayadi_id: sayadiId,
          holder_id: holder.id,
          customer_id: customerId,
          in_transit_amount: onGoing,
          in_transit_count: onGoing > 0 ? 1 : 0,
          cleared_amount: totalCleared,
          cleared_count: clearedCount,
          bounced_amount: totalBounced,
          bounced_count: bouncedCount,
          inquiry_time: new Date().toISOString().replace('T', ' ').slice(0, 19),
          status: 'success'
        };

        // Update existing or push
        const existingIdx = this.state.inquiries.findIndex(i => i.sayadi_id === sayadiId);
        if (existingIdx >= 0) {
          this.state.inquiries[existingIdx] = inquiryRecord;
        } else {
          this.state.inquiries.push(inquiryRecord);
        }

        // Update cheque holder
        const ch = this.state.cheques.find(c => c.sayadi_id === sayadiId);
        if (ch) ch.holder_id = holder.id;

        this.saveData();

        // Show result box
        const resultCard = document.getElementById('pasargad-result-card');
        resultCard.classList.remove('hidden');
        document.getElementById('res-holder-name').innerText = holder.full_name;
        document.getElementById('res-in-transit').innerText = this.formatMoney(onGoing) + ' ریال';
        document.getElementById('res-cleared').innerText = this.formatMoney(totalCleared) + ' ریال';
        document.getElementById('res-bounced').innerText = this.formatMoney(totalBounced) + ' ریال';

        this.showToast('استعلام با موفقیت از بانک پاسارگاد دریافت شد.', 'success');
        this.renderCurrentView();

        if (this.state.selectedCustomer) {
          this.viewCustomerProfile(this.state.selectedCustomer.id);
        }
      } else {
        this.showToast('پاسخی از سرور بانک پاسارگاد دریافت نشد.', 'error');
      }
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      this.showToast('خطا در اتصال به سامانه پاسارگاد', 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // ✏️ Customer CRUD Actions
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

  saveCustomerForm() {
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

    if (id) {
      // Edit
      const cust = this.state.customers.find(c => c.id === parseInt(id));
      if (cust) {
        cust.full_name = full_name;
        cust.national_id = national_id;
        cust.phone = phone;
        cust.address = address;
        cust.notes = notes;
      }
    } else {
      // Create
      const newId = Date.now();
      this.state.customers.push({
        id: newId,
        full_name,
        national_id,
        phone,
        address,
        notes,
        credit_color: 'نامشخص',
        risk_score: 0,
        created_at: new Date().toISOString().slice(0, 10)
      });
    }

    this.saveData();
    this.closeCustomerModal();
    this.showToast('اطلاعات مشتری با موفقیت ذخیره شد.', 'success');
    this.renderCurrentView();
  },

  deleteCustomer(customerId) {
    if (!confirm('آیا از حذف این مشتری اطمینان دارید؟')) return;
    this.state.customers = this.state.customers.filter(c => c.id !== customerId);
    this.saveData();
    this.showToast('مشتری با موفقیت حذف شد.', 'success');
    this.renderCurrentView();
    if (this.state.selectedCustomer && this.state.selectedCustomer.id === customerId) {
      this.closeCustomerProfile();
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 📑 Cheque CRUD Actions
  // ─────────────────────────────────────────────────────────────
  openAddChequeModal(customerId = null) {
    document.getElementById('cheque-form-id').value = '';
    document.getElementById('cheque-form-sayadi').value = '';
    document.getElementById('cheque-form-number').value = '';
    document.getElementById('cheque-form-amount').value = '';
    document.getElementById('cheque-form-date').value = '';
    document.getElementById('cheque-form-bank').value = '';
    document.getElementById('cheque-form-notes').value = '';

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

  saveChequeForm() {
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

    if (id) {
      const ch = this.state.cheques.find(c => c.id === parseInt(id));
      if (ch) {
        ch.customer_id = customer_id;
        ch.sayadi_id = sayadi_id;
        ch.cheque_number = cheque_number;
        ch.amount = amount;
        ch.cheque_date = cheque_date;
        ch.bank_name = bank_name;
        ch.holder_id = holder_id;
        ch.notes = notes;
      }
    } else {
      this.state.cheques.push({
        id: Date.now(),
        customer_id,
        sayadi_id,
        cheque_number,
        amount,
        cheque_date,
        bank_name,
        holder_id,
        status: 'pending',
        notes
      });
    }

    this.saveData();
    this.closeChequeModal();
    this.showToast('اطلاعات چک با موفقیت ذخیره گردید.', 'success');
    this.renderCurrentView();

    if (this.state.selectedCustomer) {
      this.viewCustomerProfile(this.state.selectedCustomer.id);
    }
  },

  deleteCheque(chequeId) {
    if (!confirm('آیا از حذف این چک اطمینان دارید؟')) return;
    this.state.cheques = this.state.cheques.filter(c => c.id !== chequeId);
    this.saveData();
    this.showToast('چک با موفقیت حذف گردید.', 'success');
    this.renderCurrentView();
    if (this.state.selectedCustomer) {
      this.viewCustomerProfile(this.state.selectedCustomer.id);
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 📊 Client-Side Excel Export (SheetJS)
  // ─────────────────────────────────────────────────────────────
  exportToExcel() {
    if (!window.XLSX) {
      this.showToast('کتابخانه اکسل در دسترس نیست.', 'error');
      return;
    }

    const rows = this.state.cheques.map((ch, idx) => {
      const cust = this.state.customers.find(c => c.id === ch.customer_id) || {};
      const holder = this.state.holders.find(h => h.id === ch.holder_id) || {};
      const inq = this.state.inquiries.find(i => i.sayadi_id === ch.sayadi_id) || {};

      return {
        'ردیف': idx + 1,
        'نام مشتری': cust.full_name || '---',
        'کد ملی مشتری': cust.national_id || '---',
        'وضعیت اعتباری بانک مرکزی': cust.credit_color || 'نامشخص',
        'شناسه صیادی': ch.sayadi_id,
        'شماره سریال چک': ch.cheque_number || '---',
        'مبلغ چک (ریال)': ch.amount || 0,
        'تاریخ سررسید': ch.cheque_date || '---',
        'بانک صادرکننده': ch.bank_name || '---',
        'دارنده چک (هولدر)': holder.full_name || '---',
        'مبلغ در راه پاسارگاد (ریال)': inq.in_transit_amount || 0,
        'مبلغ رفع سوءاثر پاسارگاد (ریال)': inq.cleared_amount || 0,
        'مبلغ برگشتی پاسارگاد (ریال)': inq.bounced_amount || 0
      };
    });

    const worksheet = XLSX.utils.json_to_sheet(rows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'گزارش مشتریان و چک‌ها');

    XLSX.writeFile(workbook, `sayad_customers_report_${new Date().toISOString().slice(0, 10)}.xlsx`);
    this.showToast('فایل اکسل با موفقیت تولید و دانلود شد.', 'success');
  },

  // ─────────────────────────────────────────────────────────────
  // 🛠 Helper Functions
  // ─────────────────────────────────────────────────────────────
  getCustomerCheques(customerId) {
    return this.state.cheques.filter(ch => ch.customer_id === customerId);
  },

  getCustomerChequesSum(customerId) {
    return this.getCustomerCheques(customerId).reduce((sum, ch) => sum + (parseFloat(ch.amount) || 0), 0);
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

    document.querySelectorAll('.holder-select-dropdown').forEach(s => {
      s.innerHTML = optionsHtml;
    });
  },

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
    const searchInput = document.getElementById('global-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        this.state.searchQuery = e.target.value;
        this.renderCurrentView();
      });
    }

    const colorSelect = document.getElementById('credit-color-filter');
    if (colorSelect) {
      colorSelect.addEventListener('change', (e) => {
        this.state.colorFilter = e.target.value;
        this.renderCustomersTable();
      });
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
