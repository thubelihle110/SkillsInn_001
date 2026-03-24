from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from authlib.integrations.flask_client import OAuth
from sqlalchemy import inspect, text


db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
oauth = OAuth()

login_manager.login_view = "main.login"
login_manager.login_message_category = "warning"


def register_oauth_clients(app):
    google_client_id = app.config.get("GOOGLE_CLIENT_ID")
    google_client_secret = app.config.get("GOOGLE_CLIENT_SECRET")
    facebook_client_id = app.config.get("FACEBOOK_CLIENT_ID")
    facebook_client_secret = app.config.get("FACEBOOK_CLIENT_SECRET")

    if google_client_id and google_client_secret:
        oauth.register(
            name="google",
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    if facebook_client_id and facebook_client_secret:
        oauth.register(
            name="facebook",
            client_id=facebook_client_id,
            client_secret=facebook_client_secret,
            access_token_url="https://graph.facebook.com/v22.0/oauth/access_token",
            authorize_url="https://www.facebook.com/v22.0/dialog/oauth",
            api_base_url="https://graph.facebook.com/v22.0/",
            client_kwargs={"scope": "email public_profile"},
        )


def ensure_learning_hub_schema():
    inspector = inspect(db.engine)
    if not inspector.has_table("skills"):
        return

    alter_statements = []

    skill_columns = {column["name"] for column in inspector.get_columns("skills")}
    if "skill_level" not in skill_columns:
        alter_statements.append("ALTER TABLE skills ADD COLUMN skill_level VARCHAR(30) DEFAULT 'Beginner' NOT NULL")
    if "source" not in skill_columns:
        alter_statements.append("ALTER TABLE skills ADD COLUMN source VARCHAR(30) DEFAULT 'manual' NOT NULL")
    if "earned_course_id" not in skill_columns:
        alter_statements.append("ALTER TABLE skills ADD COLUMN earned_course_id INTEGER")
    if "earned_at" not in skill_columns:
        alter_statements.append("ALTER TABLE skills ADD COLUMN earned_at DATETIME")

    if inspector.has_table("course_enrollments"):
        enrollment_columns = {column["name"] for column in inspector.get_columns("course_enrollments")}
        if "final_exam_score" not in enrollment_columns:
            alter_statements.append("ALTER TABLE course_enrollments ADD COLUMN final_exam_score INTEGER")
        if "final_exam_passed" not in enrollment_columns:
            alter_statements.append("ALTER TABLE course_enrollments ADD COLUMN final_exam_passed BOOLEAN DEFAULT 0 NOT NULL")
        if "final_exam_passed_at" not in enrollment_columns:
            alter_statements.append("ALTER TABLE course_enrollments ADD COLUMN final_exam_passed_at DATETIME")

    if inspector.has_table("chapter_progress"):
        progress_columns = {column["name"] for column in inspector.get_columns("chapter_progress")}
        if "content_viewed_at" not in progress_columns:
            alter_statements.append("ALTER TABLE chapter_progress ADD COLUMN content_viewed_at DATETIME")
        if "quiz_score" not in progress_columns:
            alter_statements.append("ALTER TABLE chapter_progress ADD COLUMN quiz_score INTEGER")
        if "quiz_passed" not in progress_columns:
            alter_statements.append("ALTER TABLE chapter_progress ADD COLUMN quiz_passed BOOLEAN DEFAULT 0 NOT NULL")
        if "quiz_passed_at" not in progress_columns:
            alter_statements.append("ALTER TABLE chapter_progress ADD COLUMN quiz_passed_at DATETIME")

    if inspector.has_table("courses"):
        course_columns = {column["name"] for column in inspector.get_columns("courses")}
        if "final_exam_duration_minutes" not in course_columns:
            alter_statements.append("ALTER TABLE courses ADD COLUMN final_exam_duration_minutes INTEGER")
        if "final_exam_attempt_limit" not in course_columns:
            alter_statements.append("ALTER TABLE courses ADD COLUMN final_exam_attempt_limit INTEGER")

    if inspector.has_table("chapter_quiz_questions"):
        quiz_columns = {column["name"] for column in inspector.get_columns("chapter_quiz_questions")}
        if "question_type" not in quiz_columns:
            alter_statements.append("ALTER TABLE chapter_quiz_questions ADD COLUMN question_type VARCHAR(30) DEFAULT 'mcq' NOT NULL")

    if inspector.has_table("final_exam_questions"):
        exam_columns = {column["name"] for column in inspector.get_columns("final_exam_questions")}
        if "question_type" not in exam_columns:
            alter_statements.append("ALTER TABLE final_exam_questions ADD COLUMN question_type VARCHAR(30) DEFAULT 'mcq' NOT NULL")

    for statement in alter_statements:
        db.session.execute(text(statement))

    if inspector.has_table("skills"):
        db.session.execute(text("UPDATE skills SET skill_level = CASE WHEN experience_level IN ('Advanced', 'Professional') THEN 'Advanced' WHEN experience_level = 'Intermediate' THEN 'Intermediate' ELSE 'Beginner' END WHERE skill_level IS NULL OR skill_level = ''"))
        db.session.execute(text("UPDATE skills SET source = 'manual' WHERE source IS NULL OR source = ''"))
        db.session.execute(text("UPDATE skills SET verification_status = 'Verified' WHERE verification_status = 'Approved'"))
        db.session.execute(text("UPDATE skills SET verification_status = 'Rejected' WHERE verification_status = 'Declined'"))

    db.session.commit()



def create_default_admins(app):
    from app.models import User

    created_any = False

    for admin_data in app.config["DEFAULT_ADMINS"]:
        existing_admin = User.query.filter_by(email=admin_data["email"]).first()

        if not existing_admin:
            admin_user = User(
                full_name=admin_data["name"],
                email=admin_data["email"],
                phone=None,
                role="admin",
                must_change_credentials=True,
                is_default_admin=True,
            )
            admin_user.set_password(admin_data["password"])
            db.session.add(admin_user)
            created_any = True

    if created_any:
        db.session.commit()
        print("Default admin accounts created successfully.")
    else:
        print("Default admin accounts already exist.")


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object("config.Config")

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    oauth.init_app(app)
    register_oauth_clients(app)

    from app.routes import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()
        ensure_learning_hub_schema()
        create_default_admins(app)

    import os
    for folder in ["profiles", "resumes", "certificates", "application_resumes", "learning_content", "learning_assignments/briefs", "learning_assignments/submissions"]:
        os.makedirs(os.path.join(app.static_folder, "uploads", folder), exist_ok=True)

    return app
