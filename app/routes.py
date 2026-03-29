import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import calendar
import requests
import hashlib
import uuid
from datetime import datetime, date, timedelta, time
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, current_app, abort, request, session
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message as MailMessage
from smtplib import SMTPException
from werkzeug.utils import secure_filename

from app import db, mail, oauth
from app.forms import (
    RegistrationForm,
    LoginForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    UpdateProfileForm,
    SkillForm,
    TeachApplicationForm,
    CourseForm,
    HelpRequestForm,
    ApplicationForm,
    ApplicationResponseForm,
    RejectVerificationForm,
    AdminSetupForm,
)
from app.models import User, SocialAccount, Skill, Notification, HelpRequest, Application, Collaboration, CollaborationRating, Message, RescheduleProposal, MessageFlag, ModerationReview, UserRestriction, Course, CourseChapter, CourseContentBlock, ChapterQuizQuestion, ChapterQuizAttempt, FinalExamQuestion, FinalExamAttempt, CourseEnrollment, ChapterProgress, TeachApplication, TeachingPermission, CourseAssignment, AssignmentSubmission

main = Blueprint("main", __name__)



def get_post_login_redirect(user):
    if user.role == "admin" and user.must_change_credentials:
        flash("Please update your admin email and password before continuing.", "warning")
        return url_for("main.admin_setup")

    if not user.phone:
        flash("Please complete your profile details.", "info")
        return url_for("main.update_profile")

    return url_for("main.dashboard")


def resolve_or_create_social_user(provider, provider_user_id, email=None, name=None, picture=None):
    social_account = SocialAccount.query.filter_by(
        provider=provider,
        provider_user_id=str(provider_user_id),
    ).first()

    if social_account:
        user = social_account.user
        if email and not social_account.provider_email:
            social_account.provider_email = email
        if name and not social_account.provider_name:
            social_account.provider_name = name
        if picture and not social_account.provider_picture:
            social_account.provider_picture = picture
        db.session.commit()
        return user

    if not email:
        return None

    normalized_email = email.lower().strip()
    user = User.query.filter_by(email=normalized_email).first()

    if not user:
        user = User(
            full_name=(name or normalized_email.split("@")[0]).strip(),
            email=normalized_email,
            phone=None,
            role="user",
            is_email_verified=True,
            email_verified_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.flush()
    elif not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = user.email_verified_at or datetime.utcnow()

    social_account = SocialAccount(
        user_id=user.id,
        provider=provider,
        provider_user_id=str(provider_user_id),
        provider_email=normalized_email,
        provider_name=name.strip() if name else None,
        provider_picture=picture,
    )
    db.session.add(social_account)
    db.session.commit()
    return user


def admin_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("main.login"))

        if current_user.role != "admin":
            abort(403)

        if current_user.must_change_credentials and request.endpoint != "main.admin_setup":
            flash("Please complete admin setup first.", "warning")
            return redirect(url_for("main.admin_setup"))

        return func(*args, **kwargs)
    return decorated_function


def user_only_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("main.login"))

        if current_user.role == "admin":
            flash("This section is for normal users only.", "warning")
            return redirect(url_for("main.admin_dashboard"))

        return func(*args, **kwargs)
    return decorated_function


def save_file(file, subfolder=""):
    if not file or not file.filename:
        return None

    upload_root = current_app.config["UPLOAD_FOLDER"]
    upload_path = os.path.join(upload_root, subfolder) if subfolder else upload_root
    os.makedirs(upload_path, exist_ok=True)

    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(upload_path, unique_filename)

    file.save(filepath)

    if subfolder:
        return f"uploads/{subfolder}/{unique_filename}"
    return f"uploads/{unique_filename}"


def get_user_active_skill_categories(user):
    skills = Skill.query.filter_by(user_id=user.id, status="Active").all()
    categories = {}
    for skill in skills:
        category_name = skill.display_category()
        if category_name:
            categories[category_name.strip().lower()] = category_name.strip()
    return categories


def get_request_skill_match(user, help_request):
    request_category = (help_request.display_category() or "").strip()
    if not request_category:
        return {
            "skills_match": False,
            "matched_category_name": None,
            "request_category_name": None,
            "user_has_skills": False,
        }
    user_categories = get_user_active_skill_categories(user)
    normalized_request_category = request_category.lower()
    return {
        "skills_match": normalized_request_category in user_categories,
        "matched_category_name": user_categories.get(normalized_request_category),
        "request_category_name": request_category,
        "user_has_skills": len(user_categories) > 0,
    }


def _weekday_name_to_index(day_name):
    mapping = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    return mapping.get(day_name)


def _time_ranges_overlap(start_a, end_a, start_b, end_b):
    if not start_a or not end_a or not start_b or not end_b:
        return False
    return start_a < end_b and end_a > start_b


def get_request_occurrences(help_request, max_occurrences=400):
    occurrences = []
    if not help_request.start_time or not help_request.end_time:
        return occurrences
    if help_request.schedule_type == "one_time":
        if help_request.date_needed:
            occurrences.append({"date": help_request.date_needed, "start_time": help_request.start_time, "end_time": help_request.end_time})
        return occurrences
    if help_request.schedule_type == "date_range":
        if help_request.start_date and help_request.end_date:
            current_day = help_request.start_date
            while current_day <= help_request.end_date and len(occurrences) < max_occurrences:
                occurrences.append({"date": current_day, "start_time": help_request.start_time, "end_time": help_request.end_time})
                current_day += timedelta(days=1)
        return occurrences
    if help_request.schedule_type == "recurring_weekly":
        if help_request.start_date and help_request.end_date:
            selected_indexes = {_weekday_name_to_index(day) for day in help_request.recurrence_days_list() if _weekday_name_to_index(day) is not None}
            current_day = help_request.start_date
            while current_day <= help_request.end_date and len(occurrences) < max_occurrences:
                if current_day.weekday() in selected_indexes:
                    occurrences.append({"date": current_day, "start_time": help_request.start_time, "end_time": help_request.end_time})
                current_day += timedelta(days=1)
        return occurrences
    if help_request.schedule_type == "recurring_monthly":
        if help_request.start_date and help_request.end_date:
            selected_days = set()
            for value in help_request.monthly_dates_list():
                try:
                    day_num = int(value)
                    if 1 <= day_num <= 31:
                        selected_days.add(day_num)
                except ValueError:
                    continue
            current_day = help_request.start_date
            while current_day <= help_request.end_date and len(occurrences) < max_occurrences:
                if current_day.day in selected_days:
                    occurrences.append({"date": current_day, "start_time": help_request.start_time, "end_time": help_request.end_time})
                current_day += timedelta(days=1)
        return occurrences
    return occurrences


def find_conflicting_accepted_request(user, target_help_request, exclude_help_request_id=None):
    target_occurrences = get_request_occurrences(target_help_request)
    if not target_occurrences:
        return None
    accepted_applications = (
        Application.query.filter_by(applicant_id=user.id, status="Accepted").order_by(Application.responded_at.desc()).all()
    )
    for application in accepted_applications:
        existing_help_request = application.help_request
        if not existing_help_request:
            continue
        if exclude_help_request_id and existing_help_request.id == exclude_help_request_id:
            continue
        existing_occurrences = get_request_occurrences(existing_help_request)
        for target in target_occurrences:
            for existing in existing_occurrences:
                if target["date"] == existing["date"] and _time_ranges_overlap(target["start_time"], target["end_time"], existing["start_time"], existing["end_time"]):
                    return {"application": application, "help_request": existing_help_request, "target_occurrence": target, "existing_occurrence": existing}
    return None


def build_conflict_info(user, target_help_request, exclude_help_request_id=None):
    conflict = find_conflicting_accepted_request(user, target_help_request, exclude_help_request_id=exclude_help_request_id)
    if not conflict:
        return {"has_conflict": False, "conflict_message": None, "conflicting_help_request": None}
    existing_help_request = conflict["help_request"]
    existing_occurrence = conflict["existing_occurrence"]
    conflict_message = (
        f'Conflict with "{existing_help_request.title}" on '
        f'{existing_occurrence["date"].strftime("%Y-%m-%d")} from '
        f'{existing_occurrence["start_time"].strftime("%H:%M")} to '
        f'{existing_occurrence["end_time"].strftime("%H:%M")}.')
    return {"has_conflict": True, "conflict_message": conflict_message, "conflicting_help_request": existing_help_request}


def create_notification(user_id, message, notification_type="info", notification_link=None):
    notification = Notification(
        user_id=user_id,
        message=message,
        notification_type=notification_type,
        notification_link=notification_link,
        is_read=False
    )
    db.session.add(notification)
    db.session.commit()



def get_or_create_collaboration(help_request, application):
    collaboration = Collaboration.query.filter_by(help_request_id=help_request.id).first()
    if collaboration:
        return collaboration, False

    collaboration = Collaboration(
        help_request_id=help_request.id,
        application_id=application.id,
        requester_id=help_request.requester_id,
        provider_id=application.applicant_id,
        status="Active"
    )
    db.session.add(collaboration)
    return collaboration, True


def create_system_message(collaboration, body):
    message = Message(
        collaboration_id=collaboration.id,
        sender_id=None,
        body=body,
        is_system_message=True
    )
    db.session.add(message)
    collaboration.updated_at = datetime.utcnow()
    return message




def _parse_date_input(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_time_input(value):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def _normalize_csv(values):
    return ",".join([value.strip() for value in values if value and value.strip()]) or None


def extract_reschedule_payload_from_request(form_data):
    payload = {
        "schedule_type": (form_data.get("schedule_type") or "").strip(),
        "date_needed": _parse_date_input(form_data.get("date_needed")),
        "start_date": _parse_date_input(form_data.get("start_date")),
        "end_date": _parse_date_input(form_data.get("end_date")),
        "start_time": _parse_time_input(form_data.get("start_time") or form_data.get("time_start")),
        "end_time": _parse_time_input(form_data.get("end_time") or form_data.get("time_end")),
        "time_flexible": form_data.get("time_flexible") in ["on", "true", "1", "yes"],
        "recurrence_days": _normalize_csv(form_data.getlist("recurrence_days")) if hasattr(form_data, "getlist") else None,
        "monthly_dates": _normalize_csv(form_data.getlist("monthly_dates")) if hasattr(form_data, "getlist") else None,
        "note": (form_data.get("note") or "").strip() or None,
    }
    return payload


def validate_reschedule_payload(payload):
    valid_schedule_types = {"one_time", "date_range", "recurring_weekly", "recurring_monthly"}
    if payload["schedule_type"] not in valid_schedule_types:
        return "Please choose a valid schedule type."

    if payload["time_flexible"]:
        if payload["start_time"] and payload["end_time"] and payload["start_time"] >= payload["end_time"]:
            return "End time must be later than start time."
    else:
        if payload["start_time"] or payload["end_time"]:
            if not payload["start_time"] or not payload["end_time"]:
                return "Please provide both start time and end time."
            if payload["start_time"] >= payload["end_time"]:
                return "End time must be later than start time."
        else:
            return "Please provide both start time and end time."

    if payload["schedule_type"] == "one_time":
        if not payload["date_needed"]:
            return "Please choose the date needed."
        return None

    if payload["schedule_type"] in ["date_range", "recurring_weekly", "recurring_monthly"]:
        if not payload["start_date"] or not payload["end_date"]:
            return "Please provide both a start date and an end date."
        if payload["start_date"] > payload["end_date"]:
            return "End date cannot be earlier than start date."

    if payload["schedule_type"] == "recurring_weekly" and not payload["recurrence_days"]:
        return "Please select at least one weekly recurrence day."

    if payload["schedule_type"] == "recurring_monthly" and not payload["monthly_dates"]:
        return "Please select at least one day of the month."

    return None


def help_request_schedule_snapshot(help_request):
    return {
        "schedule_type": help_request.schedule_type,
        "date_needed": help_request.date_needed,
        "start_date": help_request.start_date,
        "end_date": help_request.end_date,
        "start_time": help_request.start_time,
        "end_time": help_request.end_time,
        "time_flexible": help_request.time_flexible,
        "recurrence_days": help_request.recurrence_days,
        "monthly_dates": help_request.monthly_dates,
    }


def apply_schedule_payload_to_help_request(help_request, payload):
    help_request.schedule_type = payload["schedule_type"]
    help_request.date_needed = payload["date_needed"] if payload["schedule_type"] == "one_time" else None

    if payload["schedule_type"] == "one_time":
        help_request.start_date = None
        help_request.end_date = None
        help_request.recurrence_days = None
        help_request.monthly_dates = None
    else:
        help_request.start_date = payload["start_date"]
        help_request.end_date = payload["end_date"]
        help_request.recurrence_days = payload["recurrence_days"] if payload["schedule_type"] == "recurring_weekly" else None
        help_request.monthly_dates = payload["monthly_dates"] if payload["schedule_type"] == "recurring_monthly" else None

    help_request.start_time = payload["start_time"]
    help_request.end_time = payload["end_time"]
    help_request.time_flexible = payload["time_flexible"]


class TemporaryScheduleRequest:
    def __init__(self, source_help_request, payload):
        self.id = source_help_request.id
        self.schedule_type = payload["schedule_type"]
        self.date_needed = payload["date_needed"]
        self.start_date = payload["start_date"]
        self.end_date = payload["end_date"]
        self.start_time = payload["start_time"]
        self.end_time = payload["end_time"]
        self.time_flexible = payload["time_flexible"]
        self.recurrence_days = payload["recurrence_days"]
        self.monthly_dates = payload["monthly_dates"]

    def recurrence_days_list(self):
        if not self.recurrence_days:
            return []
        return [day.strip() for day in self.recurrence_days.split(",") if day.strip()]

    def monthly_dates_list(self):
        if not self.monthly_dates:
            return []
        return [day.strip() for day in self.monthly_dates.split(",") if day.strip()]


def get_pending_reschedule_proposal(collaboration):
    return (
        RescheduleProposal.query
        .filter_by(collaboration_id=collaboration.id, status="Pending")
        .order_by(RescheduleProposal.created_at.desc())
        .first()
    )


def _format_from_header(provider="resend"):
    if provider == "gmail_api":
        from_name = (current_app.config.get("GMAIL_API_FROM_NAME") or "SkillsInn").strip()
        from_email = (current_app.config.get("GMAIL_API_SENDER_EMAIL") or "").strip()
    else:
        from_name = (current_app.config.get("RESEND_FROM_NAME") or "SkillsInn").strip()
        from_email = (current_app.config.get("RESEND_FROM_EMAIL") or "onboarding@resend.dev").strip()
    return f"{from_name} <{from_email}>" if from_name else from_email


def _is_local_debug_mode():
    env = (current_app.config.get("ENV") or "").lower()
    return bool(current_app.debug or current_app.testing or env == "development")


def _gmail_api_is_configured():
    return all([
        (current_app.config.get("GMAIL_API_CLIENT_ID") or "").strip(),
        (current_app.config.get("GMAIL_API_CLIENT_SECRET") or "").strip(),
        (current_app.config.get("GMAIL_API_REFRESH_TOKEN") or "").strip(),
        (current_app.config.get("GMAIL_API_SENDER_EMAIL") or "").strip(),
    ])


def _get_gmail_access_token():
    token_uri = (current_app.config.get("GMAIL_API_TOKEN_URI") or "https://oauth2.googleapis.com/token").strip()
    client_id = (current_app.config.get("GMAIL_API_CLIENT_ID") or "").strip()
    client_secret = (current_app.config.get("GMAIL_API_CLIENT_SECRET") or "").strip()
    refresh_token = (current_app.config.get("GMAIL_API_REFRESH_TOKEN") or "").strip()
    sender_email = (current_app.config.get("GMAIL_API_SENDER_EMAIL") or "").strip()

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        print("GMAIL DEBUG: token request starting")
        print("GMAIL DEBUG: token_uri =", token_uri)
        print("GMAIL DEBUG: EMAIL_PROVIDER =", current_app.config.get("EMAIL_PROVIDER"))
        print("GMAIL DEBUG: sender_email =", sender_email)
        print("GMAIL DEBUG: client_id_present =", bool(client_id))
        print("GMAIL DEBUG: client_secret_present =", bool(client_secret))
        print("GMAIL DEBUG: refresh_token_present =", bool(refresh_token))
        if client_id:
            print("GMAIL DEBUG: client_id_suffix =", client_id[-20:])
        if refresh_token:
            print("GMAIL DEBUG: refresh_token_prefix =", refresh_token[:12])
            print("GMAIL DEBUG: refresh_token_suffix =", refresh_token[-12:])

        response = requests.post(token_uri, data=payload, timeout=20)
        print("GMAIL DEBUG: token status =", response.status_code)
        print("GMAIL DEBUG: token body =", response.text)

        if not response.ok:
            print("Gmail token refresh error:", response.status_code, response.text)
            return None

        token_data = response.json()
        access_token = token_data.get("access_token")
        print("GMAIL DEBUG: access_token_present =", bool(access_token))
        if access_token:
            print("GMAIL DEBUG: access_token_prefix =", access_token[:12])
        return access_token
    except Exception as e:
        print(f"Gmail token request error: {e}")
        return None


def send_email_via_gmail_api(to_email, subject, body, html=None):
    if not _gmail_api_is_configured():
        print("GMAIL DEBUG: Gmail API config is incomplete")
        print("GMAIL DEBUG: GMAIL_API_CLIENT_ID present =", bool((current_app.config.get("GMAIL_API_CLIENT_ID") or "").strip()))
        print("GMAIL DEBUG: GMAIL_API_CLIENT_SECRET present =", bool((current_app.config.get("GMAIL_API_CLIENT_SECRET") or "").strip()))
        print("GMAIL DEBUG: GMAIL_API_REFRESH_TOKEN present =", bool((current_app.config.get("GMAIL_API_REFRESH_TOKEN") or "").strip()))
        print("GMAIL DEBUG: GMAIL_API_SENDER_EMAIL present =", bool((current_app.config.get("GMAIL_API_SENDER_EMAIL") or "").strip()))
        return False

    access_token = _get_gmail_access_token()
    if not access_token:
        print("GMAIL DEBUG: No access token received")
        return False

    sender = _format_from_header(provider="gmail_api")

    try:
        print("GMAIL DEBUG: send starting")
        print("GMAIL DEBUG: to_email =", to_email)
        print("GMAIL DEBUG: subject =", subject)
        print("GMAIL DEBUG: sender header =", sender)

        message = MIMEMultipart("alternative")
        message["To"] = to_email
        message["From"] = sender
        message["Subject"] = subject
        message.attach(MIMEText(body or "", "plain", "utf-8"))
        if html:
            message.attach(MIMEText(html, "html", "utf-8"))

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw_message},
            timeout=20,
        )

        print("GMAIL DEBUG: send status =", response.status_code)
        print("GMAIL DEBUG: send body =", response.text)

        if response.ok:
            print("GMAIL DEBUG: Gmail send succeeded")
            return True

        print("Gmail API send error:", response.status_code, response.text)
        return False
    except Exception as e:
        print(f"Gmail API request error: {e}")
        return False


