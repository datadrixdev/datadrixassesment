import os
import json
import smtplib
import logging
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from datetime import datetime, timezone
from flask import current_app

from app.extensions import db
from app.models.assessment import AssessmentAttempt, AssessmentEvent
from app.models.discount import CandidateDiscount
from app.services.scoring_service import get_section_scores

logger = logging.getLogger(__name__)

def utc_now():
    return datetime.now(timezone.utc)

def get_proficiency_meta(percentage):
    """Derive proficiency grade, colors, and descriptive text for email report."""
    if percentage >= 85:
        return {
            "grade": "Advanced Mastery",
            "badge_color": "#10b981",
            "badge_bg": "#ecfdf5",
            "border_color": "#a7f3d0",
            "summary": "Exceptional performance across all evaluation pillars. Demonstrates outstanding analytical ability, quantitative aptitude, and grammatical accuracy."
        }
    elif percentage >= 70:
        return {
            "grade": "Proficient",
            "badge_color": "#0284c7",
            "badge_bg": "#f0f9ff",
            "border_color": "#bae6fd",
            "summary": "Strong performance reflecting solid reasoning, well-developed quantitative methods, and dependable language command."
        }
    elif percentage >= 50:
        return {
            "grade": "Average / Foundational",
            "badge_color": "#d97706",
            "badge_bg": "#fffbeb",
            "border_color": "#fde68a",
            "summary": "Satisfactory baseline performance with strong potential for advancement through targeted review in slower sections."
        }
    else:
        return {
            "grade": "Needs Improvement",
            "badge_color": "#dc2626",
            "badge_bg": "#fef2f2",
            "border_color": "#fecaca",
            "summary": "Results indicate significant opportunity for growth. Further study of fundamental aptitude and reasoning concepts is advised."
        }

def get_competency_meta(percentage):
    """Derive competency badge styling for domain breakdown."""
    if percentage >= 80:
        return {"label": "Advanced Mastery", "color": "#10b981", "bg": "#ecfdf5"}
    elif percentage >= 60:
        return {"label": "Proficient", "color": "#0284c7", "bg": "#f0f9ff"}
    elif percentage >= 40:
        return {"label": "Developing", "color": "#d97706", "bg": "#fffbeb"}
    else:
        return {"label": "Needs Focus", "color": "#dc2626", "bg": "#fef2f2"}

