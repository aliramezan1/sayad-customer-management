# -*- coding: utf-8 -*-
"""
Smart Multi-Tier Logging Service for Sayad Cheque & Customer Management System
Features:
- Dual output: Structured JSON rotating log file + Human readable text log
- In-memory thread-safe circular buffer for instant real-time UI queries (up to 2,000 entries)
- Persian (Jalali) datetime formatting with Tehran local time
- Multi-dimensional tagging (PASARGAD, CBI, DATABASE, API, SCHEDULER, SYSTEM, CLIENT)
- Performance & duration tracking, error severity analysis, and health diagnostics
"""
import os
import time
import json
import logging
import threading
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Any

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

JSON_LOG_FILE = os.path.join(LOGS_DIR, "system.json.log")
TEXT_LOG_FILE = os.path.join(LOGS_DIR, "app.log")

def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy if (gm > 2) else (gy - 1)
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def get_jalali_timestamp(dt: Optional[datetime] = None) -> str:
    if not dt:
        dt = datetime.now()
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {dt.strftime('%H:%M:%S')}"

class SmartLogger:
    def __init__(self, max_buffer_size: int = 2000):
        self._lock = threading.Lock()
        self._buffer: deque = deque(maxlen=max_buffer_size)
        self._counter: int = 0
        self._stats = {
            "total": 0,
            "info": 0,
            "warn": 0,
            "error": 0,
            "success": 0,
            "debug": 0
        }
        self.log(
            level="INFO",
            tag="SYSTEM",
            message="سرویس لاگینگ هوشمند و پایش سلامت سیستم راه‌اندازی شد.",
            details={"logs_dir": LOGS_DIR}
        )

    def log(
        self,
        level: str,
        tag: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        sayadi_id: Optional[str] = None,
        customer_name: Optional[str] = None,
        duration_ms: Optional[float] = None
    ) -> Dict[str, Any]:
        now = datetime.now()
        iso_time = now.isoformat()
        jalali_time = get_jalali_timestamp(now)
        level_upper = level.upper()

        with self._lock:
            self._counter += 1
            entry_id = self._counter
            
            entry = {
                "id": entry_id,
                "timestamp": iso_time,
                "jalali_time": jalali_time,
                "level": level_upper,
                "tag": tag.upper(),
                "message": message,
                "details": details or {},
                "sayadi_id": sayadi_id or "",
                "customer_name": customer_name or "",
                "duration_ms": round(duration_ms, 2) if duration_ms is not None else None
            }
            
            self._buffer.append(entry)
            self._stats["total"] += 1
            lvl_key = level_upper.lower()
            if lvl_key in self._stats:
                self._stats[lvl_key] += 1

            self._write_to_files(entry)
            return entry

    def _write_to_files(self, entry: Dict[str, Any]):
        try:
            with open(JSON_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
            dur_str = f" [{entry['duration_ms']}ms]" if entry.get('duration_ms') is not None else ""
            sayad_str = f" [Sayad: {entry['sayadi_id']}]" if entry.get('sayadi_id') else ""
            line = f"[{entry['jalali_time']}] [{entry['level']:<7}] [{entry['tag']:<9}] {entry['message']}{sayad_str}{dur_str}\n"
            
            with open(TEXT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def get_logs(
        self,
        level: Optional[str] = None,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        sayadi_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        with self._lock:
            entries = list(self._buffer)

        filtered = entries[::-1]

        if level and level.upper() != "ALL":
            lvl_u = level.upper()
            filtered = [e for e in filtered if e["level"] == lvl_u]

        if tag and tag.upper() != "ALL":
            tag_u = tag.upper()
            filtered = [e for e in filtered if e["tag"] == tag_u]

        if sayadi_id:
            s_clean = sayadi_id.strip()
            filtered = [e for e in filtered if s_clean in (e.get("sayadi_id") or "")]

        if search:
            q = search.strip().lower()
            filtered = [
                e for e in filtered
                if q in e["message"].lower() or
                   q in (e.get("sayadi_id") or "").lower() or
                   q in (e.get("customer_name") or "").lower() or
                   q in json.dumps(e.get("details", {}), ensure_ascii=False).lower()
            ]

        total_count = len(filtered)
        paginated = filtered[offset:offset + limit]

        return {
            "logs": paginated,
            "total_count": total_count,
            "stats": self._stats.copy()
        }

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._stats = {k: 0 for k in self._stats}
            self.log("INFO", "SYSTEM", "بافر لاگ‌های زنده توسط کاربر پاکسازی شد.")

smart_logger = SmartLogger()
