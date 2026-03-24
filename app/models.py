from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer

from app import db, login_manager


LEARNING_HUB_LEVELS = ("Beginner", "Intermediate", "Advanced")


SOUTH_AFRICA_TZ = ZoneInfo("Africa/Johannesburg")


def _to_sa_time(value):
    if not value:
        return None
    # Existing rows are treated as UTC when stored as naive datetimes.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SOUTH_AFRICA_TZ)


def _format_local_datetime(value, fmt="%d %b %Y, %H:%M"):
    local_value = _to_sa_time(value)
    if not local_value:
        return None
    return local_value.strftime(fmt)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), default="user", nullable=False)

    must_change_credentials = db.Column(db.Boolean, default=False, nullable=False)
    is_default_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_verified_at = db.Column(db.DateTime, nullable=True)

    bio = db.Column(db.Text, nullable=True)
    street_address = db.Column(db.String(200), nullable=True)
    suburb = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    postal_code = db.Column(db.String(20), nullable=True)

    availability = db.Column(db.String(50), nullable=True)
    experience_level = db.Column(db.String(50), nullable=True)
    preferred_contact_method = db.Column(db.String(50), nullable=True)
    portfolio_link = db.Column(db.String(255), nullable=True)

    profile_picture = db.Column(db.String(255), nullable=True)
    resume_file = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    skills = db.relationship("Skill", backref="owner", lazy=True, cascade="all, delete-orphan")
    notifications = db.relationship("Notification", backref="user", lazy=True, cascade="all, delete-orphan")
    help_requests = db.relationship("HelpRequest", backref="requester", lazy=True, cascade="all, delete-orphan")
    applications = db.relationship("Application", backref="applicant", lazy=True, cascade="all, delete-orphan")
    requested_collaborations = db.relationship("Collaboration", foreign_keys="Collaboration.requester_id", backref="requester_user", lazy=True, cascade="all, delete-orphan")
    provided_collaborations = db.relationship("Collaboration", foreign_keys="Collaboration.provider_id", backref="provider_user", lazy=True, cascade="all, delete-orphan")
    message_flags_reported = db.relationship("MessageFlag", foreign_keys="MessageFlag.reporter_id", backref="reporter", lazy=True, cascade="all, delete-orphan")
    message_flags_received = db.relationship("MessageFlag", foreign_keys="MessageFlag.reported_user_id", backref="reported_user", lazy=True, cascade="all, delete-orphan")
    message_flags_reviewed = db.relationship("MessageFlag", foreign_keys="MessageFlag.reviewed_by_id", backref="reviewed_by", lazy=True)
    moderation_reviews_completed = db.relationship("ModerationReview", foreign_keys="ModerationReview.reviewed_by_id", backref="reviewer", lazy=True)
    active_restrictions = db.relationship("UserRestriction", foreign_keys="UserRestriction.user_id", backref="restricted_user", lazy=True, cascade="all, delete-orphan")
    issued_restrictions = db.relationship("UserRestriction", foreign_keys="UserRestriction.created_by_id", backref="created_by", lazy=True)
    ratings_given = db.relationship("CollaborationRating", foreign_keys="CollaborationRating.rater_id", backref="rater", lazy=True, cascade="all, delete-orphan")
    ratings_received = db.relationship("CollaborationRating", foreign_keys="CollaborationRating.ratee_id", backref="ratee", lazy=True, cascade="all, delete-orphan")
    social_accounts = db.relationship("SocialAccount", backref="user", lazy=True, cascade="all, delete-orphan")
    created_courses = db.relationship("Course", foreign_keys="Course.created_by_user_id", backref="creator", lazy=True, cascade="all, delete-orphan")
    submitted_teach_applications = db.relationship("TeachApplication", foreign_keys="TeachApplication.user_id", backref="applicant", lazy=True, cascade="all, delete-orphan")
    reviewed_teach_applications = db.relationship("TeachApplication", foreign_keys="TeachApplication.reviewed_by_id", backref="reviewer", lazy=True)
    teaching_permissions = db.relationship("TeachingPermission", foreign_keys="TeachingPermission.user_id", backref="teacher", lazy=True, cascade="all, delete-orphan")
    published_courses = db.relationship("Course", foreign_keys="Course.published_by_id", backref="publisher", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def has_password(self):
        return bool(self.password_hash)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def get_reset_token(self, secret_key):
        serializer = URLSafeTimedSerializer(secret_key)
        return serializer.dumps(self.email, salt="password-reset-salt")

    @staticmethod
    def verify_reset_token(token, secret_key, max_age=3600):
        serializer = URLSafeTimedSerializer(secret_key)
        try:
            email = serializer.loads(
                token,
                salt="password-reset-salt",
                max_age=max_age
            )
        except Exception:
            return None

        return User.query.filter_by(email=email).first()

    def get_email_verification_token(self, secret_key):
        serializer = URLSafeTimedSerializer(secret_key)
        return serializer.dumps(self.email, salt="email-verification-salt")

    @staticmethod
    def verify_email_verification_token(token, secret_key, max_age=86400):
        serializer = URLSafeTimedSerializer(secret_key)
        try:
            email = serializer.loads(
                token,
                salt="email-verification-salt",
                max_age=max_age
            )
        except Exception:
            return None

        return User.query.filter_by(email=email).first()

    def email_verified_at_display(self):
        return _format_local_datetime(self.email_verified_at)

    def profile_completion_percentage(self):
        score = 0

        if self.full_name:
            score += 10
        if self.email:
            score += 10
        if self.phone:
            score += 10
        if self.bio:
            score += 10
        if self.street_address and self.suburb and self.city:
            score += 15
        if self.profile_picture:
            score += 15
        if self.resume_file:
            score += 15
        if self.availability:
            score += 10
        if self.preferred_contact_method:
            score += 5

        return score

    def missing_profile_items(self):
        missing = []

        if not self.phone:
            missing.append("Phone number")
        if not self.bio:
            missing.append("Short bio")
        if not (self.street_address and self.suburb and self.city):
            missing.append("Address details")
        if not self.profile_picture:
            missing.append("Profile picture")
        if not self.resume_file:
            missing.append("Resume / CV")
        if not self.availability:
            missing.append("Availability")
        if not self.preferred_contact_method:
            missing.append("Preferred contact method")

        return missing

    def active_messaging_restriction(self):
        now = datetime.utcnow()
        for restriction in self.active_restrictions:
            if restriction.restriction_type == "messaging" and restriction.is_currently_active(now):
                return restriction
        return None

    def is_messaging_restricted(self):
        return self.active_messaging_restriction() is not None

    def received_ratings(self):
        return sorted(self.ratings_received, key=lambda item: item.created_at or datetime.min, reverse=True)

    def rating_count_received(self):
        return len(self.ratings_received)

    def average_rating_received(self):
        if not self.ratings_received:
            return None
        total = sum(item.overall_rating for item in self.ratings_received if item.overall_rating)
        count = len([item for item in self.ratings_received if item.overall_rating])
        if count == 0:
            return None
        return round(total / count, 1)

    def average_provider_rating_received(self):
        provider_ratings = [item.overall_rating for item in self.ratings_received if item.ratee_role == "provider" and item.overall_rating]
        if not provider_ratings:
            return None
        return round(sum(provider_ratings) / len(provider_ratings), 1)

    def average_requester_rating_received(self):
        requester_ratings = [item.overall_rating for item in self.ratings_received if item.ratee_role == "requester" and item.overall_rating]
        if not requester_ratings:
            return None
        return round(sum(requester_ratings) / len(requester_ratings), 1)

    def provider_rating_count_received(self):
        return len([item for item in self.ratings_received if item.ratee_role == "provider"])

    def requester_rating_count_received(self):
        return len([item for item in self.ratings_received if item.ratee_role == "requester"])

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def __repr__(self):
        return f"<User {self.email}>"


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    category = db.Column(db.String(100), nullable=False)
    custom_category = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    experience_level = db.Column(db.String(50), nullable=False)
    availability = db.Column(db.String(50), nullable=False)
    skill_level = db.Column(db.String(30), default="Beginner", nullable=False)
    source = db.Column(db.String(30), default="manual", nullable=False)
    earned_course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    earned_at = db.Column(db.DateTime, nullable=True)

    certificate_file = db.Column(db.String(255), nullable=True)
    verification_status = db.Column(db.String(30), default="Not Submitted", nullable=False)
    verification_note = db.Column(db.Text, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    certificate_viewed_by_admin = db.Column(db.Boolean, default=False, nullable=False)
    certificate_viewed_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), default="Active", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def display_category(self):
        if self.category == "Other" and self.custom_category:
            return self.custom_category
        return self.category

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def normalized_skill_level(self):
        mapping = {
            "Beginner": "Beginner",
            "Intermediate": "Intermediate",
            "Advanced": "Advanced",
            "Professional": "Advanced",
        }
        return mapping.get(self.skill_level or self.experience_level or "Beginner", "Beginner")

    def highest_teaching_level(self):
        normalized = self.normalized_skill_level()
        if normalized == "Intermediate":
            return "Intermediate"
        if normalized == "Advanced":
            return "Advanced"
        return None

    def can_apply_to_teach(self):
        return self.normalized_skill_level() in {"Intermediate", "Advanced"}

    def earned_at_display(self):
        return _format_local_datetime(self.earned_at)

    def verified_at_display(self):
        return _format_local_datetime(self.verified_at)

    def certificate_viewed_at_display(self):
        return _format_local_datetime(self.certificate_viewed_at)

    def review_stage_label(self):
        if self.verification_status == "Approved":
            return "Approved"

        if self.verification_status == "Declined":
            return "Declined"

        if self.certificate_viewed_by_admin:
            return "Viewed · Awaiting decision"

        if self.certificate_file:
            return "Pending certificate review"

        return "No certificate submitted"

    def review_stage_badge_class(self):
        if self.verification_status == "Approved":
            return "success"

        if self.verification_status == "Declined":
            return "danger"

        if self.certificate_viewed_by_admin:
            return "warning"

        if self.certificate_file:
            return "secondary"

        return "light text-dark"

    def is_learning_hub_skill(self):
        return (self.source or "").strip().lower() == "learning_hub"

    def can_be_edited_by_owner(self):
        return not self.is_learning_hub_skill()

    def display_badge_label(self):
        if self.is_learning_hub_skill():
            return "Learning Hub"
        if self.verification_status == "Verified":
            return "Verified skill"
        if self.verification_status == "Awaiting Verification":
            return "Submitted"
        if self.verification_status == "Rejected":
            return "Needs review"
        return "Profile skill"

    def display_badge_tone(self):
        if self.is_learning_hub_skill():
            return "gold"
        if self.verification_status in {"Verified", "Awaiting Verification", "Rejected"}:
            return "bronze"
        return "silver"

    def __repr__(self):
        return f"<Skill {self.title}>"


class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    published_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False)
    skill_name = db.Column(db.String(150), nullable=False)
    skill_category = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(30), nullable=False)
    pass_mark = db.Column(db.Integer, default=70, nullable=False)
    final_exam_duration_minutes = db.Column(db.Integer, nullable=True)
    final_exam_attempt_limit = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(30), default="Draft", nullable=False)
    review_note = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    skill = db.relationship("Skill", foreign_keys=[skill_id], backref=db.backref("teaching_courses", lazy=True))
    chapters = db.relationship("CourseChapter", backref="course", lazy=True, cascade="all, delete-orphan", order_by="CourseChapter.chapter_order")
    enrollments = db.relationship("CourseEnrollment", backref="course", lazy=True, cascade="all, delete-orphan")
    earned_skills = db.relationship("Skill", foreign_keys="Skill.earned_course_id", backref="earned_course", lazy=True)
    final_exam_questions = db.relationship("FinalExamQuestion", backref="course", lazy=True, cascade="all, delete-orphan", order_by="FinalExamQuestion.display_order")
    final_exam_attempts = db.relationship("FinalExamAttempt", backref="course", lazy=True, cascade="all, delete-orphan")
    assignments = db.relationship("CourseAssignment", backref="course", lazy=True, cascade="all, delete-orphan", order_by="CourseAssignment.due_at")

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def published_at_display(self):
        return _format_local_datetime(self.published_at)

    def is_published(self):
        return self.status == "Published"

    def chapter_count(self):
        return len(self.chapters)

    def required_chapters(self):
        return [chapter for chapter in self.chapters if chapter.is_required]

    def required_chapter_count(self):
        return len(self.required_chapters())

    def final_exam_question_count(self):
        return len(self.final_exam_questions)

    def attempts_limit_label(self):
        return "Unlimited" if not self.final_exam_attempt_limit else str(self.final_exam_attempt_limit)

    def get_enrollment_for(self, user_id):
        return CourseEnrollment.query.filter_by(course_id=self.id, user_id=user_id).first()


