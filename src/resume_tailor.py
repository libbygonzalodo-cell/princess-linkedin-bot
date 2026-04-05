"""
Resume Tailor — Uses Claude API to tailor master resume to each job description
Generates a PDF of the tailored resume for upload during Easy Apply
Strict rule: only facts from master_resume.json, no fabrication
"""

import os
import json
import logging
import tempfile
from pathlib import Path

import anthropic
from resume_pdf import generate_resume_pdf

log = logging.getLogger(__name__)

TAILOR_PROMPT = """You are helping Princess Gonzalodo tailor her resume to a specific job posting.

STRICT RULES:
1. ONLY use facts that exist in the master resume provided. Do NOT invent new experience, skills, certifications, or experience.
2. You MAY reorder bullet points, adjust emphasis, and choose which bullets to lead with based on relevance to the job.
3. You MAY rewrite the summary to highlight the most relevant aspects of her background for this specific role.
4. You MAY choose which skills to list first in the skills section based on what the job description emphasizes.
5. Do NOT add any experience, skill, certification, company, or date that is not in the master resume.
6. Keep all bullet points factually accurate — do not exaggerate or add specifics that aren't there.

OUTPUT FORMAT: Return valid JSON matching exactly this structure:
{
  "summary": "tailored 2-3 sentence summary",
  "experience": [
    {
      "company": "...",
      "title": "...",
      "start": "...",
      "end": "...",
      "bullets": ["bullet 1", "bullet 2", ...]
    }
  ],
  "skills_order": ["category1", "category2", "category3", "category4"],
  "certifications_to_highlight": ["cert name"],
  "emphasis_note": "one sentence on what you emphasized and why"
}

For skills_order, use these category names in your preferred order: revops_crm, analytics_programming, accounting_finance, soft_skills

MASTER RESUME:
{master_resume}

JOB TITLE: {job_title}
COMPANY: {company}
JOB DETCRIPTION:
{job_description}

Return ONLY the JSON object, no other text."""


class ResumeTailor:
    def __init__(self, master_resume: dict, api_key: str):
        self.master_resume = master_resume
        self.enabled = bool(api_key)
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else None
        self._model = "claude-3-5-haiku-20241022"

    def tailor_and_generate_pdf(self, job: dict) -> str | None:
        """Tailor and generate PDF. Returns path to PDF file."""
        if not self.enabled or not job.get("description"):
            return self._generate_default_pdf()

        try:
            tailored = self._tailor(job)
            if tailored:
                merged = self._merge(tailored)
                return generate_resume_pdf(merged)
        except Exception as e:
            log.warning(f"Resume tailoring failed: {e}. Using default resume.")

        return self._generate_default_pdf()

    def _tailor(self, job: dict) -> dict | None:
        """Call Claude API to tailor the resume."""
        prompt = TAILOR_PROMPT.format(
            master_resume=json.dumps(self.master_resume, indent=2),
            job_title=job.get("title", ""),
            company=job.get("company", ""),
            job_description=job.get("description", "")[:3000]
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        if raw.endswith("```"):
            raw = raw[:-3]

        return json.loads(raw.strip())

    def _merge(self, tailored: dict) -> dict:
        merged = dict(self.master_resume)
        if tailored.get("summary"):
            merged["summary"] = tailored["summary"]
        if tailored.get("experience"):
            tailored_exp = {e["title"] + e["company"]: e for e in tailored["experience"]}
            new_exp = []
            for exp in merged["experience"]:
                key = exp["title"] + exp["company"]
                if key in tailored_exp:
                    new_entry = dict(exp)
                    if tailored_exp[key].get("bullets"):
                        new_entry["bullets"] = tailored_exp[key]["bullets"]
                    new_exp.append(new_entry)
                else:
                    new_exp.append(exp)
            merged["experience"] = new_exp
        if tailored.get("skills_order"):
            skills = merged.get("skills", {})
            ordered = {}
            for cat in tailored["skills_order"]:
                if cat in skills:
                    ordered[cat] = skills[cat]
            for cat, val in skills.items():
                if cat not in ordered:
                    ordered[cat] = val
            merged["skills"] = ordered
        return merged

    def _generate_default_pdf(self) -> str | None:
        try:
            return generate_resume_pdf(self.master_resume)
        except Exception as e:
            log.warning(f"Default PDF generation failed: {e}")
            return None