def send_email_via_resend(to_email, subject, body, html=None):
    api_key = (current_app.config.get("RESEND_API_KEY") or "").strip()
    from_email = (current_app.config.get("RESEND_FROM_EMAIL") or "").strip()
    if not api_key or not from_email:
        return False

    payload = {
        "from": _format_from_header(),
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if response.ok:
            return True

        print("Resend error while sending email:", response.status_code, response.text)
        return False
    except Exception as e:
        print(f"Resend request error: {e}")
        return False


def send_email_via_smtp(to_email, subject, body, html=None):
    if current_app.config.get("MAIL_USERNAME") and current_app.config.get("MAIL_PASSWORD"):
        try:
            msg = MailMessage(subject=subject, recipients=[to_email])
            msg.body = body
            if html:
                msg.html = html
            mail.send(msg)
            return True
        except SMTPException as e:
            print(f"SMTP error while sending email: {e}")
            return False
        except Exception as e:
            print(f"General mail error: {e}")
            return False
    return False


def send_transactional_email(to_email, subject, body, html=None):
    provider = (current_app.config.get("EMAIL_PROVIDER") or "auto").strip().lower()

    if provider in {"gmail", "gmail_api"}:
        return send_email_via_gmail_api(to_email, subject, body, html=html)

    if provider == "resend":
        return send_email_via_resend(to_email, subject, body, html=html)

    if provider == "smtp":
        return send_email_via_smtp(to_email, subject, body, html=html)

    if _gmail_api_is_configured():
        return send_email_via_gmail_api(to_email, subject, body, html=html)

    if current_app.config.get("RESEND_API_KEY") and current_app.config.get("RESEND_FROM_EMAIL"):
        return send_email_via_resend(to_email, subject, body, html=html)

    return send_email_via_smtp(to_email, subject, body, html=html)


def send_platform_email(to_email, subject, body):
    sent = send_transactional_email(to_email, subject, body)
    if sent:
        return True

    print("\nEMAIL NOT SENT - EMAIL PROVIDER NOT CONFIGURED OR DELIVERY FAILED")
    print(f"To: {to_email}")
    print(f"Subject: {subject}")
    print(body)
    print()
    return False


def notify_admins_about_verification(skill, action="submitted"):
    admin_users = User.query.filter_by(role="admin").all()

    for admin in admin_users:
        if action == "resubmitted":
            message = (
                f'Updated certification submitted again for skill "{skill.title}" '
                f'by {skill.owner.full_name}. Awaiting verification.'
            )
        else:
            message = (
                f'New certification submitted for skill "{skill.title}" '
                f'by {skill.owner.full_name}. Awaiting verification.'
            )

        create_notification(
            admin.id,
            message,
            "admin_verification",
            url_for("main.admin_skill_detail", skill_id=skill.id)
        )




def normalize_learning_level(level):
    mapping = {
        "Beginner": "Beginner",
        "Intermediate": "Intermediate",
        "Advanced": "Advanced",
        "Professional": "Advanced",
    }
    return mapping.get((level or "").strip(), "Beginner")


def level_rank(level):
    return {"Beginner": 1, "Intermediate": 2, "Advanced": 3}.get(normalize_learning_level(level), 1)


def allowed_course_levels_for_level(level):
    normalized = normalize_learning_level(level)
    if normalized == "Intermediate":
        return ["Beginner", "Intermediate"]
    if normalized == "Advanced":
        return ["Beginner", "Intermediate", "Advanced"]
    return []


def allowed_course_levels_for_skill(skill):
    return allowed_course_levels_for_level(skill.normalized_skill_level())


def get_active_teaching_permission(user_id, skill_id):
    return (
        TeachingPermission.query
        .filter_by(user_id=user_id, skill_id=skill_id, status="Approved")
        .first()
    )

def ensure_profile_warning_notification(user):
    completion = user.profile_completion_percentage()

    if completion >= 100:
        return

    existing_unread = Notification.query.filter_by(
        user_id=user.id,
        notification_type="profile_warning",
        is_read=False
    ).first()

    if not existing_unread:
        create_notification(
            user.id,
            f"Your profile is only {completion}% complete. Please update missing details.",
            "profile_warning",
            url_for("main.update_profile")
        )


def send_reset_email(user):
    token = user.get_reset_token(current_app.config["SECRET_KEY"])
    reset_link = url_for("main.reset_password", token=token, _external=True)

    subject = "SkillsInn - Password Reset Request"
    body = f"""Hello {user.full_name},

You requested to reset your SkillsInn password.

Click the link below to reset your password:
{reset_link}

If you did not make this request, please ignore this email.
This link will expire in 1 hour.
"""
    html = f"""
        <p>Hello {user.full_name},</p>
        <p>You requested to reset your SkillsInn password.</p>
        <p><a href="{reset_link}">Reset your password</a></p>
        <p>If you did not make this request, please ignore this email.</p>
        <p>This link will expire in 1 hour.</p>
    """

    if send_transactional_email(user.email, subject, body, html=html):
        return True

    print("\nPASSWORD RESET LINK:")
    print(reset_link)
    print()
    return _is_local_debug_mode()


def send_verification_email(user):
    token = user.get_email_verification_token(current_app.config["SECRET_KEY"])
    verify_link = url_for("main.verify_email", token=token, _external=True)

    subject = "SkillsInn - Verify Your Email"
    body = f"""Hello {user.full_name},

Welcome to SkillsInn. Please verify your email address before logging in.

Click the link below to verify your email:
{verify_link}

If you did not create this account, please ignore this email.
This link will expire in 24 hours.
"""
    html = f"""
        <p>Hello {user.full_name},</p>
        <p>Welcome to SkillsInn. Please verify your email address before logging in.</p>
        <p><a href="{verify_link}">Verify your email</a></p>
        <p>If you did not create this account, please ignore this email.</p>
        <p>This link will expire in 24 hours.</p>
    """

    sent = send_transactional_email(user.email, subject, body, html=html)
    if sent:
        return True

    print("\nEMAIL VERIFICATION LINK:")
    print(verify_link)
    print()
    return _is_local_debug_mode()


@main.app_context_processor
def inject_unread_notification_count():
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return {"unread_notification_count": unread_count}
    return {"unread_notification_count": 0}


@main.route("/")
def home():
    return render_template("home.html")


@main.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegistrationForm()

    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if existing_user:
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("main.register"))

        user = User(
            full_name=form.full_name.data.strip(),
            email=form.email.data.lower().strip(),
            phone=form.phone.data.strip() if form.phone.data else None,
            role="user",
            is_email_verified=False,
        )
        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()

        email_sent = send_verification_email(user)
        if email_sent:
            flash("Account created. Please verify your email before logging in.", "success")
        else:
            flash("Account created, but we could not send the verification email right now. You can resend it from the verification page.", "warning")

        return redirect(url_for("main.verify_email_notice", email=user.email))

    return render_template("register.html", form=form)


@main.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if user and user.check_password(form.password.data):
            if user.role != "admin" and not user.is_email_verified:
                flash("Please verify your email address before logging in.", "warning")
                return redirect(url_for("main.verify_email_notice", email=user.email))

            login_user(user)
            flash("Login successful.", "success")
            return redirect(get_post_login_redirect(user))

        flash("Invalid email or password.", "danger")

    return render_template("login.html", form=form)


@main.route("/verify-email-notice")
def verify_email_notice():
    if current_user.is_authenticated and current_user.is_email_verified:
        return redirect(url_for("main.dashboard"))

    email = (request.args.get("email") or "").strip().lower()
    user = User.query.filter_by(email=email).first() if email else None

    return render_template("verify_email_notice.html", email=email, user=user)


@main.route("/verify-email/<token>")
def verify_email(token):
    if current_user.is_authenticated and current_user.role == "admin":
        return redirect(url_for("main.admin_dashboard"))

    user = User.verify_email_verification_token(token, current_app.config["SECRET_KEY"])

    if not user:
        flash("That email verification link is invalid or has expired.", "danger")
        return redirect(url_for("main.login"))

    if not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = datetime.utcnow()
        db.session.commit()

    return render_template("email_verification_success.html", user=user)