class CourseChapter(db.Model):
    __tablename__ = "course_chapters"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    chapter_order = db.Column(db.Integer, nullable=False, default=1)
    content = db.Column(db.Text, nullable=False)
    is_required = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    content_blocks = db.relationship("CourseContentBlock", backref="chapter", lazy=True, cascade="all, delete-orphan", order_by="CourseContentBlock.display_order")
    quiz_questions = db.relationship("ChapterQuizQuestion", backref="chapter", lazy=True, cascade="all, delete-orphan", order_by="ChapterQuizQuestion.display_order")
    quiz_attempts = db.relationship("ChapterQuizAttempt", backref="chapter", lazy=True, cascade="all, delete-orphan")

    def display_content_blocks(self):
        if self.content_blocks:
            return self.content_blocks
        if self.content:
            pseudo_block = type("PseudoBlock", (), {})()
            pseudo_block.block_type = "text"
            pseudo_block.title = "Notes"
            pseudo_block.text_content = self.content
            pseudo_block.media_url = None
            pseudo_block.external_url = None
            return [pseudo_block]
        return []

    def has_quiz(self):
        return len(self.quiz_questions) > 0


class CourseContentBlock(db.Model):
    __tablename__ = "course_content_blocks"

    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("course_chapters.id"), nullable=False)
    block_type = db.Column(db.String(30), nullable=False, default="text")
    title = db.Column(db.String(150), nullable=True)
    text_content = db.Column(db.Text, nullable=True)
    media_url = db.Column(db.String(500), nullable=True)
    external_url = db.Column(db.String(500), nullable=True)
    display_order = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def is_uploaded_file(self):
        return bool(self.media_url and self.media_url.startswith("uploads/"))


