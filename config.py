import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///skillsinn.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "auto")

    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "True").lower() == "true"
    MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "False").lower() == "true"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or os.environ.get("MAIL_USERNAME")

    RESEND_API_KEY = os.environ.get("re_4zFzYDWq_PCJfXpDXt1y2txLxipWyv3Yk")
    RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    RESEND_FROM_NAME = os.environ.get("RESEND_FROM_NAME", "SkillsInn")

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join("app", "static", "uploads")

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
    FACEBOOK_CLIENT_ID = os.environ.get("FACEBOOK_CLIENT_ID")
    FACEBOOK_CLIENT_SECRET = os.environ.get("FACEBOOK_CLIENT_SECRET")

    DEFAULT_ADMINS = [
        {
            "name": "System Admin 1",
            "email": "admin1@skillsinn.com",
            "password": "AdminAdmin",
        },
        {
            "name": "System Admin 2",
            "email": "admin2@skillsinn.com",
            "password": "Admin2@123",
        },
        {
            "name": "System Admin 3",
            "email": "admin3@skillsinn.com",
            "password": "Admin3@123",
        },
    ]