def generate_result_email_html(candidate, attempt, section_scores, discount=None, base_url="http://localhost:5000"):
    """
    Generate an attractive, responsive, high-converting, professional HTML email report.
    Compatible with Gmail, Outlook, Apple Mail, and mobile email clients.
    Includes comprehensive Datadrix coding platform showcase at the bottom with official website links.
    """
    prof = get_proficiency_meta(attempt.percentage)
    completed_date = attempt.end_time.strftime("%B %d, %Y at %I:%M %p UTC") if attempt.end_time else "Just now"
    result_url = f"{base_url.rstrip('/')}/result/{attempt.id}"
    datadrix_url = "https://www.datadrix.com"

    # Build Section Rows HTML with mini progress bars
    section_rows_html = ""
    for sec in section_scores:
        pct = sec.get("percentage", 0.0)
        comp = get_competency_meta(pct)
        correct = sec.get("correct", 0)
        total = sec.get("total", 5)
        bar_width = max(5, int(pct))
        section_rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 14px 16px; font-weight: 600; color: #0f172a; font-size: 14px;">
            {sec.get('name', 'Domain')}
            <div style="width: 100%; max-width: 130px; background-color: #e2e8f0; height: 5px; border-radius: 9999px; margin-top: 6px; overflow: hidden;">
              <div style="width: {bar_width}%; height: 100%; background: linear-gradient(90deg, #06b6d4, #0284c7); border-radius: 9999px;"></div>
            </div>
          </td>
          <td style="padding: 14px 16px; text-align: center; color: #334155; font-size: 14px; font-weight: 600;">{correct} / {total}</td>
          <td style="padding: 14px 16px; text-align: center; font-weight: 700; color: #0284c7; font-size: 14px;">{pct:.1f}%</td>
          <td style="padding: 14px 16px; text-align: right;">
            <span style="display: inline-block; padding: 4px 12px; border-radius: 9999px; font-size: 11px; font-weight: 700; letter-spacing: 0.02em; color: {comp['color']}; background-color: {comp['bg']}; border: 1px solid {comp['color']}33;">
              {comp['label']}
            </span>
          </td>
        </tr>
        """

    # Build Discount Voucher HTML (if earned)
    discount_html = ""
    if discount and discount.pin:
        expires_str = discount.expires_at.strftime("%B %d, %Y") if discount.expires_at else "in 3 days"
        discount_html = f"""
        <!-- Scholarship Voucher Certificate Card -->
        <div style="margin: 30px 0; border: 2px dashed #06b6d4; background: linear-gradient(135deg, #f0fdfa 0%, #ecfeff 100%); border-radius: 14px; padding: 24px; text-align: center; position: relative;">
          <div style="display: inline-block; background: linear-gradient(90deg, #0891b2, #0284c7); color: #ffffff; padding: 5px 14px; border-radius: 9999px; font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 12px; box-shadow: 0 2px 6px rgba(8, 145, 178, 0.3);">
            🎓 Official Merit Scholarship Unlocked
          </div>
          <h3 style="margin: 0 0 8px; color: #0f172a; font-size: 20px; font-weight: 800; letter-spacing: -0.01em;">
            Congratulations! You've Earned a {discount.discount_percent}% Tuition Waiver
          </h3>
          <p style="margin: 0 0 16px; color: #475569; font-size: 13px; line-height: 1.6; max-width: 520px; margin-left: auto; margin-right: auto;">
            Based on your verified assessment score, you have qualified for an exclusive merit scholarship across all Datadrix software engineering, full-stack development, and data science master programs.
          </p>
          <div style="display: inline-block; background-color: #ffffff; border: 2px solid #06b6d4; border-radius: 10px; padding: 12px 28px; box-shadow: 0 4px 12px rgba(6, 182, 212, 0.15); margin-bottom: 12px;">
            <div style="font-size: 10px; font-weight: 800; letter-spacing: 0.1em; color: #0891b2; text-transform: uppercase; margin-bottom: 2px;">Your 10-Digit Voucher PIN</div>
            <span style="font-family: 'Courier New', Courier, monospace; font-size: 26px; font-weight: 800; letter-spacing: 5px; color: #0f172a;">
              {discount.pin}
            </span>
          </div>
          <div style="color: #64748b; font-size: 12px; line-height: 1.5;">
            ⏳ Valid until <strong>{expires_str}</strong> (72 Hours) &bull; Redeemable at <a href="{datadrix_url}" target="_blank" style="color: #0284c7; font-weight: 700; text-decoration: none;">www.datadrix.com</a>
          </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Assessment Performance Report - Datadrix</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0f1d; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; -webkit-font-smoothing: antialiased;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background: radial-gradient(circle at top, #131c31 0%, #0a0f1d 100%); padding: 36px 12px;">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 660px; background-color: #ffffff; border-radius: 18px; overflow: hidden; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.35); border: 1px solid #1e293b;">
          
          <!-- Modern Dark Header Banner -->
          <tr>
            <td style="background: linear-gradient(135deg, #090d16 0%, #0f172a 60%, #16243d 100%); padding: 32px 36px 28px; text-align: left; border-bottom: 3px solid #06b6d4;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td>
                    <!-- Datadrix Brand Tagline -->
                    <div style="display: inline-flex; align-items: center; color: #06b6d4; font-size: 11px; font-weight: 800; letter-spacing: 0.16em; text-transform: uppercase; margin-bottom: 8px;">
                      <span style="display: inline-block; width: 8px; height: 8px; background-color: #06b6d4; border-radius: 50%; margin-right: 6px;"></span>
                      DATADRIX AUTOMATED EVALUATION ENGINE
                    </div>
                    <h1 style="margin: 0 0 4px; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2;">
                      Assessment Performance Report
                    </h1>
                    <div style="color: #94a3b8; font-size: 13px;">
                      Comprehensive Competency Analytics &amp; Merit Evaluation
                    </div>
                  </td>
                  <td align="right" style="vertical-align: top;">
                    <div style="display: inline-block; background: rgba(6, 182, 212, 0.12); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.35); padding: 6px 14px; border-radius: 9999px; font-size: 11px; font-family: 'Courier New', Courier, monospace; font-weight: 800; letter-spacing: 0.05em;">
                      ATTEMPT #{attempt.attempt_number}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content Body -->
          <tr>
            <td style="padding: 34px 36px 28px;">
              <!-- Candidate Greeting -->
              <p style="margin: 0 0 14px; font-size: 16px; line-height: 1.5; color: #0f172a;">
                Dear <strong>{candidate.full_name}</strong>,
              </p>
              <p style="margin: 0 0 24px; font-size: 14px; line-height: 1.6; color: #475569;">
                Thank you for completing the Datadrix Technical Evaluation. Your assessment answers have been processed and scored by our automated engine. Below is your official performance scorecard, domain competency matrix, and scholarship status.
              </p>

              <!-- Hero Scorecard Card -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%); border-radius: 14px; border: 1.5px solid #e2e8f0; margin-bottom: 24px; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);">
                <tr>
                  <td style="padding: 26px 24px; text-align: center;">
                    <div style="font-size: 11px; font-weight: 800; color: #64748b; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 8px;">
                      Overall Evaluation Score
                    </div>
                    <div style="font-size: 46px; font-weight: 800; color: #0f172a; line-height: 1; margin-bottom: 12px; letter-spacing: -0.02em;">
                      {attempt.score} <span style="font-size: 22px; font-weight: 600; color: #64748b;">/ {attempt.max_score}</span>
                      <span style="display: inline-block; margin-left: 10px; font-size: 24px; color: #0284c7; font-weight: 800;">({attempt.percentage:.1f}%)</span>
                    </div>
                    <div style="margin-bottom: 14px;">
                      <span style="display: inline-block; padding: 6px 18px; border-radius: 9999px; font-size: 13px; font-weight: 800; color: {prof['badge_color']}; background-color: {prof['badge_bg']}; border: 1.5px solid {prof['border_color']}; box-shadow: 0 2px 6px rgba(0,0,0,0.04);">
                        Proficiency Level: {prof['grade']}
                      </span>
                    </div>
                    <p style="margin: 0 auto; max-width: 520px; font-size: 13px; color: #475569; line-height: 1.6;">
                      {prof['summary']}
                    </p>
                  </td>
                </tr>
              </table>

              <!-- 4-Stat Metric Summary Grid -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom: 28px;">
                <tr>
                  <td width="25%" style="padding: 4px;">
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 8px; text-align: center;">
                      <div style="font-size: 20px; font-weight: 800; color: #10b981;">{attempt.correct_count}</div>
                      <div style="font-size: 11px; color: #64748b; font-weight: 700; margin-top: 2px; text-transform: uppercase;">Correct</div>
                    </div>
                  </td>
                  <td width="25%" style="padding: 4px;">
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 8px; text-align: center;">
                      <div style="font-size: 20px; font-weight: 800; color: #ef4444;">{attempt.incorrect_count}</div>
                      <div style="font-size: 11px; color: #64748b; font-weight: 700; margin-top: 2px; text-transform: uppercase;">Incorrect</div>
                    </div>
                  </td>
                  <td width="25%" style="padding: 4px;">
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 8px; text-align: center;">
                      <div style="font-size: 20px; font-weight: 800; color: #64748b;">{attempt.unanswered_count}</div>
                      <div style="font-size: 11px; color: #64748b; font-weight: 700; margin-top: 2px; text-transform: uppercase;">Unanswered</div>
                    </div>
                  </td>
                  <td width="25%" style="padding: 4px;">
                    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 8px; text-align: center;">
                      <div style="font-size: 20px; font-weight: 800; color: #0284c7;">15m</div>
                      <div style="font-size: 11px; color: #64748b; font-weight: 700; margin-top: 2px; text-transform: uppercase;">Duration</div>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Domain-wise Breakdown Section -->
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <h3 style="margin: 0; color: #0f172a; font-size: 16px; font-weight: 800;">
                  Domain-Wise Performance Analysis
                </h3>
              </div>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse: collapse; border: 1.5px solid #e2e8f0; border-radius: 10px; overflow: hidden; margin-bottom: 24px;">
                <thead>
                  <tr style="background-color: #f8fafc; border-bottom: 2px solid #cbd5e1;">
                    <th align="left" style="padding: 12px 16px; font-size: 11px; font-weight: 800; color: #475569; text-transform: uppercase; letter-spacing: 0.05em;">Domain</th>
                    <th align="center" style="padding: 12px 16px; font-size: 11px; font-weight: 800; color: #475569; text-transform: uppercase; letter-spacing: 0.05em;">Score</th>
                    <th align="center" style="padding: 12px 16px; font-size: 11px; font-weight: 800; color: #475569; text-transform: uppercase; letter-spacing: 0.05em;">Accuracy</th>
                    <th align="right" style="padding: 12px 16px; font-size: 11px; font-weight: 800; color: #475569; text-transform: uppercase; letter-spacing: 0.05em;">Competency</th>
                  </tr>
                </thead>
                <tbody>
                  {section_rows_html}
                </tbody>
              </table>

              <!-- Scholarship Voucher Block (Rendered if earned) -->
              {discount_html}

              <!-- Retake Cooldown Policy Card -->
              <div style="background-color: #f0f9ff; border-left: 4px solid #0284c7; padding: 14px 18px; border-radius: 8px; margin-bottom: 26px;">
                <div style="font-size: 13px; font-weight: 700; color: #0369a1; margin-bottom: 3px;">
                  ⏱ Retake Cooldown Policy
                </div>
                <div style="font-size: 12px; color: #334155; line-height: 1.6;">
                  To maintain rigorous academic integrity, retakes unlock <strong>24 hours</strong> after assessment completion. Each attempt features a completely fresh, randomized 20-question set and server-authoritative timer.
                </div>
              </div>

              <!-- Primary CTA Button (Interactive Report) -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom: 30px;">
                <tr>
                  <td align="center">
                    <a href="{result_url}" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%); color: #ffffff; text-decoration: none; padding: 14px 34px; border-radius: 10px; font-size: 14px; font-weight: 700; letter-spacing: 0.02em; box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);">
                      View Interactive Report Online &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Candidate Record Verification Strip -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 18px; margin-bottom: 32px;">
                <tr>
                  <td style="font-size: 12px; color: #64748b; line-height: 1.6;">
                    <strong style="color: #334155;">Candidate:</strong> {candidate.full_name} &bull;
                    <strong style="color: #334155;">Email:</strong> {candidate.email} &bull;
                    <strong style="color: #334155;">Phone:</strong> {candidate.mobile_number}<br>
                    <strong style="color: #334155;">Completed:</strong> {completed_date}
                  </td>
                </tr>
              </table>

              <!-- ============================================================= -->
              <!-- ATTRACTIVE DATADRIX #1 PLATFORM SHOWCASE SECTION (BOTTOM)    -->
              <!-- ============================================================= -->
              <div style="margin-top: 10px; border-radius: 16px; background: linear-gradient(135deg, #090d16 0%, #0f172a 50%, #172554 100%); padding: 32px 28px; text-align: center; border: 1px solid #1e3a8a; box-shadow: 0 10px 25px rgba(15, 23, 42, 0.25);">
                
                <!-- Badge -->
                <div style="display: inline-block; background: linear-gradient(90deg, #06b6d4, #3b82f6); color: #ffffff; padding: 4px 16px; border-radius: 9999px; font-size: 11px; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 14px; box-shadow: 0 2px 8px rgba(6, 182, 212, 0.4);">
                  ⭐ #1 PREMIER CODING &amp; TECH CAREER PLATFORM
                </div>

                <!-- Main Pitch -->
                <h2 style="margin: 0 0 10px; color: #ffffff; font-size: 22px; font-weight: 800; letter-spacing: -0.01em; line-height: 1.3;">
                  Accelerate Your Tech Career with Datadrix
                </h2>
                <p style="margin: 0 auto 24px; max-width: 520px; color: #cbd5e1; font-size: 13px; line-height: 1.6;">
                  Datadrix is India's leading platform for mastering modern software engineering, full-stack architecture, and real-world system design. Learn from FAANG &amp; top product company tech leads with guaranteed placement pathways.
                </p>

                <!-- 3 Pillars Grid -->
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom: 24px;">
                  <tr>
                    <td width="33%" style="padding: 6px; vertical-align: top;">
                      <div style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 16px 12px; text-align: center; height: 100%;">
                        <div style="font-size: 24px; margin-bottom: 8px;">💻</div>
                        <div style="font-size: 13px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">Industry Coding</div>
                        <div style="font-size: 11px; color: #94a3b8; line-height: 1.4;">Production-grade Python, React, Next.js, and Cloud backends.</div>
                      </div>
                    </td>
                    <td width="33%" style="padding: 6px; vertical-align: top;">
                      <div style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 16px 12px; text-align: center; height: 100%;">
                        <div style="font-size: 24px; margin-bottom: 8px;">🧠</div>
                        <div style="font-size: 13px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">DSA &amp; System Design</div>
                        <div style="font-size: 11px; color: #94a3b8; line-height: 1.4;">Master algorithms, high-scale architectures, and live mock drills.</div>
                      </div>
                    </td>
                    <td width="33%" style="padding: 6px; vertical-align: top;">
                      <div style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 16px 12px; text-align: center; height: 100%;">
                        <div style="font-size: 24px; margin-bottom: 8px;">🎯</div>
                        <div style="font-size: 13px; font-weight: 700; color: #ffffff; margin-bottom: 4px;">1:1 Mentorship</div>
                        <div style="font-size: 11px; color: #94a3b8; line-height: 1.4;">Direct access to 250+ top tech hiring partners and career coaching.</div>
                      </div>
                    </td>
                  </tr>
                </table>

                <!-- Website Link Action Button -->
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom: 16px;">
                  <tr>
                    <td align="center">
                      <a href="{datadrix_url}" target="_blank" style="display: inline-block; background: linear-gradient(90deg, #06b6d4 0%, #3b82f6 100%); color: #ffffff; text-decoration: none; padding: 14px 32px; border-radius: 9999px; font-size: 14px; font-weight: 800; letter-spacing: 0.03em; box-shadow: 0 4px 16px rgba(6, 182, 212, 0.4);">
                        Explore Datadrix Coding Programs &rarr;
                      </a>
                    </td>
                  </tr>
                </table>

                <!-- Trust Stats & Official URL -->
                <div style="color: #94a3b8; font-size: 12px; line-height: 1.6;">
                  Visit the Official Website: <a href="{datadrix_url}" target="_blank" style="color: #22d3ee; font-weight: 700; text-decoration: underline;">www.datadrix.com</a><br>
                  <span style="color: #64748b; font-size: 11px;">⭐⭐⭐⭐⭐ Rated 4.9/5 by 50,000+ Aspiring Software Engineers</span>
                </div>

              </div>
              <!-- ============================================================= -->

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 24px 36px; text-align: center; color: #94a3b8; font-size: 11px; line-height: 1.6;">
              <p style="margin: 0 0 6px;">
                This performance report was generated automatically by the <strong>Datadrix Automated Evaluation Engine</strong>.
              </p>
              <p style="margin: 0;">
                Have questions or need assistance? Contact Admissions &amp; Support: 
                <a href="mailto:support@datadrix.com" style="color: #0284c7; text-decoration: none; font-weight: 600;">support@datadrix.com</a> | 
                <a href="{datadrix_url}" target="_blank" style="color: #0284c7; text-decoration: none; font-weight: 600;">www.datadrix.com</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return html