class ChapterQuizQuestion(db.Model):
    __tablename__ = "chapter_quiz_questions"

    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("course_chapters.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), default="mcq", nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def options(self):
        if self.question_type == "true_false":
            return [("A", self.option_a or "True"), ("B", self.option_b or "False")]
        return [("A", self.option_a), ("B", self.option_b), ("C", self.option_c), ("D", self.option_d)]


class ChapterQuizAttempt(db.Model):
    __tablename__ = "chapter_quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("course_enrollments.id"), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey("course_chapters.id"), nullable=False)
    score_percent = db.Column(db.Integer, nullable=False)
    is_passed = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("CourseEnrollment", backref=db.backref("chapter_quiz_attempts", lazy=True, cascade="all, delete-orphan"))


class FinalExamQuestion(db.Model):
    __tablename__ = "final_exam_questions"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), default="mcq", nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def options(self):
        if self.question_type == "true_false":
            return [("A", self.option_a or "True"), ("B", self.option_b or "False")]
        return [("A", self.option_a), ("B", self.option_b), ("C", self.option_c), ("D", self.option_d)]


class FinalExamAttempt(db.Model):
    __tablename__ = "final_exam_attempts"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("course_enrollments.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    score_percent = db.Column(db.Integer, nullable=False)
    is_passed = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    enrollment = db.relationship("CourseEnrollment", backref=db.backref("final_exam_attempts", lazy=True, cascade="all, delete-orphan"))


class CourseAssignment(db.Model):
    __tablename__ = "course_assignments"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    instructions = db.Column(db.Text, nullable=True)
    resource_file = db.Column(db.String(255), nullable=True)
    due_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    submissions = db.relationship("AssignmentSubmission", backref="assignment", lazy=True, cascade="all, delete-orphan")

    def due_at_display(self):
        return _format_local_datetime(self.due_at)

    def is_overdue(self):
        return bool(self.due_at and self.due_at < datetime.utcnow())


class AssignmentSubmission(db.Model):
    __tablename__ = "assignment_submissions"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("course_assignments.id"), nullable=False)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("course_enrollments.id"), nullable=False)
    submission_file = db.Column(db.String(255), nullable=False)
    submission_note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="Submitted", nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    feedback = db.Column(db.Text, nullable=True)

    enrollment = db.relationship("CourseEnrollment", backref=db.backref("assignment_submissions", lazy=True, cascade="all, delete-orphan"))

    def submitted_at_display(self):
        return _format_local_datetime(self.submitted_at)


class CourseEnrollment(db.Model):
    __tablename__ = "course_enrollments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    status = db.Column(db.String(30), default="Enrolled", nullable=False)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    final_exam_score = db.Column(db.Integer, nullable=True)
    final_exam_passed = db.Column(db.Boolean, default=False, nullable=False)
    final_exam_passed_at = db.Column(db.DateTime, nullable=True)

    learner = db.relationship("User", backref=db.backref("course_enrollments", lazy=True))
    progress_rows = db.relationship("ChapterProgress", backref="enrollment", lazy=True, cascade="all, delete-orphan")

    def enrolled_at_display(self):
        return _format_local_datetime(self.enrolled_at)

    def completed_at_display(self):
        return _format_local_datetime(self.completed_at)

    def progress_for_chapter(self, chapter_id):
        for row in self.progress_rows:
            if row.chapter_id == chapter_id:
                return row
        return None

    def completed_required_chapter_count(self):
        count = 0
        for chapter in self.course.required_chapters():
            progress = self.progress_for_chapter(chapter.id)
            if progress and progress.is_completed:
                count += 1
        return count

    def progress_percent(self):
        required_count = self.course.required_chapter_count()
        if required_count == 0:
            return 100 if self.final_exam_passed else 0
        return int(round((self.completed_required_chapter_count() / required_count) * 100))

    def all_required_chapters_completed(self):
        return self.completed_required_chapter_count() >= self.course.required_chapter_count() and self.course.required_chapter_count() > 0

    def next_unlocked_chapter(self):
        for chapter in self.course.chapters:
            progress = self.progress_for_chapter(chapter.id)
            if not progress or not progress.is_completed:
                return chapter
        return None

    def is_chapter_unlocked(self, chapter):
        for course_chapter in self.course.chapters:
            if course_chapter.chapter_order >= chapter.chapter_order:
                break
            progress = self.progress_for_chapter(course_chapter.id)
            if course_chapter.is_required and (not progress or not progress.is_completed):
                return False
        return True

    def submission_for_assignment(self, assignment_id):
        for submission in self.assignment_submissions:
            if submission.assignment_id == assignment_id:
                return submission
        return None

    def final_exam_attempt_count(self):
        return len(self.final_exam_attempts)

    def attempts_remaining(self):
        limit = self.course.final_exam_attempt_limit
        if not limit:
            return None
        remaining = limit - self.final_exam_attempt_count()
        return remaining if remaining > 0 else 0

    def can_take_final_exam(self):
        remaining = self.attempts_remaining()
        return remaining is None or remaining > 0


