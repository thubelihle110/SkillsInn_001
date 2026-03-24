from datetime import date
from wtforms import StringField, PasswordField, SubmitField, TextAreaField, SelectField, BooleanField, IntegerField
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField,
    PasswordField,
    SubmitField,
    TextAreaField,
    SelectField,
    DateField,
    TimeField,
    BooleanField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, URL, NumberRange


class RegistrationForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField("Phone Number", validators=[Length(max=20)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Send Reset Link")


class ResetPasswordForm(FlaskForm):
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Reset Password")


class UpdateProfileForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=120)])
    phone = StringField("Phone Number", validators=[Optional(), Length(max=20)])
    bio = TextAreaField("Short Bio", validators=[Optional(), Length(max=500)])

    street_address = StringField("Street Address", validators=[Optional(), Length(max=200)])
    suburb = StringField("Suburb", validators=[Optional(), Length(max=100)])
    city = StringField("City", validators=[Optional(), Length(max=100)])
    postal_code = StringField("Postal Code", validators=[Optional(), Length(max=20)])

    availability = SelectField(
        "Availability",
        choices=[
            ("", "Select Availability"),
            ("Weekdays", "Weekdays"),
            ("Weekends", "Weekends"),
            ("Evenings", "Evenings"),
            ("Flexible", "Flexible"),
        ],
        validators=[Optional()]
    )

    experience_level = SelectField(
        "Experience Level",
        choices=[
            ("", "Select Experience Level"),
            ("Beginner", "Beginner"),
            ("Intermediate", "Intermediate"),
            ("Advanced", "Advanced"),
            ("Professional", "Professional"),
        ],
        validators=[Optional()]
    )

    preferred_contact_method = SelectField(
        "Preferred Contact Method",
        choices=[
            ("", "Select Contact Method"),
            ("Email", "Email"),
            ("Phone", "Phone"),
            ("WhatsApp", "WhatsApp"),
        ],
        validators=[Optional()]
    )

    portfolio_link = StringField("Portfolio / LinkedIn URL", validators=[Optional(), URL()])
    profile_picture = FileField(
        "Profile Picture",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only.")]
    )
    resume_file = FileField(
        "Resume / CV (PDF)",
        validators=[FileAllowed(["pdf"], "PDF files only.")]
    )

    submit = SubmitField("Update Profile")


class SkillForm(FlaskForm):
    category = SelectField(
        "Skill Category",
        choices=[
            ("", "Select Category"),
            ("Information Technology", "Information Technology"),
            ("Engineering", "Engineering"),
            ("Manufacturing", "Manufacturing"),
            ("Construction", "Construction"),
            ("Education and Tutoring", "Education and Tutoring"),
            ("Business and Administration", "Business and Administration"),
            ("Finance and Accounting", "Finance and Accounting"),
            ("Health and Wellness", "Health and Wellness"),
            ("Creative Arts and Design", "Creative Arts and Design"),
            ("Media and Communication", "Media and Communication"),
            ("Transport and Logistics", "Transport and Logistics"),
            ("Hospitality and Tourism", "Hospitality and Tourism"),
            ("Agriculture and Environment", "Agriculture and Environment"),
            ("Home and Maintenance Services", "Home and Maintenance Services"),
            ("Beauty and Personal Care", "Beauty and Personal Care"),
            ("Fashion and Textile", "Fashion and Textile"),
            ("Legal and Compliance", "Legal and Compliance"),
            ("Community and Social Services", "Community and Social Services"),
            ("Sports and Fitness", "Sports and Fitness"),
            ("Other", "Other"),
        ],
        validators=[DataRequired()]
    )

    custom_category = StringField("If Other, specify category", validators=[Optional(), Length(max=100)])
    title = StringField("Skill Title", validators=[DataRequired(), Length(min=2, max=150)])
    description = TextAreaField("Skill Description", validators=[DataRequired(), Length(min=10, max=1000)])

    experience_level = SelectField(
        "Experience Level",
        choices=[
            ("", "Select Experience Level"),
            ("Beginner", "Beginner"),
            ("Intermediate", "Intermediate"),
            ("Advanced", "Advanced"),
            ("Professional", "Professional"),
        ],
        validators=[DataRequired()]
    )

    availability = SelectField(
        "Availability",
        choices=[
            ("", "Select Availability"),
            ("Weekdays", "Weekdays"),
            ("Weekends", "Weekends"),
            ("Evenings", "Evenings"),
            ("Flexible", "Flexible"),
        ],
        validators=[DataRequired()]
    )

    certificate_file = FileField(
        "Certification / Proof of Skill (Optional)",
        validators=[FileAllowed(["pdf", "jpg", "jpeg", "png"], "Only PDF, JPG, JPEG, and PNG files are allowed.")]
    )

    submit = SubmitField("Save Skill")