@main.route("/resend-verification", methods=["POST"])
def resend_verification():
    if current_user.is_authenticated and current_user.role == "admin":
        return redirect(url_for("main.admin_dashboard"))

    email = (request.form.get("email") or request.args.get("email") or "").strip().lower()
    if not email:
        flash("Please provide the email address used to register.", "warning")
        return redirect(url_for("main.login"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("We could not find an account with that email address.", "danger")
        return redirect(url_for("main.register"))

    if user.is_email_verified:
        flash("That email address is already verified. You can log in now.", "info")
        return redirect(url_for("main.login"))

    email_sent = send_verification_email(user)
    if email_sent:
        flash("A new verification email has been sent.", "success")
    else:
        flash("We could not send the verification email right now. Please check your mail settings and try again.", "danger")

    return redirect(url_for("main.verify_email_notice", email=user.email))


@main.route("/auth/google")
def auth_google():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    google = oauth.create_client("google")
    if not google:
        flash("Google sign-in is not configured yet.", "warning")
        return redirect(url_for("main.login"))

    redirect_uri = url_for("main.auth_google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@main.route("/auth/google/callback")
def auth_google_callback():
    google = oauth.create_client("google")
    if not google:
        flash("Google sign-in is not configured yet.", "warning")
        return redirect(url_for("main.login"))

    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo") or google.userinfo()
    except Exception:
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(url_for("main.login"))

    provider_user_id = user_info.get("sub")
    email = user_info.get("email")
    name = user_info.get("name")
    picture = user_info.get("picture")

    if not provider_user_id or not email:
        flash("Google did not return enough account information.", "danger")
        return redirect(url_for("main.login"))

    user = resolve_or_create_social_user(
        provider="google",
        provider_user_id=provider_user_id,
        email=email,
        name=name,
        picture=picture,
    )

    if not user:
        flash("Unable to complete Google sign-in.", "danger")
        return redirect(url_for("main.login"))

    login_user(user)
    flash("Logged in with Google successfully.", "success")
    return redirect(get_post_login_redirect(user))


@main.route("/auth/facebook")
def auth_facebook():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    facebook = oauth.create_client("facebook")
    if not facebook:
        flash("Facebook sign-in is not configured yet.", "warning")
        return redirect(url_for("main.login"))

    redirect_uri = url_for("main.auth_facebook_callback", _external=True)
    return facebook.authorize_redirect(redirect_uri)


@main.route("/auth/facebook/callback")
def auth_facebook_callback():
    facebook = oauth.create_client("facebook")
    if not facebook:
        flash("Facebook sign-in is not configured yet.", "warning")
        return redirect(url_for("main.login"))

    try:
        facebook.authorize_access_token()
        resp = facebook.get("me?fields=id,name,email,picture.type(large)")
        user_info = resp.json()
    except Exception:
        flash("Facebook sign-in failed. Please try again.", "danger")
        return redirect(url_for("main.login"))

    provider_user_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name")
    picture_data = ((user_info.get("picture") or {}).get("data") or {})
    picture = picture_data.get("url")

    if not provider_user_id or not email:
        flash("Facebook did not return enough account information. Please use email registration or choose a Facebook account with an email address.", "danger")
        return redirect(url_for("main.login"))

    user = resolve_or_create_social_user(
        provider="facebook",
        provider_user_id=provider_user_id,
        email=email,
        name=name,
        picture=picture,
    )

    if not user:
        flash("Unable to complete Facebook sign-in.", "danger")
        return redirect(url_for("main.login"))

    login_user(user)
    flash("Logged in with Facebook successfully.", "success")
    return redirect(get_post_login_redirect(user))

@main.route("/admin/setup", methods=["GET", "POST"])
@login_required
def admin_setup():
    if current_user.role != "admin":
        abort(403)

    form = AdminSetupForm()

    if form.validate_on_submit():
        new_email = form.email.data.lower().strip()

        existing_user = User.query.filter_by(email=new_email).first()
        if existing_user and existing_user.id != current_user.id:
            flash("That email is already in use by another account.", "danger")
            return redirect(url_for("main.admin_setup"))

        current_user.email = new_email
        current_user.set_password(form.password.data)
        current_user.must_change_credentials = False
        current_user.is_default_admin = False

        db.session.commit()

        flash("Admin credentials updated successfully.", "success")
        return redirect(url_for("main.admin_dashboard"))

    return render_template("admin_setup.html", form=form)


@main.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = ForgotPasswordForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if user:
            email_sent = send_reset_email(user)

            if email_sent:
                flash("If that email exists, a password reset link has been sent.", "info")
            else:
                flash("Could not send reset email right now. Please check your mail settings and try again.", "danger")
        else:
            flash("If that email exists, a password reset link has been sent.", "info")

        return redirect(url_for("main.login"))

    return render_template("forgot_password.html", form=form)


@main.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    user = User.verify_reset_token(token, current_app.config["SECRET_KEY"])

    if not user:
        flash("That password reset link is invalid or has expired.", "danger")
        return redirect(url_for("main.forgot_password"))

    form = ResetPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()

        flash("Your password has been reset successfully. You can now log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("reset_password.html", form=form)


@main.route("/dashboard")
@login_required
def dashboard():
    if current_user.role == "admin":
        if current_user.must_change_credentials:
            return redirect(url_for("main.admin_setup"))
        return redirect(url_for("main.admin_dashboard"))

    ensure_profile_warning_notification(current_user)

    completion = current_user.profile_completion_percentage()
    missing_items = current_user.missing_profile_items()
    user_skills = Skill.query.filter_by(user_id=current_user.id).order_by(Skill.created_at.desc()).all()
    skill_count = len(user_skills)
    moderation_warnings = (
        Notification.query
        .filter_by(user_id=current_user.id, notification_type="moderation_warning")
        .order_by(Notification.created_at.desc())
        .all()
    )
    active_messaging_restriction = current_user.active_messaging_restriction()

    return render_template(
        "dashboard.html",
        completion=completion,
        missing_items=missing_items,
        skill_count=skill_count,
        user_skills=user_skills,
        moderation_warnings=moderation_warnings,
        active_messaging_restriction=active_messaging_restriction
    )


@main.route("/notifications")
@login_required
def notifications():
    all_notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=all_notifications)


@main.route("/notifications/mark-read/<int:notification_id>", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)

    if notification.user_id != current_user.id:
        abort(403)

    notification.is_read = True
    db.session.commit()

    return redirect(url_for("main.notifications"))


@main.route("/notifications/open/<int:notification_id>")
@login_required
def open_notification(notification_id):
    notification = Notification.query.get_or_404(notification_id)

    if notification.user_id != current_user.id:
        abort(403)

    notification.is_read = True
    db.session.commit()

    if notification.notification_link:
        return redirect(notification.notification_link)

    return redirect(url_for("main.notifications"))


@main.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()

    flash("All notifications marked as read.", "success")
    return redirect(url_for("main.notifications"))


@main.route("/profile/update", methods=["GET", "POST"])
@login_required
@user_only_required
def update_profile():
    form = UpdateProfileForm()

    if form.validate_on_submit():
        current_user.full_name = form.full_name.data.strip()
        current_user.phone = form.phone.data.strip() if form.phone.data else None
        current_user.bio = form.bio.data.strip() if form.bio.data else None

        current_user.street_address = form.street_address.data.strip() if form.street_address.data else None
        current_user.suburb = form.suburb.data.strip() if form.suburb.data else None
        current_user.city = form.city.data.strip() if form.city.data else None
        current_user.postal_code = form.postal_code.data.strip() if form.postal_code.data else None

        current_user.availability = form.availability.data or None
        current_user.experience_level = form.experience_level.data or None
        current_user.preferred_contact_method = form.preferred_contact_method.data or None
        current_user.portfolio_link = form.portfolio_link.data.strip() if form.portfolio_link.data else None

        if form.profile_picture.data:
            current_user.profile_picture = save_file(form.profile_picture.data, "profiles")

        if form.resume_file.data:
            current_user.resume_file = save_file(form.resume_file.data, "resumes")

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("main.dashboard"))

    if not form.is_submitted():
        form.full_name.data = current_user.full_name
        form.phone.data = current_user.phone
        form.bio.data = current_user.bio
        form.street_address.data = current_user.street_address
        form.suburb.data = current_user.suburb
        form.city.data = current_user.city
        form.postal_code.data = current_user.postal_code
        form.availability.data = current_user.availability
        form.experience_level.data = current_user.experience_level
        form.preferred_contact_method.data = current_user.preferred_contact_method
        form.portfolio_link.data = current_user.portfolio_link

    return render_template("update_profile.html", form=form)


@main.route("/skills")
@login_required
@user_only_required
def skills():
    all_skills = Skill.query.filter(Skill.status == "Active").order_by(Skill.created_at.desc()).all()
    return render_template("skills.html", skills=all_skills)


@main.route("/skills/my")
@login_required
@user_only_required
def my_skills():
    user_skills = Skill.query.filter_by(user_id=current_user.id).order_by(Skill.created_at.desc()).all()
    return render_template("my_skills.html", skills=user_skills)


@main.route("/skills/add", methods=["GET", "POST"])
@login_required
@user_only_required
def add_skill():
    form = SkillForm()

    if form.validate_on_submit():
        verification_status = "Not Submitted"
        certificate_path = None
        verification_note = None
        verified_at = None

        if form.certificate_file.data:
            certificate_path = save_file(form.certificate_file.data, "certificates")
            verification_status = "Awaiting Verification"

        skill = Skill(
            user_id=current_user.id,
            category=form.category.data,
            custom_category=form.custom_category.data.strip() if form.custom_category.data else None,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            experience_level=form.experience_level.data,
            availability=form.availability.data,
            skill_level=normalize_learning_level(form.experience_level.data),
            source="manual",
            certificate_file=certificate_path,
            verification_status=verification_status,
            verification_note=verification_note,
            verified_at=verified_at,
            certificate_viewed_by_admin=False,
            certificate_viewed_at=None,
            status="Active"
        )

        db.session.add(skill)
        db.session.commit()

        if skill.certificate_file:
            notify_admins_about_verification(skill, action="submitted")

        flash("Skill added successfully.", "success")
        return redirect(url_for("main.my_skills"))

    return render_template("add_skill.html", form=form)


@main.route("/skills/<int:skill_id>")
@login_required
def skill_detail(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if current_user.role == "admin":
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    return render_template("skill_detail.html", skill=skill)


@main.route("/skills/<int:skill_id>/edit", methods=["GET", "POST"])
@login_required
@user_only_required
def edit_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if skill.user_id != current_user.id:
        abort(403)
    if not skill.can_be_edited_by_owner():
        flash("Skills earned from Learning Hub are locked and cannot be edited manually.", "warning")
        return redirect(url_for("main.skill_detail", skill_id=skill.id))

    form = SkillForm()

    if form.validate_on_submit():
        skill.category = form.category.data
        skill.custom_category = form.custom_category.data.strip() if form.custom_category.data else None
        skill.title = form.title.data.strip()
        skill.description = form.description.data.strip()
        skill.experience_level = form.experience_level.data
        skill.availability = form.availability.data
        skill.skill_level = normalize_learning_level(form.experience_level.data)
        skill.source = skill.source or "manual"

        uploaded_new_certificate = False

        if form.certificate_file.data:
            skill.certificate_file = save_file(form.certificate_file.data, "certificates")
            skill.verification_status = "Awaiting Verification"
            skill.verification_note = None
            skill.verified_at = None
            skill.certificate_viewed_by_admin = False
            skill.certificate_viewed_at = None
            uploaded_new_certificate = True

        db.session.commit()

        if uploaded_new_certificate:
            notify_admins_about_verification(skill, action="resubmitted")

        flash("Skill updated successfully.", "success")
        return redirect(url_for("main.my_skills"))

    if not form.is_submitted():
        form.category.data = skill.category
        form.custom_category.data = skill.custom_category
        form.title.data = skill.title
        form.description.data = skill.description
        form.experience_level.data = skill.experience_level
        form.availability.data = skill.availability

    return render_template("edit_skill.html", form=form, skill=skill)


@main.route("/skills/<int:skill_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_skill(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if skill.user_id != current_user.id:
        abort(403)

    db.session.delete(skill)
    db.session.commit()

    flash("Skill deleted successfully.", "info")
    return redirect(url_for("main.my_skills"))




def _teacher_owns_course(course):
    return current_user.is_authenticated and current_user.role == "user" and course.created_by_user_id == current_user.id


def _ensure_teacher_course_access(course):
    if not _teacher_owns_course(course):
        abort(403)


def _get_or_create_enrollment(course, user_id):
    enrollment = CourseEnrollment.query.filter_by(course_id=course.id, user_id=user_id).first()
    if enrollment:
        return enrollment, False
    enrollment = CourseEnrollment(user_id=user_id, course_id=course.id, status="Enrolled")
    db.session.add(enrollment)
    db.session.flush()
    for chapter in course.chapters:
        db.session.add(ChapterProgress(enrollment_id=enrollment.id, chapter_id=chapter.id))
    return enrollment, True


def _ensure_progress_rows(enrollment):
    existing_ids = {row.chapter_id for row in enrollment.progress_rows}
    created = False
    for chapter in enrollment.course.chapters:
        if chapter.id not in existing_ids:
            db.session.add(ChapterProgress(enrollment_id=enrollment.id, chapter_id=chapter.id))
            created = True
    if created:
        db.session.flush()


def _get_progress_or_404(enrollment, chapter_id):
    _ensure_progress_rows(enrollment)
    progress = enrollment.progress_for_chapter(chapter_id)
    if not progress:
        abort(404)
    return progress


def _parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value):
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _resequence_course_chapters(course):
    for index, chapter in enumerate(sorted(course.chapters, key=lambda item: (item.chapter_order, item.id)), start=1):
        chapter.chapter_order = index


def _award_learning_skill(user, course):
    existing_skill = Skill.query.filter_by(user_id=user.id, title=course.skill_name).first()
    level = normalize_learning_level(course.level)
    now = datetime.utcnow()
    if existing_skill:
        current_rank = level_rank(existing_skill.normalized_skill_level())
        earned_rank = level_rank(level)
        if earned_rank >= current_rank:
            existing_skill.skill_level = level
            existing_skill.experience_level = level
            existing_skill.source = "learning_hub"
            existing_skill.earned_course_id = course.id
            existing_skill.earned_at = now
            existing_skill.status = "Active"
    else:
        skill = Skill(
            user_id=user.id,
            category=course.skill_category or "Other",
            custom_category=None,
            title=course.skill_name,
            description=f"Earned from Learning Hub course: {course.title}",
            experience_level=level,
            availability="Flexible",
            skill_level=level,
            source="learning_hub",
            earned_course_id=course.id,
            earned_at=now,
            verification_status="Approved",
            verified_at=now,
            status="Active",
        )
        db.session.add(skill)


def _chapter_quiz_pass_mark():
    return 60


def _is_absolute_url(value):
    value = (value or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


def _build_question_payload(prefix="option"):
    question_type = (request.form.get("question_type") or "mcq").strip().lower()
    if question_type not in {"mcq", "true_false"}:
        question_type = "mcq"
    correct_option = (request.form.get("correct_option") or "A").strip().upper()
    if question_type == "true_false":
        if correct_option not in {"A", "B"}:
            correct_option = "A"
        return {
            "question_type": question_type,
            "option_a": "True",
            "option_b": "False",
            "option_c": "N/A",
            "option_d": "N/A",
            "correct_option": correct_option,
        }
    if correct_option not in {"A", "B", "C", "D"}:
        correct_option = "A"
    return {
        "question_type": question_type,
        "option_a": (request.form.get("option_a") or "").strip() or "Option A",
        "option_b": (request.form.get("option_b") or "").strip() or "Option B",
        "option_c": (request.form.get("option_c") or "").strip() or "Option C",
        "option_d": (request.form.get("option_d") or "").strip() or "Option D",
        "correct_option": correct_option,
    }


def _final_exam_session_key(course_id):
    return f"final_exam_start_{course_id}"


def _teacher_redirect(course, anchor="overview"):
    return redirect(url_for("main.teacher_course_detail", course_id=course.id, tab=anchor))


def _reset_enrollment_for_restart(enrollment):
    enrollment.status = "Enrolled"
    enrollment.completed_at = None
    enrollment.final_exam_score = None
    enrollment.final_exam_passed = False
    enrollment.final_exam_passed_at = None
    for attempt in list(enrollment.final_exam_attempts):
        db.session.delete(attempt)
    for row in enrollment.progress_rows:
        row.is_completed = False
        row.completed_at = None
        row.content_viewed_at = None
        row.quiz_score = None
        row.quiz_passed = False
        row.quiz_passed_at = None


def _persist_teacher_tab(default_tab="overview"):
    return (request.args.get("tab") or request.form.get("next_tab") or default_tab).strip() or default_tab


@main.route("/learning-hub")
@login_required
@user_only_required
def learning_hub():
    search_term = (request.args.get("search") or request.args.get("q") or "").strip()
    level_filter = (request.args.get("level") or "").strip()
    category_filter = (request.args.get("category") or "").strip()
    teacher_filter = (request.args.get("teacher") or "").strip()
    sort = (request.args.get("sort") or "newest").strip()

    query = Course.query.filter_by(status="Published")

    if search_term:
        like_term = f"%{search_term}%"
        query = query.filter(
            db.or_(
                Course.title.ilike(like_term),
                Course.description.ilike(like_term),
                Course.skill_name.ilike(like_term),
                Course.skill_category.ilike(like_term),
            )
        )

    if level_filter:
        query = query.filter(Course.level == level_filter)

    if category_filter:
        query = query.filter(Course.skill_category == category_filter)

    if teacher_filter:
        query = query.join(User, Course.created_by_user_id == User.id).filter(User.full_name.ilike(f"%{teacher_filter}%"))

    if sort == "oldest":
        query = query.order_by(Course.created_at.asc())
    elif sort == "title_asc":
        query = query.order_by(Course.title.asc())
    else:
        query = query.order_by(Course.created_at.desc())

    published_courses = query.all()
    all_published = Course.query.filter_by(status="Published").order_by(Course.created_at.desc()).all()
    my_enrollments = {enrollment.course_id: enrollment for enrollment in current_user.course_enrollments}
    categories = sorted({course.skill_category for course in all_published if course.skill_category})
    teachers = sorted({course.creator.full_name for course in all_published if course.creator and course.creator.full_name})

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("_learning_hub_results.html", courses=published_courses, my_enrollments=my_enrollments)

    return render_template(
        "learning_hub.html",
        courses=published_courses,
        my_enrollments=my_enrollments,
        filters={
            "q": search_term,
            "level": level_filter,
            "category": category_filter,
            "teacher": teacher_filter,
            "sort": sort,
        },
        category_options=categories,
        teacher_options=teachers,
        categories=categories,
        selected_search=search_term,
        selected_level=level_filter,
        selected_category=category_filter,
        selected_sort=sort,
    )


@main.route("/learning-hub/my-learning")
@login_required
@user_only_required
def my_learning():
    enrollments = (
        CourseEnrollment.query
        .filter_by(user_id=current_user.id)
        .order_by(CourseEnrollment.enrolled_at.desc())
        .all()
    )
    for enrollment in enrollments:
        _ensure_progress_rows(enrollment)
    db.session.commit()
    return render_template("my_learning.html", enrollments=enrollments)


@main.route("/learning-hub/courses/<int:course_id>")
@login_required
@user_only_required
def learning_course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    if course.status != "Published" and not _teacher_owns_course(course):
        abort(404)
    enrollment = None
    if current_user.is_authenticated:
        enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first()
        if enrollment:
            _ensure_progress_rows(enrollment)
            db.session.commit()
    return render_template("learning_course_detail.html", course=course, enrollment=enrollment, chapter_quiz_pass_mark=_chapter_quiz_pass_mark())


@main.route("/learning-hub/courses/<int:course_id>/enroll", methods=["POST"])
@login_required
@user_only_required
def enroll_learning_course(course_id):
    course = Course.query.get_or_404(course_id)
    if course.status != "Published":
        abort(404)
    if course.created_by_user_id == current_user.id:
        flash("Teachers cannot enroll in their own courses.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    enrollment, created = _get_or_create_enrollment(course, current_user.id)
    db.session.commit()
    if created:
        flash(f"You are now enrolled in {course.title}.", "success")
    else:
        flash("You are already enrolled in this course.", "info")
    return redirect(url_for("main.learning_course_detail", course_id=course.id))


@main.route("/learning-hub/courses/<int:course_id>/unenroll", methods=["POST"])
@login_required
@user_only_required
def unenroll_learning_course(course_id):
    course = Course.query.get_or_404(course_id)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    db.session.delete(enrollment)
    db.session.commit()
    session.pop(_final_exam_session_key(course.id), None)
    flash(f"You have unenrolled from {course.title}.", "info")
    return redirect(url_for("main.learning_hub"))


@main.route("/learning-hub/courses/<int:course_id>/chapters/<int:chapter_id>")
@login_required
@user_only_required
def learning_chapter_detail(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first()
    if not enrollment:
        flash("Enroll in the course first to open chapters.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    _ensure_progress_rows(enrollment)
    if not enrollment.is_chapter_unlocked(chapter):
        flash("Complete the previous required chapter first.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    progress = _get_progress_or_404(enrollment, chapter.id)
    return render_template("learning_chapter_detail.html", course=course, chapter=chapter, enrollment=enrollment, progress=progress, chapter_quiz_pass_mark=_chapter_quiz_pass_mark())


@main.route("/learning-hub/courses/<int:course_id>/chapters/<int:chapter_id>/quiz")
@login_required
@user_only_required
def learning_chapter_quiz(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first()
    if not enrollment:
        flash("Enroll in the course first to take the quiz.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    _ensure_progress_rows(enrollment)
    if not enrollment.is_chapter_unlocked(chapter):
        flash("Complete the previous required chapter first.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    progress = _get_progress_or_404(enrollment, chapter.id)
    if not chapter.has_quiz():
        flash("This chapter has no quiz yet.", "warning")
        return redirect(url_for("main.learning_chapter_detail", course_id=course.id, chapter_id=chapter.id))
    return render_template("learning_chapter_quiz.html", course=course, chapter=chapter, enrollment=enrollment, progress=progress, chapter_quiz_pass_mark=_chapter_quiz_pass_mark())


@main.route("/learning-hub/courses/<int:course_id>/chapters/<int:chapter_id>/mark-viewed", methods=["POST"])
@login_required
@user_only_required
def mark_learning_chapter_viewed(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    _ensure_progress_rows(enrollment)
    if not enrollment.is_chapter_unlocked(chapter):
        flash("Complete the previous required chapter first.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    progress = _get_progress_or_404(enrollment, chapter.id)
    if not progress.content_viewed_at:
        progress.content_viewed_at = datetime.utcnow()
    if not chapter.has_quiz():
        progress.is_completed = True
        progress.completed_at = progress.completed_at or datetime.utcnow()
    db.session.commit()
    if chapter.has_quiz():
        flash("Chapter marked as viewed. Pass the quiz to complete this chapter.", "info")
    else:
        flash("Chapter completed.", "success")
    return redirect(url_for("main.learning_chapter_detail", course_id=course.id, chapter_id=chapter.id))


@main.route("/learning-hub/courses/<int:course_id>/chapters/<int:chapter_id>/quiz", methods=["POST"])
@login_required
@user_only_required
def submit_learning_chapter_quiz(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    _ensure_progress_rows(enrollment)
    if not enrollment.is_chapter_unlocked(chapter):
        flash("Complete the previous required chapter first.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    progress = _get_progress_or_404(enrollment, chapter.id)
    questions = chapter.quiz_questions
    if not questions:
        flash("This chapter has no quiz yet.", "warning")
        return redirect(url_for("main.learning_chapter_detail", course_id=course.id, chapter_id=chapter.id))
    correct_answers = 0
    for question in questions:
        selected = (request.form.get(f"question_{question.id}") or "").strip().upper()
        if selected == (question.correct_option or "").strip().upper():
            correct_answers += 1
    score_percent = round((correct_answers / len(questions)) * 100) if questions else 0
    passed = score_percent >= _chapter_quiz_pass_mark()
    progress.content_viewed_at = progress.content_viewed_at or datetime.utcnow()
    progress.quiz_score = score_percent
    progress.quiz_passed = passed
    progress.quiz_passed_at = datetime.utcnow() if passed else None
    progress.is_completed = passed
    progress.completed_at = datetime.utcnow() if passed else None
    db.session.add(ChapterQuizAttempt(enrollment_id=enrollment.id, chapter_id=chapter.id, score_percent=score_percent, is_passed=passed))
    db.session.commit()
    if passed:
        flash(f"Quiz passed with {score_percent}%. Chapter completed.", "success")
    else:
        flash(f"Quiz score: {score_percent}%. You need at least {_chapter_quiz_pass_mark()}% to unlock the next chapter.", "warning")
    return redirect(url_for("main.learning_chapter_detail", course_id=course.id, chapter_id=chapter.id))


@main.route("/learning-hub/courses/<int:course_id>/final-exam")
@login_required
@user_only_required
def learning_final_exam(course_id):
    course = Course.query.get_or_404(course_id)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    _ensure_progress_rows(enrollment)
    if not enrollment.all_required_chapters_completed():
        flash("Complete all required chapters and chapter quizzes before taking the final exam.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    if not course.final_exam_questions:
        flash("This course does not have a final exam yet.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    if not enrollment.can_take_final_exam():
        flash("You have no final exam attempts remaining for this course.", "danger")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    key = _final_exam_session_key(course.id)
    started_at = session.get(key)
    now_ts = int(datetime.utcnow().timestamp())
    if course.final_exam_duration_minutes and started_at:
        elapsed_seconds = now_ts - int(started_at)
        if elapsed_seconds >= course.final_exam_duration_minutes * 60:
            session.pop(key, None)
            started_at = None
    if not started_at:
        session[key] = now_ts
        started_at = now_ts
    return render_template("learning_final_exam.html", course=course, enrollment=enrollment, started_at=started_at, now_timestamp=now_ts)


@main.route("/learning-hub/courses/<int:course_id>/final-exam", methods=["POST"])
@login_required
@user_only_required
def submit_learning_final_exam(course_id):
    course = Course.query.get_or_404(course_id)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    _ensure_progress_rows(enrollment)
    if not enrollment.all_required_chapters_completed():
        flash("Complete all required chapters and chapter quizzes before taking the final exam.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))
    questions = course.final_exam_questions
    if not questions:
        flash("This course does not have a final exam yet.", "warning")
        return redirect(url_for("main.learning_course_detail", course_id=course.id))

    key = _final_exam_session_key(course.id)
    started_at = session.get(key)
    if course.final_exam_duration_minutes and started_at:
        elapsed_seconds = int(datetime.utcnow().timestamp()) - int(started_at)
        if elapsed_seconds > course.final_exam_duration_minutes * 60:
            session.pop(key, None)
            flash("Time is up. Start the final exam again to get a fresh timer.", "danger")
            return redirect(url_for("main.learning_final_exam", course_id=course.id))

    correct_answers = 0
    for question in questions:
        selected = (request.form.get(f"final_question_{question.id}") or "").strip().upper()
        if selected == (question.correct_option or "").strip().upper():
            correct_answers += 1
    score_percent = round((correct_answers / len(questions)) * 100) if questions else 0
    passed = score_percent >= (course.pass_mark or 70)
    db.session.add(FinalExamAttempt(enrollment_id=enrollment.id, course_id=course.id, score_percent=score_percent, is_passed=passed))
    db.session.flush()
    enrollment.final_exam_score = score_percent
    enrollment.final_exam_passed = passed
    enrollment.final_exam_passed_at = datetime.utcnow() if passed else None
    if passed:
        enrollment.status = "Completed"
        enrollment.completed_at = datetime.utcnow()
        _award_learning_skill(current_user, course)
        create_notification(
            current_user.id,
            f"You passed '{course.title}' and earned {course.level} level for {course.skill_name}.",
            notification_type="course_complete",
            notification_link=url_for("main.learning_course_detail", course_id=course.id),
        )
        flash(f"Final exam passed with {score_percent}%. You earned {course.level} level for {course.skill_name}.", "success")
    else:
        enrollment.status = "Enrolled"
        remaining = enrollment.attempts_remaining()
        if remaining == 0 and course.final_exam_attempt_limit:
            _reset_enrollment_for_restart(enrollment)
            flash(f"Final exam score: {score_percent}%. You used all allowed attempts, so the course has been reset and you need to start again.", "danger")
        else:
            attempts_message = "Unlimited attempts" if remaining is None else f"{remaining} attempt(s) remaining"
            flash(f"Final exam score: {score_percent}%. You need {course.pass_mark}% to complete the course. {attempts_message}.", "warning")
    session.pop(key, None)
    db.session.commit()
    return redirect(url_for("main.learning_course_detail", course_id=course.id))


@main.route("/learning-hub/courses/<int:course_id>/assignments/<int:assignment_id>")
@login_required
@user_only_required
def learning_assignment_detail(course_id, assignment_id):
    course = Course.query.get_or_404(course_id)
    assignment = CourseAssignment.query.get_or_404(assignment_id)
    if assignment.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    submission = enrollment.submission_for_assignment(assignment.id)
    return render_template("learning_assignment_detail.html", course=course, assignment=assignment, enrollment=enrollment, submission=submission)


@main.route("/learning-hub/courses/<int:course_id>/assignments/<int:assignment_id>/submit", methods=["POST"])
@login_required
@user_only_required
def submit_learning_assignment(course_id, assignment_id):
    course = Course.query.get_or_404(course_id)
    assignment = CourseAssignment.query.get_or_404(assignment_id)
    if assignment.course_id != course.id:
        abort(404)
    enrollment = CourseEnrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first_or_404()
    uploaded_file = request.files.get("submission_file")
    if not uploaded_file or not uploaded_file.filename:
        flash("Please upload a PDF submission file.", "warning")
        return redirect(url_for("main.learning_assignment_detail", course_id=course.id, assignment_id=assignment.id))
    if not uploaded_file.filename.lower().endswith(".pdf"):
        flash("Assignment submissions must be PDF files.", "warning")
        return redirect(url_for("main.learning_assignment_detail", course_id=course.id, assignment_id=assignment.id))
    submission_path = save_file(uploaded_file, "learning_assignments/submissions")
    submission = enrollment.submission_for_assignment(assignment.id)
    if not submission:
        submission = AssignmentSubmission(assignment_id=assignment.id, enrollment_id=enrollment.id, submission_file=submission_path)
        db.session.add(submission)
    submission.submission_file = submission_path
    submission.submission_note = (request.form.get("submission_note") or "").strip() or None
    submission.status = "Submitted"
    submission.submitted_at = datetime.utcnow()
    db.session.commit()
    flash("Assignment submitted successfully.", "success")
    return redirect(url_for("main.learning_assignment_detail", course_id=course.id, assignment_id=assignment.id))


@main.route("/teaching/applications")
@login_required
@user_only_required
def my_teaching_applications():
    applications = (
        TeachApplication.query
        .filter_by(user_id=current_user.id)
        .order_by(TeachApplication.created_at.desc())
        .all()
    )
    return render_template("my_teaching_applications.html", applications=applications)


@main.route("/skills/<int:skill_id>/apply-to-teach", methods=["GET", "POST"])
@login_required
@user_only_required
def apply_to_teach(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if skill.user_id != current_user.id:
        abort(403)

    normalized_level = skill.normalized_skill_level()
    if normalized_level == "Beginner":
        flash("You cannot apply to teach this skill because your current level is Beginner. Reach Intermediate or Advanced first.", "warning")
        return redirect(url_for("main.my_skills"))

    existing_permission = get_active_teaching_permission(current_user.id, skill.id)
    if existing_permission:
        flash("You are already approved to teach this skill.", "info")
        return redirect(url_for("main.teacher_dashboard"))

    existing_pending = (
        TeachApplication.query
        .filter_by(user_id=current_user.id, skill_id=skill.id, status="Pending")
        .first()
    )
    if existing_pending:
        flash("You already have a pending teaching application for this skill.", "info")
        return redirect(url_for("main.my_teaching_applications"))

    form = TeachApplicationForm()
    if form.validate_on_submit():
        application = TeachApplication(
            user_id=current_user.id,
            skill_id=skill.id,
            application_reason=form.application_reason.data.strip() if form.application_reason.data else None,
            status="Pending",
            max_teaching_level=normalized_level if normalized_level in {"Intermediate", "Advanced"} else None,
        )
        db.session.add(application)
        db.session.commit()

        for admin in User.query.filter_by(role="admin").all():
            create_notification(
                admin.id,
                f"New teaching application: {current_user.full_name} applied to teach {skill.title}.",
                notification_type="teaching_application",
                notification_link=url_for("main.admin_teach_applications")
            )

        flash("Your teaching application has been submitted for admin review.", "success")
        return redirect(url_for("main.my_teaching_applications"))

    return render_template("teach_skill_application.html", form=form, skill=skill)


@main.route("/teaching/dashboard")
@login_required
@user_only_required
def teacher_dashboard():
    permissions = (
        TeachingPermission.query
        .filter_by(user_id=current_user.id, status="Approved")
        .order_by(TeachingPermission.created_at.desc())
        .all()
    )
    courses = Course.query.filter_by(created_by_user_id=current_user.id).order_by(Course.created_at.desc()).all()
    return render_template("teacher_dashboard.html", permissions=permissions, courses=courses)


@main.route("/teaching/courses/create", methods=["GET", "POST"])
@login_required
@user_only_required
def create_course():
    permissions = (
        TeachingPermission.query
        .filter_by(user_id=current_user.id, status="Approved")
        .all()
    )

    approved_skills = []
    level_options_by_skill = {}
    for permission in permissions:
        skill = permission.skill
        if not skill:
            continue
        approved_skills.append(skill)
        level_options_by_skill[skill.id] = allowed_course_levels_for_level(permission.max_teaching_level)

    if not approved_skills:
        flash("You need an approved teaching permission before creating a course.", "warning")
        return redirect(url_for("main.teacher_dashboard"))

    form = CourseForm()
    form.skill_id.choices = [(skill.id, f"{skill.title} ({skill.normalized_skill_level()})") for skill in approved_skills]

    selected_skill_id = form.skill_id.data or (approved_skills[0].id if approved_skills else None)
    selected_level_options = level_options_by_skill.get(selected_skill_id, [])
    form.level.choices = [(level, level) for level in selected_level_options]

    if request.method == "POST":
        selected_skill_id = form.skill_id.data
        selected_level_options = level_options_by_skill.get(selected_skill_id, [])
        form.level.choices = [(level, level) for level in selected_level_options]

    if form.validate_on_submit():
        skill = Skill.query.get_or_404(form.skill_id.data)
        permission = get_active_teaching_permission(current_user.id, skill.id)

        if not permission:
            flash("You are not approved to teach that skill.", "danger")
            return redirect(url_for("main.teacher_dashboard"))

        allowed_levels = allowed_course_levels_for_level(permission.max_teaching_level)
        selected_course_level = normalize_learning_level(form.level.data)
        if selected_course_level not in allowed_levels:
            flash("You are not allowed to create a course at that level for this skill.", "danger")
            return redirect(url_for("main.create_course"))

        course = Course(
            created_by_user_id=current_user.id,
            skill_id=skill.id,
            skill_name=skill.title,
            skill_category=skill.display_category(),
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            level=selected_course_level,
            pass_mark=form.pass_mark.data,
            status="PendingReview",
        )
        db.session.add(course)
        db.session.commit()

        for admin in User.query.filter_by(role="admin").all():
            create_notification(
                admin.id,
                f"New Learning Hub course awaiting review: {course.title}.",
                notification_type="course_review",
                notification_link=url_for("main.admin_learning_courses")
            )

        flash("Course saved and sent for admin review. You can now open it and build chapters, content, quizzes, and the final exam.", "success")
        return _teacher_redirect(course, "chapter-builder")

    return render_template(
        "course_form.html",
        form=form,
        approved_skills=approved_skills,
        level_options_by_skill=level_options_by_skill,
    )


@main.route("/teaching/courses/<int:course_id>")
@login_required
@user_only_required
def teacher_course_detail(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    return render_template("teacher_course_detail.html", course=course, chapter_quiz_pass_mark=_chapter_quiz_pass_mark(), active_tab=_persist_teacher_tab())


@main.route("/teaching/courses/<int:course_id>/chapters/add", methods=["POST"])
@login_required
@user_only_required
def add_course_chapter(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip() or "Chapter notes will appear here."
    previous_chapter = course.chapters[-1] if course.chapters else None
    if previous_chapter and len(previous_chapter.content_blocks) == 0:
        flash("Finish saving learning material for the current chapter before adding another one.", "warning")
        return _teacher_redirect(course, f"chapter-{previous_chapter.id}")
    if not title:
        flash("Chapter title is required.", "warning")
        return _teacher_redirect(course, "chapter-builder")
    chapter = CourseChapter(
        course_id=course.id,
        title=title,
        chapter_order=len(course.chapters) + 1,
        content=content,
        is_required=_parse_bool(request.form.get("is_required")),
    )
    db.session.add(chapter)
    db.session.commit()
    flash("Chapter added.", "success")
    return _teacher_redirect(course, "chapter-builder")


@main.route("/teaching/courses/<int:course_id>/chapters/<int:chapter_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_course_chapter(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    db.session.delete(chapter)
    db.session.flush()
    _resequence_course_chapters(course)
    db.session.commit()
    flash("Chapter deleted.", "info")
    return _teacher_redirect(course, "chapter-builder")


@main.route("/teaching/courses/<int:course_id>/chapters/<int:chapter_id>/blocks/add", methods=["POST"])
@login_required
@user_only_required
def add_course_content_block(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    block_type = (request.form.get("block_type") or "text").strip().lower()
    if block_type not in {"text", "image", "pdf", "media", "link"}:
        block_type = "text"
    media_url = (request.form.get("media_url") or "").strip() or None
    external_url = (request.form.get("external_url") or "").strip() or None
    uploaded_file = request.files.get("media_file")
    if block_type in {"text", "link"}:
        media_url = None
    if block_type in {"image", "pdf", "media"} and uploaded_file and uploaded_file.filename:
        media_url = save_file(uploaded_file, "learning_content")
    if block_type == "link":
        media_url = None
        if not external_url:
            flash("External link URL is required for link blocks.", "warning")
            return _teacher_redirect(course, f"chapter-{chapter.id}")
    if block_type == "text":
        media_url = None
        external_url = None
    if block_type in {"image", "pdf", "media"} and not media_url:
        flash("Upload a file from your device for image, PDF, or video content.", "warning")
        return _teacher_redirect(course, f"chapter-{chapter.id}")
    block = CourseContentBlock(
        chapter_id=chapter.id,
        block_type=block_type,
        title=(request.form.get("title") or "").strip() or None,
        text_content=(request.form.get("text_content") or "").strip() or None,
        media_url=media_url,
        external_url=external_url,
        display_order=len(chapter.content_blocks) + 1,
    )
    db.session.add(block)
    db.session.commit()
    flash("Content block added.", "success")
    return _teacher_redirect(course, f"chapter-{chapter.id}")


@main.route("/teaching/courses/<int:course_id>/chapters/<int:chapter_id>/quiz/add", methods=["POST"])
@login_required
@user_only_required
def add_chapter_quiz_question(course_id, chapter_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    if chapter.course_id != course.id:
        abort(404)
    question_text = (request.form.get("question_text") or "").strip()
    if not question_text:
        flash("Question text is required.", "warning")
        return _teacher_redirect(course, f"chapter-{chapter.id}-quiz")
    payload = _build_question_payload()
    question = ChapterQuizQuestion(
        chapter_id=chapter.id,
        question_text=question_text,
        question_type=payload["question_type"],
        option_a=payload["option_a"],
        option_b=payload["option_b"],
        option_c=payload["option_c"],
        option_d=payload["option_d"],
        correct_option=payload["correct_option"],
        display_order=len(chapter.quiz_questions) + 1,
    )
    db.session.add(question)
    db.session.commit()
    flash("Chapter quiz question added.", "success")
    return _teacher_redirect(course, f"chapter-{chapter.id}-quiz")


@main.route("/teaching/courses/<int:course_id>/final-exam/add", methods=["POST"])
@login_required
@user_only_required
def add_final_exam_question(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    question_text = (request.form.get("question_text") or "").strip()
    if not question_text:
        flash("Final exam question text is required.", "warning")
        return _teacher_redirect(course, "final-exam-builder")
    payload = _build_question_payload()
    question = FinalExamQuestion(
        course_id=course.id,
        question_text=question_text,
        question_type=payload["question_type"],
        option_a=payload["option_a"],
        option_b=payload["option_b"],
        option_c=payload["option_c"],
        option_d=payload["option_d"],
        correct_option=payload["correct_option"],
        display_order=len(course.final_exam_questions) + 1,
    )
    db.session.add(question)
    db.session.commit()
    flash("Final exam question added.", "success")
    return _teacher_redirect(course, "final-exam-builder")


@main.route("/teaching/courses/<int:course_id>/final-exam/settings", methods=["POST"])
@login_required
@user_only_required
def update_final_exam_settings(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    duration = _parse_int(request.form.get("final_exam_duration_minutes"), 0)
    attempt_limit = _parse_int(request.form.get("final_exam_attempt_limit"), 0)
    course.final_exam_duration_minutes = duration if duration > 0 else None
    course.final_exam_attempt_limit = attempt_limit if attempt_limit > 0 else None
    db.session.commit()
    flash("Final exam settings updated.", "success")
    return _teacher_redirect(course, "final-exam-builder")


@main.route("/teaching/courses/<int:course_id>/assignments/add", methods=["POST"])
@login_required
@user_only_required
def add_course_assignment(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    title = (request.form.get("title") or "").strip()
    due_at_raw = (request.form.get("due_at") or "").strip()
    instructions = (request.form.get("instructions") or "").strip() or None
    if not title or not due_at_raw:
        flash("Assignment title and due date are required.", "warning")
        return redirect(url_for("main.teacher_course_detail", course_id=course.id))
    try:
        due_at = datetime.strptime(due_at_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Use a valid due date and time.", "warning")
        return redirect(url_for("main.teacher_course_detail", course_id=course.id))
    resource_path = None
    resource_file = request.files.get("resource_file")
    if resource_file and resource_file.filename:
        if not resource_file.filename.lower().endswith(".pdf"):
            flash("Assignment brief upload must be a PDF file.", "warning")
            return redirect(url_for("main.teacher_course_detail", course_id=course.id))
        resource_path = save_file(resource_file, "learning_assignments/briefs")
    assignment = CourseAssignment(course_id=course.id, title=title, instructions=instructions, due_at=due_at, resource_file=resource_path)
    db.session.add(assignment)
    db.session.commit()
    flash("Assignment added.", "success")
    return redirect(url_for("main.teacher_course_detail", course_id=course.id))


@main.route("/teaching/courses/<int:course_id>/assignments/<int:assignment_id>")
@login_required
@user_only_required
def teacher_assignment_detail(course_id, assignment_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    assignment = CourseAssignment.query.get_or_404(assignment_id)
    if assignment.course_id != course.id:
        abort(404)
    submissions = (
        AssignmentSubmission.query
        .join(CourseEnrollment, AssignmentSubmission.enrollment_id == CourseEnrollment.id)
        .filter(AssignmentSubmission.assignment_id == assignment.id)
        .order_by(AssignmentSubmission.submitted_at.desc())
        .all()
    )
    return render_template("teacher_assignment_detail.html", course=course, assignment=assignment, submissions=submissions)


@main.route("/teaching/courses/<int:course_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    for skill in course.earned_skills:
        skill.earned_course_id = None
    db.session.delete(course)
    db.session.commit()
    flash("Course deleted. Learners keep any skills they already earned.", "info")
    return redirect(url_for("main.teacher_dashboard"))


@main.route("/teaching/courses/<int:course_id>/chapters/<int:chapter_id>/quiz/<int:question_id>/edit", methods=["POST"])
@login_required
@user_only_required
def edit_chapter_quiz_question(course_id, chapter_id, question_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    question = ChapterQuizQuestion.query.get_or_404(question_id)
    if chapter.course_id != course.id or question.chapter_id != chapter.id:
        abort(404)
    question.question_text = (request.form.get("question_text") or "").strip() or question.question_text
    payload = _build_question_payload()
    question.question_type = payload["question_type"]
    question.option_a = payload["option_a"]
    question.option_b = payload["option_b"]
    question.option_c = payload["option_c"]
    question.option_d = payload["option_d"]
    question.correct_option = payload["correct_option"]
    db.session.commit()
    flash("Quiz question updated.", "success")
    return _teacher_redirect(course, f"chapter-{chapter.id}-quiz")


@main.route("/teaching/courses/<int:course_id>/chapters/<int:chapter_id>/quiz/<int:question_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_chapter_quiz_question(course_id, chapter_id, question_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    chapter = CourseChapter.query.get_or_404(chapter_id)
    question = ChapterQuizQuestion.query.get_or_404(question_id)
    if chapter.course_id != course.id or question.chapter_id != chapter.id:
        abort(404)
    db.session.delete(question)
    db.session.commit()
    flash("Quiz question deleted.", "info")
    return _teacher_redirect(course, f"chapter-{chapter.id}-quiz")


@main.route("/teaching/courses/<int:course_id>/final-exam/<int:question_id>/edit", methods=["POST"])
@login_required
@user_only_required
def edit_final_exam_question(course_id, question_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    question = FinalExamQuestion.query.get_or_404(question_id)
    if question.course_id != course.id:
        abort(404)
    question.question_text = (request.form.get("question_text") or "").strip() or question.question_text
    payload = _build_question_payload()
    question.question_type = payload["question_type"]
    question.option_a = payload["option_a"]
    question.option_b = payload["option_b"]
    question.option_c = payload["option_c"]
    question.option_d = payload["option_d"]
    question.correct_option = payload["correct_option"]
    db.session.commit()
    flash("Final test question updated.", "success")
    return _teacher_redirect(course, "final-exam-builder")


@main.route("/teaching/courses/<int:course_id>/final-exam/<int:question_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_final_exam_question(course_id, question_id):
    course = Course.query.get_or_404(course_id)
    _ensure_teacher_course_access(course)
    question = FinalExamQuestion.query.get_or_404(question_id)
    if question.course_id != course.id:
        abort(404)
    db.session.delete(question)
    db.session.commit()
    flash("Final test question deleted.", "info")
    return _teacher_redirect(course, "final-exam-builder")


@main.route("/admin/teaching/applications")
@login_required
@admin_required
def admin_teach_applications():
    applications = TeachApplication.query.order_by(TeachApplication.created_at.desc()).all()
    return render_template("admin_teach_applications.html", applications=applications)


@main.route("/admin/teaching/applications/<int:application_id>/<decision>", methods=["POST"])
@login_required
@admin_required
def review_teach_application(application_id, decision):
    application = TeachApplication.query.get_or_404(application_id)
    decision = (decision or "").lower().strip()
    review_note = (request.form.get("review_note") or "").strip() or None

    if application.status != "Pending":
        flash("This teaching application has already been reviewed.", "info")
        return redirect(url_for("main.admin_teach_applications"))

    if decision not in {"approve", "reject"}:
        flash("Invalid review action.", "danger")
        return redirect(url_for("main.admin_teach_applications"))

    application.review_note = review_note
    application.reviewed_by_id = current_user.id
    application.reviewed_at = datetime.utcnow()

    if decision == "approve":
        normalized_level = application.skill.normalized_skill_level()
        max_teaching_level = "Advanced" if normalized_level == "Advanced" else "Intermediate"
        application.status = "Approved"
        application.max_teaching_level = max_teaching_level

        permission = get_active_teaching_permission(application.user_id, application.skill_id)
        if permission:
            permission.max_teaching_level = max_teaching_level
            permission.approved_by_id = current_user.id
            permission.approved_at = datetime.utcnow()
            permission.status = "Approved"
        else:
            permission = TeachingPermission(
                user_id=application.user_id,
                skill_id=application.skill_id,
                max_teaching_level=max_teaching_level,
                status="Approved",
                approved_by_id=current_user.id,
                approved_at=datetime.utcnow(),
            )
            db.session.add(permission)

        create_notification(
            application.user_id,
            f"Your application to teach {application.skill.title} was approved. You can now create up to {max_teaching_level} courses for this skill.",
            notification_type="teaching_application",
            notification_link=url_for("main.teacher_dashboard")
        )
        flash("Teaching application approved.", "success")
    else:
        application.status = "Rejected"
        application.max_teaching_level = None
        create_notification(
            application.user_id,
            f"Your application to teach {application.skill.title} was not approved.",
            notification_type="teaching_application",
            notification_link=url_for("main.my_teaching_applications")
        )
        flash("Teaching application rejected.", "warning")

    db.session.commit()
    return redirect(url_for("main.admin_teach_applications"))


@main.route("/admin/learning-hub/courses")
@login_required
@admin_required
def admin_learning_courses():
    courses = Course.query.order_by(Course.created_at.desc()).all()
    return render_template("admin_learning_courses.html", courses=courses)


@main.route("/admin/learning-hub/courses/<int:course_id>/<decision>", methods=["POST"])
@login_required
@admin_required
def review_learning_course(course_id, decision):
    course = Course.query.get_or_404(course_id)
    decision = (decision or "").lower().strip()
    review_note = (request.form.get("review_note") or "").strip() or None

    if decision not in {"publish", "reject"}:
        flash("Invalid course review action.", "danger")
        return redirect(url_for("main.admin_learning_courses"))

    if decision == "publish":
        course.status = "Published"
        course.review_note = review_note
        course.published_by_id = current_user.id
        course.published_at = datetime.utcnow()
        create_notification(
            course.created_by_user_id,
            f"Your Learning Hub course '{course.title}' is now published.",
            notification_type="course_review",
            notification_link=url_for("main.teacher_dashboard")
        )
        flash("Course published successfully.", "success")
    else:
        course.status = "Rejected"
        course.review_note = review_note
        create_notification(
            course.created_by_user_id,
            f"Your Learning Hub course '{course.title}' was rejected. Review the admin note and update it before resubmitting.",
            notification_type="course_review",
            notification_link=url_for("main.teacher_dashboard")
        )
        flash("Course rejected.", "warning")

    db.session.commit()
    return redirect(url_for("main.admin_learning_courses"))

@main.route("/requests")
@login_required
@user_only_required
def help_requests():
    search = (request.args.get("search") or "").strip()
    category = (request.args.get("category") or "").strip()
    urgency = (request.args.get("urgency") or "").strip()
    experience = (request.args.get("experience") or "").strip()
    schedule_type = (request.args.get("schedule_type") or "").strip()
    city = (request.args.get("city") or "").strip()
    sort = (request.args.get("sort") or "newest").strip()

    query = HelpRequest.query

    if search:
        query = query.filter(
            db.or_(
                HelpRequest.title.ilike(f"%{search}%"),
                HelpRequest.description.ilike(f"%{search}%"),
                HelpRequest.category.ilike(f"%{search}%"),
                HelpRequest.custom_category.ilike(f"%{search}%"),
                HelpRequest.city.ilike(f"%{search}%"),
                HelpRequest.suburb.ilike(f"%{search}%"),
                HelpRequest.street_address.ilike(f"%{search}%"),
            )
        )

    if category:
        if category == "Other":
            query = query.filter(HelpRequest.category == "Other")
        else:
            query = query.filter(
                db.or_(
                    HelpRequest.category == category,
                    HelpRequest.custom_category.ilike(f"%{category}%")
                )
            )

    if urgency:
        query = query.filter(HelpRequest.urgency == urgency)

    if experience:
        query = query.filter(HelpRequest.experience_level_required == experience)

    if schedule_type:
        query = query.filter(HelpRequest.schedule_type == schedule_type)

    if city:
        query = query.filter(HelpRequest.city.ilike(f"%{city}%"))

    if sort == "oldest":
        query = query.order_by(HelpRequest.created_at.asc())
    elif sort == "urgency_high":
        query = query.order_by(
            db.case(
                (HelpRequest.urgency == "High", 1),
                (HelpRequest.urgency == "Medium", 2),
                (HelpRequest.urgency == "Low", 3),
                else_=4
            ),
            HelpRequest.created_at.desc()
        )
    else:
        query = query.order_by(HelpRequest.created_at.desc())

    requests_list = query.all()

    return render_template(
        "help_requests.html",
        requests=requests_list,
        selected_search=search,
        selected_category=category,
        selected_urgency=urgency,
        selected_experience=experience,
        selected_schedule_type=schedule_type,
        selected_city=city,
        selected_sort=sort,
    )


@main.route("/requests/my")
@login_required
@user_only_required
def my_help_requests():
    my_requests = HelpRequest.query.filter_by(requester_id=current_user.id).order_by(HelpRequest.created_at.desc()).all()
    return render_template("my_help_requests.html", requests=my_requests)


@main.route("/requests/create", methods=["GET", "POST"])
@login_required
@user_only_required
def create_help_request():
    form = HelpRequestForm()

    if request.method == "POST":
        form.recurrence_days_data = request.form.getlist("recurrence_days")
        form.monthly_dates_data = request.form.getlist("monthly_dates")

    if form.validate_on_submit():
        selected_recurrence_days = request.form.getlist("recurrence_days")
        selected_monthly_dates = request.form.getlist("monthly_dates")

        help_request = HelpRequest(
            requester_id=current_user.id,
            category=form.category.data,
            custom_category=form.custom_category.data.strip() if form.custom_category.data else None,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            street_address=form.street_address.data.strip(),
            suburb=form.suburb.data.strip() if form.suburb.data else None,
            city=form.city.data.strip(),
            postal_code=form.postal_code.data.strip() if form.postal_code.data else None,
            schedule_type=form.schedule_type.data,
            date_needed=form.date_needed.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            time_flexible=form.time_flexible.data,
            recurrence_days=",".join(selected_recurrence_days) if selected_recurrence_days else None,
            monthly_dates=",".join(selected_monthly_dates) if selected_monthly_dates else None,
            urgency=form.urgency.data,
            experience_level_required=form.experience_level_required.data,
            status="Open"
        )

        db.session.add(help_request)
        db.session.commit()

        flash("Help request posted successfully.", "success")
        return redirect(url_for("main.my_help_requests"))

    return render_template("create_help_request.html", form=form)


@main.route("/requests/<int:request_id>")
@login_required
@user_only_required
def help_request_detail(request_id):
    help_request = HelpRequest.query.get_or_404(request_id)
    existing_application = Application.query.filter_by(
        help_request_id=help_request.id,
        applicant_id=current_user.id
    ).first()

    application_count = Application.query.filter_by(help_request_id=help_request.id).count()

    skill_match_info = None
    if current_user.id != help_request.requester_id:
        skill_match_info = get_request_skill_match(current_user, help_request)

    collaboration = Collaboration.query.filter_by(help_request_id=help_request.id).first()

    return render_template(
        "help_request_detail.html",
        help_request=help_request,
        existing_application=existing_application,
        application_count=application_count,
        skill_match_info=skill_match_info,
        collaboration=collaboration
    )

@main.route("/requests/<int:request_id>/edit", methods=["GET", "POST"])

@login_required
@user_only_required
def edit_help_request(request_id):
    help_request = HelpRequest.query.get_or_404(request_id)

    if help_request.requester_id != current_user.id:
        abort(403)

    if help_request.status in ["In Progress", "Completed"]:
        flash("This help request can no longer be edited.", "warning")
        return redirect(url_for("main.help_request_detail", request_id=help_request.id))

    form = HelpRequestForm()

    if request.method == "POST":
        form.recurrence_days_data = request.form.getlist("recurrence_days")
        form.monthly_dates_data = request.form.getlist("monthly_dates")

    if form.validate_on_submit():
        selected_recurrence_days = request.form.getlist("recurrence_days")
        selected_monthly_dates = request.form.getlist("monthly_dates")

        help_request.category = form.category.data
        help_request.custom_category = form.custom_category.data.strip() if form.custom_category.data else None
        help_request.title = form.title.data.strip()
        help_request.description = form.description.data.strip()
        help_request.street_address = form.street_address.data.strip()
        help_request.suburb = form.suburb.data.strip() if form.suburb.data else None
        help_request.city = form.city.data.strip()
        help_request.postal_code = form.postal_code.data.strip() if form.postal_code.data else None
        help_request.schedule_type = form.schedule_type.data
        help_request.date_needed = form.date_needed.data
        help_request.start_date = form.start_date.data
        help_request.end_date = form.end_date.data
        help_request.start_time = form.start_time.data
        help_request.end_time = form.end_time.data
        help_request.time_flexible = form.time_flexible.data
        help_request.recurrence_days = ",".join(selected_recurrence_days) if selected_recurrence_days else None
        help_request.monthly_dates = ",".join(selected_monthly_dates) if selected_monthly_dates else None
        help_request.urgency = form.urgency.data
        help_request.experience_level_required = form.experience_level_required.data

        db.session.commit()
        flash("Help request updated successfully.", "success")
        return redirect(url_for("main.my_help_requests"))

    if not form.is_submitted():
        form.category.data = help_request.category
        form.custom_category.data = help_request.custom_category
        form.title.data = help_request.title
        form.description.data = help_request.description
        form.street_address.data = help_request.street_address
        form.suburb.data = help_request.suburb
        form.city.data = help_request.city
        form.postal_code.data = help_request.postal_code
        form.schedule_type.data = help_request.schedule_type
        form.date_needed.data = help_request.date_needed
        form.start_date.data = help_request.start_date
        form.end_date.data = help_request.end_date
        form.start_time.data = help_request.start_time
        form.end_time.data = help_request.end_time
        form.time_flexible.data = help_request.time_flexible
        form.recurrence_days.data = help_request.recurrence_days
        form.monthly_dates.data = help_request.monthly_dates
        form.urgency.data = help_request.urgency
        form.experience_level_required.data = help_request.experience_level_required

    return render_template("edit_help_request.html", form=form, help_request=help_request)


@main.route("/requests/<int:request_id>/delete", methods=["POST"])
@login_required
@user_only_required
def delete_help_request(request_id):
    help_request = HelpRequest.query.get_or_404(request_id)

    if help_request.requester_id != current_user.id:
        abort(403)

    if help_request.status in ["In Progress", "Completed"]:
        flash("This help request cannot be deleted.", "warning")
        return redirect(url_for("main.help_request_detail", request_id=help_request.id))

    db.session.delete(help_request)
    db.session.commit()

    flash("Help request deleted successfully.", "info")
    return redirect(url_for("main.my_help_requests"))


@main.route("/requests/<int:request_id>/apply", methods=["GET", "POST"])
@login_required
@user_only_required
def apply_to_help_request(request_id):
    help_request = HelpRequest.query.get_or_404(request_id)

    if help_request.requester_id == current_user.id:
        flash("You cannot apply to your own help request.", "warning")
        return redirect(url_for("main.help_request_detail", request_id=help_request.id))

    if help_request.status not in ["Open", "Under Review"]:
        flash("This help request is not currently accepting new applications.", "warning")
        return redirect(url_for("main.help_request_detail", request_id=help_request.id))

    existing_application = Application.query.filter_by(
        help_request_id=help_request.id,
        applicant_id=current_user.id
    ).first()

    if existing_application:
        flash("You have already applied to this help request.", "warning")
        return redirect(url_for("main.help_request_detail", request_id=help_request.id))

    form = ApplicationForm()

    if form.validate_on_submit():
        application = Application(
            help_request_id=help_request.id,
            applicant_id=current_user.id,
            message=form.message.data.strip(),
            status="Applied"
        )

        db.session.add(application)
        db.session.commit()

        create_notification(
            help_request.requester_id,
            f'A new application was submitted for your help request "{help_request.title}".',
            "request_application",
            url_for("main.view_request_applications", request_id=help_request.id)
        )

        send_platform_email(
            help_request.requester.email,
            f"New Application for {help_request.title}",
            f"""Hello {help_request.requester.full_name},

A new application was submitted for your help request "{help_request.title}".

Please log in to SkillsInn to review applicants.
"""
        )

        flash("Application submitted successfully.", "success")
        return redirect(url_for("main.my_applications"))

    return render_template("apply_to_help_request.html", form=form, help_request=help_request)


@main.route("/applications/my")
@login_required
@user_only_required
def my_applications():
    applications = Application.query.filter_by(applicant_id=current_user.id).order_by(Application.applied_at.desc()).all()
    collaboration_map = {app.id: app.collaboration for app in applications if getattr(app, "collaboration", None)}
    return render_template("my_applications.html", applications=applications, collaboration_map=collaboration_map)


def get_category_calendar_style(category_name):
    category_name = (category_name or "general").strip().lower()

    explicit_styles = {
        "information technology": "background:#fff3cd;color:#664d03;border-left:4px solid #ffc107;",
        "software development": "background:#fff3cd;color:#664d03;border-left:4px solid #ffc107;",
        "construction": "background:#cfe2ff;color:#084298;border-left:4px solid #0d6efd;",
        "plumbing": "background:#cfe2ff;color:#084298;border-left:4px solid #0d6efd;",
        "engineering": "background:#d1e7dd;color:#0f5132;border-left:4px solid #198754;",
        "education and tutoring": "background:#e2d9f3;color:#432874;border-left:4px solid #6f42c1;",
        "home and maintenance services": "background:#f8d7da;color:#842029;border-left:4px solid #dc3545;",
        "business and administration": "background:#cff4fc;color:#055160;border-left:4px solid #0dcaf0;",
        "creative arts and design": "background:#fce5cd;color:#7c4a03;border-left:4px solid #fd7e14;",
    }

    if category_name in explicit_styles:
        return explicit_styles[category_name]

    palette = [
        "background:#fff3cd;color:#664d03;border-left:4px solid #ffc107;",
        "background:#cfe2ff;color:#084298;border-left:4px solid #0d6efd;",
        "background:#d1e7dd;color:#0f5132;border-left:4px solid #198754;",
        "background:#e2d9f3;color:#432874;border-left:4px solid #6f42c1;",
        "background:#f8d7da;color:#842029;border-left:4px solid #dc3545;",
        "background:#cff4fc;color:#055160;border-left:4px solid #0dcaf0;",
        "background:#fce5cd;color:#7c4a03;border-left:4px solid #fd7e14;",
        "background:#e9ecef;color:#212529;border-left:4px solid #6c757d;",
    ]
    digest = hashlib.md5(category_name.encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(palette)
    return palette[index]


def mark_day_conflicts(day_events):
    for event in day_events:
        event["has_conflict"] = False

    for i in range(len(day_events)):
        for j in range(i + 1, len(day_events)):
            current = day_events[i]
            other = day_events[j]

            current_start = current["start_time"]
            current_end = current["end_time"]
            other_start = other["start_time"]
            other_end = other["end_time"]

            if not all([current_start, current_end, other_start, other_end]):
                continue

            overlaps = current_start < other_end and current_end > other_start
            if overlaps:
                current["has_conflict"] = True
                other["has_conflict"] = True

    return any(event["has_conflict"] for event in day_events)


@main.route("/collaborations/my")
@login_required
@user_only_required
def my_collaborations():
    collaborations = (
        Collaboration.query
        .filter((Collaboration.requester_id == current_user.id) | (Collaboration.provider_id == current_user.id))
        .order_by(Collaboration.updated_at.desc(), Collaboration.created_at.desc())
        .all()
    )
    return render_template("my_collaborations.html", collaborations=collaborations)


@main.route("/collaborations/<int:collaboration_id>")
@login_required
@user_only_required
def collaboration_detail(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    messages = Message.query.filter_by(collaboration_id=collaboration.id).order_by(Message.created_at.asc()).all()
    pending_reschedule = get_pending_reschedule_proposal(collaboration)
    recent_reschedule_proposals = (
        RescheduleProposal.query
        .filter_by(collaboration_id=collaboration.id)
        .order_by(RescheduleProposal.created_at.desc())
        .limit(5)
        .all()
    )
    return render_template(
        "collaboration_detail.html",
        collaboration=collaboration,
        messages=messages,
        pending_reschedule=pending_reschedule,
        recent_reschedule_proposals=recent_reschedule_proposals,
        active_messaging_restriction=current_user.active_messaging_restriction() if current_user.is_authenticated else None,
    )

@main.route("/collaborations/<int:collaboration_id>/request-completion", methods=["POST"])
@login_required
@user_only_required
def request_collaboration_completion(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_request_completion(current_user):
        flash("Only the provider can mark an active collaboration as completed.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    note = (request.form.get("completion_note") or "").strip()
    if len(note) > 1000:
        flash("Completion note is too long. Please keep it under 1000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    collaboration.status = "PendingCompletionConfirmation"
    collaboration.completion_requested_by_id = current_user.id
    collaboration.completion_requested_at = datetime.utcnow()
    collaboration.completion_note = note or None
    collaboration.updated_at = datetime.utcnow()

    system_message = f'{current_user.full_name} marked the work as completed and is waiting for requester confirmation.'
    if note:
        system_message += f"\nCompletion note: {note}"
    create_system_message(collaboration, system_message)

    db.session.commit()

    create_notification(
        collaboration.requester_id,
        f'{current_user.full_name} marked "{collaboration.help_request.title}" as completed and is waiting for your confirmation.',
        "collaboration_completion_requested",
        url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section")
    )

    flash("Completion request sent to the requester.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))


@main.route("/collaborations/<int:collaboration_id>/confirm-completion", methods=["POST"])
@login_required
@user_only_required
def confirm_collaboration_completion(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_confirm_completion(current_user):
        flash("Only the requester can confirm completion at this stage.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    collaboration.status = "Completed"
    collaboration.completed_at = datetime.utcnow()
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} confirmed completion. This collaboration is now closed.'
    )
    db.session.commit()

    create_notification(
        collaboration.provider_id,
        f'The requester confirmed completion for "{collaboration.help_request.title}". You can now submit your rating.',
        "collaboration_completed",
        url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section")
    )
    create_notification(
        collaboration.requester_id,
        f'"{collaboration.help_request.title}" is now completed. You can now submit your rating.',
        "collaboration_completed",
        url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section")
    )

    flash("Collaboration marked as completed.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))


@main.route("/collaborations/<int:collaboration_id>/reject-completion", methods=["POST"])
@login_required
@user_only_required
def reject_collaboration_completion(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_reject_completion(current_user):
        flash("You cannot reject completion for this collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Please give a short reason before sending the collaboration back to active.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    if len(reason) > 1000:
        flash("Reason is too long. Please keep it under 1000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    collaboration.status = "Active"
    collaboration.completion_requested_by_id = None
    collaboration.completion_requested_at = None
    collaboration.completion_note = None
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} said the work is not completed yet. Collaboration returned to active.\nReason: {reason}'
    )
    db.session.commit()

    create_notification(
        collaboration.provider_id,
        f'The requester did not confirm completion for "{collaboration.help_request.title}".',
        "collaboration_completion_rejected",
        url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section")
    )

    flash("Completion was not confirmed. Collaboration returned to active.", "info")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))


@main.route("/collaborations/<int:collaboration_id>/request-cancellation", methods=["POST"])
@login_required
@user_only_required
def request_collaboration_cancellation(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_request_cancellation(current_user):
        flash("You can only request cancellation for an active collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    reason = (request.form.get("cancellation_reason") or "").strip()
    if not reason:
        flash("Please provide a cancellation reason.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    if len(reason) > 1000:
        flash("Cancellation reason is too long. Please keep it under 1000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    collaboration.status = "PendingCancellation"
    collaboration.cancellation_requested_by_id = current_user.id
    collaboration.cancellation_requested_at = datetime.utcnow()
    collaboration.cancellation_reason = reason
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} requested cancellation.\nReason: {reason}'
    )
    db.session.commit()

    other_party = collaboration.other_party_for(current_user)
    if other_party:
        create_notification(
            other_party.id,
            f'{current_user.full_name} requested cancellation for "{collaboration.help_request.title}".',
            "collaboration_cancellation_requested",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section")
        )

    flash("Cancellation request sent.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))


@main.route("/collaborations/<int:collaboration_id>/accept-cancellation", methods=["POST"])
@login_required
@user_only_required
def accept_collaboration_cancellation(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_decide_cancellation(current_user):
        flash("You cannot accept cancellation for this collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    collaboration.status = "Cancelled"
    collaboration.cancelled_at = datetime.utcnow()
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} accepted the cancellation request. This collaboration is now cancelled and closed.'
    )
    db.session.commit()

    other_party = collaboration.other_party_for(current_user)
    if other_party:
        create_notification(
            other_party.id,
            f'Cancellation was accepted for "{collaboration.help_request.title}".',
            "collaboration_cancelled",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section")
        )

    flash("Collaboration cancelled.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))


@main.route("/collaborations/<int:collaboration_id>/reject-cancellation", methods=["POST"])
@login_required
@user_only_required
def reject_collaboration_cancellation(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_decide_cancellation(current_user):
        flash("You cannot reject cancellation for this collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Please provide a short reason for rejecting cancellation.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    if len(reason) > 1000:
        flash("Reason is too long. Please keep it under 1000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))

    requester_name = collaboration.cancellation_requested_by.full_name if collaboration.cancellation_requested_by else "A participant"

    collaboration.status = "Active"
    collaboration.cancellation_requested_by_id = None
    collaboration.cancellation_requested_at = None
    collaboration.cancellation_reason = None
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} rejected the cancellation request from {requester_name}. Collaboration returned to active.\nReason: {reason}'
    )
    db.session.commit()

    other_party = collaboration.other_party_for(current_user)
    if other_party:
        create_notification(
            other_party.id,
            f'Cancellation request for "{collaboration.help_request.title}" was rejected.',
            "collaboration_cancellation_rejected",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section")
        )

    flash("Cancellation rejected. Collaboration returned to active.", "info")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="outcome-section"))



def _parse_rating_value(raw_value, field_label):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"Please choose a value for {field_label}.")
    if value < 1 or value > 5:
        raise ValueError(f"{field_label} must be between 1 and 5.")
    return value


@main.route("/collaborations/<int:collaboration_id>/submit-rating", methods=["POST"])
@login_required
@user_only_required
def submit_collaboration_rating(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if collaboration.status != "Completed":
        flash("Ratings can only be submitted after a collaboration is completed.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section"))

    if not collaboration.can_be_rated_by(current_user):
        flash("You have already submitted your rating for this collaboration.", "info")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section"))

    rater_role = collaboration.user_role_for(current_user)
    if rater_role == "requester":
        ratee = collaboration.provider_user
        ratee_role = "provider"
        try:
            overall_rating = _parse_rating_value(request.form.get("overall_rating"), "overall experience")
            communication_rating = _parse_rating_value(request.form.get("communication_rating"), "communication")
            timeliness_rating = _parse_rating_value(request.form.get("timeliness_rating"), "timeliness")
            quality_rating = _parse_rating_value(request.form.get("quality_rating"), "quality of work")
        except ValueError as exc:
            flash(str(exc), "warning")
            return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section"))

        rating = CollaborationRating(
            collaboration_id=collaboration.id,
            rater_id=current_user.id,
            ratee_id=ratee.id,
            rater_role=rater_role,
            ratee_role=ratee_role,
            overall_rating=overall_rating,
            communication_rating=communication_rating,
            timeliness_rating=timeliness_rating,
            quality_rating=quality_rating,
        )
    elif rater_role == "provider":
        ratee = collaboration.requester_user
        ratee_role = "requester"
        try:
            overall_rating = _parse_rating_value(request.form.get("overall_rating"), "overall experience")
            communication_rating = _parse_rating_value(request.form.get("communication_rating"), "communication")
            clarity_rating = _parse_rating_value(request.form.get("clarity_rating"), "clarity of request")
            cooperation_rating = _parse_rating_value(request.form.get("cooperation_rating"), "cooperation")
        except ValueError as exc:
            flash(str(exc), "warning")
            return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section"))

        rating = CollaborationRating(
            collaboration_id=collaboration.id,
            rater_id=current_user.id,
            ratee_id=ratee.id,
            rater_role=rater_role,
            ratee_role=ratee_role,
            overall_rating=overall_rating,
            communication_rating=communication_rating,
            clarity_rating=clarity_rating,
            cooperation_rating=cooperation_rating,
        )
    else:
        abort(403)

    db.session.add(rating)
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} submitted a {ratee_role} rating.'
    )
    db.session.commit()

    create_notification(
        ratee.id,
        f'{current_user.full_name} submitted a rating after the completion of "{collaboration.help_request.title}".',
        "collaboration_rating_submitted",
        url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section")
    )

    flash("Your rating has been submitted.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="rating-section"))


@main.route("/collaborations/<int:collaboration_id>/messages", methods=["POST"])
@login_required
@user_only_required
def send_collaboration_message(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not collaboration.can_send_messages(current_user):
        flash("You cannot send messages once a collaboration is completed or cancelled.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id))

    active_restriction = current_user.active_messaging_restriction()
    if active_restriction:
        flash("You cannot send collaboration messages while a temporary messaging restriction is active.", "danger")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("Please type a message before sending.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id))

    if len(body) > 3000:
        flash("Message is too long. Please keep it under 3000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id))

    message = Message(
        collaboration_id=collaboration.id,
        sender_id=current_user.id,
        body=body,
        is_system_message=False
    )
    db.session.add(message)
    collaboration.updated_at = datetime.utcnow()
    db.session.commit()

    other_party = collaboration.other_party_for(current_user)
    if other_party:
        create_notification(
            other_party.id,
            f'New collaboration message on "{collaboration.help_request.title}" from {current_user.full_name}.',
            "collaboration_message",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id)
        )

    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="message-composer"))


@main.route("/collaborations/<int:collaboration_id>/reschedule", methods=["POST"])
@login_required
@user_only_required
def propose_reschedule(collaboration_id):
    collaboration = Collaboration.query.get_or_404(collaboration_id)

    if not collaboration.user_can_access(current_user):
        abort(403)

    if collaboration.status != "Active":
        flash("You can only propose a reschedule for an active collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    existing_pending = get_pending_reschedule_proposal(collaboration)
    if existing_pending:
        flash("There is already a pending reschedule proposal for this collaboration.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    try:
        payload = extract_reschedule_payload_from_request(request.form)
    except ValueError:
        flash("Please provide valid date and time values for the reschedule proposal.", "danger")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    validation_error = validate_reschedule_payload(payload)
    if validation_error:
        flash(validation_error, "danger")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    current_snapshot = help_request_schedule_snapshot(collaboration.help_request)

    proposal = RescheduleProposal(
        collaboration_id=collaboration.id,
        proposer_id=current_user.id,
        current_schedule_type=current_snapshot["schedule_type"],
        current_date_needed=current_snapshot["date_needed"],
        current_start_date=current_snapshot["start_date"],
        current_end_date=current_snapshot["end_date"],
        current_start_time=current_snapshot["start_time"],
        current_end_time=current_snapshot["end_time"],
        current_time_flexible=current_snapshot["time_flexible"],
        current_recurrence_days=current_snapshot["recurrence_days"],
        current_monthly_dates=current_snapshot["monthly_dates"],
        proposed_schedule_type=payload["schedule_type"],
        proposed_date_needed=payload["date_needed"] if payload["schedule_type"] == "one_time" else None,
        proposed_start_date=payload["start_date"] if payload["schedule_type"] != "one_time" else None,
        proposed_end_date=payload["end_date"] if payload["schedule_type"] != "one_time" else None,
        proposed_start_time=payload["start_time"],
        proposed_end_time=payload["end_time"],
        proposed_time_flexible=payload["time_flexible"],
        proposed_recurrence_days=payload["recurrence_days"] if payload["schedule_type"] == "recurring_weekly" else None,
        proposed_monthly_dates=payload["monthly_dates"] if payload["schedule_type"] == "recurring_monthly" else None,
        note=payload["note"],
        status="Pending",
    )
    db.session.add(proposal)
    collaboration.updated_at = datetime.utcnow()
    db.session.flush()

    proposal_message = (
        f'{current_user.full_name} proposed a schedule change.\n'
        f'Current schedule: {proposal.current_schedule_display()}\n'
        f'Proposed schedule: {proposal.proposed_schedule_display()}'
    )
    if proposal.note:
        proposal_message += f'\nNote: {proposal.note}'

    create_system_message(collaboration, proposal_message)
    db.session.commit()

    other_party = collaboration.other_party_for(current_user)
    if other_party:
        create_notification(
            other_party.id,
            f'{current_user.full_name} proposed a reschedule for "{collaboration.help_request.title}".',
            "reschedule_proposed",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section")
        )

    flash("Reschedule proposal sent.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))


@main.route("/reschedule-proposals/<int:proposal_id>/accept", methods=["POST"])
@login_required
@user_only_required
def accept_reschedule_proposal(proposal_id):
    proposal = RescheduleProposal.query.get_or_404(proposal_id)
    collaboration = proposal.collaboration

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not proposal.can_be_decided_by(current_user):
        flash("You cannot accept this reschedule proposal.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    payload = {
        "schedule_type": proposal.proposed_schedule_type,
        "date_needed": proposal.proposed_date_needed,
        "start_date": proposal.proposed_start_date,
        "end_date": proposal.proposed_end_date,
        "start_time": proposal.proposed_start_time,
        "end_time": proposal.proposed_end_time,
        "time_flexible": proposal.proposed_time_flexible,
        "recurrence_days": proposal.proposed_recurrence_days,
        "monthly_dates": proposal.proposed_monthly_dates,
    }

    temp_request = TemporaryScheduleRequest(collaboration.help_request, payload)
    conflict_info = build_conflict_info(collaboration.provider_user, temp_request, exclude_help_request_id=collaboration.help_request.id)
    if conflict_info.get("has_conflict"):
        flash(f'Cannot accept this reschedule because it causes a provider calendar conflict. {conflict_info.get("conflict_message")}', "danger")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    apply_schedule_payload_to_help_request(collaboration.help_request, payload)
    proposal.status = "Accepted"
    proposal.responded_at = datetime.utcnow()
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} accepted the reschedule proposal. New agreed schedule: {proposal.proposed_schedule_display()}'
    )
    db.session.commit()

    if proposal.proposer_id != current_user.id:
        create_notification(
            proposal.proposer_id,
            f'Your reschedule proposal for "{collaboration.help_request.title}" was accepted.',
            "reschedule_accepted",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section")
        )

    flash("Reschedule proposal accepted and schedule updated.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))


@main.route("/reschedule-proposals/<int:proposal_id>/decline", methods=["POST"])
@login_required
@user_only_required
def decline_reschedule_proposal(proposal_id):
    proposal = RescheduleProposal.query.get_or_404(proposal_id)
    collaboration = proposal.collaboration

    if not collaboration.user_can_access(current_user):
        abort(403)

    if not proposal.can_be_decided_by(current_user):
        flash("You cannot decline this reschedule proposal.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))

    proposal.status = "Declined"
    proposal.responded_at = datetime.utcnow()
    collaboration.updated_at = datetime.utcnow()

    create_system_message(
        collaboration,
        f'{current_user.full_name} declined the reschedule proposal. The current schedule remains: {proposal.current_schedule_display()}'
    )
    db.session.commit()

    if proposal.proposer_id != current_user.id:
        create_notification(
            proposal.proposer_id,
            f'Your reschedule proposal for "{collaboration.help_request.title}" was declined.',
            "reschedule_declined",
            url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section")
        )

    flash("Reschedule proposal declined.", "info")
    return redirect(url_for("main.collaboration_detail", collaboration_id=collaboration.id, _anchor="reschedule-section"))


@main.route("/calendar/my")
@login_required
@user_only_required
def my_calendar():
    today_value = date.today()

    try:
        month = int(request.args.get("month", today_value.month))
        year = int(request.args.get("year", today_value.year))
    except (TypeError, ValueError):
        month = today_value.month
        year = today_value.year

    if month < 1 or month > 12:
        month = today_value.month
    if year < 1900 or year > 2100:
        year = today_value.year

    accepted_applications = (
        Application.query
        .filter_by(applicant_id=current_user.id, status="Accepted")
        .order_by(Application.responded_at.desc())
        .all()
    )

    month_start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)

    events_by_day = {day: [] for day in range(1, last_day + 1)}

    for application in accepted_applications:
        help_request = application.help_request
        if not help_request:
            continue

        occurrences = get_request_occurrences(help_request)

        for occurrence in occurrences:
            occurrence_date = occurrence["date"]
            if month_start <= occurrence_date <= month_end:
                day_number = occurrence_date.day
                events_by_day[day_number].append({
                    "application": application,
                    "help_request": help_request,
                    "date": occurrence_date,
                    "start_time": occurrence["start_time"],
                    "end_time": occurrence["end_time"],
                    "style": get_category_calendar_style(help_request.display_category()),
                })

    day_conflict_map = {}

    for day_number, day_events in events_by_day.items():
        day_events.sort(key=lambda item: (item["start_time"] or time.min, item["help_request"].title.lower()))
        day_conflict_map[day_number] = mark_day_conflicts(day_events)

    month_matrix = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    weekday_headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    calendar_weeks = []
    for week in month_matrix:
        week_cells = []
        for day in week:
            week_cells.append({
                "day": day,
                "is_blank": day == 0,
                "is_today": day == today_value.day and month == today_value.month and year == today_value.year,
                "has_conflict": False if day == 0 else day_conflict_map.get(day, False),
                "events": [] if day == 0 else events_by_day.get(day, []),
            })
        calendar_weeks.append(week_cells)

    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month = 1
        next_year += 1

    month_name = calendar.month_name[month]

    return render_template(
        "my_calendar.html",
        calendar_weeks=calendar_weeks,
        weekday_headers=weekday_headers,
        current_month=month,
        current_year=year,
        current_month_name=month_name,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        today=today_value,
    )

@main.route("/requests/<int:request_id>/applications")
@login_required
@user_only_required
def view_request_applications(request_id):
    help_request = HelpRequest.query.get_or_404(request_id)

    if help_request.requester_id != current_user.id:
        abort(403)

    applications = Application.query.filter_by(help_request_id=help_request.id).order_by(Application.applied_at.desc()).all()
    collaboration_map = {app.id: app.collaboration for app in applications if getattr(app, "collaboration", None)}
    return render_template("request_applications.html", help_request=help_request, applications=applications, collaboration_map=collaboration_map)


@main.route("/requests/<int:request_id>/applicants/<int:user_id>")
@login_required
@user_only_required
def applicant_profile(request_id, user_id):
    help_request = HelpRequest.query.get_or_404(request_id)

    if help_request.requester_id != current_user.id:
        abort(403)

    applicant = User.query.get_or_404(user_id)

    application = Application.query.filter_by(
        help_request_id=help_request.id,
        applicant_id=applicant.id
    ).first()

    if not application:
        abort(404)

    applicant_skills = Skill.query.filter_by(user_id=applicant.id).order_by(Skill.created_at.desc()).all()

    return render_template(
        "applicant_profile.html",
        help_request=help_request,
        applicant=applicant,
        application=application,
        applicant_skills=applicant_skills
    )


@main.route("/applications/<int:application_id>/select", methods=["POST"])
@login_required
@user_only_required
def select_applicant(application_id):
    application = Application.query.get_or_404(application_id)
    help_request = application.help_request

    if help_request.requester_id != current_user.id:
        abort(403)

    if help_request.status in ["In Progress", "Completed"]:
        flash("You can no longer select a candidate for this request.", "warning")
        return redirect(url_for("main.view_request_applications", request_id=help_request.id))

    if application.status != "Applied":
        flash("This applicant is not available for selection.", "warning")
        return redirect(url_for("main.view_request_applications", request_id=help_request.id))

    previous_selected = Application.query.filter_by(
        help_request_id=help_request.id,
        status="Selected"
    ).all()

    for prev in previous_selected:
        prev.status = "Applied"

    application.status = "Selected"
    help_request.status = "Awaiting Candidate Response"
    help_request.selected_application_id = application.id

    db.session.commit()

    create_notification(
        application.applicant_id,
        f'You were selected for help request "{help_request.title}". Please accept or decline.',
        "request_selection",
        url_for("main.respond_to_selection", application_id=application.id)
    )

    send_platform_email(
        application.applicant.email,
        f"You were selected for: {help_request.title}",
        f"""Hello {application.applicant.full_name},

You were selected for the help request "{help_request.title}".

Please log in to SkillsInn to accept or decline this selection.
"""
    )

    flash("Applicant selected successfully. Waiting for their response.", "success")
    return redirect(url_for("main.view_request_applications", request_id=help_request.id))


@main.route("/applications/<int:application_id>/respond", methods=["GET", "POST"])
@login_required
@user_only_required
def respond_to_selection(application_id):
    application = Application.query.get_or_404(application_id)
    help_request = application.help_request

    if application.applicant_id != current_user.id:
        abort(403)

    if application.status != "Selected":
        flash("This application is not awaiting your response.", "warning")
        return redirect(url_for("main.my_applications"))

    form = ApplicationResponseForm()
    conflict_info = build_conflict_info(current_user, help_request, exclude_help_request_id=help_request.id)

    if form.validate_on_submit():
        decision = form.decision.data

        if decision == "Accepted":
            if conflict_info.get("has_conflict"):
                flash("You cannot accept this request because it overlaps with another accepted request in your calendar.", "danger")
                return render_template(
                    "respond_selection.html",
                    form=form,
                    application=application,
                    help_request=help_request,
                    conflict_info=conflict_info
                )

            application.status = "Accepted"
            application.decline_reason = None
            application.decline_reason_details = None
            application.responded_at = datetime.utcnow()

            help_request.status = "In Progress"
            help_request.selected_application_id = application.id

            collaboration, collaboration_created = get_or_create_collaboration(help_request, application)
            db.session.commit()

            if collaboration_created:
                create_system_message(
                    collaboration,
                    f'Collaboration started for "{help_request.title}". Use this space to discuss the work and agree on the next steps.'
                )
                db.session.commit()

            collaboration_link = url_for("main.collaboration_detail", collaboration_id=collaboration.id)

            create_notification(
                help_request.requester_id,
                f'Your selected applicant accepted the help request "{help_request.title}". Collaboration is now open.',
                "request_accepted",
                collaboration_link
            )

            create_notification(
                application.applicant_id,
                f'Your collaboration for "{help_request.title}" is now active.',
                "collaboration_started",
                collaboration_link
            )

            send_platform_email(
                help_request.requester.email,
                f"Applicant accepted: {help_request.title}",
                f"""Hello {help_request.requester.full_name},

Your selected applicant has accepted the help request "{help_request.title}".

The request is now in progress and the collaboration space is ready.
"""
            )

            flash("You accepted the selection successfully.", "success")
            if collaboration_created:
                flash("Your collaboration workspace is now ready.", "info")
            return redirect(url_for("main.my_applications"))

        if not form.decline_reason.data:
            flash("Please select a reason for declining.", "danger")
            return render_template(
                "respond_selection.html",
                form=form,
                application=application,
                help_request=help_request,
                conflict_info=conflict_info
            )

        if form.decline_reason.data == "Other":
            if not form.other_decline_reason.data or not form.other_decline_reason.data.strip():
                flash("Please specify your reason for declining.", "danger")
                return render_template(
                    "respond_selection.html",
                    form=form,
                    application=application,
                    help_request=help_request,
                    conflict_info=conflict_info
                )
            decline_reason_text = "Other"
            decline_reason_details = form.other_decline_reason.data.strip()
            requester_reason_text = f"Other - {decline_reason_details}"
        else:
            decline_reason_text = form.decline_reason.data
            decline_reason_details = None
            requester_reason_text = decline_reason_text

        application.status = "Declined"
        application.decline_reason = decline_reason_text
        application.decline_reason_details = decline_reason_details
        application.responded_at = datetime.utcnow()

        if help_request.selected_application_id == application.id:
            help_request.selected_application_id = None
            help_request.status = "Under Review"

        db.session.commit()

        create_notification(
            help_request.requester_id,
            f'Your selected applicant declined the help request "{help_request.title}". Reason: {requester_reason_text}',
            "request_declined",
            url_for("main.view_request_applications", request_id=help_request.id)
        )

        send_platform_email(
            help_request.requester.email,
            f"Applicant declined: {help_request.title}",
            f"""Hello {help_request.requester.full_name},

Your selected applicant declined the help request "{help_request.title}".

Reason: {requester_reason_text}

You can log in to SkillsInn and select another applicant.
"""
        )

        flash("You declined the selection.", "info")
        return redirect(url_for("main.my_applications"))

    return render_template(
        "respond_selection.html",
        form=form,
        application=application,
        help_request=help_request,
        conflict_info=conflict_info
    )



def get_flagged_message_context(message, limit_before=3, limit_after=3):
    if not message:
        return []

    collaboration_messages = (
        Message.query
        .filter_by(collaboration_id=message.collaboration_id, is_system_message=False)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )

    target_index = next((index for index, item in enumerate(collaboration_messages) if item.id == message.id), None)
    if target_index is None:
        return [message] if not message.is_system_message else []

    start = max(0, target_index - limit_before)
    end = min(len(collaboration_messages), target_index + limit_after + 1)
    return collaboration_messages[start:end]


@main.route("/messages/<int:message_id>/flag", methods=["POST"])
@login_required
@user_only_required
def flag_collaboration_message(message_id):
    message = Message.query.get_or_404(message_id)
    collaboration = message.collaboration

    if not collaboration or not collaboration.user_can_access(current_user):
        abort(403)

    if not message.can_be_flagged_by(current_user):
        flash("You cannot flag this message.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=message.collaboration_id))

    existing_flag = message.existing_flag_by_user(current_user)
    if existing_flag:
        flash("You have already flagged this message.", "info")
        return redirect(url_for("main.collaboration_detail", collaboration_id=message.collaboration_id))

    reason_category = (request.form.get("reason_category") or "").strip()
    details = (request.form.get("details") or "").strip()

    if reason_category not in MessageFlag.REASON_LABELS:
        flash("Please select a valid reason for flagging this message.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=message.collaboration_id))

    if len(details) > 1000:
        flash("Additional details are too long. Please keep them under 1000 characters.", "warning")
        return redirect(url_for("main.collaboration_detail", collaboration_id=message.collaboration_id))

    flag = MessageFlag(
        message_id=message.id,
        collaboration_id=message.collaboration_id,
        reporter_id=current_user.id,
        reported_user_id=message.sender_id,
        reason_category=reason_category,
        details=details or None,
        status="Pending",
    )
    db.session.add(flag)
    db.session.commit()

    flash("Message flagged successfully. An admin will review it.", "success")
    return redirect(url_for("main.collaboration_detail", collaboration_id=message.collaboration_id))


@main.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_skills = Skill.query.count()
    pending_count = Skill.query.filter_by(verification_status="Awaiting Verification").count()
    verified_count = Skill.query.filter_by(verification_status="Verified").count()
    rejected_count = Skill.query.filter_by(verification_status="Rejected").count()
    viewed_pending_count = Skill.query.filter_by(
        verification_status="Awaiting Verification",
        certificate_viewed_by_admin=True,
    ).count()
    unviewed_pending_count = Skill.query.filter_by(
        verification_status="Awaiting Verification",
        certificate_viewed_by_admin=False,
    ).count()
    pending_flag_count = MessageFlag.query.filter_by(status="Pending").count()
    reviewed_flag_count = MessageFlag.query.filter(MessageFlag.status.in_(["Reviewed", "Dismissed"])).count()

    recent_pending = (
        Skill.query
        .filter_by(verification_status="Awaiting Verification")
        .order_by(Skill.created_at.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_skills=total_skills,
        pending_count=pending_count,
        verified_count=verified_count,
        rejected_count=rejected_count,
        viewed_pending_count=viewed_pending_count,
        unviewed_pending_count=unviewed_pending_count,
        recent_pending=recent_pending,
        pending_flag_count=pending_flag_count,
        reviewed_flag_count=reviewed_flag_count,
    )


def compute_flag_outcome(is_report_valid, violates_guidelines, severity_level, is_targeted_abuse, is_repeat_behavior, creates_safety_risk):
    if not is_report_valid or not violates_guidelines:
        return "No Violation"

    if creates_safety_risk or severity_level == "Severe" or (is_targeted_abuse and is_repeat_behavior):
        return "Temporary Messaging Restriction"

    if severity_level == "Moderate" or is_repeat_behavior or is_targeted_abuse:
        return "Final Warning"

    return "Warning"


def create_messaging_restriction_if_needed(user_id, outcome_label, reason_category, source_flag_id, created_by_id):
    if outcome_label != "Temporary Messaging Restriction":
        return None

    existing = (
        UserRestriction.query
        .filter_by(user_id=user_id, restriction_type="messaging", is_active=True)
        .order_by(UserRestriction.created_at.desc())
        .first()
    )
    if existing and existing.is_currently_active():
        return existing

    restriction = UserRestriction(
        user_id=user_id,
        created_by_id=created_by_id,
        source_flag_id=source_flag_id,
        restriction_type="messaging",
        outcome_label=outcome_label,
        reason_category=reason_category,
        starts_at=datetime.utcnow(),
        ends_at=datetime.utcnow() + timedelta(days=7),
        is_active=True,
    )
    db.session.add(restriction)
    return restriction

@main.route("/admin/message-flags")
@login_required
@admin_required
def admin_message_flags():
    status_filter = request.args.get("status", "Pending")

    query = MessageFlag.query.order_by(MessageFlag.created_at.desc())
    if status_filter != "All":
        query = query.filter_by(status=status_filter)

    flags = query.all()
    return render_template("admin_message_flags.html", flags=flags, status_filter=status_filter)


@main.route("/admin/message-flags/<int:flag_id>")
@login_required
@admin_required
def admin_message_flag_detail(flag_id):
    message_flag = MessageFlag.query.get_or_404(flag_id)
    context_messages = get_flagged_message_context(message_flag.message)
    return render_template("admin_message_flag_detail.html", message_flag=message_flag, context_messages=context_messages)


@main.route("/admin/message-flags/<int:flag_id>/review", methods=["POST"])
@login_required
@admin_required
def review_message_flag(flag_id):
    message_flag = MessageFlag.query.get_or_404(flag_id)

    if message_flag.status != "Pending":
        flash("This flagged message has already been reviewed.", "info")
        return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))

    admin_notes = (request.form.get("admin_notes") or "").strip()
    valid_answer = (request.form.get("is_report_valid") or "").strip()

    if valid_answer not in ["Yes", "No"]:
        flash("Please answer whether the report is valid.", "danger")
        return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))

    is_report_valid = valid_answer == "Yes"

    if not is_report_valid:
        violates_guidelines = False
        severity_level = "Low"
        is_targeted_abuse = False
        is_repeat_behavior = False
        creates_safety_risk = False
    else:
        violates_answer = (request.form.get("violates_guidelines") or "").strip()
        severity_level = (request.form.get("severity_level") or "").strip()
        targeted_answer = (request.form.get("is_targeted_abuse") or "").strip()
        repeat_answer = (request.form.get("is_repeat_behavior") or "").strip()
        risk_answer = (request.form.get("creates_safety_risk") or "").strip()

        if violates_answer not in ["Yes", "No"]:
            flash("Please answer whether the message violates community guidelines.", "danger")
            return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))
        if severity_level not in ["Low", "Moderate", "Severe"]:
            flash("Please select the message severity.", "danger")
            return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))
        if targeted_answer not in ["Yes", "No"]:
            flash("Please answer whether the message is targeted abuse.", "danger")
            return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))
        if repeat_answer not in ["Yes", "No"]:
            flash("Please answer whether this appears to be repeated behaviour.", "danger")
            return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))
        if risk_answer not in ["Yes", "No"]:
            flash("Please answer whether the message creates a trust or safety risk.", "danger")
            return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))

        violates_guidelines = violates_answer == "Yes"
        is_targeted_abuse = targeted_answer == "Yes"
        is_repeat_behavior = repeat_answer == "Yes"
        creates_safety_risk = risk_answer == "Yes"

    computed_outcome = compute_flag_outcome(
        is_report_valid,
        violates_guidelines,
        severity_level,
        is_targeted_abuse,
        is_repeat_behavior,
        creates_safety_risk,
    )

    review_result = "Violation Confirmed" if computed_outcome != "No Violation" else "No Violation"

    moderation_review = ModerationReview(
        flag_id=message_flag.id,
        reviewed_by_id=current_user.id,
        is_report_valid=is_report_valid,
        violates_guidelines=violates_guidelines,
        severity_level=severity_level,
        is_targeted_abuse=is_targeted_abuse,
        is_repeat_behavior=is_repeat_behavior,
        creates_safety_risk=creates_safety_risk,
        computed_outcome=computed_outcome,
        admin_notes=admin_notes or None,
    )
    db.session.add(moderation_review)

    message_flag.review_result = review_result
    message_flag.status = "Reviewed" if review_result == "Violation Confirmed" else "Dismissed"
    message_flag.admin_notes = admin_notes or None
    message_flag.reviewed_by_id = current_user.id
    message_flag.reviewed_at = datetime.utcnow()

    create_messaging_restriction_if_needed(
        user_id=message_flag.reported_user_id,
        outcome_label=computed_outcome,
        reason_category=message_flag.reason_category,
        source_flag_id=message_flag.id,
        created_by_id=current_user.id,
    )

    if review_result == "Violation Confirmed":
        user_notice = "A message you sent in a collaboration chat was reviewed and found to violate community guidelines."
        if computed_outcome == "Warning":
            user_notice += " A warning has been recorded on your dashboard."
        elif computed_outcome == "Final Warning":
            user_notice += " A final warning has been recorded on your dashboard."
        elif computed_outcome == "Temporary Messaging Restriction":
            user_notice += " A temporary messaging restriction has been applied to your account."

        create_notification(
            message_flag.reported_user_id,
            user_notice,
            "moderation_warning",
            url_for("main.collaboration_detail", collaboration_id=message_flag.collaboration_id),
        )
        create_notification(
            message_flag.reporter_id,
            f"Your flagged collaboration message was reviewed. Outcome: {computed_outcome}.",
            "moderation_update",
            url_for("main.collaboration_detail", collaboration_id=message_flag.collaboration_id),
        )
    else:
        create_notification(
            message_flag.reporter_id,
            "Your flagged collaboration message was reviewed and no violation was found.",
            "moderation_update",
            url_for("main.collaboration_detail", collaboration_id=message_flag.collaboration_id),
        )

    db.session.commit()
    flash(f"Flag review saved. System outcome: {computed_outcome}.", "success")
    return redirect(url_for("main.admin_message_flag_detail", flag_id=message_flag.id))


@main.route("/admin/verifications")
@login_required
@admin_required
def admin_verifications():
    status_filter = request.args.get("status", "Awaiting Verification")

    if status_filter == "All":
        skill_list = Skill.query.filter(Skill.certificate_file.isnot(None)).order_by(Skill.created_at.desc()).all()
    else:
        skill_list = (
            Skill.query
            .filter(Skill.certificate_file.isnot(None), Skill.verification_status == status_filter)
            .order_by(Skill.created_at.desc())
            .all()
        )

    viewed_pending_count = Skill.query.filter_by(
        verification_status="Awaiting Verification",
        certificate_viewed_by_admin=True,
    ).count()
    unviewed_pending_count = Skill.query.filter_by(
        verification_status="Awaiting Verification",
        certificate_viewed_by_admin=False,
    ).count()

    return render_template(
        "admin_verifications.html",
        skills=skill_list,
        status_filter=status_filter,
        viewed_pending_count=viewed_pending_count,
        unviewed_pending_count=unviewed_pending_count,
    )


@main.route("/admin/skills/<int:skill_id>")
@login_required
@admin_required
def admin_skill_detail(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    form = RejectVerificationForm()
    certificate_url = url_for("static", filename=skill.certificate_file) if skill.certificate_file else None
    return render_template("admin_skill_detail.html", skill=skill, form=form, certificate_url=certificate_url)


@main.route("/admin/skills/<int:skill_id>/view-certificate")
@login_required
@admin_required
def view_skill_certificate(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if not skill.certificate_file:
        flash("No certificate was uploaded for this skill.", "danger")
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    if not skill.certificate_viewed_by_admin:
        skill.certificate_viewed_by_admin = True
        skill.certificate_viewed_at = datetime.utcnow()
        db.session.commit()
        flash("Certificate marked as viewed. You can now record an approval or rejection.", "success")

    certificate_url = url_for("static", filename=skill.certificate_file)
    return render_template("admin_certificate_viewer.html", skill=skill, certificate_url=certificate_url)


@main.route("/admin/skills/<int:skill_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_skill_verification(skill_id):
    skill = Skill.query.get_or_404(skill_id)

    if not skill.certificate_file:
        flash("No certificate was uploaded for this skill.", "danger")
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    if not skill.certificate_viewed_by_admin:
        flash("View the uploaded certificate before approving this skill.", "warning")
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    skill.verification_status = "Verified"
    skill.verification_note = "Approved by admin after certificate review"
    skill.verified_at = datetime.utcnow()

    db.session.commit()

    create_notification(
        skill.user_id,
        f'Your skill "{skill.title}" certification was approved.',
        "verification_success",
        url_for("main.skill_detail", skill_id=skill.id)
    )

    flash("Skill certification approved successfully.", "success")
    return redirect(url_for("main.admin_verifications", status="Awaiting Verification"))


@main.route("/admin/skills/<int:skill_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_skill_verification(skill_id):
    skill = Skill.query.get_or_404(skill_id)
    form = RejectVerificationForm()

    if not skill.certificate_file:
        flash("No certificate was uploaded for this skill.", "danger")
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    if not skill.certificate_viewed_by_admin:
        flash("View the uploaded certificate before rejecting this skill.", "warning")
        return redirect(url_for("main.admin_skill_detail", skill_id=skill.id))

    if form.validate_on_submit():
        skill.verification_status = "Rejected"
        skill.verification_note = form.verification_note.data.strip()
        skill.verified_at = datetime.utcnow()

        db.session.commit()

        create_notification(
            skill.user_id,
            f'Your skill "{skill.title}" certification was rejected. Reason: {skill.verification_note}',
            "verification_rejected",
            url_for("main.skill_detail", skill_id=skill.id)
        )

        flash("Skill certification rejected.", "warning")
        return redirect(url_for("main.admin_verifications", status="Awaiting Verification"))

    certificate_url = url_for("static", filename=skill.certificate_file) if skill.certificate_file else None
    return render_template("admin_skill_detail.html", skill=skill, form=form, certificate_url=certificate_url)


@main.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    silent = _parse_bool(request.values.get("silent"))
    logout_user()
    if silent:
        return ("", 204)
    flash("You have been logged out.", "info")
    return redirect(url_for("main.home"))