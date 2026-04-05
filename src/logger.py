"""
Application Logger
Tracks every application, prevents duplicates and cooldowns,
writes back to applied_jobs.json and pipeline.md
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


class ApplicationLogger:
    def __init__(self, json_path: Path, pipeline_path: Path):
        self.json_path = json_path
        self.pipeline_path = pipeline_path
        self._data = self._load()

    def _load(self) -> dict:
        if self.json_path.exists():
            try:
                return json.loads(self.json_path.read_text())
            except Exception:
                pass
        return {"last_updated": "", "total_applied": 0, "applications": [], "companies_on_cooldown": {}}

    def already_applied(self, job_id: str) -> bool:
        if not job_id:
            return False
        return any(a.get("job_id") == job_id for a in self._data["applications"])

    def is_on_cooldown(self, company: str) -> bool:
        if not company:
            return False
        cooldown = self._data.get("companies_on_cooldown", {})
        if company in cooldown:
            cooldown_until = datetime.fromisoformat(cooldown[company])
            if datetime.utcnow() < cooldown_until:
                return True
            else:
                del cooldown[company]
        return False

    def log_application(self, job: dict, result: dict):
        """Record a successful application."""
        now = datetime.utcnow()
        entry = {
            "job_id": job.get("job_id", ""),
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": job.get("url", ""),
            "applied_at": now.isoformat(),
            "applied_date": now.strftime("%Y-%m-%d"),
            "method": "LinkedIn Auto (GitHub Actions)",
            "status": "Applied",
            "result": result
        }
        self._data["applications"].append(entry)
        self._data["total_applied"] = len(self._data["applications"])

        # Add company to cooldown (30 days)
        company = job.get("company", "")
        if company:
            cooldown_days = 30
            cooldown_until = (now + timedelta(days=cooldown_days)).isoformat()
            self._data["companies_on_cooldown"][company] = cooldown_until

        # Update pipeline.md
        self._append_to_pipeline(entry)

    def total_applied(self) -> int:
        return self._data.get("total_applied", 0)

    def save(self):
        """Persist the log to disk."""
        self._data["last_updated"] = datetime.utcnow().isoformat()
        self.json_path.write_text(json.dumps(self._data, indent=2))
        log.info(f"Application log saved. Total: {self._data['total_applied']}")

    def _append_to_pipeline(self, entry: dict):
        """Append a row to pipeline.md."""
        try:
            loc = entry.get("location", "")
            row = (
                f"| {entry['applied_date']} "
                f"| {entry['company']} "
                f"| {entry['title']} "
                f"| {loc} "
                f"| Auto "
                f"| Applied |\n"
            )
            with open(self.pipeline_path, "a") as f:
                f.write(row)
        except Exception as e:
            log.debug(f"Pipeline.md append error: {e}")
