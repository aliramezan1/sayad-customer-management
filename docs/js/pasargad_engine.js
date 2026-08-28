/**
 * High-Resilience Parallel Pasargad Inquiry & Auto-Scheduler Engine
 * Supports Multi-Proxy Fallback Pipeline, Parallel Concurrency, Retries, Jitter, and Cron Scheduling.
 */
class PasargadEngine {
  constructor() {
    this.proxies = [
      { name: 'Direct Gateway', format: (url) => url },
      { name: 'CORS Proxy Ultra', format: (url) => `https://corsproxy.io/?url=${encodeURIComponent(url)}` },
      { name: 'AllOrigins Mirror', format: (url) => `https://api.allorigins.win/raw?url=${encodeURIComponent(url)}` },
      { name: 'CodeTabs Gateway', format: (url) => `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(url)}` },
      { name: 'ThingProxy Cloud', format: (url) => `https://thingproxy.freeboard.io/fetch/${url}` }
    ];

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
      bouncedSum: 0
    };

    // Auto-Scheduler state
    this.scheduler = {
      enabled: false,
      intervalHours: 6, // default every 6 hours
      timerId: null,
      countdownTimerId: null,
      lastRun: null,
      nextRun: null
    };

    this.initSchedulerFromStorage();
  }

  // ─────────────────────────────────────────────────────────────
  // 🛡️ Multi-Proxy Single Cheque Inquiry Pipeline
  // ─────────────────────────────────────────────────────────────
  async queryCheque(sayadiId, holderNationalId, options = {}) {
    const cleanSayadi = String(sayadiId || '').trim();
    const cleanIdCode = String(holderNationalId || '').trim();
    const forceRefresh = options.forceRefresh || false;
    const timeoutMs = options.timeoutMs || 12000;

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

    // Check in-memory cache
    const cacheKey = `${cleanSayadi}_${cleanIdCode}`;
    if (!forceRefresh && this.cache.has(cacheKey)) {
      const cached = this.cache.get(cacheKey);
      if (Date.now() - cached.timestamp < this.cacheTTL) {
        window.AppLogger.info('PASARGAD', `استعلام صیادی ${cleanSayadi} از حافظه موقت (Cache) خوانده شد.`);
        return cached.data;
      }
    }

    const rawApiUrl = `https://sec.bpi.ir/prls/api/v1/inquiry/chequeStatus?IdCode=${cleanIdCode}&IdType=1&SayadId=${cleanSayadi}`;
    let lastError = null;

    // Try proxies in succession with retry
    for (let pIdx = 0; pIdx < this.proxies.length; pIdx++) {
      const proxy = this.proxies[pIdx];
      const targetUrl = proxy.format(rawApiUrl);

      try {
        window.AppLogger.info('PASARGAD', `ارسال درخواست صیادی ${cleanSayadi} از طریق [${proxy.name}]...`);
        
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), timeoutMs);

        const response = await fetch(targetUrl, {
          method: 'GET',
          headers: {
            'Accept': 'application/json, text/plain, */*'
          },
          signal: controller.signal
        });

        clearTimeout(timeout);

        if (!response.ok) {
          throw new Error(`HTTP Error ${response.status}: ${response.statusText}`);
        }

        const rawText = await response.text();
        let data = null;

        try {
          data = JSON.parse(rawText);
        } catch (jsonErr) {
          // If proxy wrapped json in wrapper
          const match = rawText.match(/\{[\s\S]*\}/);
          if (match) {
            data = JSON.parse(match[0]);
          } else {
            throw new Error(`پاسخ دریافتی فرمت JSON معتبر نداشت`);
          }
        }

        if (data) {
          const parsedResult = this.parsePasargadResponse(data, cleanSayadi, cleanIdCode);
          
          // Save to cache
          this.cache.set(cacheKey, {
            timestamp: Date.now(),
            data: parsedResult
          });

          window.AppLogger.success('PASARGAD', `استعلام صیادی ${cleanSayadi} با موفقیت دریافت شد. (در راه: ${parsedResult.in_transit_amount.toLocaleString('fa-IR')} | برگشتی: ${parsedResult.bounced_amount.toLocaleString('fa-IR')})`);
          return parsedResult;
        }

      } catch (err) {
        lastError = err;
        window.AppLogger.warn('PASARGAD', `عدم موفقیت با [${proxy.name}] برای صیادی ${cleanSayadi}: ${err.message}. تلاش با پروکسی بعدی...`);
        // Small jitter before trying next proxy
        await this.delay(200);
      }
    }

    const finalErrMsg = `خطا در تمام مسیرهای ارتباطی برای صیادی ${cleanSayadi}: ${lastError ? lastError.message : 'پاسخی دریافت نشد'}`;
    window.AppLogger.error('PASARGAD', finalErrMsg);
    throw new Error(finalErrMsg);
  }

  parsePasargadResponse(data, sayadiId, holderNationalId) {
    const onGoing = parseFloat(data.onGoingAmount || 0);
    const blocked = parseFloat(data.blocked || 0);
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

    return {
      status: 'success',
      sayadi_id: sayadiId,
      holder_national_id: holderNationalId,
      in_transit_amount: onGoing,
      in_transit_count: onGoing > 0 ? 1 : 0,
      cleared_amount: totalCleared,
      cleared_count: clearedCount,
      bounced_amount: totalBounced,
      bounced_count: bouncedCount,
      blocked_amount: blocked,
      owners_info: owners,
      inquiry_time: new Date().toISOString().replace('T', ' ').slice(0, 19)
    };
  }

  // ─────────────────────────────────────────────────────────────
  // ⚡ Parallel Batch Inquiry Engine (Concurrency Limiter)
  // ─────────────────────────────────────────────────────────────
  async runBatchInquiry(items, holderMap, options = {}, callbacks = {}) {
    if (this.batchState.isRunning) {
      throw new Error('یک فرآیند استعلام گروهی در حال اجرا است.');
    }

    const concurrency = options.concurrency || 3; // 3 parallel workers
    const delayBetweenRequests = options.delayMs || 300; // ms jitter
    const onProgress = callbacks.onProgress || (() => {});
    const onItemComplete = callbacks.onItemComplete || (() => {});
    const onFinished = callbacks.onFinished || (() => {});

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
      bouncedSum: 0
    };

    window.AppLogger.batch('BATCH', `آغاز استعلام دسته‌جمعی ${items.length} فقره چک با ${concurrency} فرآیند موازی...`);

    const queue = [...items];
    const results = [];

    // Worker implementation
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
          this.batchState.errorCount++;
          window.AppLogger.warn('BATCH', `چک صیادی ${item.sayadi_id} فاقد دارنده معتبر است.`);
          onProgress({ ...this.batchState, currentItem: item });
          continue;
        }

        try {
          // Add random jitter
          await this.delay(delayBetweenRequests + Math.floor(Math.random() * 200));

          const res = await this.queryCheque(item.sayadi_id, holder.national_id, {
            forceRefresh: options.forceRefresh
          });

          this.batchState.processed++;
          this.batchState.successCount++;
          this.batchState.inTransitSum += res.in_transit_amount;
          this.batchState.clearedSum += res.cleared_amount;
          this.batchState.bouncedSum += res.bounced_amount;

          results.push({ item, result: res, status: 'success' });
          onItemComplete(item, res);

        } catch (err) {
          this.batchState.processed++;
          this.batchState.errorCount++;
          results.push({ item, error: err.message, status: 'error' });
          window.AppLogger.error('BATCH', `خطا در استعلام چک صیادی ${item.sayadi_id}: ${err.message}`);
        }

        onProgress({ ...this.batchState, currentItem: item });
      }
    };

    // Launch parallel workers
    const workers = [];
    for (let i = 0; i < concurrency; i++) {
      workers.push(worker(i + 1));
    }

    await Promise.all(workers);

    this.batchState.isRunning = false;
    window.AppLogger.batch('BATCH', `پایان استعلام گروهی. موفق: ${this.batchState.successCount} | ناموفق: ${this.batchState.errorCount} | مجموع در راه: ${this.batchState.inTransitSum.toLocaleString('fa-IR')} ریال | برگشتی: ${this.batchState.bouncedSum.toLocaleString('fa-IR')} ریال`);

    onFinished({
      ...this.batchState,
      results
    });

    return results;
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
    window.AppLogger.warn('BATCH', 'فرآیند استعلام گروهی توسط کاربر لغو گردید.');
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

      window.AppLogger.info('SCHEDULER', `زمان‌بندی خودکار استعلام فعال شد (هر ${this.scheduler.intervalHours} ساعت یکبار). زمان اجرای بعدی: ${this.scheduler.nextRun.toLocaleTimeString('fa-IR')}`);

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