def generate_result_email_text(candidate, attempt, section_scores, discount=None, base_url="http://localhost:5000"):
    """Generate high-contrast, clean Plain Text fallback for the email report."""
    prof = get_proficiency_meta(attempt.percentage)
    completed_date = attempt.end_time.strftime("%B %d, %Y at %I:%M %p UTC") if attempt.end_time else "Just now"
    result_url = f"{base_url.rstrip('/')}/result/{attempt.id}"
    datadrix_url = "https://www.datadrix.com"

    lines = [
        "=" * 74,
        "          DATADRIX TECHNICAL ASSESSMENT - OFFICIAL PERFORMANCE REPORT",
        "=" * 74,
        f"Candidate:   {candidate.full_name}",
        f"Email:       {candidate.email}",
        f"Phone:       {candidate.mobile_number}",
        f"Attempt:     #{attempt.attempt_number}",
        f"Date:        {completed_date}",
        "-" * 74,
        "OVERALL EVALUATION SCORECARD",
        "-" * 74,
        f"Score:             {attempt.score} / {attempt.max_score} ({attempt.percentage:.1f}%)",
        f"Proficiency Level: {prof['grade']}",
        f"Correct Answers:   {attempt.correct_count} / {attempt.max_score}",
        f"Incorrect Answers: {attempt.incorrect_count}",
        f"Unanswered:        {attempt.unanswered_count}",
        "",
        f"Evaluation Summary: {prof['summary']}",
        "",
        "-" * 74,
        "DOMAIN-WISE PERFORMANCE ANALYSIS",
        "-" * 74,
    ]

    for sec in section_scores:
        pct = sec.get("percentage", 0.0)
        comp = get_competency_meta(pct)
        lines.append(f"- {sec.get('name', 'Domain'):<22}: {sec.get('correct', 0)}/{sec.get('total', 5)} ({pct:5.1f}%) | {comp['label']}")

    if discount and discount.pin:
        expires_str = discount.expires_at.strftime("%B %d, %Y") if discount.expires_at else "in 3 days"
        lines.extend([
            "",
            "-" * 74,
            "CAREER SCHOLARSHIP VOUCHER AWARD",
            "-" * 74,
            f"Tuition Discount: {discount.discount_percent}% Tuition Waiver",
            f"Voucher Key:      {discount.pin}",
            f"Validity:         Valid until {expires_str} (72 Hours)",
            f"Instructions:     Quote this 10-digit voucher key during enrollment at {datadrix_url}.",
        ])

    lines.extend([
        "",
        "-" * 74,
        "RETAKE POLICY & INTERACTIVE REPORT",
        "-" * 74,
        "Retake Cooldown: Available 24 hours after this assessment completion.",
        f"Interactive Online Report: {result_url}",
        "",
        "=" * 74,
        "           ⭐ ABOUT DATADRIX — #1 PREMIER CODING & TECH PLATFORM ⭐",
        "=" * 74,
        "Datadrix is India's leading platform for mastering modern software engineering,",
        "full-stack architecture, and real-world system design.",
        "",
        "WHY CHOOSE DATADRIX:",
        "1. Industry-Grade Coding Tracks: Master production-level Python, React, Next.js, and Cloud backends.",
        "2. DSA & System Design: Crack FAANG coding rounds with live mock interviews and algorithmic drills.",
        "3. 1:1 Mentorship & Placement: Direct hiring pipelines with 250+ top tech partners and 100% career guidance.",
        "",
        f"Explore Programs & Enroll: {datadrix_url}",
        "⭐⭐⭐⭐⭐ Rated 4.9/5 by 50,000+ Aspiring Software Engineers",
        "",
        "Admissions & Support: support@datadrix.com • Official Website: www.datadrix.com",
        "=" * 74
    ])

    return "\n".join(lines)

