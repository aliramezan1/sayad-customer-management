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
    logFilter: 'ALL',
    bulkDrilldown: {
      activeTab: 'failed',
      searchQuery: '',
      retryingId: null,
      expandedDiagnostics: new Set(),
      lastRenderTime: 0
    },
    lastBatchResults: null
  },

  async init() {
    window.AppLogger.info('SYSTEM', 'در حال راه‌اندازی سامانه صیاد پرو وب...');
    await this.loadData();
    await this.initRole();
    this.restoreLastBatchResults();
    this.populateHolderDropdowns();
    this.renderHoldersList();
    this.setupEventListeners();
    this.initSchedulerUI();
    this.initPWA();
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
      window.AppLogger.error('SYSTEM', 'خطا در بارگذاری دیتاست اولیه', e);
    }
  },

  restoreLastBatchResults() {
    try {
      const savedBatch = localStorage.getItem('sayad_last_batch_results');
      if (savedBatch) {
        this.state.lastBatchResults = JSON.parse(savedBatch);
        if (window.PasargadInquiryEngine && (!window.PasargadInquiryEngine.batchState.processed || window.PasargadInquiryEngine.batchState.processed === 0)) {
          window.PasargadInquiryEngine.batchState = {
            isRunning: false,
            isPaused: false,
            isCancelled: false,
            total: this.state.lastBatchResults.total || 0,
            processed: this.state.lastBatchResults.processed || 0,
            successCount: this.state.lastBatchResults.successCount || 0,
            errorCount: this.state.lastBatchResults.errorCount || 0,
            inTransitSum: this.state.lastBatchResults.inTransitSum || 0,
            clearedSum: this.state.lastBatchResults.clearedSum || 0,
            bouncedSum: this.state.lastBatchResults.bouncedSum || 0,
            failedItems: this.state.lastBatchResults.failedItems || [],
            successItems: this.state.lastBatchResults.successItems || []
          };
        }
      }
    } catch (e) {
      console.error('Error restoring last batch results:', e);
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
  // 🛡️ RBAC Role Management
  // ─────────────────────────────────────────────────────────────
  async initRole() {
    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const res = await fetch(`${backendUrl}/api/auth/current-role`);
      if (res.ok) {
        const data = await res.json();
        this.updateRoleUI(data.role, data.title);
      }
    } catch (e) {
      console.warn('Could not fetch current role:', e);
    }
  },

  toggleRoleDropdown() {
    const menu = document.getElementById('role-dropdown-menu');
    if (menu) menu.classList.toggle('hidden');
  },

  async switchRole(role) {
    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const res = await fetch(`${backendUrl}/api/auth/switch-role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: role })
      });
      if (res.ok) {
        const data = await res.json();
        this.updateRoleUI(data.current_role, data.role_info.title);
        this.showToast(data.message, 'success');
      } else {
        const err = await res.json();
        this.showToast(err.detail || 'خطا در تغییر نقش', 'error');
      }
    } catch (e) {
      this.showToast('خطا در ارتباط با سرور جهت تغییر نقش', 'error');
    }
    const menu = document.getElementById('role-dropdown-menu');
    if (menu) menu.classList.add('hidden');
  },

  updateRoleUI(role, title) {
    this.state.currentRole = role;
    const label = document.getElementById('current-role-label');
    if (label) {
      if (role === 'admin') label.textContent = 'مدیر ارشد';
      else if (role === 'operator') label.textContent = 'اپراتور';
      else if (role === 'auditor') label.textContent = 'ناظر/حسابرس';
      else label.textContent = title || role;
    }
    ['admin', 'operator', 'auditor'].forEach(r => {
      const el = document.getElementById(`role-check-${r}`);
      if (el) {
        if (r === role) el.classList.remove('hidden');
        else el.classList.add('hidden');
      }
    });
  },

  // ─────────────────────────────────────────────────────────────
  // 🛡️ Encrypted Backup Vault Management
  // ─────────────────────────────────────────────────────────────
  async openBackupModal() {
    const modal = document.getElementById('backup-vault-modal');
    if (modal) modal.classList.remove('hidden');
    await this.refreshBackupList();
  },

  closeBackupModal() {
    const modal = document.getElementById('backup-vault-modal');
    if (modal) modal.classList.add('hidden');
  },

  async refreshBackupList() {
    const tbody = document.getElementById('backup-table-body');
    const emptyNotice = document.getElementById('backup-empty-notice');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-slate-400">در حال دریافت لیست پشتیبان‌ها...</td></tr>';

    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const res = await fetch(`${backendUrl}/api/backup/list`);
      if (res.ok) {
        const data = await res.json();
        const backups = data.backups || [];
        if (backups.length === 0) {
          tbody.innerHTML = '';
          if (emptyNotice) emptyNotice.classList.remove('hidden');
          return;
        }
        if (emptyNotice) emptyNotice.classList.add('hidden');

        tbody.innerHTML = backups.map(b => `
          <tr class="hover:bg-slate-800/50 transition">
            <td class="py-2.5 px-3">
              <div class="font-mono text-sky-400 font-bold text-xs">${this.escapeHtml(b.filename)}</div>
              <div class="text-[10px] text-slate-400 mt-0.5">تگ: <span class="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">${this.escapeHtml(b.tag || 'manual')}</span> ${b.is_emergency ? '<span class="text-amber-400 font-semibold">(اسنپ‌شات اضطراری)</span>' : ''}</div>
            </td>
            <td class="py-2.5 px-3 font-mono text-[11px] text-slate-300">${b.jalali_created_at || b.created_at}</td>
            <td class="py-2.5 px-3 font-mono text-emerald-400 font-semibold text-xs">${b.formatted_size}</td>
            <td class="py-2.5 px-3 text-center">
              <span class="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[10px] font-mono inline-flex items-center gap-1">
                <i data-lucide="lock" class="w-2.5 h-2.5"></i> AES-256
              </span>
            </td>
            <td class="py-2.5 px-3 text-center">
              <div class="flex items-center justify-center gap-1.5">
                <a href="${backendUrl}/api/backup/download/${b.filename}" download class="p-1.5 bg-slate-800 hover:bg-slate-700 text-sky-400 hover:text-white rounded-lg transition" title="دانلود نسخه رمزنگاری‌شده">
                  <i data-lucide="download" class="w-3.5 h-3.5"></i>
                </a>
                <button onclick="App.restoreBackup('${b.filename}')" class="p-1.5 bg-rose-500/20 hover:bg-rose-500 text-rose-300 hover:text-white rounded-lg transition" title="بازیابی دیتابیس (فقط مدیر)">
                  <i data-lucide="rotate-ccw" class="w-3.5 h-3.5"></i>
                </button>
              </div>
            </td>
          </tr>
        `).join('');

        if (window.lucide) lucide.createIcons();
      }
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-rose-400">خطا در بارگذاری مخزن پشتیبان‌ها.</td></tr>';
    }
  },

  async createBackupFromModal() {
    const tagInput = document.getElementById('backup-tag-input');
    const tag = (tagInput && tagInput.value.trim()) || 'manual';
    const btn = document.getElementById('btn-create-backup');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>در حال رمزنگاری...</span>';
    }

    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const res = await fetch(`${backendUrl}/api/backup/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tag })
      });
      if (res.ok) {
        const data = await res.json();
        this.showToast('پشتیبان‌گیری رمزنگاری‌شده با موفقیت ایجاد شد.', 'success');
        if (tagInput) tagInput.value = '';
        await this.refreshBackupList();
      } else {
        const err = await res.json();
        this.showToast(err.detail || 'خطا در ایجاد پشتیبان', 'error');
      }
    } catch (e) {
      this.showToast('خطا در برقراری ارتباط با سرور پشتیبان', 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="plus" class="w-4 h-4"></i><span>ایجاد پشتیبان جدید</span>';
        if (window.lucide) lucide.createIcons();
      }
    }
  },

  async restoreBackup(filename) {
    if (!confirm(`هشدار امنیتی:\nآیا از بازیابی پایگاه داده از فایل '${filename}' اطمینان دارید؟\nیک اسنپ‌شات اضطراری از داده‌های فعلی به صورت خودکار ایجاد خواهد شد.`)) {
      return;
    }

    try {
      const backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
      const res = await fetch(`${backendUrl}/api/backup/restore/${filename}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        this.showToast(data.message || 'پایگاه داده با موفقیت بازیابی گردید.', 'success');
        await this.syncData();
        await this.refreshBackupList();
      } else {
        const err = await res.json();
        this.showToast(err.detail || 'خطا در بازیابی پایگاه داده', 'error');
      }
    } catch (e) {
      this.showToast('خطا در درخواست بازیابی پایگاه داده', 'error');
    }
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

    // 📱 Sync iOS Native Bottom Navigation Bar
    document.querySelectorAll('.ios-tab-item').forEach(btn => {
      if (btn.dataset.tab === tabName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    document.querySelectorAll('.tab-view').forEach(view => {
      view.classList.toggle('hidden', view.id !== `view-${tabName}`);
    });

    this.renderCurrentView();
    if (window.lucide) lucide.createIcons();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  },

  // 📱 Mobile Quick Action Sheet Handlers
  openMobileActionSheet() {
    const sheet = document.getElementById('mobile-action-sheet');
    if (sheet) {
      sheet.classList.remove('hidden');
      if (window.lucide) lucide.createIcons();
    }
  },

  closeMobileActionSheet() {
    const sheet = document.getElementById('mobile-action-sheet');
    if (sheet) sheet.classList.add('hidden');
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
    } else if (this.state.currentTab === 'risk-matrix') {
      this.renderRiskMatrix();
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

    // Phase 4: Financial Intelligence & Alerts
    this.loadPredictiveCashFlow();
    this.loadNearMaturityAlerts();
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
          <td colspan="8" class="text-center py-12 text-slate-400">
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
          <td class="py-4 px-4 text-center">
            ${this.renderFHSBadge(c)}
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

    // 📱 Mobile Touch Cards Rendering for Customers (iPhone 17 & Mobile)
    const mobileContainer = document.getElementById('customers-mobile-cards');
    if (mobileContainer) {
      if (list.length === 0) {
        mobileContainer.innerHTML = `<div class="text-center py-10 text-slate-400 text-xs">هیچ مشتری با مشخصات فیلتر فعلی یافت نشد.</div>`;
      } else {
        mobileContainer.innerHTML = list.map((c, idx) => {
          const cheques = this.getCustomerCheques(c.id);
          const inqs = this.getCustomerInquiries(c.id);
          const inTransitSum = inqs.reduce((s, i) => s + (parseFloat(i.in_transit_amount) || 0), 0);
          const clearedSum = inqs.reduce((s, i) => s + (parseFloat(i.cleared_amount) || 0), 0);
          const bouncedSum = inqs.reduce((s, i) => s + (parseFloat(i.bounced_amount) || 0), 0);
          const totalSum = cheques.reduce((s, ch) => s + (parseFloat(ch.amount) || 0), 0);

          return `
            <div class="mobile-card space-y-3">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-3">
                  <div class="w-11 h-11 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center font-black text-base shadow">
                    ${c.full_name.charAt(0)}
                  </div>
                  <div>
                    <div class="font-bold text-sm text-slate-100 flex items-center gap-2">
                      <span>${c.full_name}</span>
                      <span class="text-[10px] text-slate-400 font-mono">#${(idx + 1).toLocaleString('fa-IR')}</span>
                    </div>
                    <div class="text-[11px] text-slate-400 font-mono mt-0.5">
                      کد ملی: ${c.national_id || '---'}
                    </div>
                  </div>
                </div>
                <div class="flex flex-col items-end gap-1">
                  ${this.renderCreditBadge(c.credit_color)}
                  ${this.renderFHSBadge(c)}
                </div>
              </div>

              <div class="grid grid-cols-2 gap-2 bg-slate-900/60 p-2.5 rounded-xl border border-slate-800/80 text-xs">
                <div>
                  <span class="text-[10px] text-slate-400 block">تعداد چک‌ها</span>
                  <span class="font-bold font-mono text-blue-400">${(cheques.length).toLocaleString('fa-IR')} فقره</span>
                </div>
                <div>
                  <span class="text-[10px] text-slate-400 block">مجموع تعهدات</span>
                  <span class="font-bold font-mono text-emerald-400">${this.formatMoney(totalSum)} <span class="text-[9px] text-slate-400 font-sans">ریال</span></span>
                </div>
                <div>
                  <span class="text-[10px] text-slate-400 block">چک در راه</span>
                  <span class="font-bold font-mono text-sky-400">${this.formatMoney(inTransitSum)} <span class="text-[9px] text-slate-400 font-sans">ریال</span></span>
                </div>
                <div>
                  <span class="text-[10px] text-slate-400 block">برگشتی</span>
                  <span class="font-bold font-mono text-rose-400">${this.formatMoney(bouncedSum)} <span class="text-[9px] text-slate-400 font-sans">ریال</span></span>
                </div>
              </div>

              <div class="flex items-center justify-between pt-1 border-t border-slate-800/60">
                <button onclick="App.viewCustomerProfile(${c.id})" class="flex-1 py-2 bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition">
                  <i data-lucide="eye" class="w-4 h-4"></i>
                  <span>مشاهده پرونده کامل</span>
                </button>
                <div class="flex items-center gap-1.5 mr-2">
                  <button onclick="App.openEditCustomerModal(${c.id})" class="p-2 bg-amber-600/20 hover:bg-amber-600 text-amber-300 rounded-xl transition" title="ویرایش">
                    <i data-lucide="edit-3" class="w-4 h-4"></i>
                  </button>
                  <button onclick="App.deleteCustomer(${c.id})" class="p-2 bg-rose-600/20 hover:bg-rose-600 text-rose-300 rounded-xl transition" title="حذف">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join('');
      }
    }

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
    } else if (mode === 'near-maturity') {
      list = list.filter(ch => {
        const days = this.calculateDaysUntilDue(ch.cheque_date);
        return days !== null && days >= 0 && days <= 7;
      });
      list.sort((a, b) => (this.calculateDaysUntilDue(a.cheque_date) || 999) - (this.calculateDaysUntilDue(b.cheque_date) || 999));
      filterBanner.innerHTML = `
        <div class="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center justify-between">
          <div class="flex items-center gap-2 text-rose-400 text-sm font-semibold">
            <i data-lucide="bell-ring" class="w-4 h-4"></i>
            هشدار: نمایش چک‌های با سررسید کمتر از ۷ روز آینده (${list.length} فقره)
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

    // 📱 Mobile Touch Cards Rendering for Cheques (iPhone 17 & Mobile)
    const mobileChequesContainer = document.getElementById('cheques-mobile-cards');
    if (mobileChequesContainer) {
      if (list.length === 0) {
        mobileChequesContainer.innerHTML = `<div class="text-center py-10 text-slate-400 text-xs">هیچ چکی با مشخصات فیلتر فعلی یافت نشد.</div>`;
      } else {
        mobileChequesContainer.innerHTML = list.map((ch, idx) => {
          const cust = this.state.customers.find(c => c.id === ch.customer_id);
          const inq = this.getLatestInquiry(ch.sayadi_id);
          const defaultHolder = this.state.holders[0] || { full_name: 'علی رمضانزاده', id: 1, national_id: '0921974061' };
          const holder = this.state.holders.find(h => h.id === ch.holder_id) || defaultHolder;
          const isSayadi = ch.sayadi_id && String(ch.sayadi_id).trim().length === 16;

          return `
            <div class="mobile-card space-y-3">
              <div class="flex items-start justify-between">
                <div>
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-bold text-slate-100">${cust ? cust.full_name : 'نامشخص'}</span>
                    <span class="text-[10px] text-slate-400 font-mono">#${(idx + 1).toLocaleString('fa-IR')}</span>
                  </div>
                  <div class="text-xs text-slate-400 mt-0.5">
                    شماره چک: <strong class="text-slate-200 font-mono">${ch.cheque_number || '---'}</strong> | سررسید: <span class="font-mono text-slate-300">${ch.cheque_date || '---'}</span>
                  </div>
                </div>
                <div class="text-left">
                  <div class="text-sm font-black font-mono text-emerald-400">${this.formatMoney(ch.amount || 0)}</div>
                  <div class="text-[9px] text-slate-400 font-sans">ریال</div>
                </div>
              </div>

              <!-- Sayadi ID Box with Copy Button -->
              <div class="flex items-center justify-between bg-slate-900/80 px-3 py-2 rounded-xl border border-slate-800 text-xs font-mono">
                <div class="flex items-center gap-2 truncate">
                  <i data-lucide="credit-card" class="w-4 h-4 text-sky-400 shrink-0"></i>
                  ${isSayadi 
                    ? `<span class="text-sky-300 font-bold">${ch.sayadi_id}</span>` 
                    : `<span class="text-amber-400 text-[11px] font-sans">${ch.bank_name && ch.bank_name.includes('سفته') ? 'سند سفته (فاقد شناسه صیادی)' : 'فاقد شناسه صیادی'}</span>`
                  }
                </div>
                ${isSayadi ? `
                  <button onclick="navigator.clipboard.writeText('${ch.sayadi_id}'); App.showToast('شناسه صیادی کپی شد', 'info');" class="p-1 text-slate-400 hover:text-white transition" title="کپی شناسه">
                    <i data-lucide="copy" class="w-3.5 h-3.5"></i>
                  </button>
                ` : ''}
              </div>

              <!-- Bank & Holder & Status Chips -->
              <div class="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-300">
                <div class="flex items-center gap-1.5">
                  <i data-lucide="building" class="w-3.5 h-3.5 text-slate-400"></i>
                  <span>${ch.bank_name || '---'}</span>
                </div>
                <div class="px-2 py-0.5 rounded-lg bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-[10px]">
                  هولدر: ${holder.full_name}
                </div>
              </div>

              <!-- Action Bar -->
              <div class="flex items-center justify-between pt-1 border-t border-slate-800/60">
                ${isSayadi ? `
                  <button onclick="App.inlineInquiryCheque('${ch.sayadi_id}', ${ch.customer_id || 'null'}, this)" class="flex-1 py-2 bg-sky-600/20 hover:bg-sky-600 text-sky-300 hover:text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 transition">
                    <i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>
                    <span>استعلام صیادی زنده</span>
                  </button>
                ` : `
                  <div class="flex-1 text-[11px] text-amber-400 py-1 flex items-center gap-1">
                    <i data-lucide="alert-circle" class="w-3.5 h-3.5 shrink-0"></i>
                    <span>معاف از استعلام صیاد</span>
                  </div>
                `}
                <div class="flex items-center gap-1.5 mr-2">
                  <button onclick="App.openEditChequeModal(${ch.id})" class="p-2 bg-amber-600/20 hover:bg-amber-600 text-amber-300 rounded-xl transition" title="ویرایش">
                    <i data-lucide="edit" class="w-4 h-4"></i>
                  </button>
                  <button onclick="App.deleteCheque(${ch.id})" class="p-2 bg-rose-600/20 hover:bg-rose-600 text-rose-300 rounded-xl transition" title="حذف">
                    <i data-lucide="trash-2" class="w-4 h-4"></i>
                  </button>
                </div>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    if (window.lucide) lucide.createIcons();
  },

  // ─────────────────────────────────────────────────────────────
  // 🪟 Customer Profile Modal
  // ─────────────────────────────────────────────────────────────
  async viewCustomerProfile(customerId) {
    const c = this.state.customers.find(cust => cust.id === customerId);
    if (!c) return;

    let fhs = null;
    try {
      const res = await fetch(`/api/analytics/customer-fhs/${customerId}`, { credentials: 'omit' });
      if (res.ok) {
        fhs = await res.json();
      }
    } catch (e) {
      console.warn('Could not fetch FHS analytics for profile:', e);
    }

    if (!fhs) {
      fhs = {
        fhs_score: c.fhs_score || 50,
        level: c.fhs_level || 'متوسط',
        color: c.fhs_color || '#f59e0b',
        bg_class: c.fhs_bg_class || 'bg-amber-500/10 text-amber-400 border-amber-500/30',
        recommendation: 'بررسی تکمیلی وضعیت اعتباری و وصول چک‌ها توصیه می‌شود.',
        factors: {
          cbi_score: 60,
          cbi_component: 36,
          cleared_component: 15,
          commitment_component: 10,
          bounced_penalty: 0
        }
      };
    }

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
              ${this.renderFHSBadge(c)}
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

      <!-- FHS Intelligence Card (Phase 4) -->
      <div class="p-6 bg-slate-900/70 border-b border-slate-700/60">
        <div class="glass-card p-5 border border-sky-500/30 bg-gradient-to-l from-sky-950/30 via-slate-900/60 to-slate-900/40 space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-3">
              <div class="w-12 h-12 rounded-2xl bg-sky-500/20 border border-sky-500/40 flex items-center justify-center text-sky-400 shadow-md">
                <i data-lucide="activity" class="w-6 h-6"></i>
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <h3 class="text-base font-bold text-slate-100">کارنامه هوش مالی و سلامت اعتباری (FHS)</h3>
                  <span class="px-2.5 py-0.5 rounded-lg text-xs font-mono font-bold border ${fhs.bg_class}">${fhs.fhs_score} از ۱۰۰ (${fhs.level})</span>
                </div>
                <p class="text-xs text-slate-400 mt-0.5">تحلیل وزندار فینتک: رتبه اعتباری بانک مرکزی، نرخ وصول، توازن تعهدات و جریمه برگشتی</p>
              </div>
            </div>
            <div class="text-right">
              <div class="text-xs text-slate-400">رتبه اعتباری بانک مرکزی:</div>
              <div class="text-sm font-bold text-slate-200">${c.credit_color || 'نامشخص'} (${fhs.factors.cbi_score || 0} نمره)</div>
            </div>
          </div>

          <!-- Factor Progress Bars -->
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
              <div class="text-slate-400 mb-1 flex justify-between">
                <span>رتبه بانک مرکزی:</span>
                <strong class="font-mono text-sky-400">${fhs.factors.cbi_component || 0} / ۶۰</strong>
              </div>
              <div class="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div class="bg-sky-500 h-full" style="width: ${Math.min(100, (fhs.factors.cbi_component || 0) / 60 * 100)}%"></div>
              </div>
            </div>

            <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
              <div class="text-slate-400 mb-1 flex justify-between">
                <span>نرخ وصول چک‌ها:</span>
                <strong class="font-mono text-emerald-400">${fhs.factors.cleared_component || 0} / ۲۵</strong>
              </div>
              <div class="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div class="bg-emerald-500 h-full" style="width: ${Math.min(100, (fhs.factors.cleared_component || 0) / 25 * 100)}%"></div>
              </div>
            </div>

            <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
              <div class="text-slate-400 mb-1 flex justify-between">
                <span>توازن تعهدات:</span>
                <strong class="font-mono text-blue-400">${fhs.factors.commitment_component || 0} / ۱۵</strong>
              </div>
              <div class="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div class="bg-blue-500 h-full" style="width: ${Math.min(100, (fhs.factors.commitment_component || 0) / 15 * 100)}%"></div>
              </div>
            </div>

            <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50">
              <div class="text-slate-400 mb-1 flex justify-between">
                <span>جریمه چک برگشتی:</span>
                <strong class="font-mono text-rose-400">-${fhs.factors.bounced_penalty || 0} / ۴۰</strong>
              </div>
              <div class="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div class="bg-rose-500 h-full" style="width: ${Math.min(100, (fhs.factors.bounced_penalty || 0) / 40 * 100)}%"></div>
              </div>
            </div>
          </div>

          <!-- Recommendation box -->
          <div class="p-2.5 rounded-xl bg-slate-900/70 border border-slate-800 flex items-center gap-2 text-xs text-slate-300">
            <i data-lucide="shield-alert" class="w-4 h-4 text-amber-400 shrink-0"></i>
            <span><strong>توصیه هوش مالی:</strong> ${fhs.recommendation}</span>
          </div>
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

  serverBatchPollInterval: null,

  async checkServerBatchRunningState() {
    const backendUrl = window.PasargadInquiryEngine ? window.PasargadInquiryEngine.localBackendUrl : '';
    try {
      const res = await fetch(`${backendUrl}/api/scheduler/status`);
      if (!res.ok) return;
      const data = await res.json();
      const p = data.progress || {};
      if (p.is_running || data.current_status === 'running') {
        const btnStart = document.getElementById('btn-start-bulk');
        const btnServer = document.getElementById('btn-start-server-bulk');
        const btnCancel = document.getElementById('btn-cancel-server-bulk');
        if (btnStart) btnStart.classList.add('hidden');
        if (btnServer) btnServer.classList.add('hidden');
        if (btnCancel) btnCancel.classList.remove('hidden');

        if (!this.serverBatchPollInterval) {
          this.serverBatchPollInterval = setInterval(() => this.pollServerBatchStatus(), 1200);
        }
      }
    } catch (e) {}
  },

  openBulkInquiryModal() {
    const modal = document.getElementById('bulk-inquiry-modal');
    const totalCheques = this.state.cheques.length;
    const validSayadi = this.state.cheques.filter(c => c.sayadi_id && String(c.sayadi_id).trim().length === 16).length;
    const nonSayadi = totalCheques - validSayadi;

    const totalEl = document.getElementById('bulk-total-count');
    if (totalEl) totalEl.innerText = totalCheques.toLocaleString('fa-IR');
    const sayadiEl = document.getElementById('bulk-sayadi-count');
    if (sayadiEl) sayadiEl.innerText = validSayadi.toLocaleString('fa-IR');
    const nonSayadiEl = document.getElementById('bulk-nonsayadi-count');
    if (nonSayadiEl) nonSayadiEl.innerText = nonSayadi.toLocaleString('fa-IR');

    const bs = window.PasargadInquiryEngine.batchState;
    const lastBatch = this.state.lastBatchResults;

    if (bs && bs.isRunning) {
      // Currently running: keep progress and buttons
      document.getElementById('btn-start-bulk').classList.add('hidden');
      const btnServer = document.getElementById('btn-start-server-bulk');
      if (btnServer) btnServer.classList.add('hidden');
      document.getElementById('btn-pause-bulk').classList.toggle('hidden', bs.isPaused);
      document.getElementById('btn-resume-bulk').classList.toggle('hidden', !bs.isPaused);
    } else if (bs && (bs.processed > 0 || (bs.successCount + bs.errorCount > 0))) {
      // Completed or previous batch available
      const pct = Math.round((bs.processed / (bs.total || 1)) * 100) || 0;
      document.getElementById('bulk-progress-bar').style.width = `${pct}%`;
      document.getElementById('bulk-progress-percent').innerText = `${pct.toLocaleString('fa-IR')}٪`;
      document.getElementById('bulk-progress-text').innerText = bs.errorCount > 0 
        ? `استعلام قبلی: ${bs.successCount.toLocaleString('fa-IR')} موفق و ${bs.errorCount.toLocaleString('fa-IR')} ناموفق. برای اجرای مجدد روی شروع کلیک کنید.`
        : `استعلام با موفقیت ۱۰۰٪ پایان یافته است (${bs.successCount.toLocaleString('fa-IR')} موفق).`;
      document.getElementById('bulk-stat-success').innerText = bs.successCount.toLocaleString('fa-IR');
      document.getElementById('bulk-stat-error').innerText = bs.errorCount.toLocaleString('fa-IR');
      const subSuc = document.getElementById('bulk-stat-success-sub');
      if (subSuc) subSuc.innerText = `(${bs.successCount.toLocaleString('fa-IR')})`;
      const subErr = document.getElementById('bulk-stat-error-sub');
      if (subErr) subErr.innerText = `(${bs.errorCount.toLocaleString('fa-IR')})`;
      document.getElementById('bulk-stat-in-transit').innerText = this.formatMoney(bs.inTransitSum);
      document.getElementById('bulk-stat-bounced').innerText = this.formatMoney(bs.bouncedSum);

      const retryBox = document.getElementById('bulk-retry-prompt-box');
      if (retryBox) {
        if (bs.errorCount > 0 && bs.failedItems && bs.failedItems.length > 0) {
          retryBox.classList.remove('hidden');
          const fc = document.getElementById('bulk-failed-count-display');
          if (fc) fc.innerText = bs.errorCount.toLocaleString('fa-IR');
        } else {
          retryBox.classList.add('hidden');
        }
      }

      document.getElementById('btn-start-bulk').classList.remove('hidden');
      const btnServer = document.getElementById('btn-start-server-bulk');
      if (btnServer) btnServer.classList.remove('hidden');
      document.getElementById('btn-pause-bulk').classList.add('hidden');
      document.getElementById('btn-resume-bulk').classList.add('hidden');
    } else if (lastBatch) {
      // Restored from lastBatch storage
      const sCount = lastBatch.successCount || (lastBatch.successItems ? lastBatch.successItems.length : 0);
      const eCount = lastBatch.errorCount || (lastBatch.failedItems ? lastBatch.failedItems.length : 0);
      document.getElementById('bulk-stat-success').innerText = sCount.toLocaleString('fa-IR');
      document.getElementById('bulk-stat-error').innerText = eCount.toLocaleString('fa-IR');
      const subSuc = document.getElementById('bulk-stat-success-sub');
      if (subSuc) subSuc.innerText = `(${sCount.toLocaleString('fa-IR')})`;
      const subErr = document.getElementById('bulk-stat-error-sub');
      if (subErr) subErr.innerText = `(${eCount.toLocaleString('fa-IR')})`;
      document.getElementById('bulk-stat-in-transit').innerText = this.formatMoney(lastBatch.inTransitSum || 0);
      document.getElementById('bulk-stat-bounced').innerText = this.formatMoney(lastBatch.bouncedSum || 0);
      document.getElementById('bulk-progress-bar').style.width = '100%';
      document.getElementById('bulk-progress-percent').innerText = '۱۰۰٪';
      document.getElementById('bulk-progress-text').innerText = eCount > 0
        ? `گزارش آخرین استعلام: ${sCount.toLocaleString('fa-IR')} موفق، ${eCount.toLocaleString('fa-IR')} ناموفق`
        : `گزارش آخرین استعلام (موفقیت ۱۰۰٪)`;

      const retryBox = document.getElementById('bulk-retry-prompt-box');
      if (retryBox) {
        if (eCount > 0 && lastBatch.failedItems && lastBatch.failedItems.length > 0) {
          retryBox.classList.remove('hidden');
          const fc = document.getElementById('bulk-failed-count-display');
          if (fc) fc.innerText = eCount.toLocaleString('fa-IR');
        } else {
          retryBox.classList.add('hidden');
        }
      }

      document.getElementById('btn-start-bulk').classList.remove('hidden');
      const btnServer = document.getElementById('btn-start-server-bulk');
      if (btnServer) btnServer.classList.remove('hidden');
      document.getElementById('btn-pause-bulk').classList.add('hidden');
      document.getElementById('btn-resume-bulk').classList.add('hidden');
    } else {
      // Fresh initial state
      document.getElementById('bulk-progress-bar').style.width = '0%';
      document.getElementById('bulk-progress-percent').innerText = '۰٪';
      document.getElementById('bulk-progress-text').innerText = 'آماده شروع استعلام...';
      document.getElementById('bulk-stat-success').innerText = '۰';
      document.getElementById('bulk-stat-error').innerText = '۰';
      const subSuc = document.getElementById('bulk-stat-success-sub');
      if (subSuc) subSuc.innerText = '';
      const subErr = document.getElementById('bulk-stat-error-sub');
      if (subErr) subErr.innerText = '';
      document.getElementById('bulk-stat-in-transit').innerText = '۰';
      document.getElementById('bulk-stat-bounced').innerText = '۰';
      document.getElementById('btn-start-bulk').classList.remove('hidden');
      const btnServer = document.getElementById('btn-start-server-bulk');
      if (btnServer) btnServer.classList.remove('hidden');
      document.getElementById('btn-pause-bulk').classList.add('hidden');
      document.getElementById('btn-resume-bulk').classList.add('hidden');
      const retryBox = document.getElementById('bulk-retry-prompt-box');
      if (retryBox) retryBox.classList.add('hidden');
    }

    this.checkServerBatchRunningState();
    this.populateHolderDropdowns();
    modal.classList.remove('hidden');
    if (window.lucide) lucide.createIcons();
  },

  async startServerSideBulkInquiry() {
    const holderId = parseInt(document.getElementById('bulk-holder-select').value) || 1;
    
    document.getElementById('btn-start-bulk').classList.add('hidden');
    document.getElementById('btn-start-server-bulk').classList.add('hidden');
    document.getElementById('btn-pause-bulk').classList.add('hidden');
    const btnCancel = document.getElementById('btn-cancel-server-bulk');
    if (btnCancel) btnCancel.classList.remove('hidden');

    const progressText = document.getElementById('bulk-progress-text');
    const progressBar = document.getElementById('bulk-progress-bar');
    const progressPercent = document.getElementById('bulk-progress-percent');

    progressText.innerText = 'در حال ارسال فرمان استعلام جامع سروری...';
    progressBar.style.width = '2%';
    progressPercent.innerText = '۲٪';

    try {
      const backendUrl = window.PasargadInquiryEngine ? window.PasargadInquiryEngine.localBackendUrl : '';
      const res = await fetch(`${backendUrl}/api/scheduler/run-now?holder_id=${holderId}&force_all=true`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'خطا در آغاز استعلام سروری');
      }

      this.showToast('استعلام جامع سروری در پس‌زمینه آغاز شد. پایش زنده فعال است.', 'info');
      window.AppLogger.batch('SCHEDULER', 'فرمان استعلام جامع سروری صادر شد. پایش زنده پیشرفت آغاز گردید...');

      if (this.serverBatchPollInterval) clearInterval(this.serverBatchPollInterval);
      this.serverBatchPollInterval = setInterval(() => this.pollServerBatchStatus(), 1200);

    } catch (e) {
      this.showToast(e.message, 'error');
      document.getElementById('btn-start-bulk').classList.remove('hidden');
      document.getElementById('btn-start-server-bulk').classList.remove('hidden');
      if (btnCancel) btnCancel.classList.add('hidden');
      progressText.innerText = `خطا: ${e.message}`;
    }
  },

  async pollServerBatchStatus() {
    const backendUrl = window.PasargadInquiryEngine ? window.PasargadInquiryEngine.localBackendUrl : '';
    try {
      const res = await fetch(`${backendUrl}/api/scheduler/status`);
      if (!res.ok) return;

      const data = await res.json();
      const p = data.progress || {};
      const isRunning = p.is_running || (data.current_status === 'running');

      const progressBar = document.getElementById('bulk-progress-bar');
      const progressPercent = document.getElementById('bulk-progress-percent');
      const progressText = document.getElementById('bulk-progress-text');

      if (isRunning) {
        const pct = p.percent || Math.round(((p.processed || 0) / (p.total || 1)) * 100) || 0;
        if (progressBar) progressBar.style.width = `${pct}%`;
        if (progressPercent) progressPercent.innerText = `${pct.toLocaleString('fa-IR')}٪`;
        if (progressText) {
          progressText.innerText = `استعلام سروری: چک ${(p.processed || 0).toLocaleString('fa-IR')} از ${(p.total || 0).toLocaleString('fa-IR')} (${p.current_customer || p.current_sayadi || ''})...`;
        }

        const elSuc = document.getElementById('bulk-stat-success');
        if (elSuc) elSuc.innerText = (p.success_count || 0).toLocaleString('fa-IR');
        const elErr = document.getElementById('bulk-stat-error');
        if (elErr) elErr.innerText = (p.error_count || 0).toLocaleString('fa-IR');
        const elTrans = document.getElementById('bulk-stat-in-transit');
        if (elTrans) elTrans.innerText = App.formatMoney(p.in_transit_sum || 0);
        const elBounced = document.getElementById('bulk-stat-bounced');
        if (elBounced) elBounced.innerText = App.formatMoney(p.bounced_sum || 0);

      } else {
        // Finished
        if (this.serverBatchPollInterval) {
          clearInterval(this.serverBatchPollInterval);
          this.serverBatchPollInterval = null;
        }

        if (progressBar) progressBar.style.width = '100%';
        if (progressPercent) progressPercent.innerText = '۱۰۰٪';
        if (progressText) {
          progressText.innerText = `استعلام جامع سروری با موفقیت به پایان رسید! (${(p.success_count || 0).toLocaleString('fa-IR')} موفق، ${(p.unchanged_count || 0).toLocaleString('fa-IR')} بدون تغییر/حفظ تاریخچه)`;
        }

        const btnStart = document.getElementById('btn-start-bulk');
        if (btnStart) btnStart.classList.remove('hidden');
        const btnServer = document.getElementById('btn-start-server-bulk');
        if (btnServer) btnServer.classList.remove('hidden');
        const btnCancel = document.getElementById('btn-cancel-server-bulk');
        if (btnCancel) btnCancel.classList.add('hidden');

        // Reload data from backend so new inquiries reflect in UI
        await this.loadData();
        this.renderCurrentView();
        this.showToast('استعلام جامع سروری سبد چک‌ها با موفقیت ۱۰۰٪ پایان یافت.', 'success');
      }
    } catch (e) {
      console.warn('Error polling server batch status:', e);
    }
  },

  async cancelServerSideBulkInquiry() {
    const backendUrl = window.PasargadInquiryEngine ? window.PasargadInquiryEngine.localBackendUrl : '';
    try {
      await fetch(`${backendUrl}/api/scheduler/cancel`, { method: 'POST' });
      this.showToast('دستور لغو استعلام سروری ارسال شد.', 'warn');
      if (this.serverBatchPollInterval) {
        clearInterval(this.serverBatchPollInterval);
        this.serverBatchPollInterval = null;
      }
      const btnStart = document.getElementById('btn-start-bulk');
      if (btnStart) btnStart.classList.remove('hidden');
      const btnServer = document.getElementById('btn-start-server-bulk');
      if (btnServer) btnServer.classList.remove('hidden');
      const btnCancel = document.getElementById('btn-cancel-server-bulk');
      if (btnCancel) btnCancel.classList.add('hidden');
      document.getElementById('bulk-progress-text').innerText = 'استعلام سروری توسط کاربر لغو شد.';
    } catch (e) {
      this.showToast(e.message, 'error');
    }
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
    const concurrency = parseInt(document.getElementById('bulk-concurrency-select').value) || 2;

    // Create holder lookup map
    const holderMap = {};
    this.state.holders.forEach(h => { holderMap[h.id] = h; });

    document.getElementById('btn-start-bulk').classList.add('hidden');
    const btnServer = document.getElementById('btn-start-server-bulk');
    if (btnServer) btnServer.classList.add('hidden');
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
          const pct = Math.round((state.processed / (state.total || 1)) * 100) || 0;
          progressBar.style.width = `${pct}%`;
          progressPercent.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          progressText.innerText = `در حال بررسی چک ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}...`;

          const pipPct = document.getElementById('pip-progress-pct');
          const pipSub = document.getElementById('pip-progress-sub');
          if (pipPct) pipPct.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          if (pipSub) pipSub.innerText = `${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')} (${state.successCount.toLocaleString('fa-IR')} موفق)`;

          document.getElementById('bulk-stat-success').innerText = state.successCount.toLocaleString('fa-IR');
          document.getElementById('bulk-stat-error').innerText = state.errorCount.toLocaleString('fa-IR');
          const subSuc = document.getElementById('bulk-stat-success-sub');
          if (subSuc) subSuc.innerText = `(${state.successCount.toLocaleString('fa-IR')})`;
          const subErr = document.getElementById('bulk-stat-error-sub');
          if (subErr) subErr.innerText = `(${state.errorCount.toLocaleString('fa-IR')})`;
          document.getElementById('bulk-stat-in-transit').innerText = App.formatMoney(state.inTransitSum);
          document.getElementById('bulk-stat-bounced').innerText = App.formatMoney(state.bouncedSum);

          if (App.isBulkDrilldownOpen()) {
            const now = Date.now();
            if (now - (App.state.bulkDrilldown.lastRenderTime || 0) > 400) {
              App.state.bulkDrilldown.lastRenderTime = now;
              App.updateBulkDrilldownTabUI();
              App.renderBulkDrilldownList();
            }
          }
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
          document.getElementById('btn-start-bulk').classList.remove('hidden');
          const btnServer = document.getElementById('btn-start-server-bulk');
          if (btnServer) btnServer.classList.remove('hidden');

          const pipSub = document.getElementById('pip-progress-sub');
          if (pipSub) pipSub.innerText = `استعلام پایان یافت (${summary.successCount} موفق)`;

          App.state.lastBatchResults = {
            successItems: [...(window.PasargadInquiryEngine.batchState.successItems || [])],
            failedItems: [...(window.PasargadInquiryEngine.batchState.failedItems || [])],
            total: window.PasargadInquiryEngine.batchState.total,
            processed: window.PasargadInquiryEngine.batchState.processed,
            successCount: summary.successCount,
            errorCount: summary.errorCount,
            inTransitSum: summary.inTransitSum,
            clearedSum: summary.clearedSum,
            bouncedSum: summary.bouncedSum,
            timestamp: new Date().toISOString()
          };
          try {
            localStorage.setItem('sayad_last_batch_results', JSON.stringify(App.state.lastBatchResults));
          } catch (e) {}

          if (summary.errorCount > 0 && summary.failedItems && summary.failedItems.length > 0) {
            progressText.innerHTML = `<span class="text-amber-400 font-bold">پایان استعلام: ${summary.successCount} موفق | ${summary.errorCount} ناموفق</span>`;
            const retryBox = document.getElementById('bulk-retry-prompt-box');
            if (retryBox) {
              retryBox.classList.remove('hidden');
              document.getElementById('bulk-failed-count-display').innerText = summary.errorCount.toLocaleString('fa-IR');
            }
            App.showToast(`استعلام پایان یافت. ${summary.errorCount} مورد ناموفق نیاز به بازتلاش دارند.`, 'warn');
          } else {
            progressText.innerText = `عملیات استعلام با موفقیت ۱۰۰٪ به پایان رسید! (${summary.successCount} موفق)`;
            const retryBox = document.getElementById('bulk-retry-prompt-box');
            if (retryBox) retryBox.classList.add('hidden');
            App.showToast('استعلام دسته‌جمعی سبد مشتریان با موفقیت ۱۰۰٪ انجام شد.', 'success');
          }

          if (App.isBulkDrilldownOpen()) {
            App.updateBulkDrilldownTabUI();
            App.renderBulkDrilldownList();
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

    const initialSuccessCount = window.PasargadInquiryEngine.batchState.successCount || 0;

    progressText.innerText = 'در حال استعلام مجدد موارد ناموفق با سرعت بهینه و ضد بلاک...';

    await window.PasargadInquiryEngine.runRetryFailed(
      holderMap,
      {
        onProgress: (state) => {
          const pct = Math.round((state.processed / (state.total || 1)) * 100) || 0;
          progressBar.style.width = `${pct}%`;
          progressPercent.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          progressText.innerText = `در حال بررسی امن چک ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}...`;

          const pipPct = document.getElementById('pip-progress-pct');
          const pipSub = document.getElementById('pip-progress-sub');
          if (pipPct) pipPct.innerText = `${pct.toLocaleString('fa-IR')}٪`;
          if (pipSub) pipSub.innerText = `استعلام مجدد: ${state.processed.toLocaleString('fa-IR')} از ${state.total.toLocaleString('fa-IR')}`;

          document.getElementById('bulk-stat-success').innerText = state.successCount.toLocaleString('fa-IR');
          document.getElementById('bulk-stat-error').innerText = state.errorCount.toLocaleString('fa-IR');
          const subSuc = document.getElementById('bulk-stat-success-sub');
          if (subSuc) subSuc.innerText = `(${state.successCount.toLocaleString('fa-IR')})`;
          const subErr = document.getElementById('bulk-stat-error-sub');
          if (subErr) subErr.innerText = `(${state.errorCount.toLocaleString('fa-IR')})`;
          document.getElementById('bulk-stat-in-transit').innerText = App.formatMoney(state.inTransitSum);
          document.getElementById('bulk-stat-bounced').innerText = App.formatMoney(state.bouncedSum);

          if (App.isBulkDrilldownOpen()) {
            const now = Date.now();
            if (now - (App.state.bulkDrilldown.lastRenderTime || 0) > 400) {
              App.state.bulkDrilldown.lastRenderTime = now;
              App.updateBulkDrilldownTabUI();
              App.renderBulkDrilldownList();
            }
          }
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
          const recoveredCount = summary.successCount - initialSuccessCount;
          const remainingFailed = summary.errorCount;

          App.state.lastBatchResults = {
            successItems: [...(window.PasargadInquiryEngine.batchState.successItems || [])],
            failedItems: [...(window.PasargadInquiryEngine.batchState.failedItems || [])],
            total: window.PasargadInquiryEngine.batchState.total,
            processed: window.PasargadInquiryEngine.batchState.processed,
            successCount: summary.successCount,
            errorCount: summary.errorCount,
            inTransitSum: summary.inTransitSum,
            clearedSum: summary.clearedSum,
            bouncedSum: summary.bouncedSum,
            timestamp: new Date().toISOString()
          };
          try {
            localStorage.setItem('sayad_last_batch_results', JSON.stringify(App.state.lastBatchResults));
          } catch (e) {}

          const pipSub = document.getElementById('pip-progress-sub');

          if (remainingFailed === 0) {
            progressText.innerText = `استعلام مجدد پایان یافت. تمام ${recoveredCount.toLocaleString('fa-IR')} مورد با موفقیت بازیابی شدند (موفقیت ۱۰۰٪).`;
            if (pipSub) pipSub.innerText = `استعلام مجدد: ۱۰۰٪ موفق (${summary.successCount})`;
            App.showToast(`تمام موارد ناموفق (${recoveredCount} فقره) با موفقیت استعلام شدند.`, 'success');
            const rBox = document.getElementById('bulk-retry-prompt-box');
            if (rBox) rBox.classList.add('hidden');
          } else {
            progressText.innerHTML = `<span class="text-amber-400 font-bold">استعلام مجدد پایان یافت: ${recoveredCount.toLocaleString('fa-IR')} مورد بازیابی شد | ${remainingFailed.toLocaleString('fa-IR')} مورد همچنان ناموفق</span>`;
            if (pipSub) pipSub.innerText = `استعلام مجدد: ${recoveredCount} بازیابی شد، ${remainingFailed} ناموفق`;
            App.showToast(`${recoveredCount} فقره با موفقیت بازیابی شد. ${remainingFailed} فقره همچنان ناموفق ماند.`, 'warn');
            const rBox = document.getElementById('bulk-retry-prompt-box');
            if (rBox) {
              rBox.classList.remove('hidden');
              const fc = document.getElementById('bulk-failed-count-display');
              if (fc) fc.innerText = remainingFailed.toLocaleString('fa-IR');
            }
          }

          if (App.isBulkDrilldownOpen()) {
            App.updateBulkDrilldownTabUI();
            App.renderBulkDrilldownList();
          }
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
  // 🔍 Bulk Inquiry Drill-Down & Failure Diagnostics Controller
  // ─────────────────────────────────────────────────────────────
  isBulkDrilldownOpen() {
    const modal = document.getElementById('bulk-drilldown-modal');
    return modal && !modal.classList.contains('hidden');
  },

  openBulkDrilldown(initialTab = null) {
    const batchState = window.PasargadInquiryEngine.batchState;
    const failedItems = (batchState && batchState.failedItems) || (this.state.lastBatchResults && this.state.lastBatchResults.failedItems) || [];
    const successItems = (batchState && batchState.successItems) || (this.state.lastBatchResults && this.state.lastBatchResults.successItems) || [];

    if (initialTab) {
      this.state.bulkDrilldown.activeTab = initialTab;
    } else {
      // Smart default tab selection
      if (failedItems.length > 0) {
        this.state.bulkDrilldown.activeTab = 'failed';
      } else if (successItems.length > 0) {
        this.state.bulkDrilldown.activeTab = 'success';
      } else {
        this.state.bulkDrilldown.activeTab = 'all';
      }
    }

    const modal = document.getElementById('bulk-drilldown-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    this.updateBulkDrilldownTabUI();
    this.renderBulkDrilldownList();
    if (window.lucide) lucide.createIcons();
  },

  closeBulkDrilldownModal() {
    const modal = document.getElementById('bulk-drilldown-modal');
    if (modal) modal.classList.add('hidden');
  },

  setBulkDrilldownTab(tab) {
    this.state.bulkDrilldown.activeTab = tab;
    this.updateBulkDrilldownTabUI();
    this.renderBulkDrilldownList();
    if (window.lucide) lucide.createIcons();
  },

  updateBulkDrilldownTabUI() {
    const tab = this.state.bulkDrilldown.activeTab;
    const btnFailed = document.getElementById('drilldown-tab-failed');
    const btnSuccess = document.getElementById('drilldown-tab-success');
    const btnAll = document.getElementById('drilldown-tab-all');
    const btnRetryAll = document.getElementById('drilldown-btn-retry-all');

    if (btnFailed) {
      btnFailed.className = tab === 'failed'
        ? 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 bg-rose-600 text-white shadow'
        : 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 text-slate-400 hover:text-white';
    }
    if (btnSuccess) {
      btnSuccess.className = tab === 'success'
        ? 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 bg-emerald-600 text-white shadow'
        : 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 text-slate-400 hover:text-white';
    }
    if (btnAll) {
      btnAll.className = tab === 'all'
        ? 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 bg-sky-600 text-white shadow'
        : 'px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-2 text-slate-400 hover:text-white';
    }

    const batchState = window.PasargadInquiryEngine.batchState;
    const failedList = (batchState && batchState.failedItems) || (this.state.lastBatchResults && this.state.lastBatchResults.failedItems) || [];
    if (btnRetryAll) {
      if (failedList.length > 0 && tab !== 'success') {
        btnRetryAll.classList.remove('hidden');
      } else {
        btnRetryAll.classList.add('hidden');
      }
    }

    // Update status badge
    const badgeEl = document.getElementById('drilldown-status-badge');
    if (badgeEl) {
      if (batchState && batchState.isRunning) {
        badgeEl.className = 'px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-sky-500/20 text-sky-400 border border-sky-500/30 inline-flex items-center gap-1.5';
        badgeEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping"></span><span>در حال پردازش (${batchState.processed.toLocaleString('fa-IR')} از ${batchState.total.toLocaleString('fa-IR')})</span>`;
      } else if (failedList.length > 0) {
        badgeEl.className = 'px-2 py-0.5 rounded-full text-[10px] font-mono bg-amber-500/20 text-amber-300 border border-amber-500/30';
        badgeEl.innerText = `${failedList.length.toLocaleString('fa-IR')} مورد ناموفق`;
      } else if ((batchState && batchState.successCount > 0) || (this.state.lastBatchResults && this.state.lastBatchResults.successCount > 0)) {
        badgeEl.className = 'px-2 py-0.5 rounded-full text-[10px] font-mono bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
        badgeEl.innerText = 'استعلام موفق (۱۰۰٪)';
      } else {
        badgeEl.className = 'px-2 py-0.5 rounded-full text-[10px] font-mono bg-slate-800 text-slate-400 border border-slate-700';
        badgeEl.innerText = 'آماده';
      }
    }
  },

  filterBulkDrilldown(query) {
    this.state.bulkDrilldown.searchQuery = (query || '').trim().toLowerCase();
    this.renderBulkDrilldownList();
    if (window.lucide) lucide.createIcons();
  },

  toggleDiagnosticDetail(sayadiId) {
    const cleanId = String(sayadiId).trim();
    if (this.state.bulkDrilldown.expandedDiagnostics.has(cleanId)) {
      this.state.bulkDrilldown.expandedDiagnostics.delete(cleanId);
    } else {
      this.state.bulkDrilldown.expandedDiagnostics.add(cleanId);
    }
    const el = document.getElementById(`diag-${cleanId}`);
    if (el) {
      el.classList.toggle('hidden', !this.state.bulkDrilldown.expandedDiagnostics.has(cleanId));
    }
  },

  async retrySingleDrilldownCheque(sayadiId) {
    if (window.PasargadInquiryEngine.batchState && window.PasargadInquiryEngine.batchState.isRunning) {
      this.showToast('یک استعلام گروهی هم‌اکنون در حال اجراست. لطفاً تا پایان آن صبر کنید.', 'warn');
      return;
    }

    if (this.state.bulkDrilldown.retryingId) {
      this.showToast('یک استعلام تک‌موردی هم‌اکنون در حال اجراست. لطفاً چند لحظه صبر کنید.', 'info');
      return;
    }

    const cleanId = String(sayadiId).trim();
    this.state.bulkDrilldown.retryingId = cleanId;

    const btn = document.getElementById(`btn-retry-${cleanId}`);
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3 h-3 animate-spin"></i><span>در حال بررسی...</span>`;
      if (window.lucide) lucide.createIcons();
    }

    let cheque = this.state.cheques.find(c => String(c.sayadi_id).trim() === cleanId);
    if (!cheque) {
      const bs = window.PasargadInquiryEngine.batchState;
      const fItem = (bs.failedItems || []).find(f => String(f.item.sayadi_id).trim() === cleanId);
      if (fItem) cheque = fItem.item;
    }

    if (!cheque) {
      this.showToast('اطلاعات این فقره چک در سیستم یافت نشد.', 'error');
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3 h-3"></i><span>تلاش مجدد</span>`;
        if (window.lucide) lucide.createIcons();
      }
      this.state.bulkDrilldown.retryingId = null;
      return;
    }

    const bulkSelect = document.getElementById('bulk-holder-select');
    const holderId = bulkSelect ? parseInt(bulkSelect.value) : null;
    const defaultHolder = (holderId && this.state.holders.find(h => h.id === holderId)) || this.state.holders[0];
    const holderMap = {};
    this.state.holders.forEach(h => { holderMap[h.id] = h; });

    try {
      const res = await window.PasargadInquiryEngine.retrySingleCheque(cheque, holderMap, { defaultHolder });

      const bs = window.PasargadInquiryEngine.batchState;

      if (res.status === 'success') {
        if (res.result && res.result.holder_id) {
          cheque.holder_id = res.result.holder_id;
        }
        cheque.updated_at = new Date().toISOString();

        const inquiryRecord = {
          id: Date.now() + Math.random(),
          sayadi_id: cheque.sayadi_id,
          holder_id: res.result.holder_id || cheque.holder_id || defaultHolder.id,
          customer_id: cheque.customer_id,
          inquiry_type: 'pasargad',
          in_transit_amount: res.result.in_transit_amount || 0,
          in_transit_count: res.result.in_transit_count || 0,
          cleared_amount: res.result.cleared_amount || 0,
          cleared_count: res.result.cleared_count || 0,
          bounced_amount: res.result.bounced_amount || 0,
          bounced_count: res.result.bounced_count || 0,
          inquiry_time: res.result.inquiry_time || new Date().toISOString(),
          status: 'success'
        };

        const existingIdx = this.state.inquiries.findIndex(i => String(i.sayadi_id).trim() === cleanId);
        if (existingIdx >= 0) {
          this.state.inquiries[existingIdx] = inquiryRecord;
        } else {
          this.state.inquiries.unshift(inquiryRecord);
        }
        this.saveData();

        // Sync lastBatchResults
        this.state.lastBatchResults = {
          successItems: [...(bs.successItems || [])],
          failedItems: [...(bs.failedItems || [])],
          total: bs.total,
          processed: bs.processed,
          successCount: bs.successCount,
          errorCount: bs.errorCount,
          inTransitSum: bs.inTransitSum,
          clearedSum: bs.clearedSum,
          bouncedSum: bs.bouncedSum,
          timestamp: new Date().toISOString()
        };
        try {
          localStorage.setItem('sayad_last_batch_results', JSON.stringify(this.state.lastBatchResults));
        } catch (e) {}

        // Update bulk modal counters
        const sEl = document.getElementById('bulk-stat-success');
        if (sEl) sEl.innerText = bs.successCount.toLocaleString('fa-IR');
        const eEl = document.getElementById('bulk-stat-error');
        if (eEl) eEl.innerText = bs.errorCount.toLocaleString('fa-IR');
        const subSuc = document.getElementById('bulk-stat-success-sub');
        if (subSuc) subSuc.innerText = `(${bs.successCount.toLocaleString('fa-IR')})`;
        const subErr = document.getElementById('bulk-stat-error-sub');
        if (subErr) subErr.innerText = `(${bs.errorCount.toLocaleString('fa-IR')})`;
        const inTransitEl = document.getElementById('bulk-stat-in-transit');
        if (inTransitEl) inTransitEl.innerText = this.formatMoney(bs.inTransitSum);
        const bouncedEl = document.getElementById('bulk-stat-bounced');
        if (bouncedEl) bouncedEl.innerText = this.formatMoney(bs.bouncedSum);

        const retryBox = document.getElementById('bulk-retry-prompt-box');
        if (retryBox) {
          if (bs.errorCount <= 0) {
            retryBox.classList.add('hidden');
          } else {
            const fc = document.getElementById('bulk-failed-count-display');
            if (fc) fc.innerText = bs.errorCount.toLocaleString('fa-IR');
          }
        }

        this.showToast(`استعلام صیادی ${cheque.sayadi_id} با موفقیت دریافت و ثبت شد.`, 'success');
        this.updateBulkDrilldownTabUI();
        this.renderBulkDrilldownList();
        this.renderCurrentView();
      } else {
        // Sync lastBatchResults on failure update
        this.state.lastBatchResults = {
          successItems: [...(bs.successItems || [])],
          failedItems: [...(bs.failedItems || [])],
          total: bs.total,
          processed: bs.processed,
          successCount: bs.successCount,
          errorCount: bs.errorCount,
          inTransitSum: bs.inTransitSum,
          clearedSum: bs.clearedSum,
          bouncedSum: bs.bouncedSum,
          timestamp: new Date().toISOString()
        };
        try {
          localStorage.setItem('sayad_last_batch_results', JSON.stringify(this.state.lastBatchResults));
        } catch (e) {}

        this.showToast(res.reason || 'استعلام این فقره چک همچنان ناموفق بود.', 'warn');
        this.updateBulkDrilldownTabUI();
        this.renderBulkDrilldownList();
      }
    } catch (err) {
      this.showToast(`خطا در استعلام مجدد: ${err.message}`, 'error');
      this.updateBulkDrilldownTabUI();
      this.renderBulkDrilldownList();
    } finally {
      this.state.bulkDrilldown.retryingId = null;
    }
  },

  retryFailedBatchFromDrilldown() {
    this.closeBulkDrilldownModal();
    this.openBulkInquiryModal();
    this.retryFailedBatch();
  },

  exportBulkDrilldownToExcel() {
    if (!window.XLSX) {
      this.showToast('کتابخانه اکسل در دسترس نیست.', 'error');
      return;
    }

    const batchState = window.PasargadInquiryEngine.batchState;
    const failedItems = (batchState && batchState.failedItems) || (this.state.lastBatchResults && this.state.lastBatchResults.failedItems) || [];
    const successItems = (batchState && batchState.successItems) || (this.state.lastBatchResults && this.state.lastBatchResults.successItems) || [];
    const tab = this.state.bulkDrilldown.activeTab;

    let exportRows = [];

    if (tab === 'failed') {
      exportRows = failedItems.map((f, idx) => {
        const cust = this.state.customers.find(c => String(c.id) === String(f.item.customer_id));
        return {
          'ردیف': idx + 1,
          'شناسه صیادی': f.item.sayadi_id,
          'شماره چک': f.item.cheque_number || '---',
          'نام مشتری / صادرکننده': cust ? cust.full_name : (f.item.customer_name || 'نامشخص'),
          'کد ملی مشتری': cust ? (cust.national_id || '---') : '---',
          'مبلغ چک (ریال)': f.item.amount || 0,
          'مبلغ چک (تومان)': Math.round((f.item.amount || 0) / 10),
          'نام بانک': f.item.bank_name || '---',
          'تاریخ سررسید': f.item.cheque_date || '---',
          'وضعیت': 'ناموفق',
          'علت دقیق عدم موفقیت': f.reason || '---',
          'دسته‌بندی خطا': f.status || 'خطا',
          'جزئیات فنی / پاسخ خام سرور': typeof f.rawReason === 'object' ? JSON.stringify(f.rawReason) : (f.rawReason || '---'),
          'زمان ثبت': f.timestamp || '---'
        };
      });
    } else if (tab === 'success') {
      exportRows = successItems.map((s, idx) => {
        const cust = this.state.customers.find(c => String(c.id) === String(s.item.customer_id));
        const res = s.result || {};
        const holder = this.state.holders.find(h => h.id === (res.holder_id || s.item.holder_id));
        const holderName = res.holder_name || (holder ? holder.full_name : 'یافت‌شده');

        return {
          'ردیف': idx + 1,
          'شناسه صیادی': s.item.sayadi_id,
          'شماره چک': s.item.cheque_number || '---',
          'نام مشتری / صادرکننده': cust ? cust.full_name : (s.item.customer_name || 'نامشخص'),
          'کد ملی مشتری': cust ? (cust.national_id || '---') : '---',
          'مبلغ چک (ریال)': s.item.amount || 0,
          'مبلغ چک (تومان)': Math.round((s.item.amount || 0) / 10),
          'نام بانک': s.item.bank_name || '---',
          'تاریخ سررسید': s.item.cheque_date || '---',
          'دارنده شناسایی‌شده': holderName,
          'مبلغ در راه (ریال)': res.in_transit_amount || 0,
          'مبلغ کارسازی‌شده (ریال)': res.cleared_amount || 0,
          'مبلغ برگشتی (ریال)': res.bounced_amount || 0,
          'وضعیت برگشتی': (res.bounced_amount || 0) > 0 ? 'دارای برگشتی' : 'فاقد برگشتی',
          'وضعیت': 'موفق',
          'زمان استعلام': s.timestamp || res.inquiry_time || '---'
        };
      });
    } else {
      const fRows = failedItems.map((f, idx) => {
        const cust = this.state.customers.find(c => String(c.id) === String(f.item.customer_id));
        return {
          'ردیف': idx + 1,
          'شناسه صیادی': f.item.sayadi_id,
          'شماره چک': f.item.cheque_number || '---',
          'نام مشتری': cust ? cust.full_name : (f.item.customer_name || 'نامشخص'),
          'کد ملی مشتری': cust ? (cust.national_id || '---') : '---',
          'مبلغ چک (ریال)': f.item.amount || 0,
          'مبلغ چک (تومان)': Math.round((f.item.amount || 0) / 10),
          'بانک': f.item.bank_name || '---',
          'سررسید': f.item.cheque_date || '---',
          'وضعیت استعلام': 'ناموفق',
          'علت دقیق / دارنده': f.reason || '---',
          'مبلغ در راه (ریال)': 0,
          'مبلغ برگشتی (ریال)': 0
        };
      });

      const sRows = successItems.map((s, idx) => {
        const cust = this.state.customers.find(c => String(c.id) === String(s.item.customer_id));
        const res = s.result || {};
        const holder = this.state.holders.find(h => h.id === (res.holder_id || s.item.holder_id));
        const holderName = res.holder_name || (holder ? holder.full_name : 'یافت‌شده');

        return {
          'ردیف': fRows.length + idx + 1,
          'شناسه صیادی': s.item.sayadi_id,
          'شماره چک': s.item.cheque_number || '---',
          'نام مشتری': cust ? cust.full_name : (s.item.customer_name || 'نامشخص'),
          'کد ملی مشتری': cust ? (cust.national_id || '---') : '---',
          'مبلغ چک (ریال)': s.item.amount || 0,
          'مبلغ چک (تومان)': Math.round((s.item.amount || 0) / 10),
          'بانک': s.item.bank_name || '---',
          'سررسید': s.item.cheque_date || '---',
          'وضعیت استعلام': 'موفق',
          'علت دقیق / دارنده': `دارنده: ${holderName}`,
          'مبلغ در راه (ریال)': res.in_transit_amount || 0,
          'مبلغ برگشتی (ریال)': res.bounced_amount || 0
        };
      });

      exportRows = [...fRows, ...sRows];
    }

    if (exportRows.length === 0) {
      this.showToast('داده‌ای برای خروجی اکسل در این بخش وجود ندارد.', 'warn');
      return;
    }

    const ws = XLSX.utils.json_to_sheet(exportRows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "گزارش استعلام");
    const filename = `گزارش_استعلام_گروهی_${tab}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(wb, filename);
    this.showToast(`فایل اکسل با ${exportRows.length} ردیف دانلود شد.`, 'success');
  },

  renderBulkDrilldownList() {
    const container = document.getElementById('drilldown-content-container');
    if (!container) return;

    const prevScrollTop = container.scrollTop;

    const batchState = window.PasargadInquiryEngine.batchState;
    const failedItems = (batchState && batchState.failedItems) || (this.state.lastBatchResults && this.state.lastBatchResults.failedItems) || [];
    const successItems = (batchState && batchState.successItems) || (this.state.lastBatchResults && this.state.lastBatchResults.successItems) || [];

    // Update tab counts
    const countFailedEl = document.getElementById('drilldown-count-failed');
    const countSuccessEl = document.getElementById('drilldown-count-success');
    const countAllEl = document.getElementById('drilldown-count-all');
    if (countFailedEl) countFailedEl.innerText = failedItems.length.toLocaleString('fa-IR');
    if (countSuccessEl) countSuccessEl.innerText = successItems.length.toLocaleString('fa-IR');
    if (countAllEl) countAllEl.innerText = (failedItems.length + successItems.length).toLocaleString('fa-IR');

    // Update footer stats
    const fTotal = document.getElementById('drilldown-footer-total');
    const fSuc = document.getElementById('drilldown-footer-success');
    const fFail = document.getElementById('drilldown-footer-failed');
    const fInTransit = document.getElementById('drilldown-footer-in-transit');
    const fBounced = document.getElementById('drilldown-footer-bounced');
    if (fTotal) fTotal.innerText = (failedItems.length + successItems.length).toLocaleString('fa-IR');
    if (fSuc) fSuc.innerText = successItems.length.toLocaleString('fa-IR');
    if (fFail) fFail.innerText = failedItems.length.toLocaleString('fa-IR');
    if (fInTransit) fInTransit.innerText = this.formatMoney((batchState && batchState.inTransitSum) || (this.state.lastBatchResults && this.state.lastBatchResults.inTransitSum) || 0);
    if (fBounced) fBounced.innerText = this.formatMoney((batchState && batchState.bouncedSum) || (this.state.lastBatchResults && this.state.lastBatchResults.bouncedSum) || 0);

    const activeTab = this.state.bulkDrilldown.activeTab;
    const q = (this.state.bulkDrilldown.searchQuery || '').trim().toLowerCase();

    // If nothing has run yet
    if (failedItems.length === 0 && successItems.length === 0) {
      container.innerHTML = `
        <div class="p-12 text-center space-y-4">
          <div class="w-16 h-16 mx-auto rounded-3xl bg-slate-800/80 flex items-center justify-center text-slate-400 border border-slate-700">
            <i data-lucide="zap-off" class="w-8 h-8"></i>
          </div>
          <div class="space-y-1">
            <h4 class="font-bold text-slate-200 text-sm">هنوز استعلام گروهی اجرا نشده است</h4>
            <p class="text-xs text-slate-400 max-w-md mx-auto leading-relaxed">
              برای مشاهده موارد موفق و ناموفق، لطفاً ابتدا دکمه «شروع استعلام گروهی» را در پنجره استعلام کلیک کنید تا چک‌ها پردازش شوند.
            </p>
          </div>
          <button onclick="App.closeBulkDrilldownModal(); App.openBulkInquiryModal();" class="px-5 py-2.5 bg-gradient-to-r from-blue-600 to-sky-500 hover:from-blue-500 hover:to-sky-400 text-white rounded-2xl text-xs font-bold shadow-lg transition">
            باز کردن پنجره استعلام گروهی
          </button>
        </div>
      `;
      if (window.lucide) lucide.createIcons();
      return;
    }

    if (activeTab === 'failed') {
      let list = [...failedItems];
      if (q) {
        list = list.filter(f => {
          const cust = this.state.customers.find(c => String(c.id) === String(f.item.customer_id));
          const custName = cust ? cust.full_name.toLowerCase() : '';
          const custNid = cust ? (cust.national_id || '') : '';
          const sayadiId = String(f.item.sayadi_id || '').trim();
          const chequeNum = String(f.item.cheque_number || '').trim();
          const bankName = String(f.item.bank_name || '').toLowerCase();
          const reason = String(f.reason || '').toLowerCase();
          const status = String(f.status || '').toLowerCase();
          const rawDetail = typeof f.rawReason === 'object' ? JSON.stringify(f.rawReason).toLowerCase() : String(f.rawReason || '').toLowerCase();

          return (
            sayadiId.includes(q) ||
            chequeNum.includes(q) ||
            bankName.includes(q) ||
            reason.includes(q) ||
            status.includes(q) ||
            rawDetail.includes(q) ||
            custName.includes(q) ||
            custNid.includes(q)
          );
        });
      }

      if (list.length === 0) {
        container.innerHTML = `
          <div class="p-10 text-center space-y-3">
            <div class="w-14 h-14 mx-auto rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
              <i data-lucide="check-check" class="w-7 h-7"></i>
            </div>
            <h4 class="font-bold text-emerald-300 text-sm">${q ? 'هیچ چک ناموفقی با این عبارت جستجو یافت نشد.' : 'تبریک! هیچ چک ناموفقی در این استعلام وجود ندارد.'}</h4>
            <p class="text-xs text-slate-400">${q ? 'عبارت جستجو را تغییر دهید.' : 'تمام چک‌ها با موفقیت از درگاه بانک استعلام شدند.'}</p>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = `
        <div class="overflow-x-auto">
          <table class="w-full text-right text-xs">
            <thead class="bg-slate-950/80 text-slate-400 font-semibold border-b border-slate-800 sticky top-0 backdrop-blur-md z-10">
              <tr>
                <th class="py-3 px-3.5 text-center w-12">#</th>
                <th class="py-3 px-4">صادرکننده / مشتری</th>
                <th class="py-3 px-4">شناسه صیادی و شماره چک</th>
                <th class="py-3 px-4">مبلغ چک</th>
                <th class="py-3 px-4">بانک و سررسید</th>
                <th class="py-3 px-4 min-w-[260px]">علت دقیق عدم موفقیت</th>
                <th class="py-3 px-4 text-center w-28">عملیات</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              ${list.map((f, idx) => {
                const cust = this.state.customers.find(c => String(c.id) === String(f.item.customer_id));
                const custName = cust ? cust.full_name : (f.item.customer_name || 'نامشخص');
                const cleanSayadi = String(f.item.sayadi_id).trim();
                const isExpanded = this.state.bulkDrilldown.expandedDiagnostics.has(cleanSayadi);
                const isRetryingThis = this.state.bulkDrilldown.retryingId === cleanSayadi;
                
                let badgeClass = 'bg-rose-500/15 border-rose-500/30 text-rose-300';
                let iconName = 'alert-circle';
                let reasonCategory = 'خطای درگاه بانک';

                if (f.status === 'rate_limited') {
                  badgeClass = 'bg-amber-500/15 border-amber-500/30 text-amber-300';
                  iconName = 'hourglass';
                  reasonCategory = 'ترافیک موقت درگاه (۴۲۹)';
                } else if (f.status === 'not_in_cartable') {
                  badgeClass = 'bg-purple-500/15 border-purple-500/30 text-purple-300';
                  iconName = 'search-x';
                  reasonCategory = 'عدم وجود در کارتابل ۹ دارنده';
                } else if (f.status === 'connection_error') {
                  badgeClass = 'bg-orange-500/15 border-orange-500/30 text-orange-300';
                  iconName = 'wifi-off';
                  reasonCategory = 'خطای شبکه / ارتباط با سرور';
                } else if (f.status === 'idcode_mismatch') {
                  badgeClass = 'bg-red-500/15 border-red-500/30 text-red-300';
                  iconName = 'user-x';
                  reasonCategory = 'عدم تطابق کدملی با صیادی';
                } else if (f.status === 'invalid_holder') {
                  badgeClass = 'bg-slate-700/40 border-slate-600 text-slate-300';
                  iconName = 'user-x';
                  reasonCategory = 'تنظیمات دارنده در سامانه';
                }

                const rawText = typeof f.rawReason === 'object' ? JSON.stringify(f.rawReason, null, 2) : String(f.rawReason || f.reason || 'بدون جزئیات خام');

                return `
                  <tr class="hover:bg-slate-800/40 transition">
                    <td class="py-3 px-3.5 text-center font-mono text-slate-400 text-[11px]">${(idx + 1).toLocaleString('fa-IR')}</td>
                    <td class="py-3 px-4">
                      <div class="font-bold text-slate-200">${this.escapeHtml(custName)}</div>
                      ${cust && cust.national_id ? `<div class="text-[10px] text-slate-400 font-mono mt-0.5">${this.escapeHtml(cust.national_id)}</div>` : ''}
                    </td>
                    <td class="py-3 px-4">
                      <div class="flex items-center gap-1.5">
                        <span class="font-mono font-bold text-sky-400 text-xs">${this.escapeHtml(cleanSayadi)}</span>
                        <button onclick="App.copyToClipboard('${cleanSayadi}');" class="text-slate-400 hover:text-white p-1 rounded transition" title="کپی شناسه">
                          <i data-lucide="copy" class="w-3 h-3"></i>
                        </button>
                      </div>
                      <div class="text-[10px] text-slate-400 font-mono mt-0.5">شماره چک: ${this.escapeHtml(f.item.cheque_number || '---')}</div>
                    </td>
                    <td class="py-3 px-4">
                      <div class="font-mono font-bold text-amber-300 text-xs">${App.formatMoney(f.item.amount)} ریال</div>
                      <div class="text-[10px] text-slate-400 mt-0.5 font-mono">${(Math.round((f.item.amount || 0) / 10)).toLocaleString('fa-IR')} تومان</div>
                    </td>
                    <td class="py-3 px-4 text-slate-300 text-xs">
                      <div class="font-semibold">${this.escapeHtml(f.item.bank_name || '---')}</div>
                      <div class="text-[10px] text-slate-400 font-mono mt-0.5">سررسید: ${this.escapeHtml(f.item.cheque_date || '---')}</div>
                    </td>
                    <td class="py-3 px-4">
                      <div class="p-2.5 rounded-xl border ${badgeClass} space-y-1">
                        <div class="flex items-center gap-1.5 font-bold text-xs">
                          <i data-lucide="${iconName}" class="w-3.5 h-3.5 shrink-0"></i>
                          <span>${this.escapeHtml(f.reason || 'علت ثبت نشده')}</span>
                        </div>
                        <div class="flex items-center justify-between text-[10px] opacity-80 pt-0.5">
                          <span class="font-sans">${reasonCategory}</span>
                          <button onclick="App.toggleDiagnosticDetail('${cleanSayadi}')" class="underline hover:text-white flex items-center gap-0.5 transition" title="مشاهده جزئیات پاسخ سرور">
                            <i data-lucide="terminal" class="w-2.5 h-2.5"></i>
                            <span>جزئیات فنی</span>
                          </button>
                        </div>
                      </div>
                      <div id="diag-${cleanSayadi}" class="${isExpanded ? '' : 'hidden'} mt-1.5 p-2 bg-slate-950 rounded-xl text-[10px] font-mono text-slate-300 border border-slate-800/80 break-all select-all">
                        <div class="text-[9px] text-slate-500 mb-0.5">پاسخ تشخیصی سرور:</div>
                        ${this.escapeHtml(rawText)}
                      </div>
                    </td>
                    <td class="py-3 px-4 text-center">
                      <button id="btn-retry-${cleanSayadi}" onclick="App.retrySingleDrilldownCheque('${cleanSayadi}')" ${isRetryingThis ? 'disabled' : ''} class="px-3 py-1.5 bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-white text-xs font-bold rounded-xl flex items-center justify-center gap-1.5 shadow transition w-full ${isRetryingThis ? 'opacity-70 cursor-wait' : ''}" title="استعلام مجدد فقط همین چک">
                        <i data-lucide="refresh-cw" class="w-3 h-3 ${isRetryingThis ? 'animate-spin' : ''}"></i>
                        <span>${isRetryingThis ? 'در حال بررسی...' : 'تلاش مجدد'}</span>
                      </button>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
      container.scrollTop = prevScrollTop;
      if (window.lucide) lucide.createIcons();
      return;
    }

    if (activeTab === 'success') {
      let list = [...successItems];
      if (q) {
        list = list.filter(s => {
          const cust = this.state.customers.find(c => String(c.id) === String(s.item.customer_id));
          const custName = cust ? cust.full_name.toLowerCase() : '';
          const custNid = cust ? (cust.national_id || '') : '';
          const holderName = s.result ? (s.result.holder_name || '').toLowerCase() : '';
          const sayadiId = String(s.item.sayadi_id || '').trim();
          const chequeNum = String(s.item.cheque_number || '').trim();
          const bankName = String(s.item.bank_name || '').toLowerCase();
          const hasBounced = s.result && (s.result.bounced_amount || 0) > 0;
          const isBouncedQuery = (q.includes('برگشت') || q.includes('bounced')) && hasBounced;
          const isNoBouncedQuery = (q.includes('فاقد') || q.includes('سالم') || q.includes('سبز')) && !hasBounced;
          const isInTransitQuery = (q.includes('راه') || q.includes('transit')) && (s.result && (s.result.in_transit_amount || 0) > 0);

          return (
            sayadiId.includes(q) ||
            chequeNum.includes(q) ||
            bankName.includes(q) ||
            custName.includes(q) ||
            custNid.includes(q) ||
            holderName.includes(q) ||
            isBouncedQuery ||
            isNoBouncedQuery ||
            isInTransitQuery
          );
        });
      }

      if (list.length === 0) {
        container.innerHTML = `
          <div class="p-10 text-center space-y-3">
            <div class="w-14 h-14 mx-auto rounded-2xl bg-slate-800 flex items-center justify-center text-slate-400">
              <i data-lucide="inbox" class="w-7 h-7"></i>
            </div>
            <h4 class="font-bold text-slate-300 text-sm">هیچ مورد موفقی یافت نشد</h4>
            <p class="text-xs text-slate-400">موردی مطابق فیلتر جاری یافت نشد.</p>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = `
        <div class="overflow-x-auto">
          <table class="w-full text-right text-xs">
            <thead class="bg-slate-950/80 text-slate-400 font-semibold border-b border-slate-800 sticky top-0 backdrop-blur-md z-10">
              <tr>
                <th class="py-3 px-3.5 text-center w-12">#</th>
                <th class="py-3 px-4">صادرکننده / مشتری</th>
                <th class="py-3 px-4">شناسه صیادی و چک</th>
                <th class="py-3 px-4">مبلغ چک</th>
                <th class="py-3 px-4">دارنده شناسایی‌شده</th>
                <th class="py-3 px-4">مبلغ در راه</th>
                <th class="py-3 px-4">کارسازی‌شده</th>
                <th class="py-3 px-4">وضعیت برگشتی</th>
                <th class="py-3 px-4 text-center">بانک و تاریخ</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              ${list.map((s, idx) => {
                const cust = this.state.customers.find(c => String(c.id) === String(s.item.customer_id));
                const custName = cust ? cust.full_name : (s.item.customer_name || 'نامشخص');
                const cleanSayadi = String(s.item.sayadi_id).trim();
                const res = s.result || {};
                const hasBounced = (res.bounced_amount || 0) > 0;
                const holder = this.state.holders.find(h => h.id === (res.holder_id || s.item.holder_id));
                const holderName = res.holder_name || (holder ? holder.full_name : 'یافت‌شده');

                return `
                  <tr class="hover:bg-slate-800/40 transition">
                    <td class="py-3 px-3.5 text-center font-mono text-slate-400 text-[11px]">${(idx + 1).toLocaleString('fa-IR')}</td>
                    <td class="py-3 px-4">
                      <div class="font-bold text-slate-200">${this.escapeHtml(custName)}</div>
                      ${cust && cust.national_id ? `<div class="text-[10px] text-slate-400 font-mono mt-0.5">${this.escapeHtml(cust.national_id)}</div>` : ''}
                    </td>
                    <td class="py-3 px-4">
                      <div class="flex items-center gap-1.5">
                        <span class="font-mono font-bold text-sky-400 text-xs">${this.escapeHtml(cleanSayadi)}</span>
                        <button onclick="App.copyToClipboard('${cleanSayadi}');" class="text-slate-400 hover:text-white p-1 rounded transition" title="کپی شناسه">
                          <i data-lucide="copy" class="w-3 h-3"></i>
                        </button>
                      </div>
                      <div class="text-[10px] text-slate-400 font-mono mt-0.5">شماره: ${this.escapeHtml(s.item.cheque_number || '---')}</div>
                    </td>
                    <td class="py-3 px-4">
                      <div class="font-mono font-bold text-emerald-400 text-xs">${App.formatMoney(s.item.amount)} ریال</div>
                      <div class="text-[10px] text-slate-400 mt-0.5 font-mono">${(Math.round((s.item.amount || 0) / 10)).toLocaleString('fa-IR')} تومان</div>
                    </td>
                    <td class="py-3 px-4">
                      <span class="px-2.5 py-1 rounded-xl bg-sky-500/10 border border-sky-500/30 text-sky-300 font-semibold text-xs inline-flex items-center gap-1">
                        <i data-lucide="user-check" class="w-3 h-3"></i>
                        ${this.escapeHtml(holderName)}
                      </span>
                    </td>
                    <td class="py-3 px-4 font-mono font-semibold text-sky-300">${App.formatMoney(res.in_transit_amount || 0)}</td>
                    <td class="py-3 px-4 font-mono font-semibold text-emerald-300">${App.formatMoney(res.cleared_amount || 0)}</td>
                    <td class="py-3 px-4">
                      ${hasBounced 
                        ? `<span class="px-2 py-1 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/30 font-bold font-mono text-[11px] inline-flex items-center gap-1">
                            <i data-lucide="alert-triangle" class="w-3 h-3"></i>
                            ${App.formatMoney(res.bounced_amount)} ریال
                           </span>`
                        : `<span class="px-2 py-0.5 rounded-lg bg-emerald-500/10 text-emerald-400 text-[11px] border border-emerald-500/20 inline-flex items-center gap-1">
                            <i data-lucide="check" class="w-3 h-3"></i> فاقد برگشتی
                           </span>`
                      }
                    </td>
                    <td class="py-3 px-4 text-center text-slate-400 text-[11px]">
                      <div>${this.escapeHtml(s.item.bank_name || '---')}</div>
                      <div class="font-mono text-[10px] mt-0.5">${this.escapeHtml(s.item.cheque_date || '---')}</div>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
      container.scrollTop = prevScrollTop;
      if (window.lucide) lucide.createIcons();
      return;
    }

    if (activeTab === 'all') {
      const combined = [
        ...failedItems.map(f => ({ type: 'failed', ...f })),
        ...successItems.map(s => ({ type: 'success', ...s }))
      ];

      let list = combined;
      if (q) {
        list = list.filter(item => {
          const cust = this.state.customers.find(c => String(c.id) === String(item.item.customer_id));
          const custName = cust ? cust.full_name.toLowerCase() : '';
          const custNid = cust ? (cust.national_id || '') : '';
          const holderName = item.result ? (item.result.holder_name || '').toLowerCase() : '';
          const reasonText = String(item.reason || '').toLowerCase();
          const sayadiId = String(item.item.sayadi_id || '').trim();
          const chequeNum = String(item.item.cheque_number || '').trim();
          const bankName = String(item.item.bank_name || '').toLowerCase();
          const isSuc = item.type === 'success';
          const isStatusQuery = (q === 'موفق' && isSuc) || (q === 'ناموفق' && !isSuc);
          const hasBounced = item.result && (item.result.bounced_amount || 0) > 0;
          const isBouncedQuery = (q.includes('برگشت') || q.includes('bounced')) && hasBounced;

          return (
            sayadiId.includes(q) ||
            chequeNum.includes(q) ||
            bankName.includes(q) ||
            custName.includes(q) ||
            custNid.includes(q) ||
            holderName.includes(q) ||
            reasonText.includes(q) ||
            isStatusQuery ||
            isBouncedQuery
          );
        });
      }

      if (list.length === 0) {
        container.innerHTML = `
          <div class="p-10 text-center space-y-3">
            <div class="w-14 h-14 mx-auto rounded-2xl bg-slate-800 flex items-center justify-center text-slate-400">
              <i data-lucide="inbox" class="w-7 h-7"></i>
            </div>
            <h4 class="font-bold text-slate-300 text-sm">موردی یافت نشد</h4>
            <p class="text-xs text-slate-400">${q ? 'هیچ چکی مطابق با عبارت جستجوی واردشده پیدا نشد.' : 'لیست چک‌ها در این بخش خالی است.'}</p>
          </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
      }

      container.innerHTML = `
        <div class="overflow-x-auto">
          <table class="w-full text-right text-xs">
            <thead class="bg-slate-950/80 text-slate-400 font-semibold border-b border-slate-800 sticky top-0 backdrop-blur-md z-10">
              <tr>
                <th class="py-3 px-3.5 text-center w-12">#</th>
                <th class="py-3 px-4">صادرکننده / مشتری</th>
                <th class="py-3 px-4">شناسه صیادی</th>
                <th class="py-3 px-4">مبلغ چک</th>
                <th class="py-3 px-4">بانک و تاریخ</th>
                <th class="py-3 px-4">وضعیت</th>
                <th class="py-3 px-4">شرح وضعیت / دارنده</th>
                <th class="py-3 px-4 text-center w-28">عملیات</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              ${list.map((cItem, idx) => {
                const cust = this.state.customers.find(c => String(c.id) === String(cItem.item.customer_id));
                const custName = cust ? cust.full_name : (cItem.item.customer_name || 'نامشخص');
                const cleanSayadi = String(cItem.item.sayadi_id).trim();
                const isSuc = cItem.type === 'success';
                const isRetryingThis = this.state.bulkDrilldown.retryingId === cleanSayadi;

                return `
                  <tr class="hover:bg-slate-800/40 transition">
                    <td class="py-3 px-3.5 text-center font-mono text-slate-400 text-[11px]">${(idx + 1).toLocaleString('fa-IR')}</td>
                    <td class="py-3 px-4">
                      <div class="font-bold text-slate-200">${this.escapeHtml(custName)}</div>
                      ${cust && cust.national_id ? `<div class="text-[10px] text-slate-400 font-mono mt-0.5">${this.escapeHtml(cust.national_id)}</div>` : ''}
                    </td>
                    <td class="py-3 px-4">
                      <div class="flex items-center gap-1.5">
                        <span class="font-mono font-bold text-sky-400 text-xs">${this.escapeHtml(cleanSayadi)}</span>
                        <button onclick="App.copyToClipboard('${cleanSayadi}');" class="text-slate-400 hover:text-white p-1 rounded transition" title="کپی شناسه">
                          <i data-lucide="copy" class="w-3 h-3"></i>
                        </button>
                      </div>
                      <div class="text-[10px] text-slate-400 font-mono mt-0.5">شماره: ${this.escapeHtml(cItem.item.cheque_number || '---')}</div>
                    </td>
                    <td class="py-3 px-4">
                      <div class="font-mono font-bold text-xs">${App.formatMoney(cItem.item.amount)} ریال</div>
                      <div class="text-[10px] text-slate-400 mt-0.5 font-mono">${(Math.round((cItem.item.amount || 0) / 10)).toLocaleString('fa-IR')} تومان</div>
                    </td>
                    <td class="py-3 px-4 text-slate-300 text-xs">${this.escapeHtml(cItem.item.bank_name || '---')} (${this.escapeHtml(cItem.item.cheque_date || '---')})</td>
                    <td class="py-3 px-4">
                      ${isSuc 
                        ? `<span class="px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-bold inline-flex items-center gap-1">
                            <i data-lucide="check-circle-2" class="w-3 h-3"></i> موفق
                           </span>`
                        : `<span class="px-2.5 py-1 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-500/30 text-xs font-bold inline-flex items-center gap-1">
                            <i data-lucide="alert-triangle" class="w-3 h-3"></i> ناموفق
                           </span>`
                      }
                    </td>
                    <td class="py-3 px-4 text-xs">
                      ${isSuc 
                        ? `<span class="text-emerald-300">دارنده: ${this.escapeHtml(cItem.result ? cItem.result.holder_name : 'یافت‌شده')} (در راه: ${App.formatMoney(cItem.result ? cItem.result.in_transit_amount : 0)})</span>`
                        : `<span class="text-rose-300 font-semibold">${this.escapeHtml(cItem.reason || 'ناموفق')}</span>`
                      }
                    </td>
                    <td class="py-3 px-4 text-center">
                      ${!isSuc 
                        ? `<button id="btn-retry-${cleanSayadi}" onclick="App.retrySingleDrilldownCheque('${cleanSayadi}')" ${isRetryingThis ? 'disabled' : ''} class="px-3 py-1 bg-amber-600 hover:bg-amber-500 text-white rounded-xl text-xs font-bold transition flex items-center justify-center gap-1 w-full ${isRetryingThis ? 'opacity-70 cursor-wait' : ''}">
                            <i data-lucide="refresh-cw" class="w-3 h-3 ${isRetryingThis ? 'animate-spin' : ''}"></i><span>${isRetryingThis ? 'در حال بررسی...' : 'تلاش مجدد'}</span>
                           </button>`
                        : `<span class="text-slate-500 text-xs">---</span>`
                      }
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      `;
      container.scrollTop = prevScrollTop;
      if (window.lucide) lucide.createIcons();
      return;
    }
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

  escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  },

  copyToClipboard(text, message = 'شناسه صیادی با موفقیت در حافظه کپی شد') {
    if (!text) return;
    const clean = String(text).trim();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(clean).then(() => {
        this.showToast(message, 'info');
      }).catch(() => {
        this.fallbackCopyText(clean, message);
      });
    } else {
      this.fallbackCopyText(clean, message);
    }
  },

  fallbackCopyText(text, message) {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      this.showToast(message, 'info');
    } catch (e) {
      this.showToast('امکان کپی خودکار فراهم نشد.', 'warn');
    }
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
  },

  // ─────────────────────────────────────────────────────────────
  // 🔷 Phase 4: Fintech Intelligence, Risk Matrix & PWA UX Methods
  // ─────────────────────────────────────────────────────────────

  renderFHSBadge(c) {
    const score = (c.fhs_score !== undefined && c.fhs_score !== null) ? Math.round(c.fhs_score) : null;
    const level = c.fhs_level || 'نامشخص';
    if (score === null) {
      return `<span class="px-2.5 py-1 rounded-xl text-xs font-mono bg-slate-800 text-slate-400 border border-slate-700">---</span>`;
    }
    let bgClass = 'bg-slate-800 text-slate-300 border-slate-700';
    if (score >= 85) {
      bgClass = 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40 shadow-sm';
    } else if (score >= 70) {
      bgClass = 'bg-blue-500/15 text-blue-300 border-blue-500/40 shadow-sm';
    } else if (score >= 50) {
      bgClass = 'bg-amber-500/15 text-amber-300 border-amber-500/40 shadow-sm';
    } else {
      bgClass = 'bg-rose-500/15 text-rose-300 border-rose-500/40 shadow-sm';
    }
    return `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-bold font-mono border ${bgClass}" title="شاخص سلامت مالی مشتری (FHS: Financial Health Score)">
      <span>${score}</span>
      <span class="text-[10px] font-sans font-normal opacity-90">(${level})</span>
    </span>`;
  },

  jalaliToGregorian(jy, jm, jd) {
    jy += 1595;
    let days = -355668 + (365 * jy) + Math.floor(jy / 33) * 8 + Math.floor(((jy % 33) + 3) / 4) + jd + (jm < 7 ? (jm - 1) * 31 : ((jm - 7) * 30) + 186);
    let gy = 400 * Math.floor(days / 146097);
    days %= 146097;
    if (days > 36524) {
      days -= 1;
      gy += 100 * Math.floor(days / 36524);
      days %= 36524;
      if (days >= 365) days += 1;
    }
    gy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) {
      gy += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    let gd = days + 1;
    const salA = [0, 31, ((gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let gm = 0;
    while (gm < 13 && gd > salA[gm]) {
      gd -= salA[gm];
      gm += 1;
    }
    return [gy, gm, gd];
  },

  calculateDaysUntilDue(chequeDateStr) {
    if (!chequeDateStr) return null;
    const s = String(chequeDateStr).replace(/[^0-9]/g, '');
    if (s.length !== 8) return null;
    try {
      const jy = parseInt(s.slice(0, 4), 10);
      const jm = parseInt(s.slice(4, 6), 10);
      const jd = parseInt(s.slice(6, 8), 10);
      const [gy, gm, gd] = this.jalaliToGregorian(jy, jm, jd);
      const dueDate = new Date(gy, gm - 1, gd);
      const now = new Date();
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const diffMs = dueDate.getTime() - today.getTime();
      return Math.round(diffMs / (1000 * 60 * 60 * 24));
    } catch (e) {
      return null;
    }
  },

  drilldownCheques(mode) {
    this.switchTab('cheques', mode);
  },

  currentCashFlowHorizon: 30,
  cashFlowData: null,

  async loadPredictiveCashFlow() {
    try {
      const res = await fetch('/api/analytics/cash-flow?days=90', { credentials: 'omit' });
      if (res.ok) {
        this.cashFlowData = await res.json();
        this.renderPredictiveCashFlow();
      }
    } catch (e) {
      console.warn('Could not load predictive cash flow from API:', e);
      this.calculateLocalCashFlowFallback();
    }
  },

  setCashFlowHorizon(days) {
    this.currentCashFlowHorizon = days;
    [30, 60, 90].forEach(d => {
      const btn = document.getElementById(`cf-tab-${d}`);
      if (btn) {
        if (d === days) {
          btn.className = 'px-3 py-1.5 rounded-lg font-bold transition bg-sky-600 text-white shadow';
        } else {
          btn.className = 'px-3 py-1.5 rounded-lg font-bold transition text-slate-400 hover:text-slate-200';
        }
      }
    });
    this.renderPredictiveCashFlow();
  },

  renderPredictiveCashFlow() {
    if (!this.cashFlowData || !this.cashFlowData.horizons) return;

    const horizonKey = `${this.currentCashFlowHorizon}_days`;
    const horizon = this.cashFlowData.horizons[horizonKey] || this.cashFlowData.horizons['30_days'];
    const overdue = this.cashFlowData.horizons.overdue || { nominal: 0, count: 0 };

    const nominalEl = document.getElementById('cf-nominal-amount');
    const chequesCountEl = document.getElementById('cf-cheques-count');
    const realizableEl = document.getElementById('cf-realizable-amount');
    const rateEl = document.getElementById('cf-realization-rate');
    const shortfallEl = document.getElementById('cf-shortfall-amount');
    const overdueAmtEl = document.getElementById('cf-overdue-amount');
    const overdueCntEl = document.getElementById('cf-overdue-count');
    const progressPercEl = document.getElementById('cf-progress-percentage');
    const progressBar = document.getElementById('cf-progress-bar');
    const shortfallBar = document.getElementById('cf-shortfall-bar');

    if (nominalEl) nominalEl.innerHTML = `${this.formatMoney(horizon.nominal)} <span class="text-xs font-normal text-slate-400">ریال</span>`;
    if (chequesCountEl) chequesCountEl.innerText = `${(horizon.count || 0).toLocaleString('fa-IR')} فقره چک سررسید`;
    if (realizableEl) realizableEl.innerHTML = `${this.formatMoney(horizon.realizable)} <span class="text-xs font-normal text-emerald-500">ریال</span>`;
    if (rateEl) rateEl.innerText = `نرخ وصول انتظاری: ${(horizon.realization_rate || 100).toLocaleString('fa-IR')}٪`;
    if (shortfallEl) shortfallEl.innerHTML = `${this.formatMoney(horizon.shortfall)} <span class="text-xs font-normal text-rose-500">ریال</span>`;
    if (overdueAmtEl) overdueAmtEl.innerHTML = `${this.formatMoney(overdue.nominal)} <span class="text-xs font-normal text-amber-500">ریال</span>`;
    if (overdueCntEl) overdueCntEl.innerText = `${(overdue.count || 0).toLocaleString('fa-IR')} فقره نیازمند پیگیری فوری`;

    const pct = horizon.nominal > 0 ? Math.min(100, Math.round((horizon.realizable / horizon.nominal) * 100)) : 100;
    const shortPct = 100 - pct;

    if (progressPercEl) progressPercEl.innerText = `${pct.toLocaleString('fa-IR')}٪ محقق‌شونده`;
    if (progressBar) progressBar.style.width = `${pct}%`;
    if (shortfallBar) shortfallBar.style.width = `${shortPct}%`;
  },

  calculateLocalCashFlowFallback() {
    let n30 = 0, r30 = 0, c30 = 0;
    let n60 = 0, r60 = 0, c60 = 0;
    let n90 = 0, r90 = 0, c90 = 0;
    let nOverdue = 0, cOverdue = 0;

    const probMap = { 'سفید': 1.0, 'سبز': 0.95, 'زرد': 0.85, 'نارنجی': 0.60, 'قرمز': 0.20, 'قهوه ای': 0.20 };

    this.state.cheques.forEach(ch => {
      const amt = parseFloat(ch.amount) || 0;
      const days = this.calculateDaysUntilDue(ch.cheque_date);
      const cust = this.state.customers.find(c => c.id === ch.customer_id);
      const color = cust ? (cust.credit_color || 'نامشخص') : 'نامشخص';
      const p = probMap[color] || 0.5;
      const real = amt * p;

      if (days !== null && days < 0) {
        nOverdue += amt;
        cOverdue++;
      } else if (days !== null) {
        if (days <= 30) { n30 += amt; r30 += real; c30++; }
        if (days <= 60) { n60 += amt; r60 += real; c60++; }
        if (days <= 90) { n90 += amt; r90 += real; c90++; }
      }
    });

    this.cashFlowData = {
      horizons: {
        '30_days': { nominal: n30, realizable: r30, shortfall: n30 - r30, count: c30, realization_rate: n30 ? Math.round(r30/n30*100) : 100 },
        '60_days': { nominal: n60, realizable: r60, shortfall: n60 - r60, count: c60, realization_rate: n60 ? Math.round(r60/n60*100) : 100 },
        '90_days': { nominal: n90, realizable: r90, shortfall: n90 - r90, count: c90, realization_rate: n90 ? Math.round(r90/n90*100) : 100 },
        'overdue': { nominal: nOverdue, count: cOverdue }
      }
    };
    this.renderPredictiveCashFlow();
  },

  async loadNearMaturityAlerts() {
    const container = document.getElementById('near-maturity-alert-container');
    const listEl = document.getElementById('near-maturity-alert-list');
    const countEl = document.getElementById('near-maturity-alert-count');
    if (!container || !listEl) return;

    let alerts = [];
    try {
      const res = await fetch('/api/analytics/alerts/near-maturity?days=7', { credentials: 'omit' });
      if (res.ok) {
        const data = await res.json();
        alerts = data.alerts || [];
      }
    } catch (e) {
      console.warn('Could not load near maturity alerts from API:', e);
      alerts = this.state.cheques
        .filter(ch => {
          const d = this.calculateDaysUntilDue(ch.cheque_date);
          return d !== null && d >= 0 && d <= 7;
        })
        .map(ch => {
          const cust = this.state.customers.find(c => c.id === ch.customer_id);
          const d = this.calculateDaysUntilDue(ch.cheque_date);
          const col = cust ? (cust.credit_color || 'نامشخص') : 'نامشخص';
          return {
            cheque_id: ch.id,
            customer_id: ch.customer_id,
            customer_name: cust ? cust.full_name : 'نامشخص',
            amount: parseFloat(ch.amount) || 0,
            cheque_date: ch.cheque_date,
            days_remaining: d,
            credit_color: col,
            priority: (col === 'قرمز' || d <= 2) ? 'critical' : (col === 'زرد' || col === 'نارنجی') ? 'warning' : 'normal',
            priority_fa: (col === 'قرمز' || d <= 2) ? 'بحرانی' : (col === 'زرد' || col === 'نارنجی') ? 'هشدار' : 'عادی'
          };
        });
    }

    if (alerts.length === 0) {
      container.classList.add('hidden');
      return;
    }

    if (countEl) countEl.innerText = alerts.length.toLocaleString('fa-IR');
    container.classList.remove('hidden');

    listEl.innerHTML = alerts.slice(0, 6).map(a => {
      const isCrit = a.priority === 'critical';
      const cardBorder = isCrit ? 'border-rose-500/50 bg-rose-950/40' : 'border-amber-500/40 bg-amber-950/30';
      const badgeClass = isCrit ? 'bg-rose-500/20 text-rose-300 border-rose-500/40' : 'bg-amber-500/20 text-amber-300 border-amber-500/40';

      return `
        <div onclick="App.viewCustomerProfile(${a.customer_id})" class="p-3 rounded-xl border ${cardBorder} flex flex-col justify-between gap-2 hover:scale-[1.01] transition cursor-pointer shadow-sm">
          <div class="flex items-center justify-between">
            <span class="font-bold text-slate-100 text-xs truncate max-w-[140px]">${a.customer_name}</span>
            <span class="px-2 py-0.5 rounded-md text-[10px] font-bold border ${badgeClass}">
              ${a.priority_fa} (${a.days_remaining} روز)
            </span>
          </div>
          <div class="flex items-center justify-between text-xs pt-1 border-t border-slate-700/40">
            <span class="text-slate-400 font-mono text-[11px]">${a.cheque_date}</span>
            <span class="font-mono font-bold text-slate-200">${this.formatMoney(a.amount)} <span class="text-[10px] font-normal text-slate-400">ریال</span></span>
          </div>
        </div>
      `;
    }).join('');

    if (window.lucide) lucide.createIcons();
  },

  riskMatrixData: null,
  activeRiskMatrixFilter: 'all',

  async loadRiskMatrix() {
    try {
      const res = await fetch('/api/analytics/risk-matrix', { credentials: 'omit' });
      if (res.ok) {
        this.riskMatrixData = await res.json();
      }
    } catch (e) {
      console.warn('Could not load risk matrix from API:', e);
    }
  },

  async renderRiskMatrix() {
    if (!this.riskMatrixData) {
      await this.loadRiskMatrix();
    }
    const rm = this.riskMatrixData;
    if (!rm || !rm.quadrants) return;

    const qStars = rm.quadrants.stars;
    const qOpps = rm.quadrants.opportunities;
    const qWatch = rm.quadrants.watchlist;
    const qCrit = rm.quadrants.critical;

    const elStarsCnt = document.getElementById('rm-count-stars');
    const elStarsAmt = document.getElementById('rm-amount-stars');
    const elOppsCnt = document.getElementById('rm-count-opportunities');
    const elOppsAmt = document.getElementById('rm-amount-opportunities');
    const elWatchCnt = document.getElementById('rm-count-watchlist');
    const elWatchAmt = document.getElementById('rm-amount-watchlist');
    const elCritCnt = document.getElementById('rm-count-critical');
    const elCritAmt = document.getElementById('rm-amount-critical');

    if (elStarsCnt) elStarsCnt.innerText = (qStars.count || 0).toLocaleString('fa-IR');
    if (elStarsAmt) elStarsAmt.innerText = `${this.formatMoney(qStars.total_amount)} ریال`;
    if (elOppsCnt) elOppsCnt.innerText = (qOpps.count || 0).toLocaleString('fa-IR');
    if (elOppsAmt) elOppsAmt.innerText = `${this.formatMoney(qOpps.total_amount)} ریال`;
    if (elWatchCnt) elWatchCnt.innerText = (qWatch.count || 0).toLocaleString('fa-IR');
    if (elWatchAmt) elWatchAmt.innerText = `${this.formatMoney(qWatch.total_amount)} ریال`;
    if (elCritCnt) elCritCnt.innerText = (qCrit.count || 0).toLocaleString('fa-IR');
    if (elCritAmt) elCritAmt.innerText = `${this.formatMoney(qCrit.total_amount)} ریال`;

    this.renderRiskMatrixTable();
  },

  filterRiskMatrixQuadrant(key) {
    this.activeRiskMatrixFilter = key;
    ['all', 'stars', 'opportunities', 'watchlist', 'critical'].forEach(k => {
      const btn = document.getElementById(`rm-btn-${k}`);
      if (btn) {
        if (k === key) {
          btn.className = 'px-3 py-1.5 rounded-xl font-bold transition bg-blue-600 text-white shadow';
        } else {
          btn.className = 'px-3 py-1.5 rounded-xl font-bold transition bg-slate-800 text-slate-300 hover:text-white';
        }
      }
    });
    this.renderRiskMatrixTable();
  },

  renderRiskMatrixTable() {
    const rm = this.riskMatrixData;
    const tbody = document.getElementById('risk-matrix-table-body');
    const countBadge = document.getElementById('rm-filter-count-badge');
    if (!rm || !tbody) return;

    let items = [];
    const filter = this.activeRiskMatrixFilter;

    if (filter === 'all') {
      const addQuadrant = (qList, qName, qBadgeClass) => {
        if (qList) qList.forEach(c => items.push({ ...c, quadrant_name: qName, quadrant_class: qBadgeClass }));
      };
      addQuadrant(rm.quadrants.stars.customers, 'ستاره‌ها (Q1)', 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40');
      addQuadrant(rm.quadrants.opportunities.customers, 'فرصت‌ها (Q2)', 'bg-blue-500/20 text-blue-300 border-blue-500/40');
      addQuadrant(rm.quadrants.watchlist.customers, 'تحت نظر (Q3)', 'bg-amber-500/20 text-amber-300 border-amber-500/40');
      addQuadrant(rm.quadrants.critical.customers, 'هشدار قرمز (Q4)', 'bg-rose-500/20 text-rose-300 border-rose-500/40');
    } else {
      const q = rm.quadrants[filter];
      if (q && q.customers) {
        const titleMap = {
          stars: ['ستاره‌ها (Q1)', 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'],
          opportunities: ['فرصت‌ها (Q2)', 'bg-blue-500/20 text-blue-300 border-blue-500/40'],
          watchlist: ['تحت نظر (Q3)', 'bg-amber-500/20 text-amber-300 border-amber-500/40'],
          critical: ['هشدار قرمز (Q4)', 'bg-rose-500/20 text-rose-300 border-rose-500/40']
        };
        const meta = titleMap[filter] || ['ناحیه', ''];
        items = q.customers.map(c => ({ ...c, quadrant_name: meta[0], quadrant_class: meta[1] }));
      }
    }

    if (countBadge) {
      countBadge.innerText = `نمایش ${items.length.toLocaleString('fa-IR')} از ۵۲ مشتری`;
    }

    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="text-center py-10 text-slate-400">هیچ رکوردی در این ناحیه یافت نشد.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map((c, idx) => {
      return `
        <tr class="border-b border-slate-700/30 hover:bg-slate-500/10 transition">
          <td class="py-3.5 px-4 font-mono text-sm text-slate-400">${(idx + 1).toLocaleString('fa-IR')}</td>
          <td class="py-3.5 px-4 font-semibold text-slate-100">${c.full_name}</td>
          <td class="py-3.5 px-4 text-center">
            <span class="px-2 py-0.5 rounded-lg text-xs font-bold border ${c.quadrant_class}">${c.quadrant_name}</span>
          </td>
          <td class="py-3.5 px-4 text-center">
            ${this.renderFHSBadge(c)}
          </td>
          <td class="py-3.5 px-4 text-center">
            ${this.renderCreditBadge(c.cbi_rating)}
          </td>
          <td class="py-3.5 px-4 text-left font-mono">
            <span class="text-emerald-400 font-bold">${this.formatMoney(c.total_amount)}</span> <span class="text-[10px] text-slate-400">ریال</span>
          </td>
          <td class="py-3.5 px-4 text-center">
            ${(c.bounced_count || 0) > 0 
              ? `<span class="px-2 py-0.5 rounded-md bg-rose-500/20 text-rose-300 border border-rose-500/40 font-mono text-xs font-bold">${c.bounced_count} برگشتی</span>`
              : `<span class="text-xs text-emerald-400">فاقد برگشتی</span>`
            }
          <td class="py-3.5 px-4 text-center">
            <button onclick="App.viewCustomerProfile(${c.customer_id})" class="px-3 py-1 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded-xl text-xs font-semibold flex items-center gap-1 transition mx-auto">
              <i data-lucide="eye" class="w-3.5 h-3.5"></i>
              <span>پرونده</span>
            </button>
          </td>
        </tr>
      `;
    }).join('');

    // 📱 Mobile Touch Cards for Risk Matrix
    const mobileRmContainer = document.getElementById('risk-matrix-mobile-cards');
    if (mobileRmContainer) {
      if (items.length === 0) {
        mobileRmContainer.innerHTML = `<div class="text-center py-10 text-slate-400 text-xs">هیچ رکوردی در این ناحیه یافت نشد.</div>`;
      } else {
        mobileRmContainer.innerHTML = items.map((c, idx) => {
          return `
            <div class="mobile-card space-y-2.5">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2.5">
                  <div class="w-10 h-10 rounded-xl bg-slate-800 border border-slate-700 text-white flex items-center justify-center font-bold text-sm">
                    ${(idx + 1).toLocaleString('fa-IR')}
                  </div>
                  <div>
                    <h5 class="font-bold text-sm text-slate-100">${c.full_name}</h5>
                    <span class="text-[10px] text-slate-400">شناسه مشتری: #${c.customer_id}</span>
                  </div>
                </div>
                <span class="px-2 py-0.5 rounded-lg text-xs font-bold border ${c.quadrant_class}">${c.quadrant_name}</span>
              </div>

              <div class="flex items-center justify-between bg-slate-900/60 p-2.5 rounded-xl border border-slate-800 text-xs">
                <div>
                  <span class="text-[10px] text-slate-400 block mb-0.5">شاخص FHS</span>
                  ${this.renderFHSBadge(c)}
                </div>
                <div>
                  <span class="text-[10px] text-slate-400 block mb-0.5">رتبه بانک مرکزی</span>
                  ${this.renderCreditBadge(c.cbi_rating)}
                </div>
                <div>
                  <span class="text-[10px] text-slate-400 block mb-0.5">وضعیت برگشتی</span>
                  ${(c.bounced_count || 0) > 0 
                    ? `<span class="text-rose-400 font-bold font-mono text-[11px]">${c.bounced_count} برگشتی</span>`
                    : `<span class="text-emerald-400 text-[11px]">فاقد برگشتی</span>`
                  }
                </div>
              </div>

              <div class="flex items-center justify-between pt-1 border-t border-slate-800/60">
                <div>
                  <span class="text-[10px] text-slate-400 block">مجموع تعهدات</span>
                  <span class="font-bold font-mono text-emerald-400 text-sm">${this.formatMoney(c.total_amount)} <span class="text-[9px] text-slate-400 font-sans">ریال</span></span>
                </div>
                <button onclick="App.viewCustomerProfile(${c.customer_id})" class="px-4 py-2 bg-blue-600/20 hover:bg-blue-600 text-blue-300 hover:text-white rounded-xl text-xs font-bold flex items-center gap-1.5 transition">
                  <i data-lucide="eye" class="w-4 h-4"></i>
                  <span>مشاهده پرونده</span>
                </button>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    if (window.lucide) lucide.createIcons();
  },

  exportRiskMatrixExcel() {
    if (!this.riskMatrixData) return;
    const all = [];
    ['stars', 'opportunities', 'watchlist', 'critical'].forEach(k => {
      const q = this.riskMatrixData.quadrants[k];
      if (q && q.customers) {
        q.customers.forEach(c => {
          all.push({
            "نام مشتری": c.full_name,
            "کد ملی": c.national_id || '',
            "ناحیه ماتریس ریسک": q.title,
            "شاخص سلامت مالی FHS": c.fhs_score,
            "سطح ریسک": c.level,
            "رتبه اعتباری بانک مرکزی": c.cbi_rating,
            "مجموع ارزش تعهدات (ریال)": c.total_amount,
            "تعداد چک‌ها": c.cheque_count,
            "تعداد برگشتی": c.bounced_count,
            "مبلغ برگشتی": c.bounced_amount,
            "توصیه اعتباری": c.recommendation
          });
        });
      }
    });

    const ws = XLSX.utils.json_to_sheet(all);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "ماتریس ریسک");
    XLSX.writeFile(wb, "ماتریس_ریسک_مشتریان_صیاد_پرو.xlsx");
    this.showToast('خروجی اکسل ماتریس ریسک با موفقیت دانلود شد.', 'success');
  },

  deferredPwaPrompt: null,

  initPWA() {
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        const swPath = window.location.pathname.includes('/docs') ? './sw.js' : '/sw.js';
        navigator.serviceWorker.register(swPath)
          .then((reg) => {
            window.AppLogger?.info('PWA', 'سرویس ورکر صیاد پرو فعال شد.');
            reg.onupdatefound = () => {
              const installingWorker = reg.installing;
              if (installingWorker) {
                installingWorker.onstatechange = () => {
                  if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {
                    this.showToast('نسخه جدید صیاد پرو در دسترس است.', 'info');
                  }
                };
              }
            };
          })
          .catch((err) => {
            console.warn('[PWA] ServiceWorker registration failed:', err);
          });
      });
    }

    const updateNetworkStatus = () => {
      const pill = document.getElementById('pwa-status-pill');
      const text = document.getElementById('pwa-status-text');
      if (!pill || !text) return;

      if (navigator.onLine) {
        pill.className = 'hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-[11px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
        pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span>برخط (PWA)</span>`;
      } else {
        pill.className = 'flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-[11px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/40 animate-bounce';
        pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400"></span><span>حالت آفلاین (کش محلی)</span>`;
        this.showToast('اتصال شبکه قطع شد. برنامه در وضعیت آفلاین از کش محلی بارگذاری می‌شود.', 'warning');
      }
    };

    window.addEventListener('online', updateNetworkStatus);
    window.addEventListener('offline', updateNetworkStatus);
    updateNetworkStatus();

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      this.deferredPwaPrompt = e;
      const installBtn = document.getElementById('pwa-install-btn');
      if (installBtn) {
        installBtn.classList.remove('hidden');
        installBtn.classList.add('flex');
      }
    });

    window.addEventListener('appinstalled', () => {
      this.deferredPwaPrompt = null;
      const installBtn = document.getElementById('pwa-install-btn');
      if (installBtn) installBtn.classList.add('hidden');
      this.showToast('اپلیکیشن صیاد پرو با موفقیت بر روی دستگاه شما نصب شد.', 'success');
    });
  },

  promptPwaInstall() {
    if (this.deferredPwaPrompt) {
      this.deferredPwaPrompt.prompt();
      this.deferredPwaPrompt.userChoice.then((choiceResult) => {
        if (choiceResult.outcome === 'accepted') {
          console.log('[PWA] User accepted install prompt');
        }
        this.deferredPwaPrompt = null;
        const installBtn = document.getElementById('pwa-install-btn');
        if (installBtn) installBtn.classList.add('hidden');
      });
    } else {
      this.showToast('برای نصب برنامه، از منوی مرورگر گزینه Install App یا Add to Home screen را انتخاب نمایید.', 'info');
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});

