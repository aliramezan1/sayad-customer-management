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
        while self.is_running:
            now = datetime.now()
            # Run daily at 08:30 AM or if never run before today
            today_str = now.strftime("%Y-%m-%d")
            
            # Check if run already recorded for today
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM scheduler_logs WHERE run_time LIKE ? AND status = 'success'", (f"{today_str}%",))
            already_ran = cursor.fetchone()[0] > 0
            conn.close()

            # If it is past 8 AM and hasn't run today, execute
            if now.hour >= 8 and not already_ran:
                logger.info(f"Triggering scheduled daily inquiry for {today_str}...")
                self.run_batch_inquiry()

            # Sleep 10 minutes between checks
            time.sleep(600)

    def run_batch_inquiry(self, default_holder_id: int = 1) -> dict:
        """Run batch inquiry for all cheques in database."""
        self.status = "running"
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_run = start_time
        
        conn = get_db()
        cursor = conn.cursor()

        # Get all distinct cheques with valid sayadi IDs
        cursor.execute("""
        SELECT DISTINCT c.sayadi_id, COALESCE(c.holder_id, ?) as holder_id, c.customer_id
        FROM cheques c
        WHERE c.sayadi_id IS NOT NULL AND length(c.sayadi_id) = 16
        """, (default_holder_id,))
        cheques_to_query = cursor.fetchall()
        
        success_count = 0
        error_count = 0
        
        for ch in cheques_to_query:
            sayadi_id = ch["sayadi_id"]
            holder_id = ch["holder_id"]
            cust_id = ch["customer_id"]

            try:
                res = record_pasargad_inquiry(sayadi_id, holder_id, cust_id)
                if res["status"] == "success":
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"Error inquiring {sayadi_id}: {e}")
                error_count += 1
            
            # Small delay to be polite to the server
            time.sleep(1.0)

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
        return {
            "status": status_str,
            "success_count": success_count,
            "error_count": error_count,
            "total_processed": total_processed,
            "run_time": start_time
        }

    def get_status(self) -> dict:
        """Get current scheduler status and recent logs."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM scheduler_logs ORDER BY id DESC LIMIT 10")
        logs = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return {
            "is_running": self.is_running,
            "current_status": self.status,
            "last_run": self.last_run,
            "recent_logs": logs
        }

scheduler_instance = DailyScheduler()