class ChapterProgress(db.Model):
    __tablename__ = "chapter_progress"

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("course_enrollments.id"), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey("course_chapters.id"), nullable=False)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    content_viewed_at = db.Column(db.DateTime, nullable=True)
    quiz_score = db.Column(db.Integer, nullable=True)
    quiz_passed = db.Column(db.Boolean, default=False, nullable=False)
    quiz_passed_at = db.Column(db.DateTime, nullable=True)

    chapter = db.relationship("CourseChapter", backref=db.backref("progress_rows", lazy=True))

    def completed_at_display(self):
        return _format_local_datetime(self.completed_at)


class TeachApplication(db.Model):
    __tablename__ = "teach_applications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False)
    application_reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    max_teaching_level = db.Column(db.String(30), nullable=True)
    review_note = db.Column(db.Text, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    skill = db.relationship("Skill", backref=db.backref("teach_applications", lazy=True))

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def reviewed_at_display(self):
        return _format_local_datetime(self.reviewed_at)


class TeachingPermission(db.Model):
    __tablename__ = "teaching_permissions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False)
    max_teaching_level = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), default="Approved", nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    skill = db.relationship("Skill", backref=db.backref("teaching_permissions", lazy=True))
    approver = db.relationship("User", foreign_keys=[approved_by_id], backref=db.backref("approved_teaching_permissions", lazy=True))

    def approved_at_display(self):
        return _format_local_datetime(self.approved_at)


def _split_csv_values(value):
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item and item.strip()]


def _ordinal_day(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _human_join(items):
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _monthly_ordinal_list(values):
    return [_ordinal_day(value) for value in _split_csv_values(values)]


def _monthly_days_summary(values, direct_limit=4):
    ordinals = _monthly_ordinal_list(values)
    if not ordinals:
        return "selected days"
    if len(ordinals) <= direct_limit:
        return _human_join(ordinals)
    return f"{len(ordinals)} selected days"


def _format_short_date(value):
    if not value:
        return None
    return value.strftime("%d %b %Y")


def _format_short_time(value):
    if not value:
        return None
    return value.strftime("%H:%M")


def _display_schedule_type_label(schedule_type):
    labels = {
        "one_time": "one-time arrangement",
        "date_range": "date-range arrangement",
        "recurring_weekly": "weekly recurring arrangement",
        "recurring_monthly": "monthly recurring arrangement",
    }
    return labels.get(schedule_type, "updated arrangement")


def _humanize_day_count(day_count):
    if day_count is None:
        return None
    if day_count % 365 == 0 and day_count >= 365:
        years = day_count // 365
        return f"{years} year" + ("s" if years != 1 else "")
    if day_count % 30 == 0 and day_count >= 30:
        months = day_count // 30
        return f"{months} month" + ("s" if months != 1 else "")
    if day_count % 7 == 0 and day_count >= 7:
        weeks = day_count // 7
        return f"{weeks} week" + ("s" if weeks != 1 else "")
    return f"{day_count} day" + ("s" if day_count != 1 else "")


def _schedule_duration_days(schedule_type, date_needed=None, start_date=None, end_date=None):
    if schedule_type == "one_time" and date_needed:
        return 1
    if schedule_type in ["date_range", "recurring_weekly", "recurring_monthly"] and start_date and end_date:
        return (end_date - start_date).days + 1
    return None


def _schedule_display_from_values(schedule_type, date_needed=None, start_date=None, end_date=None,
                                  start_time=None, end_time=None, time_flexible=False,
                                  recurrence_days=None, monthly_dates=None):
    time_part = ""
    if start_time and end_time:
        time_part = f"{_format_short_time(start_time)} - {_format_short_time(end_time)}"

    flexible_part = " (Flexible time)" if time_flexible else ""

    if schedule_type == "one_time":
        if date_needed and time_part:
            return f"{_format_short_date(date_needed)} | {time_part}{flexible_part}"
        if date_needed:
            return f"{_format_short_date(date_needed)}{flexible_part}"
        return "Schedule not specified"

    if schedule_type == "date_range":
        if start_date and end_date and time_part:
            return f"{_format_short_date(start_date)} to {_format_short_date(end_date)} | {time_part} daily{flexible_part}"
        if start_date and end_date:
            return f"{_format_short_date(start_date)} to {_format_short_date(end_date)}{flexible_part}"
        return "Schedule not specified"

    if schedule_type == "recurring_weekly":
        days = ", ".join(_split_csv_values(recurrence_days)) or "Selected days"
        if start_date and end_date and time_part:
            return f"Weekly on {days} | {time_part} | {_format_short_date(start_date)} to {_format_short_date(end_date)}{flexible_part}"
        if start_date and end_date:
            return f"Weekly on {days} | {_format_short_date(start_date)} to {_format_short_date(end_date)}{flexible_part}"
        return f"Weekly on {days}{flexible_part}"

    if schedule_type == "recurring_monthly":
        dates = _monthly_days_summary(monthly_dates)
        if start_date and end_date and time_part:
            return f"Monthly on {dates} | {time_part} | {_format_short_date(start_date)} to {_format_short_date(end_date)}{flexible_part}"
        if start_date and end_date:
            return f"Monthly on {dates} | {_format_short_date(start_date)} to {_format_short_date(end_date)}{flexible_part}"
        return f"Monthly on {dates}{flexible_part}"

    return "Schedule not specified"


class HelpRequest(db.Model):
    __tablename__ = "help_requests"

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    category = db.Column(db.String(100), nullable=False)
    custom_category = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)

    street_address = db.Column(db.String(200), nullable=False)
    suburb = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20), nullable=True)

    schedule_type = db.Column(db.String(30), default="one_time", nullable=False)

    date_needed = db.Column(db.Date, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)

    time_flexible = db.Column(db.Boolean, default=False, nullable=False)

    recurrence_days = db.Column(db.String(100), nullable=True)
    monthly_dates = db.Column(db.String(100), nullable=True)

    urgency = db.Column(db.String(30), nullable=False)
    experience_level_required = db.Column(db.String(50), nullable=False)

    status = db.Column(db.String(40), default="Open", nullable=False)
    selected_application_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    applications = db.relationship("Application", backref="help_request", lazy=True, cascade="all, delete-orphan")
    collaboration = db.relationship("Collaboration", backref="help_request", uselist=False, lazy=True, cascade="all, delete-orphan")

    def display_category(self):
        if self.category == "Other" and self.custom_category:
            return self.custom_category
        return self.category

    def full_location(self):
        parts = [self.street_address, self.suburb, self.city, self.postal_code]
        return ", ".join([part for part in parts if part])

    def recurrence_days_list(self):
        if not self.recurrence_days:
            return []
        return [day.strip() for day in self.recurrence_days.split(",") if day.strip()]

    def monthly_dates_list(self):
        if not self.monthly_dates:
            return []
        return [day.strip() for day in self.monthly_dates.split(",") if day.strip()]

    def monthly_dates_ordinal_list(self):
        return _monthly_ordinal_list(self.monthly_dates)

    def monthly_dates_summary(self):
        return _monthly_days_summary(self.monthly_dates)

    def has_collapsed_monthly_dates(self):
        return len(self.monthly_dates_list()) > 4

    def schedule_display(self):
        return _schedule_display_from_values(
            self.schedule_type,
            date_needed=self.date_needed,
            start_date=self.start_date,
            end_date=self.end_date,
            start_time=self.start_time,
            end_time=self.end_time,
            time_flexible=self.time_flexible,
            recurrence_days=self.recurrence_days,
            monthly_dates=self.monthly_dates,
        )

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def __repr__(self):
        return f"<HelpRequest {self.title}>"


