"""
Daily Automated Inquiry Scheduler
Runs background tasks to refresh Pasargad credit metrics for all active Sayadi cheques.
"""
import threading
import time
import logging
from datetime import datetime
from app.database import get_db
from app.services.pasargad import record_pasargad_inquiry
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

    def run_batch_inquiry(self, default_holder_id: int = 1) -> dict:
        """Run batch inquiry for all cheques in database with safe pacing."""
        if self.status == "running":
            return {"status": "busy", "message": "زمان‌بند در حال حاضر در حال اجراست"}
            
        self.status = "running"
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_run = start_time
        
        conn = get_db()
        cursor = conn.cursor()

        # Get all distinct cheques with valid 16-digit sayadi IDs
        cursor.execute("""
        SELECT DISTINCT c.sayadi_id, COALESCE(c.holder_id, ?) as holder_id, c.customer_id
        FROM cheques c
        WHERE c.sayadi_id IS NOT NULL AND length(trim(c.sayadi_id)) = 16
        """, (default_holder_id,))
        cheques_to_query = cursor.fetchall()
        
        success_count = 0
        error_count = 0
        
        for ch in cheques_to_query:
            if not self.is_running:
                break

            sayadi_id = ch["sayadi_id"]
            holder_id = ch["holder_id"]
            cust_id = ch["customer_id"]

            try:
                res = record_pasargad_inquiry(sayadi_id, holder_id, cust_id)
                if res.get("status") == "success":
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Scheduler inquiry error for {sayadi_id}: {e}")
                error_count += 1
            
            # Safe pacing between cheques (1.5 seconds)
            time.sleep(1.5)

        total_processed = success_count + error_count
        status_str = "success" if error_count == 0 else ("partial" if success_count > 0 else "error")

        cursor.execute("""
        INSERT INTO scheduler_logs (task_name, status, details, items_processed)
        VALUES (?, ?, ?, ?)
        """, (
            "استعلام روزانه بانک پاسارگاد",
            status_str,
            f"موفق: {success_count} | خطا: {error_count} | مجموع: {total_processed}",
            total_processed
        ))
        conn.commit()
        conn.close()

        self.status = "idle"
        smart_logger.log(
            "SUCCESS" if status_str == "success" else "INFO",
            "SCHEDULER",
            f"پایان استعلام زمان‌بندی‌شده روزانه. موفق: {success_count} | خطا: {error_count}",
            details={"success": success_count, "error": error_count, "total": total_processed}
        )
        return {
            "status": status_str,
            "success_count": success_count,
            "error_count": error_count,
            "total_processed": total_processed,
            "start_time": start_time,
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    def stop(self):
        """Stop the background scheduler."""
        self.is_running = False
        self.status = "stopped"
        logger.info("Daily scheduler stopped.")

scheduler_instance = DailyScheduler()
scheduler_service = scheduler_instance
