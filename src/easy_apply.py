"""
LinkedIn Easy Apply Handler
Handles the multi-step Easy Apply modal with smart form filling
"""

import os
import time
import random
import logging
import tempfile
from pathlib import Path
from playwright.sync_api import Page

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent


class EasyApply:
    def __init__(self, page: Page, config: dict, app_logger, tailor, master_resume: dict):
        self.page = page
        self.config = config
        self.app_logger = app_logger
        self.tailor = tailor
        self.master_resume = master_resume
        self.applicant = config["applicant"]

    def apply(self, job: dict) -> dict:
        """Attempt to apply to a job via Easy Apply. Returns result dict."""
        try:
            # Get full job description for resume tailoring
            self.page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            time.sleep(random.uniform(1.5, 3.0))

            # Expand description
            show_more = self.page.query_selector(".jobs-description__footer-button, button[aria-label*='more']")
            if show_more:
                try:
                    show_more.click()
                    time.sleep(0.5)
                except Exception:
                    pass

            desc_el = self.page.query_selector(".jobs-description-content__text, .jobs-box__html-content")
            job["description"] = (desc_el.inner_text() if desc_el else "").strip()

            # Find Easy Apply button
            easy_apply_btn = self.page.query_selector(
                "button[aria-label*='Easy Apply'], .jobs-apply-button--top-card, "
                ".jobs-unified-top-card__apply-button, button:has-text('Easy Apply')"
            )

            if not easy_apply_btn:
                return {"success": False, "error": "No Easy Apply button found"}

            # Tailor resume to this job description
            tailored_resume_path = None
            if job.get("description") and self.tailor.enabled:
                log.info(f"    Tailoring resume for: {job.get('title')} @ {job.get('company')}")
                tailored_resume_path = self.tailor.tailor_and_generate_pdf(job)

            easy_apply_btn.click()
            time.sleep(random.uniform(1.5, 2.5))

            # Handle the modal
            result = self._handle_modal(job, tailored_resume_path)
            return result

        except Exception as e:
            log.warning(f"Apply error for {job.get('job_id')}: {e}")
            return {"success": False, "error": str(e)}

    def _handle_modal(self, job: dict, resume_path: str | None) -> dict:
        """Step through the Easy Apply modal pages."""
        max_pages = 8
        pages_completed = 0

        for page_num in range(max_pages):
            time.sleep(random.uniform(0.8, 1.5))

            # Check if modal is still open
            modal = self.page.query_selector(".jobs-easy-apply-modal, .artdeco-modal")
            if not modal:
                break

            # Check for success state
            if self._is_success_screen():
                return {"success": True, "pages_completed": pages_completed}

            # Check for complex form requiring manual input
            if self._requires_manual_review():
                self._close_modal()
                return {"success": False, "skip_reason": "manual_review_required"}

            # Handle resume upload on first page if we have a tailored resume
            if page_num == 0 and resume_path:
                self._upload_resume(resume_path)

            # Fill visible form fields
            self._fill_form_fields()

            # Try to advance to next page
            advanced = self._click_next_or_submit()
            if not advanced:
                # Couldn't advance — likely a required field we can't fill
                self._close_modal()
                return {"success": False, "skip_reason": "manual_review_required"}

            pages_completed += 1

        # If we exited the loop without success, close modal
        self._close_modal()
        return {"success": False, "error": "Could not complete modal flow"}

    def _fill_form_fields(self):
        """Fill standard Easy Apply form fields intelligently."""
        try:
            # Phone number
            phone_fields = self.page.query_selector_all("input[id*='phone'], input[name*='phone'], input[aria-label*='Phone']")
            for field in phone_fields:
                if not field.input_value():
                    field.fill(self.applicant.get("phone", ""))

            # City / location fields
            city_fields = self.page.query_selector_all("input[id*='city'], input[name*='city'], input[aria-label*='City']")
            for field in city_fields:
                if not field.input_value():
                    field.fill("San Francisco Bay Area, CA")

            # LinkedIn profile URL fields
            linkedin_fields = self.page.query_selector_all("input[id*='linkedin'], input[name*='linkedin'], input[aria-label*='LinkedIn']")
            for field in linkedin_fields:
                if not field.input_value():
                    field.fill(self.applicant.get("linkedin", ""))

            # Website / portfolio fields (optional — leave blank)
            # Radio buttons — handle common yes/no questions
            self._handle_radio_buttons()

            # Select dropdowns — handle common ones
            self._handle_dropdowns()

        except Exception as e:
            log.debug(f"Form fill partial error: {e}")

    def _handle_radio_buttons(self):
        """Handle common radio button questions in Easy Apply."""
        try:
            # "Are you legally authorized to work in the United States?" → Yes
            auth_labels = self.page.query_selector_all("label:has-text('authorized'), label:has-text('legally authorized')")
            for label in auth_labels:
                yes_radio = self.page.query_selector("input[type='radio'][value='Yes'], input[type='radio'][value='yes']")
                if yes_radio:
                    yes_radio.check()

            # "Will you now or in the future require sponsorship?" → No
            sponsor_labels = self.page.query_selector_all("label:has-text('sponsorship'), label:has-text('visa')")
            for label in sponsor_labels:
                no_radio = self.page.query_selector("input[type='radio'][value='No'], input[type='radio'][value='no']")
                if no_radio:
                    no_radio.check()
        except Exception as e:
            log.debug(f"Radio button error: {e}")

    def _handle_dropdowns(self):
        """Handle common dropdown questions."""
        try:
            selects = self.page.query_selector_all("select")
            for select in selects:
                label_text = ""
                select_id = select.get_attribute("id") or ""

                # Try to find associated label
                if select_id:
                    label_el = self.page.query_selector(f"label[for='{select_id}']")
                    label_text = (label_el.inner_text() if label_el else "").lower()

                options = select.query_selector_all("option")
                if len(options) <= 1:
                    continue

                # Experience years → pick something reasonable
                if "years" in label_text or "experience" in label_text:
                    # Try to select 2-3 years
                    for opt in options:
                        val = opt.get_attribute("value") or opt.inner_text()
                        if val in ["2", "3", "1-3", "2-3", "2-4"]:
                            select.select_option(value=val)
                            break
                    else:
                        # Select first non-empty option
                        for opt in options[1:]:
                            val = opt.get_attribute("value")
                            if val:
                                select.select_option(value=val)
                                break

        except Exception as e:
            log.debug(f"Dropdown error: {e}")

    def _upload_resume(self, resume_path: str):
        """Upload tailored resume if a file input is present."""
        try:
            file_input = self.page.query_selector("input[type='file'][accept*='pdf'], input[type='file'][accept*='doc']")
            if file_input and resume_path and os.path.exists(resume_path):
                file_input.set_input_files(resume_path)
                time.sleep(1.0)
                log.info("    Resume uploaded.")
        except Exception as e:
            log.debug(f"Resume upload error: {e}")

    def _click_next_or_submit(self) -> bool:
        """Click the Next or Submit button. Returns True if clicked."""
        try:
            # Try Submit first (final step)
            submit_btn = self.page.query_selector(
                "button[aria-label='Submit application'], button:has-text('Submit application')"
            )
            if submit_btn and submit_btn.is_enabled():
                submit_btn.click()
                time.sleep(random.uniform(1.5, 2.5))
                return True

            # Try Next / Review / Continue
            next_btn = self.page.query_selector(
                "button[aria-label='Continue to next step'], button[aria-label='Review your application'], "
                "button:has-text('Next'), button:has-text('Review'), button:has-text('Continue')"
            )
            if next_btn and next_btn.is_enabled():
                next_btn.click()
                time.sleep(random.uniform(1.0, 2.0))
                return True

            return False
        except Exception as e:
            log.debug(f"Click next/submit error: {e}")
            return False

    def _is_success_screen(self) -> bool:
        """Check if the application was submitted successfully."""
        try:
            success_el = self.page.query_selector(
                ".artdeco-inline-feedback--success, "
                "[class*='success'], "
                "h3:has-text('application was sent'), "
                "p:has-text('Your application was sent')"
            )
            return success_el is not None
        except Exception:
            return False

    def _requires_manual_review(self) -> bool:
        """Detect if the form has complex fields we can't auto-fill safely."""
        try:
            # Salary expectation fields are tricky — skip if required
            salary_required = self.page.query_selector(
                "input[aria-label*='salary'][required], input[id*='salary'][required]"
            )
            if salary_required and not salary_required.input_value():
                return True

            # Cover letter text areas that are required
            cover_letter = self.page.query_selector("textarea[required][id*='cover'], textarea[required][name*='cover']")
            if cover_letter and not cover_letter.input_value():
                return True

            return False
        except Exception:
            return False

    def _close_modal(self):
        """Close the Easy Apply modal."""
        try:
            close_btn = self.page.query_selector(
                "button[aria-label='Dismiss'], button[data-test-modal-close-btn], "
                ".artdeco-modal__dismiss, button[aria-label='Close']"
            )
            if close_btn:
                close_btn.click()
                time.sleep(0.8)

            # Handle "discard" confirmation if it pops up
            discard_btn = self.page.query_selector("button:has-text('Discard'), button[data-control-name='discard_application_confirm_btn']")
            if discard_btn:
                discard_btn.click()
                time.sleep(0.5)
        except Exception as e:
            log.debug(f"Close modal error: {e}")