class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    help_request_id = db.Column(db.Integer, db.ForeignKey("help_requests.id"), nullable=False)
    applicant_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Applied", nullable=False)
    decline_reason = db.Column(db.String(100), nullable=True)
    decline_reason_details = db.Column(db.String(255), nullable=True)

    resume_source = db.Column(db.String(20), default="profile", nullable=False)
    resume_file = db.Column(db.String(255), nullable=True)
    resume_label = db.Column(db.String(120), nullable=True)

    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    responded_at = db.Column(db.DateTime, nullable=True)

    def submitted_resume_path(self):
        if self.resume_source == "custom" and self.resume_file:
            return self.resume_file
        return self.applicant.resume_file

    def submitted_resume_name(self):
        if self.resume_label:
            return self.resume_label
        if self.resume_source == "custom":
            return "Custom CV"
        return "Profile CV"

    def applied_at_display(self):
        return _format_local_datetime(self.applied_at)

    def responded_at_display(self):
        return _format_local_datetime(self.responded_at)

    def __repr__(self):
        return f"<Application {self.id}>"


class Collaboration(db.Model):
    __tablename__ = "collaborations"

    id = db.Column(db.Integer, primary_key=True)
    help_request_id = db.Column(db.Integer, db.ForeignKey("help_requests.id"), nullable=False, unique=True)
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=False, unique=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    status = db.Column(db.String(40), default="Active", nullable=False)

    completion_requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    completion_requested_at = db.Column(db.DateTime, nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    cancellation_requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cancellation_requested_at = db.Column(db.DateTime, nullable=True)
    cancellation_reason = db.Column(db.Text, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    application = db.relationship("Application", backref=db.backref("collaboration", uselist=False), lazy=True)
    messages = db.relationship("Message", backref="collaboration", lazy=True, cascade="all, delete-orphan", order_by="Message.created_at.asc()")
    reschedule_proposals = db.relationship("RescheduleProposal", backref="collaboration", lazy=True, cascade="all, delete-orphan", order_by="RescheduleProposal.created_at.desc()")
    ratings = db.relationship("CollaborationRating", backref="collaboration", lazy=True, cascade="all, delete-orphan", order_by="CollaborationRating.created_at.desc()")

    completion_requested_by = db.relationship("User", foreign_keys=[completion_requested_by_id], lazy=True)
    cancellation_requested_by = db.relationship("User", foreign_keys=[cancellation_requested_by_id], lazy=True)

    def other_party_for(self, user):
        if not user:
            return None
        if user.id == self.requester_id:
            return self.provider_user
        if user.id == self.provider_id:
            return self.requester_user
        return None

    def user_can_access(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return user.role == "admin" or user.id in [self.requester_id, self.provider_id]

    def is_system_user(self, user):
        return False if not user else False

    def user_role_for(self, user):
        if not user:
            return None
        if user.id == self.requester_id:
            return "requester"
        if user.id == self.provider_id:
            return "provider"
        return None

    def is_open(self):
        return self.status in ["Active", "PendingCompletionConfirmation", "PendingCancellation"]

    def is_closed(self):
        return self.status in ["Completed", "Cancelled"]

    def is_pending_completion(self):
        return self.status == "PendingCompletionConfirmation"

    def is_pending_cancellation(self):
        return self.status == "PendingCancellation"

    def can_send_messages(self, user):
        return self.user_can_access(user) and not self.is_closed()

    def can_request_completion(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return (
            self.status == "Active"
            and user.id == self.provider_id
        )

    def can_confirm_completion(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return (
            self.status == "PendingCompletionConfirmation"
            and user.id == self.requester_id
        )

    def can_reject_completion(self, user):
        return self.can_confirm_completion(user)

    def can_request_cancellation(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return (
            self.status == "Active"
            and user.id in [self.requester_id, self.provider_id]
        )

    def can_decide_cancellation(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return (
            self.status == "PendingCancellation"
            and user.id in [self.requester_id, self.provider_id]
            and user.id != self.cancellation_requested_by_id
        )

    def rating_given_by(self, user):
        if not user:
            return None
        return next((item for item in self.ratings if item.rater_id == user.id), None)

    def requester_rating(self):
        return next((item for item in self.ratings if item.rater_id == self.requester_id), None)

    def provider_rating(self):
        return next((item for item in self.ratings if item.rater_id == self.provider_id), None)

    def can_be_rated_by(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.status != "Completed":
            return False
        if user.id not in [self.requester_id, self.provider_id]:
            return False
        return self.rating_given_by(user) is None

    def rating_pending_for(self, user):
        return self.status == "Completed" and self.rating_given_by(user) is None and user and user.id in [self.requester_id, self.provider_id]

    def rater_target_label(self, user):
        role = self.user_role_for(user)
        if role == "requester":
            return "provider"
        if role == "provider":
            return "requester"
        return "participant"

    def rating_status_label_for(self, user):
        if self.status != "Completed":
            return "Rating locked"
        return "Rating pending" if self.rating_pending_for(user) else "Rated"

    def outcome_status_badge_class(self):
        mapping = {
            "Active": "bg-success",
            "PendingCompletionConfirmation": "bg-warning text-dark",
            "PendingCancellation": "bg-warning text-dark",
            "Completed": "bg-primary",
            "Cancelled": "bg-danger",
        }
        return mapping.get(self.status, "bg-secondary")

    def outcome_status_label(self):
        mapping = {
            "Active": "Active",
            "PendingCompletionConfirmation": "Awaiting completion confirmation",
            "PendingCancellation": "Cancellation pending",
            "Completed": "Completed",
            "Cancelled": "Cancelled",
        }
        return mapping.get(self.status, self.status)

    def completion_requested_at_display(self):
        return _format_local_datetime(self.completion_requested_at)

    def cancellation_requested_at_display(self):
        return _format_local_datetime(self.cancellation_requested_at)

    def completed_at_display(self):
        return _format_local_datetime(self.completed_at)

    def cancelled_at_display(self):
        return _format_local_datetime(self.cancelled_at)

    def last_message_preview(self):
        if not self.messages:
            return "No messages yet"
        latest = self.messages[-1]
        if latest.is_system_message:
            return latest.body
        return latest.body[:80] + ("..." if len(latest.body) > 80 else "")

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def updated_at_display(self):
        return _format_local_datetime(self.updated_at)

    def __repr__(self):
        return f"<Collaboration {self.id}>"


class CollaborationRating(db.Model):
    __tablename__ = "collaboration_ratings"
    __table_args__ = (
        db.UniqueConstraint("collaboration_id", "rater_id", name="uq_collaboration_rating_rater"),
    )

    id = db.Column(db.Integer, primary_key=True)
    collaboration_id = db.Column(db.Integer, db.ForeignKey("collaborations.id"), nullable=False, index=True)
    rater_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ratee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    rater_role = db.Column(db.String(20), nullable=False)
    ratee_role = db.Column(db.String(20), nullable=False)

    overall_rating = db.Column(db.Integer, nullable=False)
    communication_rating = db.Column(db.Integer, nullable=False)
    timeliness_rating = db.Column(db.Integer, nullable=True)
    quality_rating = db.Column(db.Integer, nullable=True)
    clarity_rating = db.Column(db.Integer, nullable=True)
    cooperation_rating = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def rating_stars(self, value):
        if not value:
            return "Not rated"
        value = max(1, min(5, int(value)))
        return "★" * value + "☆" * (5 - value)

    def overall_rating_stars(self):
        return self.rating_stars(self.overall_rating)

    def dimension_rows(self):
        rows = [("Overall experience", self.overall_rating), ("Communication", self.communication_rating)]
        if self.ratee_role == "provider":
            rows.extend([
                ("Timeliness", self.timeliness_rating),
                ("Quality of work", self.quality_rating),
            ])
        else:
            rows.extend([
                ("Clarity of request", self.clarity_rating),
                ("Cooperation", self.cooperation_rating),
            ])
        return rows

    def quiz_title(self):
        if self.ratee_role == "provider":
            return "Provider rating"
        return "Requester rating"

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def __repr__(self):
        return f"<CollaborationRating {self.id}>"


class Message(db.Model):

    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    collaboration_id = db.Column(db.Integer, db.ForeignKey("collaborations.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    body = db.Column(db.Text, nullable=False)
    is_system_message = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    sender = db.relationship("User", backref=db.backref("messages_sent", lazy=True))
    flags = db.relationship("MessageFlag", backref="message", lazy=True, cascade="all, delete-orphan", order_by="MessageFlag.created_at.desc()")

    def can_be_flagged_by(self, user):
        if self.is_system_message or not user or not getattr(user, "is_authenticated", False):
            return False
        if not self.collaboration or not self.collaboration.user_can_access(user):
            return False
        return self.sender_id is not None and self.sender_id != user.id

    def existing_flag_by_user(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return None
        return next((flag for flag in self.flags if flag.reporter_id == user.id), None)

    def is_sent_by(self, user):
        return bool(user and self.sender_id and self.sender_id == user.id)

    def display_sender_name(self):
        if self.is_system_message:
            return "System"
        return self.sender.full_name if self.sender else "Unknown User"

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def created_at_compact_display(self):
        return _format_local_datetime(self.created_at, "%d %b, %H:%M")

    def __repr__(self):
        return f"<Message {self.id}>"


class RescheduleProposal(db.Model):
    __tablename__ = "reschedule_proposals"

    id = db.Column(db.Integer, primary_key=True)
    collaboration_id = db.Column(db.Integer, db.ForeignKey("collaborations.id"), nullable=False, index=True)
    proposer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    current_schedule_type = db.Column(db.String(30), nullable=False)
    current_date_needed = db.Column(db.Date, nullable=True)
    current_start_date = db.Column(db.Date, nullable=True)
    current_end_date = db.Column(db.Date, nullable=True)
    current_start_time = db.Column(db.Time, nullable=True)
    current_end_time = db.Column(db.Time, nullable=True)
    current_time_flexible = db.Column(db.Boolean, default=False, nullable=False)
    current_recurrence_days = db.Column(db.String(100), nullable=True)
    current_monthly_dates = db.Column(db.String(100), nullable=True)

    proposed_schedule_type = db.Column(db.String(30), nullable=False)
    proposed_date_needed = db.Column(db.Date, nullable=True)
    proposed_start_date = db.Column(db.Date, nullable=True)
    proposed_end_date = db.Column(db.Date, nullable=True)
    proposed_start_time = db.Column(db.Time, nullable=True)
    proposed_end_time = db.Column(db.Time, nullable=True)
    proposed_time_flexible = db.Column(db.Boolean, default=False, nullable=False)
    proposed_recurrence_days = db.Column(db.String(100), nullable=True)
    proposed_monthly_dates = db.Column(db.String(100), nullable=True)

    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)

    proposer = db.relationship("User", backref=db.backref("reschedule_proposals_made", lazy=True))

    def current_schedule_display(self):
        return _schedule_display_from_values(
            self.current_schedule_type,
            date_needed=self.current_date_needed,
            start_date=self.current_start_date,
            end_date=self.current_end_date,
            start_time=self.current_start_time,
            end_time=self.current_end_time,
            time_flexible=self.current_time_flexible,
            recurrence_days=self.current_recurrence_days,
            monthly_dates=self.current_monthly_dates,
        )

    def proposed_schedule_display(self):
        return _schedule_display_from_values(
            self.proposed_schedule_type,
            date_needed=self.proposed_date_needed,
            start_date=self.proposed_start_date,
            end_date=self.proposed_end_date,
            start_time=self.proposed_start_time,
            end_time=self.proposed_end_time,
            time_flexible=self.proposed_time_flexible,
            recurrence_days=self.proposed_recurrence_days,
            monthly_dates=self.proposed_monthly_dates,
        )

    def proposed_recurrence_days_list(self):
        return _split_csv_values(self.proposed_recurrence_days)

    def proposed_monthly_dates_list(self):
        return _split_csv_values(self.proposed_monthly_dates)

    def current_monthly_dates_ordinal_list(self):
        return _monthly_ordinal_list(self.current_monthly_dates)

    def proposed_monthly_dates_ordinal_list(self):
        return _monthly_ordinal_list(self.proposed_monthly_dates)

    def current_monthly_dates_summary(self):
        return _monthly_days_summary(self.current_monthly_dates)

    def proposed_monthly_dates_summary(self):
        return _monthly_days_summary(self.proposed_monthly_dates)

    def current_has_collapsed_monthly_dates(self):
        return len(self.current_monthly_dates_list()) > 4

    def proposed_has_collapsed_monthly_dates(self):
        return len(self.proposed_monthly_dates_list()) > 4

    def current_monthly_dates_list(self):
        return _split_csv_values(self.current_monthly_dates)

    def can_be_decided_by(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return False
        return self.status == "Pending" and user.id in [self.collaboration.requester_id, self.collaboration.provider_id] and user.id != self.proposer_id

    def proposed_duration_days(self):
        return _schedule_duration_days(
            self.proposed_schedule_type,
            date_needed=self.proposed_date_needed,
            start_date=self.proposed_start_date,
            end_date=self.proposed_end_date,
        )

    def current_duration_days(self):
        return _schedule_duration_days(
            self.current_schedule_type,
            date_needed=self.current_date_needed,
            start_date=self.current_start_date,
            end_date=self.current_end_date,
        )

    def impact_summary(self):
        current_duration = self.current_duration_days()
        proposed_duration = self.proposed_duration_days()

        if self.current_schedule_type != self.proposed_schedule_type:
            return f"This change will convert the schedule to a {_display_schedule_type_label(self.proposed_schedule_type)}."

        if self.proposed_schedule_type == "one_time":
            if self.current_date_needed != self.proposed_date_needed and self.proposed_date_needed:
                return f"This change will move the work to {_format_short_date(self.proposed_date_needed)}."
            if self.current_start_time != self.proposed_start_time or self.current_end_time != self.proposed_end_time or self.current_time_flexible != self.proposed_time_flexible:
                return "This change will keep the same day but adjust the working time."
            return "This change keeps the same one-time arrangement."

        if self.proposed_schedule_type == "date_range":
            if current_duration and proposed_duration and proposed_duration != current_duration:
                difference = abs(proposed_duration - current_duration)
                human = _humanize_day_count(difference)
                if proposed_duration > current_duration:
                    return f"This change will extend the collaboration by {human}."
                return f"This change will shorten the collaboration by {human}."
            if (self.current_start_date != self.proposed_start_date) or (self.current_end_date != self.proposed_end_date):
                return "This change will keep the same duration but move the scheduled dates."
            if self.current_start_time != self.proposed_start_time or self.current_end_time != self.proposed_end_time or self.current_time_flexible != self.proposed_time_flexible:
                return "This change will keep the same day range but adjust the working time."
            return "This change keeps the same date-range arrangement."

        if self.proposed_schedule_type == "recurring_weekly":
            if self.current_recurrence_days != self.proposed_recurrence_days:
                return "This change will update the weekly working days."
            if current_duration and proposed_duration and proposed_duration != current_duration:
                difference = abs(proposed_duration - current_duration)
                human = _humanize_day_count(difference)
                if proposed_duration > current_duration:
                    return f"This change will extend the weekly arrangement by {human}."
                return f"This change will shorten the weekly arrangement by {human}."
            if self.current_start_time != self.proposed_start_time or self.current_end_time != self.proposed_end_time or self.current_time_flexible != self.proposed_time_flexible:
                return "This change will keep the same weekly arrangement but adjust the working time."
            return "This change keeps the same weekly recurring arrangement."

        if self.proposed_schedule_type == "recurring_monthly":
            if self.current_monthly_dates != self.proposed_monthly_dates:
                return "This change will update the monthly working dates."
            if current_duration and proposed_duration and proposed_duration != current_duration:
                difference = abs(proposed_duration - current_duration)
                human = _humanize_day_count(difference)
                if proposed_duration > current_duration:
                    return f"This change will extend the monthly arrangement by {human}."
                return f"This change will shorten the monthly arrangement by {human}."
            if self.current_start_time != self.proposed_start_time or self.current_end_time != self.proposed_end_time or self.current_time_flexible != self.proposed_time_flexible:
                return "This change will keep the same monthly arrangement but adjust the working time."
            return "This change keeps the same monthly recurring arrangement."

        return "This change will update the agreed schedule."

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def responded_at_display(self):
        return _format_local_datetime(self.responded_at)

    def created_at_compact_display(self):
        return _format_local_datetime(self.created_at, "%d %b, %H:%M")

    def __repr__(self):
        return f"<RescheduleProposal {self.id}>"


class MessageFlag(db.Model):
    __tablename__ = "message_flags"

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey("messages.id"), nullable=False, index=True)
    collaboration_id = db.Column(db.Integer, db.ForeignKey("collaborations.id"), nullable=False, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reported_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reason_category = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="Pending", nullable=False)
    review_result = db.Column(db.String(50), nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    collaboration = db.relationship("Collaboration", backref=db.backref("message_flags", lazy=True, cascade="all, delete-orphan"))

    REASON_LABELS = {
        "offensive": "Abusive or offensive",
        "harassment": "Harassment or bullying",
        "spam": "Spam or repeated unwanted messages",
        "fraud": "Scam or fraud concern",
        "inappropriate": "Inappropriate content",
        "other": "Other",
    }

    def reason_label(self):
        return self.REASON_LABELS.get(self.reason_category, self.reason_category.replace("_", " ").title())

    def status_badge_class(self):
        mapping = {
            "Pending": "warning text-dark",
            "Reviewed": "success",
            "Dismissed": "secondary",
        }
        return mapping.get(self.status, "secondary")

    def review_summary(self):
        if self.status == "Pending":
            return "Pending review"
        if self.review_result == "Violation Confirmed":
            return "Violation confirmed"
        if self.review_result == "No Violation":
            return "No violation found"
        return self.status

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def reviewed_at_local(self):
        return _to_sa_time(self.reviewed_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def reviewed_at_display(self):
        return _format_local_datetime(self.reviewed_at)

    def created_at_compact_display(self):
        return _format_local_datetime(self.created_at, "%d %b, %H:%M")

    def __repr__(self):
        return f"<MessageFlag {self.id}>"


class ModerationReview(db.Model):
    __tablename__ = "moderation_reviews"

    id = db.Column(db.Integer, primary_key=True)
    flag_id = db.Column(db.Integer, db.ForeignKey("message_flags.id"), nullable=False, unique=True, index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    is_report_valid = db.Column(db.Boolean, nullable=False)
    violates_guidelines = db.Column(db.Boolean, nullable=False)
    severity_level = db.Column(db.String(20), nullable=False)
    is_targeted_abuse = db.Column(db.Boolean, nullable=False, default=False)
    is_repeat_behavior = db.Column(db.Boolean, nullable=False, default=False)
    creates_safety_risk = db.Column(db.Boolean, nullable=False, default=False)
    computed_outcome = db.Column(db.String(50), nullable=False)
    admin_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    flag = db.relationship("MessageFlag", backref=db.backref("moderation_review", uselist=False, cascade="all, delete-orphan"))

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def __repr__(self):
        return f"<ModerationReview {self.id}>"


class UserRestriction(db.Model):
    __tablename__ = "user_restrictions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    source_flag_id = db.Column(db.Integer, db.ForeignKey("message_flags.id"), nullable=True, index=True)
    restriction_type = db.Column(db.String(30), nullable=False, default="messaging")
    outcome_label = db.Column(db.String(50), nullable=False)
    reason_category = db.Column(db.String(50), nullable=True)
    starts_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    source_flag = db.relationship("MessageFlag", backref=db.backref("generated_restrictions", lazy=True))

    def is_currently_active(self, current_time=None):
        current_time = current_time or datetime.utcnow()
        if not self.is_active:
            return False
        if self.ends_at and self.ends_at <= current_time:
            return False
        return True

    def remaining_label(self):
        if not self.ends_at:
            return "Until removed"
        remaining = self.ends_at - datetime.utcnow()
        if remaining.total_seconds() <= 0:
            return "Expired"
        days = remaining.days
        if days >= 1:
            return f"{days} day" + ("s" if days != 1 else "") + " remaining"
        hours = max(1, int(remaining.total_seconds() // 3600))
        return f"{hours} hour" + ("s" if hours != 1 else "") + " remaining"

    def period_label(self):
        if not self.ends_at:
            return "Until removed"
        return f"{_format_local_datetime(self.starts_at)} to {_format_local_datetime(self.ends_at)}"

    def starts_at_display(self):
        return _format_local_datetime(self.starts_at)

    def ends_at_display(self):
        return _format_local_datetime(self.ends_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def __repr__(self):
        return f"<UserRestriction {self.id}>"


class SocialAccount(db.Model):
    __tablename__ = "social_accounts"
    __table_args__ = (
        db.UniqueConstraint("provider", "provider_user_id", name="uq_social_provider_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    provider_user_id = db.Column(db.String(255), nullable=False)
    provider_email = db.Column(db.String(255), nullable=True)
    provider_name = db.Column(db.String(255), nullable=True)
    provider_picture = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SocialAccount {self.provider}:{self.provider_user_id}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default="info")
    notification_link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def created_at_local(self):
        return _to_sa_time(self.created_at)

    def created_at_display(self):
        return _format_local_datetime(self.created_at)

    def created_at_compact_display(self):
        return _format_local_datetime(self.created_at, "%d %b, %H:%M")

    def __repr__(self):
        return f"<Notification {self.id} for user {self.user_id}>"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
