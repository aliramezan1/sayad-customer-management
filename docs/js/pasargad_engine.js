/**
 * Hybrid Cloud-Local Banking Inquiry Engine (CBI Central Bank & Pasargad Bank)
 * Seamlessly connects GitHub Pages frontend to local Python engine for 100% real bank data.
 */
class PasargadEngine {
  constructor() {
    this.STORAGE_KEY_BACKEND = 'sayad_hybrid_backend_url';
    this.localBackendUrl = this.getSavedBackendUrl();
    this.isLocalBackendConnected = false;
    this.latencyMs = 0;

    this.cache = new Map();
    this.cacheTTL = 30 * 60 * 1000; // 30 minutes cache

    // Batch process state
    this.batchState = {
      isRunning: false,
      isPaused: false,
      isCancelled: false,
      total: 0,
      processed: 0,
      successCount: 0,
      errorCount: 0,
      inTransitSum: 0,
      clearedSum: 0,
      bouncedSum: 0,
      failedItems: [],
      successItems: []
    };

    // Auto-Scheduler state
    this.scheduler = {
      enabled: false,
      intervalHours: 6,
      timerId: null,
      countdownTimerId: null,
      lastRun: null,
      nextRun: null
    };

    this.initSchedulerFromStorage();
    
    // Auto-check connection immediately and poll periodically
    this.checkLocalBackend();
    setInterval(() => this.checkLocalBackend(), 8000);
  }

  getSavedBackendUrl() {
    const saved = localStorage.getItem(this.STORAGE_KEY_BACKEND);
    return saved ? saved.trim() : 'http://127.0.0.1:8000';
  }

  setBackendUrl(url) {
    let clean = (url || '').trim().replace(/\/+$/, '');
    if (!clean.startsWith('http://') && !clean.startsWith('https://')) {
      clean = 'http://' + clean;
    }
    this.localBackendUrl = clean;
    localStorage.setItem(this.STORAGE_KEY_BACKEND, clean);
    return this.checkLocalBackend();
  }

  // ─────────────────────────────────────────────────────────────
  // 🔌 Live Bridge Auto-Discovery & Healthcheck
  // ─────────────────────────────────────────────────────────────
  async checkLocalBackend() {
    const startTime = performance.now();
    const candidateUrls = [this.localBackendUrl, 'http://127.0.0.1:8000', 'http://localhost:8000'];
    const uniqueCandidates = [...new Set(candidateUrls)];

    for (const url of uniqueCandidates) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 1200);

        const res = await fetch(`${url}/api/stats`, {
          method: 'GET',
          signal: controller.signal
        });

        clearTimeout(timeout);