class TeachApplicationForm(FlaskForm):
    application_reason = TextAreaField(
        "Why should you be allowed to teach this skill?",
        validators=[Optional(), Length(max=1000)]
    )
    submit = SubmitField("Submit application")


class CourseForm(FlaskForm):
    skill_id = SelectField("Skill to teach", coerce=int, validators=[DataRequired()])
    title = StringField("Course Title", validators=[DataRequired(), Length(min=3, max=150)])
    description = TextAreaField("Course Description", validators=[DataRequired(), Length(min=20, max=3000)])
    level = SelectField(
        "Course Level",
        choices=[],
        validators=[DataRequired()]
    )
    pass_mark = IntegerField("Final Pass Mark (%)", validators=[DataRequired(), NumberRange(min=50, max=100)], default=70)
    submit = SubmitField("Save course")



class HelpRequestForm(FlaskForm):
    category = SelectField(
        "Request Category",
        choices=[
            ("", "Select Category"),
            ("Information Technology", "Information Technology"),
            ("Engineering", "Engineering"),
            ("Manufacturing", "Manufacturing"),
            ("Construction", "Construction"),
            ("Education and Tutoring", "Education and Tutoring"),
            ("Business and Administration", "Business and Administration"),
            ("Finance and Accounting", "Finance and Accounting"),
            ("Health and Wellness", "Health and Wellness"),
            ("Creative Arts and Design", "Creative Arts and Design"),
            ("Media and Communication", "Media and Communication"),
            ("Transport and Logistics", "Transport and Logistics"),
            ("Hospitality and Tourism", "Hospitality and Tourism"),
            ("Agriculture and Environment", "Agriculture and Environment"),
            ("Home and Maintenance Services", "Home and Maintenance Services"),
            ("Beauty and Personal Care", "Beauty and Personal Care"),
            ("Fashion and Textile", "Fashion and Textile"),
            ("Legal and Compliance", "Legal and Compliance"),
            ("Community and Social Services", "Community and Social Services"),
            ("Sports and Fitness", "Sports and Fitness"),
            ("Other", "Other"),
        ],
        validators=[DataRequired()]
    )

    custom_category = StringField("If Other, specify category", validators=[Optional(), Length(max=100)])
    title = StringField("Request Title", validators=[DataRequired(), Length(min=3, max=150)])
    description = TextAreaField(
        "Request Description",
        validators=[DataRequired(), Length(min=15, max=1500)]
    )

    street_address = StringField("Street Address", validators=[DataRequired(), Length(max=200)])
    suburb = StringField("Suburb", validators=[Optional(), Length(max=100)])
    city = StringField("Town / City", validators=[DataRequired(), Length(max=100)])
    postal_code = StringField("Postal Code", validators=[Optional(), Length(max=20)])

    schedule_type = SelectField(
        "Work Schedule Type",
        choices=[
            ("one_time", "One-time"),
            ("date_range", "Multi-day Period"),
            ("recurring_weekly", "Recurring Weekly"),
            ("recurring_monthly", "Recurring Monthly"),
        ],
        validators=[DataRequired()]
    )

    date_needed = DateField("Required Date", format="%Y-%m-%d", validators=[Optional()])
    start_date = DateField("Start Date", format="%Y-%m-%d", validators=[Optional()])
    end_date = DateField("End Date", format="%Y-%m-%d", validators=[Optional()])

    start_time = TimeField("Start Time", format="%H:%M", validators=[Optional()])
    end_time = TimeField("End Time", format="%H:%M", validators=[Optional()])

    time_flexible = BooleanField("Schedule is flexible")

    recurrence_days = StringField("Select Working Days", validators=[Optional(), Length(max=100)])
    monthly_dates = StringField("Select Days of the Month", validators=[Optional(), Length(max=100)])

    urgency = SelectField(
        "Urgency",
        choices=[
            ("Low", "Low"),
            ("Medium", "Medium"),
            ("High", "High"),
            ("Urgent", "Urgent"),
        ],
        validators=[DataRequired()]
    )

    experience_level_required = SelectField(
        "Required Experience Level",
        choices=[
            ("Beginner", "Beginner"),
            ("Intermediate", "Intermediate"),
            ("Advanced", "Advanced"),
            ("Professional", "Professional"),
        ],
        validators=[DataRequired()]
    )

    submit = SubmitField("Save Help Request")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False

        today = date.today()

        if not self.start_time.data:
            self.start_time.errors.append("Start Time is required.")
            return False

        if not self.end_time.data:
            self.end_time.errors.append("End Time is required.")
            return False

        if self.end_time.data <= self.start_time.data:
            self.end_time.errors.append("End Time must be later than Start Time.")
            return False

        if self.schedule_type.data == "one_time":
            if not self.date_needed.data:
                self.date_needed.errors.append("Required Date is required for a one-time schedule.")
                return False
            if self.date_needed.data < today:
                self.date_needed.errors.append("Required Date cannot be in the past.")
                return False

        elif self.schedule_type.data in ["date_range", "recurring_weekly", "recurring_monthly"]:
            if not self.start_date.data:
                self.start_date.errors.append("Start Date is required.")
                return False
            if not self.end_date.data:
                self.end_date.errors.append("End Date is required.")
                return False
            if self.start_date.data < today:
                self.start_date.errors.append("Start Date cannot be in the past.")
                return False
            if self.end_date.data < today:
                self.end_date.errors.append("End Date cannot be in the past.")
                return False
            if self.end_date.data < self.start_date.data:
                self.end_date.errors.append("End Date cannot be earlier than Start Date.")
                return False

        if self.schedule_type.data == "recurring_weekly":
            recurrence_days = getattr(self, "recurrence_days_data", None)
            if not recurrence_days:
                self.recurrence_days.errors.append("Please select at least one working day.")
                return False

        if self.schedule_type.data == "recurring_monthly":
            monthly_dates = getattr(self, "monthly_dates_data", None)
            if not monthly_dates:
                self.monthly_dates.errors.append("Please select at least one day of the month.")
                return False

        return True


