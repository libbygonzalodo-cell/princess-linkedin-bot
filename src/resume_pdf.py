"""
Resume PDF Generator
Creates a clean, formatted PDF resume from a resume dict
Uses fpdf2 — pure Python, no external dependencies
"""

import tempfile
import os
import logging
from pathlib import Path

from fpdf import FPDF, XPos, YPos

log = logging.getLogger(__name__)

# Colors
ACCENT_R, ACCENT_G, ACCENT_B = 26, 107, 124      # Deep teal
DARK_R, DARK_G, DARK_B       = 28, 43, 54         # Near-black body text
MID_R, MID_G, MID_B          = 74, 101, 114       # Slate gray for dates/secondary

FONT = "Helvetica"


class ResumePDF(FPDF):
    def __init__(self):
        super().__init__(unit="pt", format="Letter")
        self.set_margins(left=40, top=40, right=40)
        self.set_auto_page_break(auto=True, margin=40)

    def header_bar(self, resume: dict):
        """Dark teal name bar across the top."""
        hdr = resume.get("header", {})
        self.set_fill_color(ACCENT_R, ACCENT_G, ACCENT_B)
        self.rect(0, 0, 612, 72, "F")

        # Name
        self.set_xy(40, 14)
        self.set_text_color(255, 255, 255)
        self.set_font(FONT, "B", 24)
        self.cell(0, 12, hdr.get("name", ""), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Sub-headline
        self.set_font(FONT, "", 10)
        self.set_text_color(208, 236, 242)
        self.set_x(40)
        self.cell(0, 8, "Revenue Operations  ·  Business Analytics", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # Contact info — right-aligned
        contact_parts = [
            hdr.get("location", ""),
            hdr.get("email", ""),
            hdr.get("linkedin", "")
        ]
        self.set_font(FONT, "", 8)
        self.set_text_color(208, 236, 242)
        for part in contact_parts:
            if part:
                self.set_xy(40, self.get_y())
                self.cell(530, 6, part, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.ln(10)

    def section_header(self, title: str):
        """Teal-accented section header with bottom rule."""
        self.set_text_color(ACCENT_R, ACCENT_G, ACCENT_B)
        self.set_font(FONT, "B", 10)
        self.set_draw_color(ACCENT_R, ACCENT_G, ACCENT_B)
        self.set_line_width(0.5)
        y = self.get_y() + 4
        self.set_xy(40, y)
        self.cell(0, 9, title.upper(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.line(40, self.get_y(), 572, self.get_y())
        self.ln(4)

    def role_header(self, title: str, company: str, dates: str):
        """Job title + company + right-aligned dates."""
        self.set_text_color(DARK_R, DARK_G, DARK_B)
        self.set_font(FONT, "B", 10)
        y = self.get_y()
        self.set_xy(40, y)
        # Title + company (left)
        title_company = f"{title}  ·  {company}"
        self.cell(390, 11, title_company, new_x=XPos.RIGHT)
        # Dates (right)
        self.set_text_color(MID_R, MID_G, MID_B)
        self.set_font(FONT, "I", 9)
        self.cell(142, 11, dates, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def bullet_point(self, text: str):
        """Indented bullet point."""
        self.set_text_color(DARK_R, DARK_G, DARK_B)
        self.set_font(FONT, "", 9)
        self.set_x(48)
        self.cell(8, 8, "\u2022")
        self.set_x(58)
        self.multi_cell(514, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def skill_row(self, label: str, skills: list):
        """Bold teal label + skill list."""
        self.set_x(40)
        self.set_text_color(ACCENT_R, ACCENT_G, ACCENT_B)
        self.set_font(FONT, "B", 9)
        self.cell(100, 9, label)
        self.set_text_color(DARK_R, DARK_G, DARK_B)
        self.set_font(FONT, "", 9)
        self.multi_cell(432, 9, ", ".join(skills), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def generate_resume_pdf(resume: dict) -> str:
    """Generate a PDF from a resume dict. Returns path to temp PDF file."""
    pdf = ResumePDF()
    pdf.add_page()

    # Header bar
    pdf.header_bar(resume)

    # Summary
    if resume.get("summary"):
        pdf.section_header("Professional Summary")
        pdf.set_text_color(DARK_R, DARK_G, DARK_B)
        pdf.set_font(FONT, "", 9)
        pdf.set_x(40)
        pdf.multi_cell(532, 9, resume["summary"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

    # Experience
    if resume.get("experience"):
        pdf.section_header("Experience")
        for exp in resume["experience"]:
            dates = f"{exp.get('start', '')} – {exp.get('end', '')}"
            pdf.role_header(exp.get("title", ""), exp.get("company", ""), dates)
            for bullet in exp.get("bullets", []):
                pdf.bullet_point(bullet)
            if exp.get("company_description"):
                pdf.set_x(40)
                pdf.set_text_color(MID_R, MID_G, MID_B)
                pdf.set_font(FONT, "I", 8)
                pdf.cell(0, 7, exp["company_description"], new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(4)

    # Education
    if resume.get("education"):
        pdf.section_header("Education")
        for edu in resume["education"]:
            status = f" ({edu.get('status', '')})" if edu.get("status") else ""
            pdf.set_x(40)
            pdf.set_text_color(DARK_R, DARK_G, DARK_B)
            pdf.set_font(FONT, "B", 9)
            pdf.cell(300, 9, f"{edu.get('degree', '')}{status}")
            pdf.set_font(FONT, "", 9)
            pdf.set_text_color(MID_R, MID_G, MID_B)
            pdf.cell(232, 9, edu.get("institution", ""), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

    # Certifications
    if resume.get("certifications"):
        pdf.section_header("Certifications")
        for cert in resume["certifications"]:
            pdf.set_x(40)
            pdf.set_text_color(DARK_R, DARK_G, DARK_B)
            pdf.set_font(FONT, "", 9)
            pdf.cell(440, 9, cert.get("name", ""))
            pdf.set_text_color(MID_R, MID_G, MID_B)
            pdf.set_font(FONT, "I", 9)
            pdf.cell(92, 9, cert.get("year", ""), align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(4)

    # Skills
    if resume.get("skills"):
        pdf.section_header("Skills")
        pdf.ln(2)
        skill_labels = {
            "revops_crm": "CRM & RevOps",
            "analytics_programming": "Analytics & Code",
            "accounting_finance": "Accounting & Finance",
            "soft_skills": "Soft Skills"
        }
        for cat, items in resume["skills"].items():
            if items:
                label = skill_labels.get(cat, cat.replace("_", " ").title())
                pdf.skill_row(f"{label}:", items)

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="princess_resume_")
    pdf.output(tmp.name)
    tmp.close()
    return tmp.name