def save_sent_email_copy(attempt_id, recipient, subject, html_content, text_content):
    """
    Saves an offline copy of the dispatched email report into instance/sent_emails/
    so developers and candidates can immediately inspect the exact email delivered.
    """
    try:
        base_dir = current_app.config.get("BASE_DIR", os.getcwd())
        output_dir = os.path.join(base_dir, "instance", "sent_emails")
        os.makedirs(output_dir, exist_ok=True)

        meta = {
            "attempt_id": attempt_id,
            "recipient": recipient,
            "subject": subject,
            "sent_at": utc_now().isoformat()
        }

        # Save HTML version
        html_path = os.path.join(output_dir, f"{attempt_id}_report.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Save Text version
        txt_path = os.path.join(output_dir, f"{attempt_id}_report.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text_content)

        # Save Metadata
        json_path = os.path.join(output_dir, f"{attempt_id}_meta.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        logger.info("Saved local copy of sent email to %s", html_path)
        return html_path
    except Exception as e:
        logger.warning("Could not save local email copy: %s", e)
        return None

def send_email_message(to_email, subject, html_content, text_content=None, attempt_id=None):
    """
    Delivers a multipart email via configured SMTP server, or archives locally if SMTP is unconfigured.
    Returns delivery status dictionary.
    """
    import ssl
    from dotenv import load_dotenv
    load_dotenv(override=True)

    smtp_server = (os.environ.get("SMTP_SERVER") or current_app.config.get("SMTP_SERVER", "")).strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or current_app.config.get("SMTP_PORT", 587))
    smtp_user = (os.environ.get("SMTP_USERNAME") or current_app.config.get("SMTP_USERNAME", "")).strip().strip('"').strip("'")
    smtp_pass = (os.environ.get("SMTP_PASSWORD") or current_app.config.get("SMTP_PASSWORD", "")).strip().strip('"').strip("'").replace(" ", "")
    smtp_tls = os.environ.get("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")
    smtp_ssl = os.environ.get("SMTP_USE_SSL", "False").lower() in ("true", "1", "yes")
    sender = (os.environ.get("MAIL_DEFAULT_SENDER") or current_app.config.get("MAIL_DEFAULT_SENDER") or "Datadrix Assessments <datadrix@gmail.com>").strip().strip('"')
    save_local = current_app.config.get("MAIL_SAVE_LOCAL_COPY", True)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="datadrix.com")

    if text_content:
        msg.attach(MIMEText(text_content, "plain", "utf-8"))
    if html_content:
        msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Always preserve local archive if requested
    if save_local and attempt_id:
        save_sent_email_copy(attempt_id, to_email, subject, html_content, text_content or "")

    if smtp_server:
        try:
            if smtp_ssl:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=15)
                server.ehlo()
            else:
                server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
                server.ehlo()
                if smtp_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                    server.ehlo()

            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)

            server.send_message(msg)
            server.quit()
            logger.info("Delivered assessment report email to %s via SMTP %s", to_email, smtp_server)
            return {"status": "sent", "channel": "smtp", "recipient": to_email}
        except Exception as e:
            logger.error("SMTP delivery to %s failed: %s", to_email, e)
            return {"status": "smtp_failed", "error": str(e), "recipient": to_email}
    else:
        logger.info("SMTP_SERVER not configured. Email report generated and recorded locally for %s", to_email)
        return {"status": "archived_locally", "channel": "local", "recipient": to_email}

