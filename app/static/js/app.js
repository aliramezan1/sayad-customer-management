/**
 * Sayad Pro Web Application Controller
 * Handles Data Persistence, View Navigation, Drilldowns, Holders CRUD, Batch Inquiry & Log Console.
 */
const App = {
  STORAGE_KEY: 'sayad_app_local_data_v4',
  state: {
    currentTab: 'dashboard',
    chequeFilterMode: 'all', // 'all', 'in-transit', 'cleared', 'bounced', 'sorted-amount'
    holders: [],
    customers: [],
    cheques: [],
    inquiries: [],
    searchQuery: '',
    colorFilter: 'all',
    selectedCustomer: null,
    charts: {},
    logFilter: 'ALL'
  },

  async init() {
    window.AppLogger.info('SYSTEM', 'در حال راه‌اندازی سامانه صیاد پرو وب...');
    await this.loadData();
    this.populateHolderDropdowns();
    this.renderHoldersList();
    this.setupEventListeners();
    this.initSchedulerUI();
    this.renderCurrentView();
    
    // Listen to logs to update log badges
    window.AppLogger.addListener(() => {
      this.updateLogBadge();
      if (!document.getElementById('logs-modal').classList.contains('hidden')) {
        this.renderLogsList();
      }
    });

    if (window.lucide) lucide.createIcons();
    window.AppLogger.success('SYSTEM', `سامانه با ${this.state.customers.length} مشتری و ${this.state.cheques.length} فقره چک با موفقیت بارگذاری شد.`);
  },

  // ─────────────────────────────────────────────────────────────
  // 💾 Data Storage & Persistence
  // ─────────────────────────────────────────────────────────────
  async loadData() {
    // 1. Try to fetch live data from FastAPI backend if connected
    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 1500);

      const statsRes = await fetch(`${backendUrl}/api/stats`, { signal: controller.signal });
      clearTimeout(timeout);

      if (statsRes.ok) {
        const [custRes, chRes, holdRes, inqRes] = await Promise.all([
          fetch(`${backendUrl}/api/customers?limit=1000`),
          fetch(`${backendUrl}/api/cheques?limit=1000`),
          fetch(`${backendUrl}/api/holders`),
          fetch(`${backendUrl}/api/inquiries?limit=3000`).catch(() => null)
        ]);

        if (custRes.ok && chRes.ok && holdRes.ok) {
          const custData = await custRes.json();
          const chData = await chRes.json();
          const holdData = await holdRes.json();

          if (custData.customers && custData.customers.length > 0) {
            this.state.customers = custData.customers;
            this.state.cheques = chData.cheques || [];
            this.state.holders = holdData.holders || [];

            if (inqRes && inqRes.ok) {
              const inqData = await inqRes.json();
              this.state.inquiries = inqData.inquiries || [];
            }

            // Fallback for inquiries if empty from endpoint
            if (!this.state.inquiries || this.state.inquiries.length === 0) {
              try {
                const initRes = await fetch('data/initial_dataset.json');
                if (initRes.ok) {
                  const initData = await initRes.json();
                  this.state.inquiries = initData.inquiries || [];
                }
              } catch (e) {}
            }

            this.saveData();
            window.AppLogger.success('SYSTEM', `داده‌های زنده از پایگاه داده متصل سرور (${this.state.customers.length} مشتری، ${this.state.cheques.length} چک، ${this.state.inquiries.length} استعلام) بارگذاری شد.`);
            return;
          }
        }
      }
    } catch (e) {
      // Backend offline or unreachable
    }

    // 2. Check localStorage (v4)
    const saved = localStorage.getItem(this.STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed.customers && parsed.customers.length >= 20 && parsed.cheques && parsed.cheques.length >= 50 && parsed.inquiries && parsed.inquiries.length >= 50) {
          this.state.holders = parsed.holders || [];
          this.state.customers = parsed.customers || [];
          this.state.cheques = parsed.cheques || [];
          this.state.inquiries = parsed.inquiries || [];
          window.AppLogger.info('SYSTEM', 'داده‌های جامع از حافظه محلی مرورگر بازیابی شد.');
          return;
        }
      } catch (e) {
        window.AppLogger.error('SYSTEM', 'خطا در بارگذاری داده‌های ذخیره‌شده محلی', e);
      }
    }

    // 3. Fallback: Fetch bundled rich initial dataset
    try {
      const res = await fetch('data/initial_dataset.json');
      if (res.ok) {
        const data = await res.json();
        this.state.holders = data.holders || [];
        this.state.customers = data.customers || [];
        this.state.cheques = data.cheques || [];
        this.state.inquiries = data.inquiries || [];
        this.saveData();
        window.AppLogger.success('SYSTEM', `دیتاست جامع با ${this.state.customers.length} مشتری، ${this.state.cheques.length} چک و ${this.state.inquiries.length} سابقه استعلام بارگذاری شد.`);
      }
    } catch (e) {
      window.AppLogger.error('SYSTEM', 'خطا در واکشی دیتاست اولیه', e);
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

  async syncData() {
    window.AppLogger.info('SYSTEM', 'در حال همگام‌سازی و بارگذاری مجدد کامل پایگاه داده...');
    localStorage.removeItem(this.STORAGE_KEY);
    localStorage.removeItem('sayad_app_local_data_v3');
    localStorage.removeItem('sayad_app_local_data_v2');
    localStorage.removeItem('sayad_app_local_data_v1');
    localStorage.removeItem('sayad_app_local_data');
    await this.loadData();
    this.populateHolderDropdowns();
    this.renderHoldersList();
    this.renderCurrentView();
    this.showToast('پایگاه داده و دیتاست با موفقیت همگام‌سازی و بارگذاری مجدد شد.', 'success');
  },

  resetToDefaultData() {
    if (!confirm('آیا می‌خواهید تمام داده‌ها به حالت اولیه (فایل اکسل اولیه) بازگردند؟ تمام تغییرات محلی ریست خواهد شد.')) {
      return;
    }
    localStorage.removeItem(this.STORAGE_KEY);
    localStorage.removeItem('sayad_app_local_data_v3');
    window.AppLogger.warn('SYSTEM', 'پایگاه داده به مقادیر اولیه کارخانه بازگردانی شد.');
    window.location.reload();
  },

  backupDataJSON() {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(localStorage.getItem(this.STORAGE_KEY));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `sayad_backup_${new Date().toISOString().slice(0,10)}.json`);
    dlAnchorElem.click();
    window.AppLogger.info('SYSTEM', 'فایل پشتیبان داده‌ها توسط کاربر استخراج شد.');
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
          window.AppLogger.success('SYSTEM', 'داده‌های جدید با موفقیت از فایل پشتیبان جایگزین شدند.');
          this.showToast('داده‌ها با موفقیت بازیابی شدند.', 'success');
          setTimeout(() => window.location.reload(), 800);
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

    // Map latest inquiry per distinct sayadi_id to prevent duplicate history additions
    const latestInquiries = {};
    (this.state.inquiries || []).forEach(i => {
      const say = String(i.sayadi_id || '').trim();
      if (say) {
        if (!latestInquiries[say] || (i.id && i.id > (latestInquiries[say].id || 0))) {
          latestInquiries[say] = i;
        }
      }
    });
    const uniqueInquiries = Object.values(latestInquiries);

    const inTransitSum = uniqueInquiries.reduce((sum, i) => sum + (parseFloat(i.in_transit_amount) || 0), 0);
    const clearedSum = uniqueInquiries.reduce((sum, i) => sum + (parseFloat(i.cleared_amount) || 0), 0);
    const bouncedSum = uniqueInquiries.reduce((sum, i) => sum + (parseFloat(i.bounced_amount) || 0), 0);

    const inTransitCount = uniqueInquiries.filter(i => (parseFloat(i.in_transit_amount) || 0) > 0).length;
    const clearedCount = uniqueInquiries.filter(i => (parseFloat(i.cleared_amount) || 0) > 0).length;
    const bouncedCount = uniqueInquiries.filter(i => (parseFloat(i.bounced_amount) || 0) > 0).length;

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
      inTransitCount,
      clearedSum,
      clearedCount,
      bouncedSum,
      bouncedCount,
      creditColors: colors
    };
  },

  // ─────────────────────────────────────────────────────────────
  // 🎨 Views & Navigation (With Drilldown Support)
  // ─────────────────────────────────────────────────────────────
  switchTab(tabName, filterMode = 'all') {
    this.state.currentTab = tabName;
    this.state.chequeFilterMode = filterMode;

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
    window.scrollTo({ top: 0, behavior: 'smooth' });
  },

  // 🎯 Stat Card Drilldown Click Handlers
  drilldown(type) {
    if (type === 'customers') {
      window.AppLogger.info('SYSTEM', 'انتقال به فهرست تفصیلی مشتریان');
      this.switchTab('customers');
    } else if (type === 'cheques') {
      window.AppLogger.info('SYSTEM', 'انتقال به فهرست تمام چک‌ها');
      this.switchTab('cheques', 'all');
    } else if (type === 'total-amount') {
      window.AppLogger.info('SYSTEM', 'انتقال به فهرست چک‌ها بر اساس بیشترین مبالغ');
      this.switchTab('cheques', 'sorted-amount');
    } else if (type === 'in-transit') {
      window.AppLogger.info('SYSTEM', 'انتقال به صفحه اختصاصی چک‌های در راه پاسارگاد');
      this.switchTab('cheques', 'in-transit');
    } else if (type === 'cleared') {
      window.AppLogger.info('SYSTEM', 'انتقال به صفحه اختصاصی چک‌های رفع سوءاثر شده');
      this.switchTab('cheques', 'cleared');
    } else if (type === 'bounced') {
      window.AppLogger.info('SYSTEM', 'انتقال به صفحه اختصاصی چک‌های برگشتی و پرریسک');
      this.switchTab('cheques', 'bounced');
    }
  },

  renderCurrentView() {
    if (this.state.currentTab === 'dashboard') {
      this.renderDashboard();
    } else if (this.state.currentTab === 'customers') {
      this.renderCustomersTable();
    } else if (this.state.currentTab === 'cheques') {
      this.renderChequesTable();
    } else if (this.state.currentTab === 'logs') {
      this.renderLogsView();
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
    this.renderHoldersList();
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
      'قهوه ای': '#b45309',
      'قهوه‌ای': '#b45309',
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
              font: { family: 'Vazirmatn', size: 11 },
              color: document.documentElement.getAttribute('data-theme') === 'dark' ? '#cbd5e1' : '#334155'
            }
          }
        }
      }
    });
  },

  // ─────────────────────────────────────────────────────────────
  // 👥 Customers Directory Table (With Drilldown & Breakdown Modes)
  // ─────────────────────────────────────────────────────────────
  renderCustomersTable() {
    const container = document.getElementById('customers-table-body');
    const headerTitle = document.getElementById('customers-view-title');
    const filterBanner = document.getElementById('customers-filter-banner');
    if (!container) return;

    let list = [...this.state.customers];
    const mode = this.state.customerFilterMode || 'all';

    // Apply drilldown filter mode
    if (mode === 'in-transit') {
      list = list.filter(c => {
        const inqs = this.getCustomerInquiries(c.id);
        return inqs.some(i => i.in_transit_amount > 0);
      });
      list.sort((a, b) => {
        const sumA = this.getCustomerInquiries(a.id).reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
        const sumB = this.getCustomerInquiries(b.id).reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
        return sumB - sumA;
      });
      if (filterBanner) {
        filterBanner.innerHTML = `
          <div class="p-3 bg-sky-500/10 border border-sky-500/30 rounded-xl flex items-center justify-between">
            <div class="flex items-center gap-2 text-sky-400 text-sm font-semibold">
              <i data-lucide="truck" class="w-4 h-4"></i>
              تفکیک مشتریان دارای چک‌های در راه پاسارگاد (${list.length} مشتری)
            </div>
            <button onclick="App.switchTab('customers', 'all')" class="text-xs text-sky-300 hover:underline">نمایش همه مشتریان</button>
          </div>`;
        filterBanner.classList.remove('hidden');
      }
    } else if (mode === 'cleared') {
      list = list.filter(c => {
        const inqs = this.getCustomerInquiries(c.id);
        return inqs.some(i => i.cleared_amount > 0);
      });
      list.sort((a, b) => {
        const sumA = this.getCustomerInquiries(a.id).reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
        const sumB = this.getCustomerInquiries(b.id).reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
        return sumB - sumA;
      });
      if (filterBanner) {
        filterBanner.innerHTML = `
          <div class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center justify-between">
            <div class="flex items-center gap-2 text-emerald-400 text-sm font-semibold">
              <i data-lucide="check-check" class="w-4 h-4"></i>
              تفکیک مشتریان دارای سابقه رفع سوءاثر شده (${list.length} مشتری)
            </div>
            <button onclick="App.switchTab('customers', 'all')" class="text-xs text-emerald-300 hover:underline">نمایش همه مشتریان</button>
          </div>`;
        filterBanner.classList.remove('hidden');
      }
    } else if (mode === 'bounced') {
      list = list.filter(c => {
        const inqs = this.getCustomerInquiries(c.id);
        return inqs.some(i => i.bounced_amount > 0);
      });
      list.sort((a, b) => {
        const sumA = this.getCustomerInquiries(a.id).reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);
        const sumB = this.getCustomerInquiries(b.id).reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);
        return sumB - sumA;
      });
      if (filterBanner) {
        filterBanner.innerHTML = `
          <div class="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center justify-between">
            <div class="flex items-center gap-2 text-rose-400 text-sm font-semibold">
              <i data-lucide="alert-triangle" class="w-4 h-4"></i>
              هشدار: تفکیک مشتریان دارای سوابق چک برگشتی (${list.length} مشتری)
            </div>
            <button onclick="App.switchTab('customers', 'all')" class="text-xs text-rose-300 hover:underline">نمایش همه مشتریان</button>
          </div>`;
        filterBanner.classList.remove('hidden');
      }
    } else if (mode === 'amount') {
      list.sort((a, b) => this.getCustomerChequesSum(b.id) - this.getCustomerChequesSum(a.id));
      if (filterBanner) {
        filterBanner.innerHTML = `
          <div class="p-3 bg-blue-500/10 border border-blue-500/30 rounded-xl flex items-center justify-between">
            <div class="flex items-center gap-2 text-blue-400 text-sm font-semibold">
              <i data-lucide="arrow-down-narrow-wide" class="w-4 h-4"></i>
              تفکیک مشتریان بر اساس مجموع ارزش ریالی سبد چک‌ها
            </div>
            <button onclick="App.switchTab('customers', 'all')" class="text-xs text-blue-300 hover:underline">حالت عادی</button>
          </div>`;
        filterBanner.classList.remove('hidden');
      }
    } else {
      if (filterBanner) filterBanner.classList.add('hidden');
      list.sort((a, b) => this.getCustomerChequesSum(b.id) - this.getCustomerChequesSum(a.id));
    }

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

    if (list.length === 0) {
      container.innerHTML = `
        <tr>
          <td colspan="7" class="text-center py-12 text-slate-400">
            <i data-lucide="users" class="w-12 h-12 mx-auto mb-3 opacity-40"></i>
            هیچ مشتری با مشخصات فیلتر فعلی یافت نشد.
          </td>
        </tr>`;
      if (window.lucide) lucide.createIcons();
      return;
    }

    container.innerHTML = list.map((c, idx) => {
      const cheques = this.getCustomerCheques(c.id);
      const inqs = this.getCustomerInquiries(c.id);
      
      const inTransitSum = inqs.reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
      const clearedSum = inqs.reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
      const bouncedSum = inqs.reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);
      const totalSum = cheques.reduce((s, ch) => s + (parseFloat(ch.amount) || 0), 0);

      let metricColHtml = '';
      if (mode === 'in-transit') {
        metricColHtml = `<span class="text-sky-400 font-bold font-mono">${this.formatMoney(inTransitSum)}</span> <span class="text-[10px] text-slate-400">ریال در راه</span>`;
      } else if (mode === 'cleared') {
        metricColHtml = `<span class="text-emerald-400 font-bold font-mono">${this.formatMoney(clearedSum)}</span> <span class="text-[10px] text-slate-400">ریال رفع اثر</span>`;
      } else if (mode === 'bounced') {
        metricColHtml = `<span class="text-rose-400 font-bold font-mono">${this.formatMoney(bouncedSum)}</span> <span class="text-[10px] text-slate-400">ریال برگشتی</span>`;
      } else {
        metricColHtml = `<span class="text-emerald-400 font-bold font-mono">${this.formatMoney(totalSum)}</span> <span class="text-[10px] text-slate-400">ریال کل</span>`;
      }

      return `
        <tr class="border-b border-slate-700/30 hover:bg-slate-500/10 transition">
          <td class="py-4 px-4 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
          <td class="py-4 px-4 font-semibold text-slate-100 flex items-center gap-3">
            <div class="w-10 h-10 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold">
              ${c.full_name.charAt(0)}
            </div>
            <div>
              <div class="font-bold">${c.full_name}</div>
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
          <td class="py-4 px-4 text-left font-mono">
            ${metricColHtml}
          </td>
          <td class="py-4 px-4 text-center">
            <div class="flex items-center justify-center gap-2">
              <button onclick="App.viewCustomerProfile(${c.id})" class="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded-xl text-xs font-semibold flex items-center gap-1 transition" title="مشاهده پرونده و سوابق استعلام">
                <i data-lucide="eye" class="w-3.5 h-3.5"></i>
                <span>پرونده</span>
              </button>
              <button onclick="App.openEditCustomerModal(${c.id})" class="p-1.5 bg-amber-600/20 hover:bg-amber-600 text-amber-400 hover:text-white rounded-lg transition" title="ویرایش">
                <i data-lucide="edit-3" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="App.deleteCustomer(${c.id})" class="p-1.5 bg-rose-600/20 hover:bg-rose-600 text-rose-400 hover:text-white rounded-lg transition" title="حذف">
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
  // 📑 Cheques Directory Table (With Dynamic Filter Modes)
  // ─────────────────────────────────────────────────────────────
  renderChequesTable() {
    const container = document.getElementById('cheques-table-body');
    const filterBanner = document.getElementById('cheques-filter-banner');
    if (!container) return;

    let list = [...this.state.cheques];
    const mode = this.state.chequeFilterMode;

    // Apply drilldown filter mode
    if (mode === 'in-transit') {
      list = list.filter(ch => {
        const inq = this.getLatestInquiry(ch.sayadi_id);
        return inq && (parseFloat(inq.in_transit_amount) || 0) > 0;
      });
      filterBanner.innerHTML = `
        <div class="p-3 bg-sky-500/10 border border-sky-500/30 rounded-xl flex items-center justify-between">
          <div class="flex items-center gap-2 text-sky-400 text-sm font-semibold">
            <i data-lucide="truck" class="w-4 h-4"></i>
            نمایش فیلترشده: فقط چک‌های در راه استعلام‌شده از پاسارگاد (${list.length} فقره)
          </div>
          <button onclick="App.switchTab('cheques', 'all')" class="text-xs text-sky-300 hover:underline">نمایش تمام چک‌ها</button>
        </div>`;
      filterBanner.classList.remove('hidden');
    } else if (mode === 'cleared') {
      list = list.filter(ch => {
        const inq = this.getLatestInquiry(ch.sayadi_id);
        return inq && (parseFloat(inq.cleared_amount) || 0) > 0;
      });
      filterBanner.innerHTML = `
        <div class="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center justify-between">
          <div class="flex items-center gap-2 text-emerald-400 text-sm font-semibold">
            <i data-lucide="check-check" class="w-4 h-4"></i>
            نمایش فیلترشده: چک‌های رفع سوءاثر شده پاسارگاد (${list.length} فقره)
          </div>
          <button onclick="App.switchTab('cheques', 'all')" class="text-xs text-emerald-300 hover:underline">نمایش تمام چک‌ها</button>
        </div>`;
      filterBanner.classList.remove('hidden');
    } else if (mode === 'bounced') {
      list = list.filter(ch => {
        const inq = this.getLatestInquiry(ch.sayadi_id);
        return inq && (parseFloat(inq.bounced_amount) || 0) > 0;
      });
      filterBanner.innerHTML = `
        <div class="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center justify-between">
          <div class="flex items-center gap-2 text-rose-400 text-sm font-semibold">
            <i data-lucide="alert-triangle" class="w-4 h-4"></i>
            هشدار: نمایش چک‌های دارای سوءاثر و برگشتی (${list.length} فقره)
          </div>
          <button onclick="App.switchTab('cheques', 'all')" class="text-xs text-rose-300 hover:underline">نمایش تمام چک‌ها</button>
        </div>`;
      filterBanner.classList.remove('hidden');
    } else if (mode === 'sorted-amount') {
      list.sort((a, b) => (parseFloat(b.amount) || 0) - (parseFloat(a.amount) || 0));
      filterBanner.innerHTML = `
        <div class="p-3 bg-indigo-500/10 border border-indigo-500/30 rounded-xl flex items-center justify-between">
          <div class="flex items-center gap-2 text-indigo-400 text-sm font-semibold">
            <i data-lucide="arrow-down-narrow-wide" class="w-4 h-4"></i>
            مرتب‌سازی: بر اساس بیشترین ارزش ریالی
          </div>
          <button onclick="App.switchTab('cheques', 'all')" class="text-xs text-indigo-300 hover:underline">حالت پیش‌فرض</button>
        </div>`;
      filterBanner.classList.remove('hidden');
    } else {
      filterBanner.classList.add('hidden');
    }

    // Global Search
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
            هیچ چکی با مشخصات فیلتر فعلی یافت نشد.
          </td>
        </tr>`;
      if (window.lucide) lucide.createIcons();
      return;
    }

    container.innerHTML = list.map((ch, idx) => {
      const cust = this.state.customers.find(c => c.id === ch.customer_id);
      const inq = this.getLatestInquiry(ch.sayadi_id);
      const defaultHolder = this.state.holders[0] || { full_name: 'علی رمضانزاده', id: 1, national_id: '0921974061' };
      const holder = this.state.holders.find(h => h.id === ch.holder_id) || defaultHolder;

      return `
        <tr class="border-b border-slate-700/30 hover:bg-slate-500/10 transition">
          <td class="py-4 px-3 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
          <td class="py-4 px-3 font-mono text-blue-400 font-bold">${ch.sayadi_id}</td>
          <td class="py-4 px-3 font-medium text-slate-200">
            <button onclick="App.viewCustomerProfile(${ch.customer_id})" class="hover:text-blue-400 hover:underline text-right">
              ${cust ? cust.full_name : 'نامشخص'}
            </button>
          </td>
          <td class="py-4 px-3 font-mono text-slate-300">${ch.cheque_number || '---'}</td>
          <td class="py-4 px-3 font-mono font-bold text-emerald-400">${this.formatMoney(ch.amount || 0)}</td>
          <td class="py-4 px-3 font-mono text-sm text-slate-300">${ch.cheque_date || '---'}</td>
          <td class="py-4 px-3 text-xs text-slate-300">
            <div>${ch.bank_name || '---'}</div>
            <div class="text-[10px] text-slate-400 mt-0.5">هولدر: <strong class="text-slate-200">${holder.full_name}</strong></div>
          </td>
          <td class="py-4 px-3 text-center">
            <div class="flex items-center justify-center gap-2">
              <button onclick="App.inlineInquiryCheque('${ch.sayadi_id}', ${ch.customer_id || 'null'}, this)" class="px-2.5 py-1.5 bg-sky-600 hover:bg-sky-500 text-white text-xs rounded-lg flex items-center gap-1 shadow-sm transition" title="استعلام زنده بدون تغییر صفحه">
                <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
                <span>استعلام</span>
              </button>
              <button onclick="App.openEditChequeModal(${ch.id})" class="p-1.5 bg-amber-600/20 hover:bg-amber-600 text-amber-400 hover:text-white rounded-lg transition" title="ویرایش">
                <i data-lucide="edit" class="w-3.5 h-3.5"></i>
              </button>
              <button onclick="App.deleteCheque(${ch.id})" class="p-1.5 bg-rose-600/20 hover:bg-rose-600 text-rose-400 hover:text-white rounded-lg transition" title="حذف">
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

    const inquiries = this.getCustomerInquiries(customerId);
    const inTransitSum = inquiries.reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
    const clearedSum = inquiries.reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
    const bouncedSum = inquiries.reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);
    const historyInquiries = this.getCustomerInquiriesHistory(customerId);

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
              ${c.original_name_alias ? `<span>صندوق: <strong class="text-slate-200">${c.original_name_alias}</strong></span>` : ''}
            </div>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button onclick="App.openAddChequeModal(${c.id})" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl text-sm font-semibold flex items-center gap-2 shadow-lg transition">
            <i data-lucide="plus-circle" class="w-4 h-4"></i>
            ثبت چک برای این مشتری
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
                const defaultHolder = this.state.holders[0] || { full_name: 'علی رمضانزاده', id: 1, national_id: '0921974061' };
                const holder = this.state.holders.find(h => h.id === ch.holder_id) || defaultHolder;
                const inq = this.getLatestInquiry(ch.sayadi_id);
                const hasBounced = inq && (parseFloat(inq.bounced_amount) || 0) > 0;

                return `
                  <tr class="hover:bg-slate-800/30 transition">
                    <td class="py-3 px-4 font-mono font-bold text-blue-400">${ch.sayadi_id}</td>
                    <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_number || '---'}</td>
                    <td class="py-3 px-4 font-mono font-bold text-emerald-400">${this.formatMoney(ch.amount)}</td>
                    <td class="py-3 px-4 font-mono text-slate-300">${ch.cheque_date || '---'}</td>
                    <td class="py-3 px-4 text-slate-300">${ch.bank_name || '---'}</td>
                    <td class="py-3 px-4 text-xs font-semibold text-slate-200">${holder.full_name}</td>
                    <td class="py-3 px-4 text-center">
                      ${hasBounced 
                        ? `<span class="px-2 py-1 bg-rose-500/20 text-rose-400 rounded-md text-xs font-bold font-mono">برگشتی: ${this.formatMoney(inq.bounced_amount)}</span>`
                        : (inq ? `<span class="px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded-md text-xs font-bold font-mono">فاقد برگشتی</span>` : `<span class="text-xs text-slate-500">استعلام نشده</span>`)}
                    </td>
                    <td class="py-3 px-4 text-center">
                      <div class="flex items-center justify-center gap-2">
                        <button onclick="App.inlineInquiryCheque('${ch.sayadi_id}', ${c.id}, this)" class="px-2.5 py-1 bg-sky-600 hover:bg-sky-500 text-white text-xs rounded-lg flex items-center gap-1 transition" title="استعلام زنده آنی بدون جابجایی صفحه">
                          <i data-lucide="refresh-cw" class="w-3 h-3"></i>
                          <span>استعلام</span>
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


      <!-- 📜 Comprehensive Customer Inquiries History & Audit Log -->
      <div class="p-6 pt-0">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-bold text-slate-200 flex items-center gap-2">
            <i data-lucide="history" class="w-5 h-5 text-indigo-400"></i>
            سوابق و تاریخچه استعلام‌های این مشتری (به وقت تهران)
          </h3>
          <span class="text-xs text-slate-400 font-mono">${historyInquiries.length.toLocaleString('fa-IR')} رکورد استعلام ثبت‌شده</span>
        </div>

        <div class="overflow-x-auto rounded-xl border border-slate-700/60">
          <table class="w-full text-right text-sm">
            <thead class="bg-slate-800/80 text-slate-400 text-xs">
              <tr>
                <th class="py-3 px-3 w-10">#</th>
                <th class="py-3 px-3">تاریخ و ساعت (وقت تهران)</th>
                <th class="py-3 px-3">نوع استعلام</th>
                <th class="py-3 px-3">شناسه صیادی</th>
                <th class="py-3 px-3">دارنده (هولدر)</th>
                <th class="py-3 px-3">چک در راه</th>
                <th class="py-3 px-3">رفع سوءاثر</th>
                <th class="py-3 px-3">چک برگشتی</th>
                <th class="py-3 px-3 text-center">وضعیت</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 font-mono text-xs">
              ${historyInquiries.length === 0 ? `
                <tr>
                  <td colspan="9" class="text-center py-6 text-slate-500 font-sans text-xs">
                    هنوز هیچ سابقه‌ای برای استعلام چک‌های این مشتری ثبت نشده است.
                  </td>
                </tr>
              ` : historyInquiries.map((inq, idx) => {
                const holder = this.state.holders.find(h => h.id === inq.holder_id);
                const hasBounced = inq.bounced_amount > 0;
                const formattedTime = this.formatTehranShamsi(inq.inquiry_time || inq.created_at);

                return `
                  <tr class="hover:bg-slate-800/30 transition">
                    <td class="py-2.5 px-3 text-slate-500">${(idx + 1).toLocaleString('fa-IR')}</td>
                    <td class="py-2.5 px-3 text-slate-300 font-bold font-sans">${formattedTime}</td>
                    <td class="py-2.5 px-3">
                      <span class="px-2 py-0.5 rounded text-[10px] font-sans font-bold bg-sky-500/10 text-sky-400 border border-sky-500/30">
                        ${inq.inquiry_type === 'cbi' ? 'بانک مرکزی (CBI)' : 'بانک پاسارگاد'}
                      </span>
                    </td>
                    <td class="py-2.5 px-3 text-blue-400 font-bold">${inq.sayadi_id}</td>
                    <td class="py-2.5 px-3 font-sans text-slate-300">${holder ? holder.full_name : 'علی رمضانزاده'}</td>
                    <td class="py-2.5 px-3 text-sky-300">${this.formatMoney(inq.in_transit_amount || 0)}</td>
                    <td class="py-2.5 px-3 text-emerald-300">${this.formatMoney(inq.cleared_amount || 0)}</td>
                    <td class="py-2.5 px-3 ${hasBounced ? 'text-rose-400 font-bold' : 'text-slate-400'}">${this.formatMoney(inq.bounced_amount || 0)}</td>
                    <td class="py-2.5 px-3 text-center">
                      <span class="inline-flex items-center gap-1 text-emerald-400 font-sans text-xs">
                        <i data-lucide="check" class="w-3.5 h-3.5"></i> موفق
                      </span>
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

  formatTehranShamsi(dateInput) {
    if (!dateInput) return '---';
    try {
      let d = new Date(dateInput);
      if (isNaN(d.getTime())) {
        d = new Date(String(dateInput).replace(' ', 'T'));
      }
      if (isNaN(d.getTime())) return dateInput;

      return new Intl.DateTimeFormat('fa-IR', {
        timeZone: 'Asia/Tehran',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
      }).format(d);
    } catch (e) {
      return String(dateInput);
    }
  },

  closeCustomerProfile() {
    document.getElementById('customer-profile-modal').classList.add('hidden');
  },


  // ─────────────────────────────────────────────────────────────
  // ⚡ Inline Instant Pasargad Inquiry (In-place without navigating away)
  // ─────────────────────────────────────────────────────────────
  async inlineInquiryCheque(sayadiId, customerId, btnElement) {
    if (!sayadiId || sayadiId.length !== 16) {
      this.showToast('شناسه صیادی نامعتبر است.', 'error');
      return;
    }

    const defaultHolder = this.state.holders[0] || { full_name: 'علی رمضانزاده', id: 1, national_id: '0921974061' };
    const ch = this.state.cheques.find(c => c.sayadi_id === sayadiId);
    const holder = (ch && this.state.holders.find(h => h.id === ch.holder_id)) || defaultHolder;
    const finalCustId = customerId || (ch ? ch.customer_id : null);

    // Set spinning loader on the button
    const origHtml = btnElement ? btnElement.innerHTML : '';
    if (btnElement) {
      btnElement.disabled = true;
      btnElement.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin text-amber-300"></i> <span class="text-[10px]">استعلام...</span>`;
      if (window.lucide) lucide.createIcons();
    }

    try {
      const res = await window.PasargadInquiryEngine.queryCheque(sayadiId, holder.national_id, {
        forceRefresh: true,
        holderId: holder.id,
        customerId: finalCustId
      });

      const matchedHolderId = res.holder_id || holder.id;
      const matchedHolder = this.state.holders.find(h => h.id === matchedHolderId) || holder;

      const latestInq = this.getLatestInquiry(sayadiId);
      const hasValidExisting = latestInq && (
        (parseFloat(latestInq.in_transit_amount) || 0) > 0 ||
        (parseFloat(latestInq.cleared_amount) || 0) > 0 ||
        (parseFloat(latestInq.bounced_amount) || 0) > 0
      );

      if (res.status === 'success') {
        const inquiryRecord = {
          id: Date.now(),
          sayadi_id: sayadiId,
          holder_id: matchedHolderId,
          customer_id: finalCustId,
          inquiry_type: 'pasargad',
          in_transit_amount: parseFloat(res.in_transit_amount) || 0,
          in_transit_count: parseInt(res.in_transit_count) || 0,
          cleared_amount: parseFloat(res.cleared_amount) || 0,
          cleared_count: parseInt(res.cleared_count) || 0,
          bounced_amount: parseFloat(res.bounced_amount) || 0,
          bounced_count: parseInt(res.bounced_count) || 0,
          inquiry_time: new Date().toISOString(),
          status: 'success'
        };

        this.state.inquiries.unshift(inquiryRecord);
        if (ch) ch.holder_id = matchedHolderId;
        this.saveData();

        this.showToast(`استعلام دارنده (${matchedHolder.full_name}) با موفقیت ثبت شد.`, 'success');
      } else {
        // Inquiry was not successful (not_in_cartable, rate_limited, or error)
        // CRITICAL: NEVER wipe existing valid numbers with 0s!
        if (hasValidExisting) {
          // Keep existing valid numbers! Do not touch or overwrite with zeros.
          this.showToast(`${res.message || 'چک در کارتابل یافت نشد'} (اطلاعات معتبر قبلی حفظ شد)`, 'warn');
        } else if (res.preserved_from_history && ((parseFloat(res.in_transit_amount) || 0) > 0 || (parseFloat(res.cleared_amount) || 0) > 0 || (parseFloat(res.bounced_amount) || 0) > 0)) {
          // Backend returned preserved historical record
          const inquiryRecord = {
            id: Date.now(),
            sayadi_id: sayadiId,
            holder_id: matchedHolderId,
            customer_id: finalCustId,
            inquiry_type: 'pasargad',
            in_transit_amount: parseFloat(res.in_transit_amount) || 0,
            in_transit_count: parseInt(res.in_transit_count) || 0,
            cleared_amount: parseFloat(res.cleared_amount) || 0,
            cleared_count: parseInt(res.cleared_count) || 0,
            bounced_amount: parseFloat(res.bounced_amount) || 0,
            bounced_count: parseInt(res.bounced_count) || 0,
            inquiry_time: latestInq ? latestInq.inquiry_time : new Date().toISOString(),
            status: 'success'
          };
          this.state.inquiries.unshift(inquiryRecord);
          this.saveData();
          this.showToast(`${res.message || 'چک در کارتابل یافت نشد'} (اطلاعات معتبر قبلی حفظ شد)`, 'warn');
        } else {
          this.showToast(res.message || 'چک در کارتابل هیچ‌یک از دارندگان یافت نشد.', 'warn');
        }
      }

      // Update current view or open modal smoothly in-place
      if (this.state.selectedCustomer && this.state.selectedCustomer.id === finalCustId) {
        this.viewCustomerProfile(finalCustId);
      } else {
        this.renderCurrentView();
      }

    } catch (err) {
      if (btnElement) {
        btnElement.disabled = false;
        btnElement.innerHTML = origHtml;
        if (window.lucide) lucide.createIcons();
      }
      this.showToast(`خطا در استعلام: ${err.message}`, 'error');
    }
  },


  // ─────────────────────────────────────────────────────────────
  // 📱 Window Management: Minimize / Maximize / FullScreen
  // ─────────────────────────────────────────────────────────────
  minimizeBulkModal() {
    const modal = document.getElementById('bulk-inquiry-modal');
    const pip = document.getElementById('bulk-pip-widget');
    if (modal) modal.classList.add('hidden');
    if (pip) {
      pip.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
    }
    this.showToast('استعلام در پس‌زمینه ادامه دارد. برای مشاهده روی ابزارک پایین کلیک کنید.', 'info');
  },

  maximizeBulkModal() {
    const modal = document.getElementById('bulk-inquiry-modal');
    const pip = document.getElementById('bulk-pip-widget');
    if (pip) pip.classList.add('hidden');
    if (modal) modal.classList.remove('hidden');
  },

  toggleFullScreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      this.showToast('حالت تمام‌صفحه فعال شد.', 'info');
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
        this.showToast('حالت تمام‌صفحه غیرفعال شد.', 'info');
      }
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 🏦 Live Single Pasargad Inquiry Action
  // ─────────────────────────────────────────────────────────────

  openPasargadModalForCheque(sayadiId, customerId) {
    document.getElementById('pasargad-sayadi-input').value = sayadiId || '';
    document.getElementById('pasargad-customer-id-hidden').value = customerId || '';
    document.getElementById('pasargad-result-card').classList.add('hidden');
    this.populateHolderDropdowns();
    this.switchTab('pasargad');
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
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> در حال استعلام از موتور پاسارگاد...`;
    if (window.lucide) lucide.createIcons();

    try {
      const res = await window.PasargadInquiryEngine.queryCheque(sayadiId, holder.national_id, {
        forceRefresh: true,
        holderId: holder.id,
        customerId: customerId
      });

      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      if (window.lucide) lucide.createIcons();

      // Record in state
      const ch = this.state.cheques.find(c => c.sayadi_id === sayadiId);
      const finalCustomerId = customerId || (ch ? ch.customer_id : null);
      const latestInq = this.getLatestInquiry(sayadiId);
      const hasValidExisting = latestInq && (
        (parseFloat(latestInq.in_transit_amount) || 0) > 0 ||
        (parseFloat(latestInq.cleared_amount) || 0) > 0 ||
        (parseFloat(latestInq.bounced_amount) || 0) > 0
      );

      if (res.status === 'success') {
        const inquiryRecord = {
          id: Date.now(),
          sayadi_id: sayadiId,
          holder_id: res.holder_id || holder.id,
          customer_id: finalCustomerId,
          inquiry_type: 'pasargad',
          in_transit_amount: parseFloat(res.in_transit_amount) || 0,
          in_transit_count: parseInt(res.in_transit_count) || 0,
          cleared_amount: parseFloat(res.cleared_amount) || 0,
          cleared_count: parseInt(res.cleared_count) || 0,
          bounced_amount: parseFloat(res.bounced_amount) || 0,
          bounced_count: parseInt(res.bounced_count) || 0,
          inquiry_time: new Date().toISOString(),
          status: 'success'
        };

        this.state.inquiries.unshift(inquiryRecord);

        if (ch) ch.holder_id = res.holder_id || holder.id;
        this.saveData();

        // Display result box
        const resultCard = document.getElementById('pasargad-result-card');
        resultCard.classList.remove('hidden');
        document.getElementById('res-holder-name').innerText = res.holder_name || holder.full_name;
        document.getElementById('res-in-transit').innerText = this.formatMoney(res.in_transit_amount) + ' ریال';
        document.getElementById('res-cleared').innerText = this.formatMoney(res.cleared_amount) + ' ریال';
        document.getElementById('res-bounced').innerText = this.formatMoney(res.bounced_amount) + ' ریال';

        this.showToast('استعلام با موفقیت از بانک پاسارگاد دریافت و در سوابق ذخیره شد.', 'success');
      } else {
        // Handle non-success: preserve existing valid data
        const displayInTransit = (hasValidExisting ? latestInq.in_transit_amount : 0) || parseFloat(res.in_transit_amount) || 0;
        const displayCleared = (hasValidExisting ? latestInq.cleared_amount : 0) || parseFloat(res.cleared_amount) || 0;
        const displayBounced = (hasValidExisting ? latestInq.bounced_amount : 0) || parseFloat(res.bounced_amount) || 0;

        if (displayInTransit > 0 || displayCleared > 0 || displayBounced > 0) {
          if (!hasValidExisting && res.preserved_from_history) {
            const inquiryRecord = {
              id: Date.now(),
              sayadi_id: sayadiId,
              holder_id: res.holder_id || holder.id,
              customer_id: finalCustomerId,
              inquiry_type: 'pasargad',
              in_transit_amount: displayInTransit,
              in_transit_count: res.in_transit_count || 1,
              cleared_amount: displayCleared,
              cleared_count: res.cleared_count || 1,
              bounced_amount: displayBounced,
              bounced_count: res.bounced_count || 1,
              inquiry_time: new Date().toISOString(),
              status: 'success'
            };
            this.state.inquiries.unshift(inquiryRecord);
            this.saveData();
          }

          const resultCard = document.getElementById('pasargad-result-card');
          resultCard.classList.remove('hidden');
          document.getElementById('res-holder-name').innerText = '(آخرین سابقه معتبر) ' + (res.holder_name || holder.full_name);
          document.getElementById('res-in-transit').innerText = this.formatMoney(displayInTransit) + ' ریال';
          document.getElementById('res-cleared').innerText = this.formatMoney(displayCleared) + ' ریال';
          document.getElementById('res-bounced').innerText = this.formatMoney(displayBounced) + ' ریال';
          this.showToast(`${res.message || 'چک در کارتابل یافت نشد'} (اطلاعات معتبر قبلی حفظ شد)`, 'warn');
        } else {
          this.showToast(res.message || 'چک در کارتابل هیچ‌یک از دارندگان یافت نشد.', 'warn');
        }
      }

      this.renderCurrentView();

    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> دریافت استعلام آنی`;
      this.showToast(`خطا در استعلام: ${err.message}`, 'error');
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 🏛️ Live Central Bank (CBI) Inquiry Action
  // ─────────────────────────────────────────────────────────────
  openCBISayadiModal(sayadiId) {
    document.getElementById('cbi-sayadi-input').value = sayadiId || '';
    document.getElementById('cbi-result-card').classList.add('hidden');
    this.switchTab('cbi');
  },

  async submitCBIInquiry() {
    const sayadiId = document.getElementById('cbi-sayadi-input').value.trim();
    if (!sayadiId || sayadiId.length !== 16) {
      this.showToast('لطفاً شناسه صیادی ۱۶ رقمی را به درستی وارد کنید.', 'error');
      return;
    }

    const btn = document.getElementById('btn-submit-cbi');
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> در حال استعلام از بانک مرکزی...`;
    if (window.lucide) lucide.createIcons();

    try {
      const res = await window.PasargadInquiryEngine.queryCBI(sayadiId);

      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> استعلام از بانک مرکزی`;
      if (window.lucide) lucide.createIcons();

      // Update customer credit color and save history
      const ch = this.state.cheques.find(c => c.sayadi_id === sayadiId);
      const custId = ch ? ch.customer_id : null;
      if (custId) {
        const cust = this.state.customers.find(c => c.id === custId);
        if (cust) cust.credit_color = res.credit_color;
      }

      const cbiInquiryRecord = {
        id: Date.now(),
        sayadi_id: sayadiId,
        customer_id: custId,
        inquiry_type: 'cbi',
        credit_color: res.credit_color,
        in_transit_amount: 0,
        cleared_amount: 0,
        bounced_amount: 0,
        inquiry_time: new Date().toISOString(),
        status: 'success'
      };

      this.state.inquiries.unshift(cbiInquiryRecord);
      this.saveData();

      // Show result box
      const resultCard = document.getElementById('cbi-result-card');
      resultCard.classList.remove('hidden');
      document.getElementById('res-cbi-name').innerText = res.full_name || 'تاییدشده';
      document.getElementById('res-cbi-badge').innerHTML = this.renderCreditBadge(res.credit_color);
      document.getElementById('res-cbi-source').innerText = res.source === 'cbi_live' ? 'استعلام زنده برخط سامانه صیاد' : 'پایگاه داده استعلام‌شده';

      this.showToast(`استعلام بانک مرکزی با موفقیت ثبت شد: ${res.credit_color}`, 'success');
      this.renderCurrentView();


    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="shield-check" class="w-4 h-4"></i> استعلام از بانک مرکزی`;
      this.showToast(`خطا در استعلام بانک مرکزی: ${err.message}`, 'error');
    }
  },


  // ─────────────────────────────────────────────────────────────
  // 🔌 Bridge Settings Modal Actions
  // ─────────────────────────────────────────────────────────────
  openBridgeSettingsModal() {
    const input = document.getElementById('bridge-url-input');
    if (input) input.value = window.PasargadInquiryEngine.localBackendUrl;
    this.updateBridgeModalStatus();
    document.getElementById('bridge-settings-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closeBridgeSettingsModal() {
    document.getElementById('bridge-settings-modal').classList.add('hidden');
  },

  async testBridgeConnection() {
    const input = document.getElementById('bridge-url-input');
    const statusText = document.getElementById('bridge-modal-status-text');
    const testBtn = document.getElementById('btn-test-bridge');
    
    if (testBtn) {
      testBtn.disabled = true;
      testBtn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i> در حال تست اتصال...`;
      if (window.lucide) lucide.createIcons();
    }

    const targetUrl = input ? input.value : 'http://127.0.0.1:8000';
    window.PasargadInquiryEngine.localBackendUrl = targetUrl;
    const ok = await window.PasargadInquiryEngine.checkLocalBackend();

    if (testBtn) {
      testBtn.disabled = false;
      testBtn.innerHTML = `<i data-lucide="refresh-cw" class="w-4 h-4"></i> تست مجدد اتصال`;
      if (window.lucide) lucide.createIcons();
    }

    this.updateBridgeModalStatus();

    if (ok) {
      this.showToast('ارتباط با سرور پایتون برقرار است! (استعلام زنده فعال شد)', 'success');
    } else {
      this.showToast('ارتباط برقرار نشد. مطمئن شوید run.bat اجرا شده است.', 'error');
    }
  },

  async saveBridgeSettings() {
    const input = document.getElementById('bridge-url-input');
    const url = input ? input.value : 'http://127.0.0.1:8000';
    await window.PasargadInquiryEngine.setBackendUrl(url);
    this.closeBridgeSettingsModal();
    this.showToast('تنظیمات پل ارتباطی ذخیره گردید.', 'success');
  },

  updateBridgeModalStatus() {
    const isConn = window.PasargadInquiryEngine.isLocalBackendConnected;
    const statusBox = document.getElementById('bridge-modal-status-box');
    const statusText = document.getElementById('bridge-modal-status-text');
    const latencyText = document.getElementById('bridge-modal-latency');

    if (statusBox && statusText) {
      if (isConn) {
        statusBox.className = 'p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-2xl flex items-center justify-between';
        statusText.innerHTML = `<span class="flex items-center gap-2 text-emerald-400 font-bold text-xs"><i data-lucide="check-circle" class="w-4 h-4"></i> وضعیت: متصل به موتور پایتون</span>`;
        if (latencyText) latencyText.innerText = `تاخیر: ${window.PasargadInquiryEngine.latencyMs}ms`;
      } else {
        statusBox.className = 'p-3 bg-amber-500/10 border border-amber-500/30 rounded-2xl flex items-center justify-between';
        statusText.innerHTML = `<span class="flex items-center gap-2 text-amber-400 font-bold text-xs"><i data-lucide="alert-circle" class="w-4 h-4"></i> وضعیت: آفلاین (run.bat را باز کنید)</span>`;
        if (latencyText) latencyText.innerText = 'قطع ارتباط';
      }
      if (window.lucide) lucide.createIcons();
    }
  },

  // ─────────────────────────────────────────────────────────────
  // ⚡ Bulk Portfolio Inquiry Actions
  // ─────────────────────────────────────────────────────────────

  openBulkInquiryModal() {
    const modal = document.getElementById('bulk-inquiry-modal');
    document.getElementById('bulk-total-count').innerText = this.state.cheques.length.toLocaleString('fa-IR');
    document.getElementById('bulk-progress-bar').style.width = '0%';
    document.getElementById('bulk-progress-percent').innerText = '۰٪';
    document.getElementById('bulk-progress-text').innerText = 'آماده شروع استعلام...';
    document.getElementById('bulk-stat-success').innerText = '۰';
    document.getElementById('bulk-stat-error').innerText = '۰';
    document.getElementById('bulk-stat-in-transit').innerText = '۰';
    document.getElementById('bulk-stat-bounced').innerText = '۰';
    document.getElementById('btn-start-bulk').classList.remove('hidden');
    document.getElementById('btn-pause-bulk').classList.add('hidden');
    document.getElementById('btn-resume-bulk').classList.add('hidden');

    this.populateHolderDropdowns();
    modal.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closeBulkInquiryModal() {
    if (window.PasargadInquiryEngine.batchState.isRunning) {
      if (!confirm('فرآیند استعلام در حال اجرا است. آیا لغو شود؟')) return;
      window.PasargadInquiryEngine.cancelBatch();
    }
    document.getElementById('bulk-inquiry-modal').classList.add('hidden');
  },

  async startBulkInquiry() {
    const holderId = parseInt(document.getElementById('bulk-holder-select').value);
    const defaultHolder = this.state.holders.find(h => h.id === holderId) || this.state.holders[0];
    const concurrency = parseInt(document.getElementById('bulk-concurrency-select').value) || 3;

    // Create holder lookup map
    const holderMap = {};
    this.state.holders.forEach(h => { holderMap[h.id] = h; });

    document.getElementById('btn-start-bulk').classList.add('hidden');
    document.getElementById('btn-pause-bulk').classList.remove('hidden');

    const progressBar = document.getElementById('bulk-progress-bar');
    const progressPercent = document.getElementById('bulk-progress-percent');
    const progressText = document.getElementById('bulk-progress-text');

    await window.PasargadInquiryEngine.runBatchInquiry(
      this.state.cheques,
      holderMap,
      {
        concurrency: concurrency,
        defaultHolder: defaultHolder,
        forceRefresh: true
      },
      {
        onProgress: (state) => {
          const pct = Math.round((state.processed / state.total) * 100) || 0;
          progressBar.style.width = `${pct}%`;
          progressPercent.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          progressText.innerText = `در حال بررسی چک ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}...`;

          const pipPct = document.getElementById('pip-progress-pct');
          const pipSub = document.getElementById('pip-progress-sub');
          if (pipPct) pipPct.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          if (pipSub) pipSub.innerText = `${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')} (${state.successCount.toLocaleString('fa-IR')} موفق)`;

          document.getElementById('bulk-stat-success').innerText = state.successCount.toLocaleString('fa-IR');
          document.getElementById('bulk-stat-error').innerText = state.errorCount.toLocaleString('fa-IR');
          document.getElementById('bulk-stat-in-transit').innerText = App.formatMoney(state.inTransitSum);
          document.getElementById('bulk-stat-bounced').innerText = App.formatMoney(state.bouncedSum);
        },
        onItemComplete: (item, res) => {
          if (res && res.status === 'success') {
            const inquiryRecord = {
              id: Date.now() + Math.random(),
              sayadi_id: item.sayadi_id,
              holder_id: res.holder_id || item.holder_id || defaultHolder.id,
              customer_id: item.customer_id,
              inquiry_type: 'pasargad',
              in_transit_amount: res.in_transit_amount || 0,
              in_transit_count: res.in_transit_count || 0,
              cleared_amount: res.cleared_amount || 0,
              cleared_count: res.cleared_count || 0,
              bounced_amount: res.bounced_amount || 0,
              bounced_count: res.bounced_count || 0,
              inquiry_time: res.inquiry_time || new Date().toISOString(),
              status: 'success'
            };

            const existingIdx = App.state.inquiries.findIndex(i => i.sayadi_id === item.sayadi_id);
            if (existingIdx >= 0) {
              App.state.inquiries[existingIdx] = inquiryRecord;
            } else {
              App.state.inquiries.unshift(inquiryRecord);
            }
            App.saveData();
          }
        },
        onFinished: (summary) => {
          document.getElementById('btn-pause-bulk').classList.add('hidden');
          document.getElementById('btn-resume-bulk').classList.add('hidden');

          const pipSub = document.getElementById('pip-progress-sub');
          if (pipSub) pipSub.innerText = `استعلام پایان یافت (${summary.successCount} موفق)`;

          if (summary.errorCount > 0 && summary.failedItems && summary.failedItems.length > 0) {
            progressText.innerHTML = `<span class="text-amber-400 font-bold">پایان مرحله اول: ${summary.successCount} موفق | ${summary.errorCount} ناموفق (ترافیک بانک)</span>`;
            const retryBox = document.getElementById('bulk-retry-prompt-box');
            if (retryBox) {
              retryBox.classList.remove('hidden');
              document.getElementById('bulk-failed-count-display').innerText = summary.errorCount.toLocaleString('fa-IR');
            }
            App.showToast(`استعلام پایان یافت. ${summary.errorCount} مورد نیاز به بازتلاش امن دارند.`, 'warn');
          } else {
            progressText.innerText = `عملیات استعلام با موفقیت ۱۰۰٪ به پایان رسید! (${summary.successCount} موفق)`;
            const retryBox = document.getElementById('bulk-retry-prompt-box');
            if (retryBox) retryBox.classList.add('hidden');
            App.showToast('استعلام دسته‌جمعی سبد مشتریان با موفقیت ۱۰۰٪ انجام شد.', 'success');
          }

          App.renderCurrentView();
        }
      }
    );
  },

  async retryFailedBatch() {
    const holderId = parseInt(document.getElementById('bulk-holder-select').value);
    const defaultHolder = this.state.holders.find(h => h.id === holderId) || this.state.holders[0];
    const holderMap = {};
    this.state.holders.forEach(h => { holderMap[h.id] = h; });

    const retryBox = document.getElementById('bulk-retry-prompt-box');
    if (retryBox) retryBox.classList.add('hidden');

    const progressBar = document.getElementById('bulk-progress-bar');
    const progressPercent = document.getElementById('bulk-progress-percent');
    const progressText = document.getElementById('bulk-progress-text');

    progressText.innerText = 'در حال استعلام مجدد موارد ناموفق با سرعت بهینه و ضد بلاک...';

    await window.PasargadInquiryEngine.runRetryFailed(
      holderMap,
      {
        onProgress: (state) => {
          const pct = Math.round((state.processed / state.total) * 100) || 0;
          progressBar.style.width = `${pct}%`;
          progressPercent.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          progressText.innerText = `در حال بررسی امن چک ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}...`;

          const pipPct = document.getElementById('pip-progress-pct');
          const pipSub = document.getElementById('pip-progress-sub');
          if (pipPct) pipPct.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          if (pipSub) pipSub.innerText = `استعلام مجدد: ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}`;

          document.getElementById('bulk-stat-success').innerText = (parseInt(document.getElementById('bulk-stat-success').innerText) + state.successCount).toLocaleString('fa-IR');
          document.getElementById('bulk-stat-error').innerText = state.errorCount.toLocaleString('fa-IR');
          document.getElementById('bulk-stat-in-transit').innerText = App.formatMoney(state.inTransitSum);
          document.getElementById('bulk-stat-bounced').innerText = App.formatMoney(state.bouncedSum);
        },
        onItemComplete: (item, res) => {
          if (res && res.status === 'success') {
            const inquiryRecord = {
              id: Date.now() + Math.random(),
              sayadi_id: item.sayadi_id,
              holder_id: res.holder_id || item.holder_id || defaultHolder.id,
              customer_id: item.customer_id,
              inquiry_type: 'pasargad',
              in_transit_amount: res.in_transit_amount || 0,
              in_transit_count: res.in_transit_count || 0,
              cleared_amount: res.cleared_amount || 0,
              cleared_count: res.cleared_count || 0,
              bounced_amount: res.bounced_amount || 0,
              bounced_count: res.bounced_count || 0,
              inquiry_time: res.inquiry_time || new Date().toISOString(),
              status: 'success'
            };

            const existingIdx = App.state.inquiries.findIndex(i => i.sayadi_id === item.sayadi_id);
            if (existingIdx >= 0) {
              App.state.inquiries[existingIdx] = inquiryRecord;
            } else {
              App.state.inquiries.unshift(inquiryRecord);
            }
            App.saveData();
          }
        },
        onFinished: (summary) => {
          progressText.innerText = `استعلام مجدد به پایان رسید! (${summary.successCount} مورد بازیابی و با موفقیت ثبت شد)`;
          const pipSub = document.getElementById('pip-progress-sub');
          if (pipSub) pipSub.innerText = `استعلام مجدد به پایان رسید (${summary.successCount} موفق)`;
          App.showToast('موارد ناموفق با موفقیت استعلام شدند.', 'success');
          App.renderCurrentView();
        }
      }
    );
  },


  pauseBulkInquiry() {
    window.PasargadInquiryEngine.pauseBatch();
    document.getElementById('btn-pause-bulk').classList.add('hidden');
    document.getElementById('btn-resume-bulk').classList.remove('hidden');
    document.getElementById('bulk-progress-text').innerText = 'عملیات موقتاً متوقف شد.';
  },

  resumeBulkInquiry() {
    window.PasargadInquiryEngine.resumeBatch();
    document.getElementById('btn-resume-bulk').classList.add('hidden');
    document.getElementById('btn-pause-bulk').classList.remove('hidden');
  },


  // ─────────────────────────────────────────────────────────────
  // 👥 Dynamic Holders Management (CRUD)
  // ─────────────────────────────────────────────────────────────
  renderHoldersList() {
    const container = document.getElementById('dashboard-holders-container');
    if (!container) return;

    container.innerHTML = this.state.holders.map((h, idx) => {
      const activeCheques = this.state.cheques.filter(ch => ch.holder_id === h.id).length;
      return `
        <div class="p-3.5 bg-slate-900/50 border border-slate-700/50 rounded-2xl flex flex-col justify-between transition hover:border-blue-500/40">
          <div>
            <div class="flex items-center justify-between mb-1">
              <span class="font-bold text-blue-400 text-sm">${(idx + 1).toLocaleString('fa-IR')}. ${h.full_name}</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-300 font-mono">${activeCheques.toLocaleString('fa-IR')} چک</span>
            </div>
            <div class="font-mono text-xs text-slate-400">${h.national_id}</div>
            <div class="text-[11px] text-slate-500 mt-1">${h.relationship || 'بدون نسبت'}</div>
          </div>
          <div class="flex items-center justify-end gap-1.5 mt-3 pt-2 border-t border-slate-800">
            <button onclick="App.openEditHolderModal(${h.id})" class="p-1.5 text-amber-400 hover:bg-slate-800 rounded-lg text-xs transition" title="ویرایش">
              <i data-lucide="edit-2" class="w-3.5 h-3.5"></i>
            </button>
            <button onclick="App.deleteHolder(${h.id})" class="p-1.5 text-rose-400 hover:bg-slate-800 rounded-lg text-xs transition" title="حذف">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  },

  openAddHolderModal() {
    document.getElementById('holder-form-id').value = '';
    document.getElementById('holder-form-name').value = '';
    document.getElementById('holder-form-national-id').value = '';
    document.getElementById('holder-form-relationship').value = '';
    document.getElementById('holder-modal-title').innerText = 'افزودن دارنده چک (هولدر جدید)';
    document.getElementById('holder-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  openEditHolderModal(holderId) {
    const h = this.state.holders.find(item => item.id === holderId);
    if (!h) return;

    document.getElementById('holder-form-id').value = h.id;
    document.getElementById('holder-form-name').value = h.full_name || '';
    document.getElementById('holder-form-national-id').value = h.national_id || '';
    document.getElementById('holder-form-relationship').value = h.relationship || '';
    document.getElementById('holder-modal-title').innerText = 'ویرایش دارنده چک';
    document.getElementById('holder-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closeHolderModal() {
    document.getElementById('holder-modal').classList.add('hidden');
  },

  saveHolderForm() {
    const id = document.getElementById('holder-form-id').value;
    const full_name = document.getElementById('holder-form-name').value.trim();
    const national_id = document.getElementById('holder-form-national-id').value.trim();
    const relationship = document.getElementById('holder-form-relationship').value.trim();

    if (!full_name || !national_id) {
      this.showToast('نام و کد ملی دارنده چک الزامی است.', 'error');
      return;
    }

    if (id) {
      // Edit
      const h = this.state.holders.find(item => item.id === parseInt(id));
      if (h) {
        h.full_name = full_name;
        h.national_id = national_id;
        h.relationship = relationship;
        window.AppLogger.info('CRUD', `اطلاعات هولدر ${full_name} ویرایش شد.`);
      }
    } else {
      // Add
      const newHolder = {
        id: Date.now(),
        full_name,
        national_id,
        relationship,
        is_active: 1,
        created_at: new Date().toISOString().replace('T', ' ').slice(0, 19)
      };
      this.state.holders.push(newHolder);
      window.AppLogger.success('CRUD', `دارنده جدید ${full_name} (${national_id}) با موفقیت به سامانه اضافه شد.`);
    }

    this.saveData();
    this.populateHolderDropdowns();
    this.renderHoldersList();
    this.closeHolderModal();
    this.showToast('دارنده چک با موفقیت ذخیره شد.', 'success');
  },

  deleteHolder(holderId) {
    const h = this.state.holders.find(item => item.id === holderId);
    if (!h) return;
    if (!confirm(`آیا از حذف دارنده "${h.full_name}" اطمینان دارید؟`)) return;

    this.state.holders = this.state.holders.filter(item => item.id !== holderId);
    this.saveData();
    this.populateHolderDropdowns();
    this.renderHoldersList();
    window.AppLogger.warn('CRUD', `دارنده "${h.full_name}" از سامانه حذف گردید.`);
    this.showToast('دارنده با موفقیت حذف شد.', 'success');
  },

  // ─────────────────────────────────────────────────────────────
  // 📜 Log Console Actions
  // ─────────────────────────────────────────────────────────────
  openLogsModal() {
    this.renderLogsList();
    document.getElementById('logs-modal').classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  closeLogsModal() {
    document.getElementById('logs-modal').classList.add('hidden');
  },

  setLogFilter(level) {
    this.state.logFilter = level;
    document.querySelectorAll('.log-filter-btn').forEach(btn => {
      if (btn.dataset.level === level) {
        btn.classList.add('bg-blue-600', 'text-white');
        btn.classList.remove('bg-slate-800', 'text-slate-400');
      } else {
        btn.classList.remove('bg-blue-600', 'text-white');
        btn.classList.add('bg-slate-800', 'text-slate-400');
      }
    });
    this.renderLogsList();
  },

  renderLogsList() {
    const container = document.getElementById('log-terminal-content');
    if (!container) return;

    let list = window.AppLogger.logs;
    if (this.state.logFilter !== 'ALL') {
      list = list.filter(l => l.level === this.state.logFilter);
    }

    if (list.length === 0) {
      container.innerHTML = `<div class="p-6 text-center text-slate-500 text-xs">هیچ رکوردی برای نمایش وجود ندارد.</div>`;
      return;
    }

    const badgeColors = {
      INFO: 'text-sky-400 bg-sky-500/10 border-sky-500/30',
      SUCCESS: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
      WARN: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
      ERROR: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
      BATCH: 'text-purple-400 bg-purple-500/10 border-purple-500/30'
    };

    container.innerHTML = list.map(l => `
      <div class="p-2.5 border-b border-slate-800/80 text-xs font-mono flex items-start gap-3 hover:bg-slate-900/40 transition">
        <span class="text-slate-500 shrink-0 select-none">${l.timeFormatted}</span>
        <span class="px-2 py-0.5 rounded border text-[10px] font-bold shrink-0 ${badgeColors[l.level] || 'text-slate-300'}">${l.level}</span>
        <span class="text-indigo-400 font-semibold shrink-0">[${l.category}]</span>
        <span class="text-slate-200 flex-1 break-all">${l.message}</span>
      </div>
    `).join('');
  },

  updateLogBadge() {
    const errorCount = window.AppLogger.logs.filter(l => l.level === 'ERROR').length;
    const badge = document.getElementById('sidebar-log-count');
    if (badge) {
      badge.innerText = window.AppLogger.logs.length.toLocaleString('fa-IR');
    }
  },

  clearAllLogs() {
    if (!confirm('آیا از پاکسازی تمام لاگ‌ها اطمینان دارید؟')) return;
    window.AppLogger.clearLogs();
    this.renderLogsList();
    this.showToast('لاگ‌ها با موفقیت پاکسازی شدند.', 'info');
  },

  exportLogs(type) {
    let dataStr = "";
    let filename = `sayad_logs_${new Date().toISOString().slice(0,10)}`;
    
    if (type === 'json') {
      dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(window.AppLogger.exportLogsJSON());
      filename += ".json";
    } else {
      dataStr = "data:text/plain;charset=utf-8," + encodeURIComponent(window.AppLogger.exportLogsTXT());
      filename += ".log";
    }

    const a = document.createElement('a');
    a.setAttribute('href', dataStr);
    a.setAttribute('download', filename);
    a.click();
    this.showToast('فایل لاگ با موفقیت دانلود شد.', 'success');
  },

  // ─────────────────────────────────────────────────────────────
  // ⏰ Scheduler Settings UI
  // ─────────────────────────────────────────────────────────────
  initSchedulerUI() {
    const toggle = document.getElementById('scheduler-toggle-checkbox');
    const select = document.getElementById('scheduler-interval-select');
    const countdown = document.getElementById('scheduler-countdown-display');

    if (toggle) {
      toggle.checked = window.PasargadInquiryEngine.scheduler.enabled;
      toggle.addEventListener('change', (e) => {
        const enabled = e.target.checked;
        const interval = select ? select.value : 6;
        window.PasargadInquiryEngine.configureScheduler(enabled, interval, () => {
          App.startBulkInquiry();
        });
      });
    }

    if (select) {
      select.value = window.PasargadInquiryEngine.scheduler.intervalHours;
      select.addEventListener('change', (e) => {
        if (toggle && toggle.checked) {
          window.PasargadInquiryEngine.configureScheduler(true, e.target.value, () => {
            App.startBulkInquiry();
          });
        }
      });
    }

    // Live countdown timer updater
    setInterval(() => {
      if (countdown) {
        countdown.innerText = window.PasargadInquiryEngine.getNextRunRemainingFormatted();
      }
    }, 1000);
  },

  // ─────────────────────────────────────────────────────────────
  // 📊 Client-Side Excel Export (SheetJS)
  // ─────────────────────────────────────────────────────────────
  exportToExcel() {
    if (!window.XLSX) {
      this.showToast('کتابخانه اکسل در دسترس نیست.', 'error');
      return;
    }

    window.AppLogger.info('SYSTEM', 'در حال تولید خروجی کامل اکسل...');

    const rows = this.state.cheques.map((ch, idx) => {
      const cust = this.state.customers.find(c => c.id === ch.customer_id) || {};
      const holder = this.state.holders.find(h => h.id === ch.holder_id) || {};
      const inq = this.getLatestInquiry(ch.sayadi_id) || {};

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
    window.AppLogger.success('SYSTEM', 'فایل اکسل با موفقیت تولید و دانلود گردید.');
    this.showToast('فایل اکسل با موفقیت تولید و دانلود شد.', 'success');
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
      const cust = this.state.customers.find(c => c.id === parseInt(id));
      if (cust) {
        cust.full_name = full_name;
        cust.national_id = national_id;
        cust.phone = phone;
        cust.address = address;
        cust.notes = notes;
        window.AppLogger.info('CRUD', `اطلاعات مشتری ${full_name} بروزرسانی شد.`);
      }
    } else {
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
      window.AppLogger.success('CRUD', `مشتری جدید ${full_name} به سامانه اضافه گردید.`);
    }

    this.saveData();
    this.closeCustomerModal();
    this.showToast('اطلاعات مشتری با موفقیت ذخیره شد.', 'success');
    this.renderCurrentView();
  },

  deleteCustomer(customerId) {
    const cust = this.state.customers.find(c => c.id === customerId);
    if (!confirm(`آیا از حذف مشتری "${cust ? cust.full_name : ''}" اطمینان دارید؟`)) return;
    this.state.customers = this.state.customers.filter(c => c.id !== customerId);
    this.saveData();
    window.AppLogger.warn('CRUD', `مشتری "${cust ? cust.full_name : ''}" از سامانه حذف شد.`);
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

    this.populateHolderDropdowns();
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

    this.populateHolderDropdowns();
    const holderSelect = document.getElementById('cheque-form-holder-select');
    if (holderSelect && ch.holder_id) holderSelect.value = ch.holder_id;

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
        window.AppLogger.info('CRUD', `اطلاعات چک صیادی ${sayadi_id} بروزرسانی شد.`);
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
      window.AppLogger.success('CRUD', `چک صیادی جدید ${sayadi_id} به مبلغ ${amount.toLocaleString('fa-IR')} ریال ثبت شد.`);
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
    const ch = this.state.cheques.find(c => c.id === chequeId);
    if (!confirm('آیا از حذف این چک اطمینان دارید؟')) return;
    this.state.cheques = this.state.cheques.filter(c => c.id !== chequeId);
    this.saveData();
    window.AppLogger.warn('CRUD', `چک صیادی ${ch ? ch.sayadi_id : ''} از سامانه حذف شد.`);
    this.showToast('چک با موفقیت حذف گردید.', 'success');
    this.renderCurrentView();
    if (this.state.selectedCustomer) {
      this.viewCustomerProfile(this.state.selectedCustomer.id);
    }
  },

  // ─────────────────────────────────────────────────────────────
  // 🛠 Helper Functions
  // ─────────────────────────────────────────────────────────────
  getCustomerCheques(customerId) {
    return this.state.cheques.filter(ch => ch.customer_id === customerId);
  },

  getLatestInquiry(sayadiId) {
    if (!sayadiId) return null;
    const cleanId = String(sayadiId).trim();
    const inqs = this.state.inquiries.filter(i => String(i.sayadi_id).trim() === cleanId);
    if (!inqs || inqs.length === 0) return null;
    if (inqs.length === 1) return inqs[0];
    return inqs.reduce((best, cur) => {
      const timeCur = cur.inquiry_time ? new Date(cur.inquiry_time).getTime() : (cur.id || 0);
      const timeBest = best.inquiry_time ? new Date(best.inquiry_time).getTime() : (best.id || 0);
      if (timeCur !== timeBest) {
        return timeCur > timeBest ? cur : best;
      }
      return (cur.id || 0) >= (best.id || 0) ? cur : best;
    });
  },

  getCustomerInquiries(customerId) {
    const cheques = this.getCustomerCheques(customerId);
    const inqList = [];
    const seenSayadi = new Set();

    cheques.forEach(ch => {
      if (ch.sayadi_id && !seenSayadi.has(ch.sayadi_id)) {
        seenSayadi.add(ch.sayadi_id);
        const latest = this.getLatestInquiry(ch.sayadi_id);
        if (latest) inqList.push(latest);
      }
    });

    const customerInqs = this.state.inquiries.filter(i => i.customer_id === customerId);
    customerInqs.forEach(inq => {
      if (inq.sayadi_id && !seenSayadi.has(inq.sayadi_id)) {
        seenSayadi.add(inq.sayadi_id);
        const latest = this.getLatestInquiry(inq.sayadi_id);
        if (latest) inqList.push(latest);
      }
    });

    return inqList;
  },

  getCustomerInquiriesHistory(customerId) {
    const cheques = this.getCustomerCheques(customerId);
    const chequesSayadi = new Set(cheques.map(c => c.sayadi_id));
    const list = this.state.inquiries.filter(i => i.customer_id === customerId || chequesSayadi.has(i.sayadi_id));
    return [...list].sort((a, b) => {
      const timeA = a.inquiry_time ? new Date(a.inquiry_time).getTime() : (a.id || 0);
      const timeB = b.inquiry_time ? new Date(b.inquiry_time).getTime() : (b.id || 0);
      return (timeB || 0) - (timeA || 0);
    });
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
    return `<span class="px-2.5 py-1 rounded-full text-xs font-bold bg-slate-700/50 text-slate-300 border border-slate-600">نامشخص</span>`;
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
    const bg = type === 'success' ? 'bg-emerald-600' : (type === 'error' ? 'bg-rose-600' : (type === 'warn' ? 'bg-amber-600' : 'bg-blue-600'));
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

  // ─────────────────────────────────────────────────────────────
  // ⚡ Quick Inline Customer Creation in Cheque Modal
  // ─────────────────────────────────────────────────────────────
  toggleQuickNewCustomerInline(show = true) {
    const box = document.getElementById('inline-quick-customer-box');
    const select = document.getElementById('cheque-form-customer-select');
    if (!box) return;

    if (show) {
      box.classList.remove('hidden');
      if (select) select.classList.add('opacity-50', 'pointer-events-none');
      const nameInput = document.getElementById('quick-cust-name');
      if (nameInput) nameInput.focus();
    } else {
      box.classList.add('hidden');
      if (select) select.classList.remove('opacity-50', 'pointer-events-none');
    }
  },

  saveQuickCustomerInline() {
    const nameInput = document.getElementById('quick-cust-name');
    const phoneInput = document.getElementById('quick-cust-phone');
    const nationalInput = document.getElementById('quick-cust-national-id');

    const name = nameInput ? nameInput.value.trim() : '';
    const phone = phoneInput ? phoneInput.value.trim() : '';
    const national_id = nationalInput ? nationalInput.value.trim() : '';

    if (!name) {
      this.showToast('نام مشتری الزامی است.', 'error');
      return;
    }

    const newCust = {
      id: Date.now(),
      full_name: name,
      national_id: national_id,
      phone: phone,
      address: '',
      notes: 'ایجاد سریع از فرم چک',
      credit_color: 'نامشخص',
      risk_score: 0,
      created_at: new Date().toISOString().slice(0, 10)
    };

    this.state.customers.push(newCust);
    this.saveData();

    // Populate dropdown and select new customer
    this.populateCustomerDropdowns();
    const select = document.getElementById('cheque-form-customer-select');
    if (select) select.value = newCust.id;

    // Reset and hide
    if (nameInput) nameInput.value = '';
    if (phoneInput) phoneInput.value = '';
    if (nationalInput) nationalInput.value = '';
    this.toggleQuickNewCustomerInline(false);

    window.AppLogger.success('CRUD', `مشتری جدید "${name}" به صورت سریع ایجاد و انتخاب شد.`);
    this.showToast(`مشتری "${name}" ایجاد و انتخاب شد.`, 'success');
  },

  populateCustomerDropdowns() {
    const select = document.getElementById('cheque-form-customer-select');
    if (!select) return;

    select.innerHTML = this.state.customers.map(c => `
      <option value="${c.id}">${c.full_name} ${c.national_id ? `(${c.national_id})` : ''}</option>
    `).join('');
  },

  // ─────────────────────────────────────────────────────────────
  // 📱 Mobile Hamburger Drawer Toggle
  // ─────────────────────────────────────────────────────────────
  toggleMobileSidebar(open = null) {
    const sidebar = document.getElementById('app-sidebar');
    const backdrop = document.getElementById('mobile-sidebar-backdrop');
    if (!sidebar) return;

    const isOpen = !sidebar.classList.contains('translate-x-full');
    const shouldOpen = open !== null ? open : !isOpen;

    if (shouldOpen) {
      sidebar.classList.remove('translate-x-full');
      if (backdrop) backdrop.classList.remove('hidden');
    } else {
      sidebar.classList.add('translate-x-full');
      if (backdrop) backdrop.classList.add('hidden');
    }
  },
  // ─────────────────────────────────────────────────────────────
  // 📊 Smart Multi-Tier Logging, Diagnostics & Floating Drawer
  // ─────────────────────────────────────────────────────────────
  async renderLogsView() {
    await this.refreshLogsView();
  },

  async refreshLogsView() {
    const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
    const levelSelect = document.getElementById('logs-filter-level');
    const tagSelect = document.getElementById('logs-filter-tag');
    const searchInput = document.getElementById('logs-search-input');

    const level = levelSelect ? levelSelect.value : 'ALL';
    const tag = tagSelect ? tagSelect.value : 'ALL';
    const search = searchInput ? searchInput.value.trim() : '';

    let logsList = [];
    let stats = { total: 0, success: 0, warn: 0, error: 0 };

    try {
      const params = new URLSearchParams();
      if (level && level !== 'ALL') params.append('level', level);
      if (tag && tag !== 'ALL') params.append('tag', tag);
      if (search) params.append('search', search);
      params.append('limit', '200');

      const res = await fetch(`${backendUrl}/api/logs?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        logsList = data.logs || [];
        stats = data.stats || stats;
      } else {
        throw new Error('Endpoint error');
      }
    } catch (e) {
      logsList = window.AppLogger.getLogs({ level, tag, search });
      const allLogs = window.AppLogger.logs || [];
      stats = {
        total: allLogs.length,
        success: allLogs.filter(l => l.level === 'SUCCESS').length,
        warn: allLogs.filter(l => l.level === 'WARN').length,
        error: allLogs.filter(l => l.level === 'ERROR').length
      };
    }

    const totalEl = document.getElementById('metric-total-logs');
    const succEl = document.getElementById('metric-success-logs');
    const warnEl = document.getElementById('metric-warn-logs');
    const errEl = document.getElementById('metric-error-logs');
    const countEl = document.getElementById('logs-rendered-count');

    if (totalEl) totalEl.innerText = (stats.total || 0).toLocaleString('fa-IR');
    if (succEl) succEl.innerText = (stats.success || 0).toLocaleString('fa-IR');
    if (warnEl) warnEl.innerText = (stats.warn || 0).toLocaleString('fa-IR');
    if (errEl) errEl.innerText = (stats.error || 0).toLocaleString('fa-IR');
    if (countEl) countEl.innerText = logsList.length.toLocaleString('fa-IR');

    const tbody = document.getElementById('logs-table-body');
    if (!tbody) return;

    if (logsList.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" class="text-center py-8 text-slate-500 font-sans">
            هیچ لاگ یا رویدادی مطابق با فیلترهای انتخابی یافت نشد.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = logsList.map(l => {
      const lvl = (l.level || 'INFO').toUpperCase();
      const badgeColors = {
        SUCCESS: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
        INFO: 'bg-sky-500/15 text-sky-400 border border-sky-500/30',
        WARN: 'bg-amber-500/15 text-amber-400 border border-amber-500/30',
        ERROR: 'bg-rose-500/15 text-rose-400 border border-rose-500/30',
        DEBUG: 'bg-slate-700/40 text-slate-400 border border-slate-600/30'
      };
      const badgeStyle = badgeColors[lvl] || badgeColors.INFO;

      const tagColors = {
        PASARGAD: 'text-amber-300 font-semibold',
        CBI: 'text-blue-300 font-semibold',
        DATABASE: 'text-purple-300',
        SCHEDULER: 'text-sky-300',
        SYSTEM: 'text-slate-300',
        CLIENT: 'text-teal-300'
      };
      const tagStyle = tagColors[l.tag] || 'text-slate-400';
      const rowId = `log-detail-${l.id || Math.random().toString(36).substring(2,7)}`;
      const hasDetails = l.details && Object.keys(l.details).length > 0;

      return `
        <tr class="hover:bg-slate-800/40 transition">
          <td class="p-3 text-slate-400 whitespace-nowrap">${l.jalali_time || l.timeFormatted || '---'}</td>
          <td class="p-3 whitespace-nowrap">
            <span class="px-2 py-0.5 rounded text-[10px] font-bold ${badgeStyle}">${lvl}</span>
          </td>
          <td class="p-3 whitespace-nowrap font-bold ${tagStyle}">[${l.tag || l.category || 'SYSTEM'}]</td>
          <td class="p-3 font-sans text-slate-200">${l.message || ''}</td>
          <td class="p-3 font-mono text-slate-300 whitespace-nowrap">
            ${l.sayadi_id ? `
              <span class="inline-flex items-center gap-1 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-700/60">
                <span>${l.sayadi_id}</span>
                <button onclick="navigator.clipboard.writeText('${l.sayadi_id}'); App.showToast('شناسه کپی شد', 'info');" class="text-slate-400 hover:text-white" title="کپی شناسه">
                  <i data-lucide="copy" class="w-3 h-3"></i>
                </button>
              </span>
            ` : '<span class="text-slate-600">---</span>'}
          </td>
          <td class="p-3 text-slate-400 whitespace-nowrap font-mono">
            ${l.duration_ms ? `${l.duration_ms}ms` : '---'}
          </td>
          <td class="p-3 text-center whitespace-nowrap">
            ${hasDetails ? `
              <button onclick="document.getElementById('${rowId}').classList.toggle('hidden')" class="p-1 rounded bg-slate-800 hover:bg-slate-700 text-indigo-400 transition" title="مشاهده جزئیات Payload">
                <i data-lucide="eye" class="w-3.5 h-3.5"></i>
              </button>
            ` : '<span class="text-slate-600">-</span>'}
          </td>
        </tr>
        ${hasDetails ? `
          <tr id="${rowId}" class="hidden bg-slate-950/80">
            <td colspan="7" class="p-3 text-right">
              <pre class="bg-slate-900 p-3 rounded-xl border border-slate-800 text-[10px] text-slate-300 overflow-x-auto text-left font-mono">${JSON.stringify(l.details, null, 2)}</pre>
            </td>
          </tr>
        ` : ''}
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  },

  filterLogsView() {
    this.refreshLogsView();
  },

  async checkGatewayHealthNow() {
    const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
    try {
      const res = await fetch(`${backendUrl}/api/health`);
      if (res.ok) {
        const data = await res.json();
        const gw = data.pasargad_gateway || {};
        const isOnline = gw.status === 'online';

        const badge = document.getElementById('logs-gateway-badge');
        const text = document.getElementById('logs-gateway-text');
        const miniHealth = document.getElementById('console-minibar-health-text');

        if (text) text.innerText = `درگاه پاسارگاد: ${isOnline ? 'آنلاین' : 'کندی/ترافیک'} (${gw.latency_ms || 0}ms)`;
        if (miniHealth) miniHealth.innerText = `درگاه بانک: ${isOnline ? 'آنلاین' : 'قطع'} (${gw.latency_ms || 0}ms)`;
        if (badge) {
          badge.className = `flex items-center gap-2 px-3.5 py-1.5 rounded-2xl ${isOnline ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border-rose-500/20 text-rose-400'} text-xs font-semibold`;
        }

        this.showToast(`پایش درگاه بانک: ${isOnline ? 'آنلاین و فعال' : 'اختلال درگاه'} (${gw.latency_ms}ms)`, isOnline ? 'success' : 'warn');
      }
    } catch (e) {
      this.showToast('خطا در ارتباط با سرور سلامت محلی', 'error');
    }
  },

  consoleState: {
    isOpen: false,
    isPaused: false,
    count: 0
  },

  toggleConsoleDrawer(force = null) {
    const drawer = document.getElementById('console-drawer');
    if (!drawer) return;
    this.consoleState.isOpen = force !== null ? force : !this.consoleState.isOpen;
    drawer.classList.toggle('hidden', !this.consoleState.isOpen);
    if (window.lucide) lucide.createIcons();
  },

  toggleConsoleStreamPause() {
    this.consoleState.isPaused = !this.consoleState.isPaused;
    const btn = document.getElementById('btn-pause-stream');
    if (btn) {
      btn.innerText = this.consoleState.isPaused ? 'ادامه ثبت زنده' : 'توقف موقت';
      btn.className = this.consoleState.isPaused ? 'px-2.5 py-1 rounded-lg bg-amber-600 text-white font-sans text-xs transition' : 'px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-sans text-xs transition';
    }
  },

  clearConsoleDrawer() {
    const feed = document.getElementById('console-drawer-feed');
    if (feed) feed.innerHTML = '';
    this.consoleState.count = 0;
    const cnt = document.getElementById('console-drawer-count');
    if (cnt) cnt.innerText = '۰ رخداد';
  },

  appendLiveLogEntry(entry) {
    const latestEl = document.getElementById('console-minibar-latest');
    if (latestEl) {
      latestEl.innerText = `[${entry.level}] ${entry.message}`;
    }

    if (!this.consoleState.isPaused) {
      const feed = document.getElementById('console-drawer-feed');
      if (feed) {
        this.consoleState.count++;
        const cnt = document.getElementById('console-drawer-count');
        if (cnt) cnt.innerText = `${this.consoleState.count.toLocaleString('fa-IR')} رخداد`;

        const levelColors = {
          SUCCESS: 'text-emerald-400',
          INFO: 'text-sky-400',
          WARN: 'text-amber-400',
          ERROR: 'text-rose-400 font-bold',
          DEBUG: 'text-slate-400'
        };
        const colorCls = levelColors[entry.level] || 'text-slate-300';
        const line = document.createElement('div');
        line.className = 'flex items-start gap-2 leading-relaxed hover:bg-slate-900/60 px-1 rounded transition';
        line.innerHTML = `
          <span class="text-slate-500 whitespace-nowrap">${entry.jalali_time || entry.timeFormatted || ''}</span>
          <span class="font-bold ${colorCls} whitespace-nowrap">[${entry.level}]</span>
          <span class="text-indigo-400 whitespace-nowrap">[${entry.tag || entry.category || 'SYS'}]</span>
          <span class="text-slate-200 flex-1">${entry.message}</span>
          ${entry.sayadi_id ? `<span class="text-slate-400 bg-slate-900 px-1.5 rounded font-mono text-[10px]">${entry.sayadi_id}</span>` : ''}
        `;
        feed.appendChild(line);
        feed.scrollTop = feed.scrollHeight;

        while (feed.children.length > 200) {
          feed.removeChild(feed.firstChild);
        }
      }
    }
  },

  exportLogsJSON() {
    window.AppLogger.exportLogsAsJSON();
    this.showToast('فایل JSON لاگ‌ها دانلود شد.', 'success');
  },

  exportLogsText() {
    window.AppLogger.exportLogsAsText();
    this.showToast('فایل متنی لاگ‌ها دانلود شد.', 'success');
  },

  clearSystemLogsPrompt() {
    if (confirm('آیا از پاکسازی تمام لاگ‌های ثبت‌شده مطمئن هستید؟')) {
      window.AppLogger.clearLogs();
      this.clearConsoleDrawer();
      this.refreshLogsView();
      this.showToast('تمام لاگ‌ها با موفقیت پاکسازی شدند.', 'success');
    }
  },

  openLogsModal() {
    this.switchTab('logs');
  },

  closeLogsModal() {
    const modal = document.getElementById('logs-modal');
    if (modal) modal.classList.add('hidden');
  },

  setupEventListeners() {
    // Global Search Input
    const searchInput = document.getElementById('global-search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        this.state.searchQuery = e.target.value;
        if (this.state.searchQuery.trim() && this.state.currentTab === 'dashboard') {
          this.switchTab('customers', 'all');
        } else {
          this.renderCurrentView();
        }
      });
    }

    // Color filter select
    const colorSelect = document.getElementById('credit-color-filter');
    if (colorSelect) {
      colorSelect.addEventListener('change', (e) => {
        this.state.colorFilter = e.target.value;
        this.renderCustomersTable();
      });
    }

    // 🚪 Backdrop Click to Close all Modals
    document.querySelectorAll('.modal-backdrop').forEach(modal => {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          modal.classList.add('hidden');
        }
      });
    });

    // ⌨️ ESC Key to Close Modals
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.add('hidden'));
        this.toggleMobileSidebar(false);
      }
    });
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});

