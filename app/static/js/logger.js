/**
 * Enterprise Client-Side Logging Engine for Sayad Pro
 * Handles persistent log storage, event emitting, filtering, and export.
 */
class SystemLogger {
  constructor(maxLogs = 500) {
    this.STORAGE_KEY = 'sayad_app_system_logs_v2';
    this.maxLogs = maxLogs;
    this.logs = this.loadLogs();
    this.listeners = [];
  }

  loadLogs() {
    try {
      const saved = localStorage.getItem(this.STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch (e) {
      console.error('Failed to load logs from localStorage:', e);
      return [];
    }
  }

  saveLogs() {
    try {
      // Keep only recent maxLogs
      if (this.logs.length > this.maxLogs) {
        this.logs = this.logs.slice(0, this.maxLogs);
      }
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.logs));
    } catch (e) {
      console.error('Failed to save logs to localStorage:', e);
    }
  }

  log(level, category, message, details = null) {
    const timestamp = new Date();
    const timeStr = timestamp.toLocaleTimeString('fa-IR', { hour12: false });
    const dateStr = timestamp.toLocaleDateString('fa-IR');
    
    const entry = {
      id: Date.now() + Math.random().toString(36).substring(2, 7),
      timestamp: timestamp.toISOString(),
      timeFormatted: `${dateStr} ${timeStr}`,
      level: level.toUpperCase(), // 'INFO', 'SUCCESS', 'WARN', 'ERROR', 'BATCH'
      category: category,         // 'PASARGAD', 'AUTH', 'CRUD', 'SCHEDULER', 'SYSTEM'
      message: message,
      details: details ? (typeof details === 'object' ? JSON.stringify(details, null, 2) : String(details)) : null
    };

    this.logs.unshift(entry);
    this.saveLogs();
    this.notifyListeners(entry);

    // Also output to browser console with styled colors
    const colors = {
      INFO: 'color: #38bdf8',
      SUCCESS: 'color: #10b981',
      WARN: 'color: #f59e0b',
      ERROR: 'color: #ef4444; font-weight: bold',
      BATCH: 'color: #a855f7; font-weight: bold'
    };
    console.log(`%c[${entry.level}] [${entry.category}] ${entry.message}`, colors[entry.level] || 'color: #94a3b8', details || '');

    return entry;
  }

  info(category, message, details) { return this.log('INFO', category, message, details); }
  success(category, message, details) { return this.log('SUCCESS', category, message, details); }
  warn(category, message, details) { return this.log('WARN', category, message, details); }
  error(category, message, details) { return this.log('ERROR', category, message, details); }
  batch(category, message, details) { return this.log('BATCH', category, message, details); }

  clearLogs() {
    this.logs = [];
    localStorage.removeItem(this.STORAGE_KEY);
    this.notifyListeners(null);
    this.info('SYSTEM', 'تمام لاگ‌های سیستم توسط کاربر پاکسازی شدند.');
  }

  exportLogsTXT() {
    if (this.logs.length === 0) return '';
    let content = `=======================================================\n`;
    content += ` گزارش جامع وقایع و لاگ‌های سامانه صیاد پرو\n`;
    content += ` تاریخ تولید: ${new Date().toLocaleString('fa-IR')}\n`;
    content += ` تعداد لاگ‌ها: ${this.logs.length}\n`;
    content += `=======================================================\n\n`;

    this.logs.forEach(l => {
      content += `[${l.timeFormatted}] [${l.level.padEnd(7)}] [${l.category.padEnd(10)}] ${l.message}\n`;
      if (l.details) {
        content += `   جزئیات: ${l.details.replace(/\n/g, '\n   ')}\n`;
      }
      content += `-------------------------------------------------------\n`;
    });

    return content;
  }

  exportLogsJSON() {
    return JSON.stringify(this.logs, null, 2);
  }

  addListener(fn) {
    if (typeof fn === 'function') {
      this.listeners.push(fn);
    }
  }

  notifyListeners(entry) {
    this.listeners.forEach(fn => {
      try { fn(entry, this.logs); } catch (e) { console.error('Error in log listener:', e); }
    });
  }
}

// Global Singleton Instance
window.AppLogger = new SystemLogger(500);