def send_assessment_result_email(attempt, async_send=False):
    """
    Main entry point: Automatically formats and dispatches the comprehensive result report
    to the candidate's registered email address upon test completion.
    """
    if isinstance(attempt, str):
        attempt = db.session.get(AssessmentAttempt, attempt)
    if not attempt or not attempt.candidate:
        logger.warning("Cannot send assessment email: attempt or candidate not found.")
        return None

    candidate = attempt.candidate
    if not candidate.email:
        logger.warning("Cannot send assessment email: candidate %s has no email.", candidate.id)
        return None

    # Get section breakdown
    section_scores = get_section_scores(attempt)

    # Get discount voucher if qualified
    discount = CandidateDiscount.query.filter_by(attempt_id=attempt.id).first()
    if not discount and (attempt.score or 0) >= 4:
        from app.services.discount_service import create_or_get_discount
        try:
            discount = create_or_get_discount(attempt)
        except Exception:
            discount = None

    base_url = current_app.config.get("APP_BASE_URL", "http://localhost:5000")
    subject = f"Your Assessment Performance Report - Datadrix Evaluation (Attempt #{attempt.attempt_number})"
    html_content = generate_result_email_html(candidate, attempt, section_scores, discount, base_url)
    text_content = generate_result_email_text(candidate, attempt, section_scores, discount, base_url)

    def _deliver():
        result = send_email_message(candidate.email, subject, html_content, text_content, attempt.id)
        # Log AssessmentEvent for audit tracking
        try:
            event = AssessmentEvent(
                attempt_id=attempt.id,
                event_type="ASSESSMENT_REPORT_EMAILED",
                timestamp=utc_now(),
                metadata_json=json.dumps({
                    "recipient_email": candidate.email,
                    "recipient_name": candidate.full_name,
                    "score": attempt.score,
                    "percentage": attempt.percentage,
                    "pin": discount.pin if discount else None,
                    "delivery_status": result.get("status") if result else "unknown"
                })
            )
            db.session.add(event)
            db.session.commit()
        except Exception as log_err:
            logger.warning("Could not log email event: %s", log_err)
        return result

    if async_send:
        t = threading.Thread(target=_deliver, daemon=True)
        t.start()
        return {"status": "dispatched_async", "recipient": candidate.email}
    else:
        return _deliver()