class ApplicationForm(FlaskForm):
    message = TextAreaField(
        "Application Message",
        validators=[DataRequired(), Length(min=10, max=1000)]
    )

    resume_choice = SelectField(
        "CV to Submit",
        choices=[
            ("profile", "Use my default profile CV"),
            ("custom", "Upload a custom CV for this request"),
        ],
        validators=[DataRequired()]
    )

    resume_label = StringField(
        "CV Label / Version Name",
        validators=[Optional(), Length(max=120)]
    )

    resume_file = FileField(
        "Upload Custom CV (PDF)",
        validators=[FileAllowed(["pdf"], "PDF files only.")]
    )

    submit = SubmitField("Submit Application")


class ApplicationResponseForm(FlaskForm):
    decision = SelectField(
        "Your Response",
        choices=[
            ("Accepted", "Accept Request"),
            ("Declined", "Decline Request"),
        ],
        validators=[DataRequired()]
    )

    decline_reason = SelectField(
        "Reason for Declining",
        choices=[
            ("", "Select a reason"),
            ("No longer available", "No longer available"),
            ("Request is too far", "Request is too far"),
            ("Schedule conflict", "Schedule conflict"),
            ("Skills do not match", "Skills do not match"),
            ("Other", "Other"),
        ],
        validators=[Optional()]
    )

    other_decline_reason = StringField(
        "Please specify",
        validators=[Optional(), Length(max=255)]
    )

    submit = SubmitField("Submit Response")


class RejectVerificationForm(FlaskForm):
    verification_note = TextAreaField(
        "Reason for Rejection",
        validators=[DataRequired(), Length(min=5, max=500)]
    )
    submit = SubmitField("Reject Certification")


class AdminSetupForm(FlaskForm):
    email = StringField("New Admin Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("New Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")]
    )
    submit = SubmitField("Save Admin Credentials")