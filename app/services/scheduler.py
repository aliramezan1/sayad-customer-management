"""
Daily Automated Inquiry Scheduler
Runs background tasks to refresh Pasargad credit metrics for all active Sayadi cheques.
"""
import threading
import time
import logging
from datetime import datetime
from app.database import get_db
from app.services.pasargad import record_pasargad_inquiry, calculate_days_until_due
from app.services.smart_logger import smart_logger

logger = logging.getLogger("app.services.scheduler")

class DailyScheduler:
    def __init__(self):
        self.is_running = False
        self.thread = None
        self.last_run = None
        self.next_run = None
        self.status = "idle"
        self.log_history = []
        self.cancel_requested = False
        self.current_progress = {
            "is_running": False,
            "total": 0,
            "processed": 0,
            "success_count": 0,
            "unchanged_count": 0,
            "error_count": 0,
            "excluded_count": 0,
            "percent": 0,
            "current_sayadi": "",
            "current_customer": "",
            "in_transit_sum": 0.0,
            "bounced_sum": 0.0,
            "cleared_sum": 0.0,
            "mode": "idle"
        }

    def start(self):
        """Start the background scheduler daemon."""
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        logger.info("Daily inquiry scheduler started.")

    def _run_loop(self):
        """Main loop: checks periodically if daily execution is due."""
        # Initial gentle pause after startup before checking schedules
        time.sleep(45)
        
        while self.is_running:
            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                
                # Check if run already recorded for today (any status)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM scheduler_logs WHERE run_time LIKE ?", (f"{today_str}%",))
                already_ran = cursor.fetchone()[0] > 0
                conn.close()

                # Run daily at 08:30 AM once per day
                if now.hour == 8 and now.minute >= 30 and not already_ran:
                    smart_logger.log("INFO", "SCHEDULER", f"آغاز زمان‌بندی روزانه استعلامات برای تاریخ {today_str}...")
                    self.run_batch_inquiry()

            except Exception as ex:
                logger.error(f"Scheduler loop error: {ex}")

            # Sleep 10 minutes between checks
            time.sleep(600)

    def cancel_batch(self):
        """Request cooperative cancellation of currently running batch."""
        if self.status == "running":
            self.cancel_requested = True
            smart_logger.log("WARN", "SCHEDULER", "دستور لغو استعلام دسته‌جمعی دریافت شد...")
            return True
        return False

    def run_batch_inquiry(self, default_holder_id: int = 1, force_all: bool = False) -> dict:
        """
        Tiered Smart Maturity Polling or Full Portfolio Batch Inquiry:
        - If force_all is True: Queries 100% of all valid 16-digit Sayadi cheques in portfolio without exclusion.
        - If force_all is False: Excludes settled/cleared old cheques (>30 days overdue with 0 in-transit) to conserve quota.
        - Updates real-time progress for mobile and frontend live dashboards.
        """
        if self.status == "running":
            return {"status": "busy", "message": "زمان‌بند در حال حاضر در حال اجراست", "progress": self.current_progress}
            
        self.status = "running"
        self.cancel_requested = False
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_run = start_time
        
        conn = get_db()
        cursor = conn.cursor()

        # Get all distinct cheques with valid 16-digit sayadi IDs and latest inquiry metrics
        cursor.execute("""
        SELECT 
            c.id,
            c.sayadi_id,
            COALESCE(c.holder_id, ?) as holder_id,
            c.customer_id,
            c.cheque_date,
            c.amount as cheque_amount,
            c.status as cheque_status,
            cust.full_name as customer_name,
            (SELECT in_transit_amount FROM pasargad_inquiries WHERE sayadi_id = c.sayadi_id ORDER BY id DESC LIMIT 1) as last_in_transit,
            (SELECT cleared_amount FROM pasargad_inquiries WHERE sayadi_id = c.sayadi_id ORDER BY id DESC LIMIT 1) as last_cleared,
            (SELECT bounced_amount FROM pasargad_inquiries WHERE sayadi_id = c.sayadi_id ORDER BY id DESC LIMIT 1) as last_bounced,
            (SELECT status FROM pasargad_inquiries WHERE sayadi_id = c.sayadi_id ORDER BY id DESC LIMIT 1) as last_inquiry_status
        FROM cheques c
        LEFT JOIN customers cust ON c.customer_id = cust.id
        WHERE c.sayadi_id IS NOT NULL AND length(trim(c.sayadi_id)) = 16
        ORDER BY c.id ASC
        """, (default_holder_id,))
        raw_cheques = [dict(r) for r in cursor.fetchall()]

        eligible_cheques = []
        excluded_count = 0

        # Smart Filtering or Full Portfolio Selection
        for ch in raw_cheques:
            days_due = calculate_days_until_due(ch["cheque_date"])
            is_old_settled = False
            
            if not force_all and days_due is not None and days_due < -30:
                in_transit = ch.get("last_in_transit") or 0.0
                status = (ch.get("cheque_status") or "").lower()
                last_inq_status = (ch.get("last_inquiry_status") or "").lower()
                cleared = ch.get("last_cleared") or 0.0
                
                if in_transit == 0:
                    if status in ("passed", "cleared", "settled", "paid"):
                        is_old_settled = True
                    elif cleared > 0:
                        is_old_settled = True
                    elif last_inq_status == "not_in_cartable":
                        is_old_settled = True

            if is_old_settled:
                excluded_count += 1
                smart_logger.log(
                    "DEBUG", "SCHEDULER",
                    f"چک {ch['sayadi_id']} به دلیل گذشت بیش از ۳۰ روز از سررسید ({days_due} روز) و تسویه قطعی، از استعلام معاف شد.",
                    sayadi_id=ch["sayadi_id"],
                    customer_name=ch.get("customer_name") or ""
                )
            else:
                eligible_cheques.append((ch, days_due))

        # Tiered Prioritization:
        # Tier 1: <= 7 days (or overdue unsettled)
        # Tier 2: 8 to 30 days
        # Tier 3: > 30 days or unspecified
        def _tier_sort_key(item):
            _, days = item
            if days is None:
                return (3, 99999)
            if days <= 7:
                return (1, days)
            if days <= 30:
                return (2, days)
            return (3, days)

        eligible_cheques.sort(key=_tier_sort_key)

        tier1_count = sum(1 for _, d in eligible_cheques if d is not None and d <= 7)
        tier2_count = sum(1 for _, d in eligible_cheques if d is not None and 7 < d <= 30)
        tier3_count = len(eligible_cheques) - tier1_count - tier2_count

        total_eligible = len(eligible_cheques)
        self.current_progress = {
            "is_running": True,
            "total": total_eligible,
            "processed": 0,
            "success_count": 0,
            "unchanged_count": 0,
            "error_count": 0,
            "excluded_count": excluded_count,
            "percent": 0,
            "current_sayadi": "",
            "current_customer": "",
            "in_transit_sum": 0.0,
            "bounced_sum": 0.0,
            "cleared_sum": 0.0,
            "mode": "full_portfolio" if force_all else "tiered_smart"
        }

        smart_logger.log(
            "INFO", "SCHEDULER",
            f"آغاز استعلام {'کامل سبد چک‌ها (۱۰۰٪)' if force_all else 'چندسطحی هوشمند'}: {total_eligible} چک واجد شرایط (سطح ۱: {tier1_count}، سطح ۲: {tier2_count}، سطح ۳: {tier3_count}) | معاف: {excluded_count}",
            details={
                "force_all": force_all,
                "eligible": total_eligible,
                "tier1": tier1_count,
                "tier2": tier2_count,
                "tier3": tier3_count,
                "excluded": excluded_count,
                "total": len(raw_cheques)
            }
        )

        success_count = 0
        unchanged_count = 0
        error_count = 0
        in_transit_sum = 0.0
        bounced_sum = 0.0
        cleared_sum = 0.0

        for idx, (ch, days_due) in enumerate(eligible_cheques):
            if self.cancel_requested or self.status != "running":
                smart_logger.log("WARN", "SCHEDULER", f"فرآیند استعلام توسط کاربر لغو شد. ({idx} از {total_eligible} پردازش شد)")
                break

            sayadi_id = ch["sayadi_id"]
            holder_id = ch["holder_id"]
            cust_id = ch["customer_id"]
            cust_name = ch.get("customer_name") or ""

            self.current_progress["current_sayadi"] = sayadi_id
            self.current_progress["current_customer"] = cust_name

            try:
                res = record_pasargad_inquiry(
                    sayadi_id=sayadi_id,
                    holder_id=holder_id,
                    customer_id=cust_id,
                    customer_name=cust_name
                )
                
                if res.get("status") == "success":
                    success_count += 1
                    in_transit_sum += float(res.get("in_transit_amount", 0) or 0)
                    bounced_sum += float(res.get("bounced_amount", 0) or 0)
                    cleared_sum += float(res.get("cleared_amount", 0) or 0)
                elif res.get("preserved_from_history"):
                    unchanged_count += 1
                    in_transit_sum += float(res.get("in_transit_amount", 0) or 0)
                    bounced_sum += float(res.get("bounced_amount", 0) or 0)
                    cleared_sum += float(res.get("cleared_amount", 0) or 0)
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Scheduler inquiry error for {sayadi_id}: {e}")
                error_count += 1

            processed = idx + 1
            pct = round((processed / (total_eligible or 1)) * 100, 1)
            self.current_progress["processed"] = processed
            self.current_progress["percent"] = pct
            self.current_progress["success_count"] = success_count
            self.current_progress["unchanged_count"] = unchanged_count
            self.current_progress["error_count"] = error_count
            self.current_progress["in_transit_sum"] = in_transit_sum
            self.current_progress["bounced_sum"] = bounced_sum
            self.current_progress["cleared_sum"] = cleared_sum

            # Safe pacing between cheques (600ms)
            time.sleep(0.6)

        total_processed = success_count + unchanged_count + error_count
        status_str = "success" if error_count == 0 else ("partial" if (success_count > 0 or unchanged_count > 0) else "error")
        details_str = f"موفق: {success_count} | بدون تغییر/حفظ تاریخچه: {unchanged_count} | ناموفق: {error_count} | معاف: {excluded_count} | کل پردازش: {total_processed}"

        cursor.execute("""
        INSERT INTO scheduler_logs (task_name, status, details, items_processed)
        VALUES (?, ?, ?, ?)
        """, (
            "استعلام کامل سبد چک‌های صیادی (پاسارگاد)" if force_all else "استعلام چندسطحی پارتو بانک پاسارگاد",
            status_str,
            details_str,
            total_processed
        ))
        conn.commit()
        conn.close()

        # Invalidate dashboard stats cache so newly recorded inquiries reflect immediately
        try:
            from app.main import invalidate_stats_cache
            invalidate_stats_cache()
        except Exception as e:
            logger.debug(f"Stats cache invalidation from scheduler skipped: {e}")

        self.status = "idle"
        self.current_progress["is_running"] = False
        self.current_progress["percent"] = 100.0

        smart_logger.log(
            "SUCCESS" if status_str == "success" else "INFO",
            "SCHEDULER",
            f"پایان استعلام دسته‌جمعی سبد چک‌ها. {details_str}",
            details={
                "force_all": force_all,
                "success": success_count,
                "unchanged": unchanged_count,
                "error": error_count,
                "excluded": excluded_count,
                "total_processed": total_processed,
                "total_portfolio": len(raw_cheques)
            }
        )
        return {
            "status": status_str,
            "success_count": success_count,
            "unchanged_count": unchanged_count,
            "error_count": error_count,
            "excluded_count": excluded_count,
            "total_processed": total_processed,
            "total_cheques": len(raw_cheques),
            "in_transit_sum": in_transit_sum,
            "bounced_sum": bounced_sum,
            "cleared_sum": cleared_sum,
            "start_time": start_time,
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def get_status(self) -> dict:
        """Get current scheduler status, live progress, and recent logs."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduler_logs ORDER BY id DESC LIMIT 10")
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {
            "is_running": self.is_running,
            "current_status": self.status,
            "last_run": self.last_run,
            "recent_logs": logs,
            "progress": self.current_progress
        }

    def stop(self):
        """Stop the background scheduler."""
        self.is_running = False
        self.status = "stopped"
        logger.info("Daily scheduler stopped.")

scheduler_instance = DailyScheduler()
scheduler_service = scheduler_instance
