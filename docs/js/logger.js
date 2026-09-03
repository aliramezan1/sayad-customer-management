/**
 * Enterprise Multi-Tier Smart Logging Engine for Sayad Pro
 * Handles persistent log storage, live backend telemetry forwarding, event emitting, and floating console hooks.
 */
class SystemLogger {
  constructor(maxLogs = 1000) {
    this.STORAGE_KEY = 'sayad_app_system_logs_v3';
    this.maxLogs = maxLogs;
    this.logs = this.loadLogs();
    this.listeners = [];
    this.backendUrl = (window.PasargadInquiryEngine && window.PasargadInquiryEngine.getSavedBackendUrl()) || 'http://127.0.0.1:8000';
  }

  loadLogs() {
    try {
      const saved = localStorage.getItem(this.STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch (e) {
      return [];
    }
  }

  saveLogs() {
    try {
      if (this.logs.length > this.maxLogs) {
        this.logs = this.logs.slice(0, this.maxLogs);
      }
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.logs));
    } catch (e) {}
  }

  log(level, category, message, details = null, sayadiId = null, customerName = null) {
    const timestamp = new Date();
    const timeStr = timestamp.toLocaleTimeString('fa-IR', { hour12: false });
    const dateStr = timestamp.toLocaleDateString('fa-IR');
    
    const entry = {
      id: Date.now() + Math.random().toString(36).substring(2, 7),
      timestamp: timestamp.toISOString(),
      timeFormatted: `${dateStr} ${timeStr}`,
      jalali_time: `${dateStr} ${timeStr}`,
      level: (level || 'INFO').toUpperCase(), // 'INFO', 'SUCCESS', 'WARN', 'ERROR', 'DEBUG', 'BATCH'
      tag: (category || 'SYSTEM').toUpperCase(),
      category: (category || 'SYSTEM').toUpperCase(),
      message: message,
      sayadi_id: sayadiId || '',
      customer_name: customerName || '',
      details: details ? (typeof details === 'object' ? details : { raw: String(details) }) : {}
    };

    this.logs.unshift(entry);
    this.saveLogs();
    this.notifyListeners(entry);

    // Forward to backend smart logger in background (fire-and-forget)
    this._forwardToBackend(entry);

    // Output to browser console
    const colors = {
      INFO: 'color: #38bdf8',
      SUCCESS: 'color: #10b981; font-weight: bold',
      WARN: 'color: #f59e0b; font-weight: bold',
      ERROR: 'color: #ef4444; font-weight: bold',
      DEBUG: 'color: #94a3b8',
      BATCH: 'color: #a855f7; font-weight: bold'
    };
    const style = colors[entry.level] || 'color: #94a3b8';
    console.log(`%c[${entry.level}] [${entry.tag}] ${entry.message}`, style, details || '');

    // Live update bottom floating console if open
    if (window.SayadApp && typeof window.SayadApp.appendLiveLogEntry === 'function') {
      window.SayadApp.appendLiveLogEntry(entry);
    }

    return entry;
  }

  async _forwardToBackend(entry) {
    try {
      fetch(`${this.backendUrl}/api/logs/client`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          level: entry.level,
          tag: entry.tag,
          message: entry.message,
          details: entry.details,
          sayadi_id: entry.sayadi_id,
          customer_name: entry.customer_name
        })
      }).catch(() => {});
    } catch (e) {}
  }

  info(category, message, details = null) {
    return this.log('INFO', category, message, details);
  }

  success(category, message, details = null) {
    return this.log('SUCCESS', category, message, details);
  }

  warn(category, message, details = null) {
    return this.log('WARN', category, message, details);
  }

  error(category, message, details = null) {
    return this.log('ERROR', category, message, details);
  }

  debug(category, message, details = null) {
    return this.log('DEBUG', category, message, details);
  }

  batch(category, message, details = null) {
    return this.log('BATCH', category, message, details);
  }

  clearLogs() {
    this.logs = [];
    localStorage.removeItem(this.STORAGE_KEY);
    this.notifyListeners(null);
    try {
      fetch(`${this.backendUrl}/api/logs`, { method: 'DELETE' }).catch(() => {});
    } catch (e) {}
  }

  getLogs(filter = {}) {
    return this.logs.filter(log => {
      if (filter.level && filter.level !== 'ALL' && log.level !== filter.level) return false;
      if (filter.category && filter.category !== 'ALL' && log.category !== filter.category) return false;
      if (filter.tag && filter.tag !== 'ALL' && log.tag !== filter.tag) return false;
      if (filter.search) {
        const q = filter.search.toLowerCase();
        const msg = (log.message || '').toLowerCase();
        const sayad = (log.sayadi_id || '').toLowerCase();
        const cust = (log.customer_name || '').toLowerCase();
        const det = JSON.stringify(log.details || '').toLowerCase();
        if (!msg.includes(q) && !sayad.includes(q) && !cust.includes(q) && !det.includes(q)) return false;
      }
      return true;
    });
  }

  subscribe(callback) {
    if (typeof callback === 'function') {
      this.listeners.push(callback);
    }
  }

  unsubscribe(callback) {
    this.listeners = this.listeners.filter(cb => cb !== callback);
  }

  notifyListeners(entry) {
    this.listeners.forEach(cb => {
      try {
        cb(entry, this.logs);
      } catch (err) {
        console.error('Log listener error:', err);
      }
    });
  }

  exportLogsAsJSON() {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(this.logs, null, 2));
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `sayad_system_logs_${new Date().toISOString().slice(0,10)}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  }

  exportLogsAsText() {
    let text = `======================================================\n`;
    text += `   گزارش جامع وقایع و لاگ‌های سیستم صیاد پرو\n`;
    text += `   تاریخ خروجی: ${new Date().toLocaleDateString('fa-IR')} ${new Date().toLocaleTimeString('fa-IR')}\n`;
    text += `======================================================\n\n`;

    this.logs.forEach(l => {
      text += `[${l.timeFormatted}] [${l.level.padEnd(7)}] [${l.category.padEnd(9)}] ${l.message}\n`;
      if (l.details && Object.keys(l.details).length > 0) {
        text += `   جزئیات: ${JSON.stringify(l.details)}\n`;
      }
    });

    const dataStr = "data:text/plain;charset=utf-8," + encodeURIComponent(text);
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `sayad_system_logs_${new Date().toISOString().slice(0,10)}.txt`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  }
}

// Global logger instance
window.AppLogger = new SystemLogger();