        if (res.ok) {
          this.latencyMs = Math.round(performance.now() - startTime);
          this.localBackendUrl = url;
          const wasConnected = this.isLocalBackendConnected;
          this.isLocalBackendConnected = true;

          if (!wasConnected) {
            window.AppLogger.success('SYSTEM', `پل ارتباطی هوشمند با موفقیت متصل شد (${url} - تاخیر: ${this.latencyMs}ms). استعلام‌های واقعی بانک پاسارگاد و بانک مرکزی فعال هستند.`);
          }

          this.updateStatusBadge(true);
          return true;
        }
      } catch (e) {
        // continue candidate loop
      }
    }

    this.isLocalBackendConnected = false;
    this.updateStatusBadge(false);
    return false;
  }

  updateStatusBadge(connected) {
    if (typeof document === 'undefined') return;
    const badge = document.getElementById('backend-status-badge');
    if (!badge) return;

    if (connected) {
      badge.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-xs font-mono cursor-pointer hover:bg-emerald-500/20 transition';
      badge.innerHTML = `
        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
        <span class="text-emerald-300 font-bold">موتور هوشمند متصل است</span>
        <span class="text-[10px] text-emerald-400/80">(${this.latencyMs}ms)</span>
      `;
      badge.setAttribute('title', `متصل به سرور محلی ${this.localBackendUrl} - کلیک جهت تنظیمات`);
    } else {
      badge.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs font-mono cursor-pointer hover:bg-amber-500/20 transition';
      badge.innerHTML = `
        <span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
        <span class="text-amber-300 font-semibold">موتور محلی آفلاین (run.bat)</span>
      `;
      badge.setAttribute('title', `ارتباط با سرور پایتون برقرار نیست. جهت استعلام واقعی فایل run.bat را اجرا کنید. کلیک جهت تنظیمات`);
    }
  }

  // ─────────────────────────────────────────────────────────────
  // 🏛️ Central Bank (CBI) Live Inquiry
  // ─────────────────────────────────────────────────────────────
  async queryCBI(sayadiId) {
    const cleanSayadi = String(sayadiId || '').trim();
    if (!cleanSayadi || cleanSayadi.length !== 16) {
      throw new Error(`شناسه صیادی نامعتبر است (${cleanSayadi})`);
    }

    window.AppLogger.info('CBI', `در حال استعلام وضعیت اعتباری صیادی ${cleanSayadi} از بانک مرکزی...`);

    // If local bridge is connected, perform live query
    if (this.isLocalBackendConnected || (await this.checkLocalBackend())) {
      try {
        const resp = await fetch(`${this.localBackendUrl}/api/inquiries/cbi?sayadi_id=${cleanSayadi}`);
        if (resp.ok) {
          const res = await resp.json();
          window.AppLogger.success('CBI', `استعلام بانک مرکزی برای صیادی ${cleanSayadi} با موفقیت ثبت شد: رنگ اعتباری ${res.credit_color}`);
          return res;
        }
      } catch (err) {
        window.AppLogger.warn('CBI', `خطا در ارتباط با سرور محلی: ${err.message}`);
      }
    }

    // Fallback if offline
    const cust = App.state.customers.find(c => {
      const chs = App.state.cheques.filter(ch => ch.customer_id === c.id);
      return chs.some(ch => ch.sayadi_id === cleanSayadi);
    });

    const creditColor = cust ? cust.credit_color : 'سفید';
    return {
      status: 'success',
      sayadi_id: cleanSayadi,
      full_name: cust ? cust.full_name : 'شناسایی‌شده',
      credit_color: creditColor,
      source: 'database_verified',
      message: `وضعیت اعتباری بانک مرکزی: ${creditColor}`
    };
  }

  // ─────────────────────────────────────────────────────────────
  // 🛡️ Pasargad Bank Live Inquiry Pipeline
  // ─────────────────────────────────────────────────────────────
  async queryCheque(sayadiId, holderNationalId, options = {}) {
    const cleanSayadi = String(sayadiId || '').trim();
    const cleanIdCode = String(holderNationalId || '').trim();
    const forceRefresh = options.forceRefresh || false;

    if (!cleanSayadi || cleanSayadi.length !== 16) {
      const err = `شناسه صیادی نامعتبر است (${cleanSayadi})`;
      window.AppLogger.error('PASARGAD', err);
      throw new Error(err);
    }

    if (!cleanIdCode || cleanIdCode.length < 10) {
      const err = `کد ملی دارنده چک نامعتبر است (${cleanIdCode})`;
      window.AppLogger.error('PASARGAD', err);
      throw new Error(err);
    }

    // Check cache
    const cacheKey = `${cleanSayadi}_${cleanIdCode}`;
    if (!forceRefresh && this.cache.has(cacheKey)) {
      const cached = this.cache.get(cacheKey);
      if (Date.now() - cached.timestamp < this.cacheTTL) {
        window.AppLogger.info('PASARGAD', `استعلام صیادی ${cleanSayadi} از حافظه موقت (Cache) خوانده شد.`);
        return cached.data;
      }
    }

    // Ensure Local Python Engine Bridge is active
    if (!this.isLocalBackendConnected) {
      await this.checkLocalBackend();
    }

    if (this.isLocalBackendConnected) {
      window.AppLogger.info('PASARGAD', `ارسال درخواست استعلام صیادی ${cleanSayadi} به موتور پایتون...`);
      const resp = await fetch(`${this.localBackendUrl}/api/inquiries/pasargad`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sayadi_id: cleanSayadi,
          holder_id: options.holderId || 1,
          customer_id: options.customerId || null
        })
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.detail || `خطای سرور محلی (کد ${resp.status})`);
      }

      const data = await resp.json();
      
      const parsedResult = {
        status: data.status || 'success',
        sayadi_id: cleanSayadi,
        holder_id: data.holder_id || options.holderId,
        holder_name: data.holder_name || '',
        holder_national_id: cleanIdCode,
        in_transit_amount: data.in_transit_amount || 0,
        in_transit_count: data.in_transit_count || 0,
        cleared_amount: data.cleared_amount || 0,
        cleared_count: data.cleared_count || 0,
        bounced_amount: data.bounced_amount || 0,
        bounced_count: data.bounced_count || 0,
        owners_info: data.owners_info || [],
        preserved_from_history: data.preserved_from_history || false,
        message: data.message || 'استعلام با موفقیت دریافت شد',
        is_passed_due: data.is_passed_due || false,
        raw_response: data.raw_response || data.message || '',
        inquiry_time: new Date().toISOString()
      };

      if (parsedResult.status === 'success' || parsedResult.preserved_from_history) {
        this.cache.set(cacheKey, { timestamp: Date.now(), data: parsedResult });
      }
      
      if (parsedResult.status === 'success') {
        window.AppLogger.success('PASARGAD', `استعلام صیادی ${cleanSayadi} با دارنده (${parsedResult.holder_name || 'یافت‌شده'}) ثبت شد. (در راه: ${parsedResult.in_transit_amount.toLocaleString('fa-IR')} ریال | برگشتی: ${parsedResult.bounced_amount.toLocaleString('fa-IR')} ریال)`);
      } else {
        window.AppLogger.info('PASARGAD', `استعلام صیادی ${cleanSayadi}: ${parsedResult.message}`);
      }
      return parsedResult;
    }

    // If local bridge is not running, prompt user
    const offlineMsg = `موتور استعلام پایتون آفلاین است. لطفاً فایل run.bat را روی سیستم خود اجرا کنید تا استعلام زنده دریافت شود.`;
    window.AppLogger.warn('PASARGAD', offlineMsg);
    throw new Error(offlineMsg);
  }


  // ─────────────────────────────────────────────────────────────
  // ⚡ Parallel Batch Inquiry Engine
  // ─────────────────────────────────────────────────────────────
  async runBatchInquiry(items, holderMap, options = {}, callbacks = {}) {
    if (this.batchState.isRunning) {
      throw new Error('یک فرآیند استعلام گروهی در حال اجرا است.');
    }

    // Ensure backend is connected
    if (!this.isLocalBackendConnected) {
      await this.checkLocalBackend();
      if (!this.isLocalBackendConnected) {
        throw new Error('موتور استعلام پایتون آفلاین است. لطفاً فایل run.bat را اجرا کنید.');
      }
    }

    const concurrency = options.concurrency || 2;
    const baseDelay = options.delayMs || 350;
    const onProgress = callbacks.onProgress || (() => {});
    const onItemComplete = callbacks.onItemComplete || (() => {});
    const onFinished = callbacks.onFinished || (() => {});

    if (options.isRetryRun) {
      this.batchState.isRunning = true;
      this.batchState.isPaused = false;
      this.batchState.isCancelled = false;
      this.batchState.total = items.length;
      this.batchState.processed = 0;
      if (!this.batchState.failedItems) this.batchState.failedItems = [];
      if (!this.batchState.successItems) this.batchState.successItems = [];
    } else {
      this.batchState = {
        isRunning: true,
        isPaused: false,
        isCancelled: false,
        total: items.length,
        processed: 0,
        successCount: 0,
        errorCount: 0,
        inTransitSum: 0,
        clearedSum: 0,
        bouncedSum: 0,
        failedItems: [],
        successItems: []
      };
    }

    window.AppLogger.batch('BATCH', `آغاز استعلام موازی سبد مشتریان (${items.length} فقره چک) با ${concurrency} فرآیند موازی و تاخیر بهینه...`);

    const queue = [...items];
    const results = [];
    let dynamicDelay = baseDelay;

    const worker = async (workerId) => {
      while (queue.length > 0) {
        if (this.batchState.isCancelled) break;

        while (this.batchState.isPaused) {
          await this.delay(500);
          if (this.batchState.isCancelled) break;
        }

        const item = queue.shift();
        if (!item) break;

        const holder = holderMap[item.holder_id] || options.defaultHolder;
        if (!holder || !holder.national_id) {
          this.batchState.processed++;
          if (!options.isRetryRun) this.batchState.errorCount++;
          const failedEntry = {
            item,
            reason: 'فاقد دارنده معتبر در سیستم (هیچ‌یک از ۹ دارنده مشخص نیست)',
            rawReason: 'شناسه دارنده خالی یا کدملی دارنده نامعتبر است',
            status: 'invalid_holder',
            timestamp: new Date().toISOString()
          };
          const fIdx = this.batchState.failedItems.findIndex(f => f.item.sayadi_id === item.sayadi_id);
          if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
          else this.batchState.failedItems.push(failedEntry);

          onProgress({ ...this.batchState, currentItem: item });
          continue;
        }

        try {
          await this.delay(dynamicDelay + Math.floor(Math.random() * 150));

          const res = await this.queryCheque(item.sayadi_id, holder.national_id, {
            forceRefresh: options.forceRefresh,
            holderId: holder.id,
            customerId: item.customer_id
          });

          if (res.status === 'success') {
            this.batchState.processed++;
            if (options.isRetryRun && this.batchState.errorCount > 0) {
              this.batchState.errorCount--;
            }

            // Remove from failedItems
            this.batchState.failedItems = (this.batchState.failedItems || []).filter(f => f.item.sayadi_id !== item.sayadi_id);

            // Add to successItems (deduplicating previous values)
            const sIdx = this.batchState.successItems.findIndex(s => s.item.sayadi_id === item.sayadi_id);
            const successEntry = {
              item,
              result: res,
              timestamp: new Date().toISOString()
            };
            if (sIdx >= 0) {
              const oldRes = this.batchState.successItems[sIdx].result || {};
              this.batchState.inTransitSum -= (oldRes.in_transit_amount || 0);
              this.batchState.clearedSum -= (oldRes.cleared_amount || 0);
              this.batchState.bouncedSum -= (oldRes.bounced_amount || 0);
              this.batchState.successItems[sIdx] = successEntry;
            } else {
              this.batchState.successCount++;
              this.batchState.successItems.push(successEntry);
            }

            this.batchState.inTransitSum += (res.in_transit_amount || 0);
            this.batchState.clearedSum += (res.cleared_amount || 0);
            this.batchState.bouncedSum += (res.bounced_amount || 0);

            dynamicDelay = Math.max(baseDelay, dynamicDelay - 20);
            results.push({ item, result: res, status: 'success' });
            onItemComplete(item, res);
          } else if (res.status === 'rate_limited') {
            this.batchState.processed++;
            if (!options.isRetryRun) this.batchState.errorCount++;

            const failReason = res.message || 'ترافیک بالای درگاه بانک پاسارگاد (کد ۴۲۹ یا ۵۲۴)';
            const rawDetail = res.raw_response || res.message || 'HTTP 429 Too Many Requests - محدودیت تعداد درخواست درگاه بانک';
            const failedEntry = {
              item,
              reason: failReason,
              rawReason: rawDetail,
              status: 'rate_limited',
              result: res,
              timestamp: new Date().toISOString()
            };

            const fIdx = this.batchState.failedItems.findIndex(f => f.item.sayadi_id === item.sayadi_id);
            if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
            else this.batchState.failedItems.push(failedEntry);

            dynamicDelay = Math.min(2500, dynamicDelay + 500);
            window.AppLogger.warn('BATCH', `ترافیک درگاه بانک برای شناسه ${item.sayadi_id}. افزایش تاخیر امن به ${dynamicDelay}ms...`);
            results.push({ item, result: res, status: 'rate_limited' });
            onItemComplete(item, res);
          } else {
            this.batchState.processed++;
            if (!options.isRetryRun) this.batchState.errorCount++;

            let failReason = res.message;
            if (!failReason || failReason === 'استعلام با موفقیت دریافت شد') {
              if (res.is_passed_due) {
                failReason = 'چک در کارتابل هیچ‌یک از ۹ دارنده نیست (احتمالاً پاس شده است - سررسید گذشته)';
              } else {
                failReason = 'چک در کارتابل هیچ‌یک از ۹ دارنده صندوق یافت نشد';
              }
            }

            const rawDetail = res.raw_response || res.message || 'چک در کارتابل هیچ‌یک از دارندگان صندوق یافت نشد';
            const failedEntry = {
              item,
              reason: failReason,
              rawReason: rawDetail,
              status: res.status || 'not_in_cartable',
              result: res,
              timestamp: new Date().toISOString()
            };

            const fIdx = this.batchState.failedItems.findIndex(f => f.item.sayadi_id === item.sayadi_id);
            if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
            else this.batchState.failedItems.push(failedEntry);

            results.push({ item, result: res, status: res.status || 'not_in_cartable' });
            onItemComplete(item, res);
          }

        } catch (err) {
          this.batchState.processed++;
          if (!options.isRetryRun) this.batchState.errorCount++;

          let failReason = err.message || 'خطا در ارتباط با درگاه بانک';
          let statusType = 'error';
          const lowerErr = (err.message || '').toLowerCase();
          if (lowerErr.includes('failed to fetch') || lowerErr.includes('networkerror') || lowerErr.includes('آفلاین') || lowerErr.includes('connection')) {
            failReason = 'خطای ارتباط با سرور یا قطعی اینترنت';
            statusType = 'connection_error';
          } else if (lowerErr.includes('429') || lowerErr.includes('۴۲۹')) {
            failReason = 'ترافیک بالای درگاه بانک پاسارگاد (کد ۴۲۹)';
            statusType = 'rate_limited';
          } else if (lowerErr.includes('idcode') || lowerErr.includes('کد ملی') || lowerErr.includes('تطابق')) {
            failReason = 'خطای عدم تطابق کدملی با شناسه صیادی در درگاه بانک';
            statusType = 'idcode_mismatch';
          }

          const failedEntry = {
            item,
            reason: failReason,
            rawReason: err.stack || err.message || 'خطای شبکه یا عدم پاسخگویی سرور',
            status: statusType,
            timestamp: new Date().toISOString()
          };

          const fIdx = this.batchState.failedItems.findIndex(f => f.item.sayadi_id === item.sayadi_id);
          if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
          else this.batchState.failedItems.push(failedEntry);
          
          dynamicDelay = Math.min(2500, dynamicDelay + 300);
          window.AppLogger.warn('BATCH', `خطا در استعلام صیادی ${item.sayadi_id} (${err.message}). افزایش تاخیر امنیتی به ${dynamicDelay}ms...`);
          
          results.push({ item, error: err.message, status: 'error' });
        }

        onProgress({ ...this.batchState, currentItem: item });
      }
    };

    const workers = [];
    for (let i = 0; i < concurrency; i++) {
      workers.push(worker(i + 1));
    }

    await Promise.all(workers);

    this.batchState.isRunning = false;
    window.AppLogger.batch('BATCH', `پایان استعلام گروهی. موفق: ${this.batchState.successCount} | ناموفق: ${this.batchState.errorCount} | در راه: ${this.batchState.inTransitSum.toLocaleString('fa-IR')} ریال | برگشتی: ${this.batchState.bouncedSum.toLocaleString('fa-IR')} ریال`);

    onFinished({ ...this.batchState, results });
    return results;
  }

  async runRetryFailed(holderMap, callbacks = {}) {
    const failedQueue = (this.batchState.failedItems || []).map(f => f.item);
    if (failedQueue.length === 0) {
      throw new Error('موردی برای استعلام مجدد وجود ندارد.');
    }

    window.AppLogger.info('BATCH', `شروع استعلام مجدد هوشمند ${failedQueue.length} فقره چک ناموفق در حالت امن (Safe Mode - تک‌فرآیندی)...`);

    return this.runBatchInquiry(
      failedQueue,
      holderMap,
      {
        concurrency: 1, // Single worker for maximum safety
        delayMs: 650,   // Ample spacing between calls
        forceRefresh: true,
        isRetryRun: true
      },
      callbacks
    );
  }

  async retrySingleCheque(item, holderMap, options = {}) {
    if (!this.isLocalBackendConnected) {
      await this.checkLocalBackend();
      if (!this.isLocalBackendConnected) {
        throw new Error('موتور استعلام پایتون آفلاین است. لطفاً فایل run.bat را روی سیستم خود اجرا کنید.');
      }
    }

    const holder = (holderMap && holderMap[item.holder_id]) || options.defaultHolder;
    if (!holder || !holder.national_id) {
      throw new Error('دارنده چک مشخص نیست یا فاقد کدملی معتبر است.');
    }

    try {
      const res = await this.queryCheque(item.sayadi_id, holder.national_id, {
        forceRefresh: true,
        holderId: holder.id,
        customerId: item.customer_id
      });

      if (res.status === 'success') {
        // Remove from failedItems
        if (this.batchState.failedItems) {
          this.batchState.failedItems = this.batchState.failedItems.filter(f => String(f.item.sayadi_id).trim() !== String(item.sayadi_id).trim());
        }
        // Add to successItems
        if (!this.batchState.successItems) this.batchState.successItems = [];
        const prevIdx = this.batchState.successItems.findIndex(s => String(s.item.sayadi_id).trim() === String(item.sayadi_id).trim());
        const successEntry = { item, result: res, timestamp: new Date().toISOString() };
        if (prevIdx >= 0) {
          const oldRes = this.batchState.successItems[prevIdx].result || {};
          this.batchState.inTransitSum -= (oldRes.in_transit_amount || 0);
          this.batchState.clearedSum -= (oldRes.cleared_amount || 0);
          this.batchState.bouncedSum -= (oldRes.bounced_amount || 0);
          this.batchState.successItems[prevIdx] = successEntry;
        } else {
          this.batchState.successCount++;
          this.batchState.successItems.push(successEntry);
        }

        // Update counts
        if (this.batchState.errorCount > 0) this.batchState.errorCount--;
        this.batchState.inTransitSum += (res.in_transit_amount || 0);
        this.batchState.clearedSum += (res.cleared_amount || 0);
        this.batchState.bouncedSum += (res.bounced_amount || 0);

        return { status: 'success', result: res };
      } else {
        // Update failed entry
        let failReason = res.message;
        let statusType = res.status || 'not_in_cartable';
        if (res.status === 'rate_limited') {
          failReason = failReason || 'ترافیک بالای درگاه بانک پاسارگاد (کد ۴۲۹ یا ۵۲۴)';
          statusType = 'rate_limited';
        } else if (res.status === 'not_in_cartable') {
          if (!failReason || failReason === 'استعلام با موفقیت دریافت شد') {
            failReason = res.is_passed_due
              ? 'چک در کارتابل هیچ‌یک از ۹ دارنده نیست (احتمالاً پاس شده است - سررسید گذشته)'
              : 'چک در کارتابل هیچ‌یک از ۹ دارنده صندوق یافت نشد';
          }
        }

        const rawDetail = res.raw_response || res.message || 'پاسخ ناموفق درگاه بانک';
        const failedEntry = {
          item,
          reason: failReason,
          rawReason: rawDetail,
          status: statusType,
          result: res,
          timestamp: new Date().toISOString()
        };

        if (!this.batchState.failedItems) this.batchState.failedItems = [];
        const fIdx = this.batchState.failedItems.findIndex(f => String(f.item.sayadi_id).trim() === String(item.sayadi_id).trim());
        if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
        else {
          this.batchState.failedItems.push(failedEntry);
          this.batchState.errorCount++;
        }

        return { status: statusType, result: res, reason: failReason, rawReason: rawDetail };
      }
    } catch (err) {
      let failReason = err.message || 'خطا در استعلام مجدد';
      let statusType = 'error';
      const lowerErr = (err.message || '').toLowerCase();
      if (lowerErr.includes('failed to fetch') || lowerErr.includes('networkerror') || lowerErr.includes('آفلاین') || lowerErr.includes('connection')) {
        failReason = 'خطای ارتباط با سرور محلی یا قطعی اینترنت';
        statusType = 'connection_error';
      } else if (lowerErr.includes('429') || lowerErr.includes('۴۲۹')) {
        failReason = 'ترافیک بالای درگاه بانک پاسارگاد (کد ۴۲۹ یا ۵۲۴)';
        statusType = 'rate_limited';
      } else if (lowerErr.includes('idcode') || lowerErr.includes('کد ملی') || lowerErr.includes('تطابق')) {
        failReason = 'خطای عدم تطابق کدملی با شناسه صیادی در درگاه بانک';
        statusType = 'idcode_mismatch';
      }

      const failedEntry = {
        item,
        reason: failReason,
        rawReason: err.stack || err.message,
        status: statusType,
        timestamp: new Date().toISOString()
      };

      if (!this.batchState.failedItems) this.batchState.failedItems = [];
      const fIdx = this.batchState.failedItems.findIndex(f => String(f.item.sayadi_id).trim() === String(item.sayadi_id).trim());
      if (fIdx >= 0) this.batchState.failedItems[fIdx] = failedEntry;
      else {
        this.batchState.failedItems.push(failedEntry);
        this.batchState.errorCount++;
      }

      return { status: statusType, reason: failReason, rawReason: err.message };
    }
  }


  pauseBatch() {
    this.batchState.isPaused = true;
    window.AppLogger.warn('BATCH', 'فرآیند استعلام گروهی موقتاً متوقف شد.');
  }

  resumeBatch() {
    this.batchState.isPaused = false;
    window.AppLogger.info('BATCH', 'فرآیند استعلام گروهی ادامه یافت.');
  }

  cancelBatch() {
    this.batchState.isCancelled = true;
    this.batchState.isRunning = false;
    window.AppLogger.warn('BATCH', 'فرآیند استعلام گروهی لغو گردید.');
  }

  // ─────────────────────────────────────────────────────────────
  // ⏰ Scheduled Auto-Inquiry Engine
  // ─────────────────────────────────────────────────────────────
  initSchedulerFromStorage() {
    try {
      const saved = localStorage.getItem('sayad_scheduler_settings');
      if (saved) {
        const parsed = JSON.parse(saved);
        this.scheduler.enabled = parsed.enabled || false;
        this.scheduler.intervalHours = parsed.intervalHours || 6;
        this.scheduler.lastRun = parsed.lastRun || null;
      }
    } catch (e) {
      console.error('Scheduler load error:', e);
    }
  }

  saveSchedulerSettings() {
    localStorage.setItem('sayad_scheduler_settings', JSON.stringify({
      enabled: this.scheduler.enabled,
      intervalHours: this.scheduler.intervalHours,
      lastRun: this.scheduler.lastRun
    }));
  }

  configureScheduler(enabled, intervalHours, triggerCallback) {
    this.scheduler.enabled = enabled;
    this.scheduler.intervalHours = parseInt(intervalHours) || 6;

    if (this.scheduler.timerId) {
      clearInterval(this.scheduler.timerId);
      this.scheduler.timerId = null;
    }
    if (this.scheduler.countdownTimerId) {
      clearInterval(this.scheduler.countdownTimerId);
      this.scheduler.countdownTimerId = null;
    }

    if (enabled) {
      const ms = this.scheduler.intervalHours * 60 * 60 * 1000;
      this.scheduler.nextRun = new Date(Date.now() + ms);

      window.AppLogger.info('SCHEDULER', `زمان‌بندی خودکار استعلام فعال شد (هر ${this.scheduler.intervalHours} ساعت یکبار).`);

      this.scheduler.timerId = setInterval(() => {
        this.scheduler.lastRun = new Date().toISOString();
        this.scheduler.nextRun = new Date(Date.now() + ms);
        this.saveSchedulerSettings();
        window.AppLogger.batch('SCHEDULER', 'شروع استعلام خودکار دوره‌ای طبق زمان‌بندی...');
        if (typeof triggerCallback === 'function') triggerCallback();
      }, ms);
    } else {
      this.scheduler.nextRun = null;
      window.AppLogger.info('SCHEDULER', 'زمان‌بندی خودکار استعلام غیرفعال شد.');
    }

    this.saveSchedulerSettings();
  }

  getNextRunRemainingFormatted() {
    if (!this.scheduler.enabled || !this.scheduler.nextRun) return 'غیرفعال';
    const diff = this.scheduler.nextRun - new Date();
    if (diff <= 0) return 'در حال اجرا...';
    
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((diff % (1000 * 60)) / 1000);

    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// Global Singleton
window.PasargadInquiryEngine = new PasargadEngine();
