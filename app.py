import json
import os
import re
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance_advisor.db")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-secret-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"

# Current Gemini default. It can be overridden with GEMINI_MODEL in .env.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# SkillWallet-specified thresholds used in prompt engineering and local calculations.
CATEGORY_TIPS = {
    "rent": 30,
    "food": 15,
    "transport": 10,
    "dining": 8,
    "entertainment": 8,
    "utilities": 10,
    "savings": 20,
}

GOAL_DESCRIPTIONS = {
    "emergency_fund": "Build an emergency fund covering essential expenses, prioritising consistent monthly saving.",
    "vacation": "Create a realistic travel fund while keeping essential costs and emergency savings protected.",
    "gadget": "Save for a planned gadget purchase without relying on debt or sacrificing core financial needs.",
    "investment": "Build a stable saving base first, then consider long-term diversified investing according to risk tolerance.",
    "general_savings": "Improve the monthly savings rate and create a sustainable buffer for future needs.",
}

BUDGET_SCHEMA = {
    "type": "object",
    "properties": {
        "budget": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "recommended_amount": {"type": "number"},
                    "percentage": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["category", "recommended_amount", "percentage", "reason"],
            },
        },
        "analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "spent": {"type": "number"},
                    "percentage": {"type": "number"},
                    "status": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["category", "spent", "percentage", "status", "message"],
            },
        },
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "amount": {"type": "number"},
                    "target": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["title", "amount", "target", "action"],
            },
        },
        "summary": {
            "type": "object",
            "properties": {
                "income": {"type": "number"},
                "expenses": {"type": "number"},
                "estimated_savings": {"type": "number"},
                "savings_rate": {"type": "number"},
                "goal": {"type": "string"},
                "headline": {"type": "string"},
            },
            "required": ["income", "expenses", "estimated_savings", "savings_rate", "goal", "headline"],
        },
    },
    "required": ["budget", "analysis", "suggestions", "summary"],
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access your finance dashboard."


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    incomes = db.relationship("Income", backref="user", lazy=True, cascade="all, delete-orphan")
    expenses = db.relationship("Expense", backref="user", lazy=True, cascade="all, delete-orphan")
    analyses = db.relationship("AnalysisResult", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    source = db.Column(db.String(120), default="Primary income")
    month = db.Column(db.String(7), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255), default="")
    month = db.Column(db.String(7), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AnalysisResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    month = db.Column(db.String(7), nullable=False)
    goal = db.Column(db.String(60), nullable=False)
    income = db.Column(db.Float, nullable=False)
    expenses = db.Column(db.Float, nullable=False)
    estimated_savings = db.Column(db.Float, nullable=False)
    savings_rate = db.Column(db.Float, nullable=False)
    payload_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def clean_amount(value, field_name, minimum=0, maximum=100_000_000):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")
    if not minimum <= number <= maximum:
        raise ValueError(f"{field_name} must be between ₹{minimum:,.0f} and ₹{maximum:,.0f}.")
    return round(number, 2)


def normalise_expenses(expenses):
    if not isinstance(expenses, dict):
        raise ValueError("Expenses must be provided as an object of categories and amounts.")
    cleaned = {}
    for raw_category, raw_amount in expenses.items():
        category = re.sub(r"[^a-zA-Z_ ]", "", str(raw_category)).strip().lower().replace(" ", "_")
        if not category:
            continue
        amount = clean_amount(raw_amount, f"Expense for {category}")
        if amount > 0:
            cleaned[category] = amount
    if not cleaned:
        raise ValueError("Please provide at least one expense greater than zero.")
    return cleaned


def goal_label(goal):
    labels = {
        "emergency_fund": "Emergency fund",
        "vacation": "Vacation",
        "gadget": "Gadget purchase",
        "investment": "Investment",
        "general_savings": "General savings",
    }
    return labels.get(goal, "General savings")


def local_budget_plan(income, expenses, goal):
    """Deterministic baseline budget used for reliable arithmetic and fallback/demo mode."""
    savings_contribution = expenses.get("savings", 0)
    total_expenses = sum(amount for category, amount in expenses.items() if category != "savings")
    desired_savings = income * 0.20
    available_for_spending = max(income - desired_savings, 0)

    category_order = ["rent", "food", "transport", "utilities", "dining", "entertainment", "other"]
    raw_caps = {
        "rent": income * 0.30,
        "food": income * 0.15,
        "transport": income * 0.10,
        "utilities": income * 0.10,
        "dining": income * 0.08,
        "entertainment": income * 0.08,
    }

    base_budget = []
    remaining = available_for_spending
    for category in category_order:
        if category == "other":
            continue
        amount = round(min(raw_caps[category], remaining), 2)
        if amount > 0:
            base_budget.append({
                "category": category,
                "recommended_amount": amount,
                "percentage": round((amount / income) * 100, 1) if income else 0,
                "reason": f"Target is around {CATEGORY_TIPS.get(category, 0)}% of income where practical.",
            })
            remaining -= amount

    # Remaining allocation is intentionally shown as a flexible buffer rather than forcing spending.
    if remaining > 0:
        base_budget.append({
            "category": "flexible_buffer",
            "recommended_amount": round(remaining, 2),
            "percentage": round((remaining / income) * 100, 1) if income else 0,
            "reason": "Keep this amount flexible for irregular essentials or additional savings.",
        })

    analysis = []
    for category, spent in expenses.items():
        threshold = CATEGORY_TIPS.get(category)
        pct = round((spent / income) * 100, 1) if income else 0
        if threshold is None:
            status = "on_track" if pct <= 12 else "review"
            message = f"{pct}% of income is going to {category.replace('_', ' ')}. Review if it is discretionary."
        elif category == "savings":
            status = "on_track" if pct >= threshold else "overspending"
            message = f"Savings are {pct}% of income; the baseline target is at least {threshold}%."
        else:
            status = "overspending" if pct > threshold else "on_track"
            message = f"Spending is {pct}% of income versus a guideline of {threshold}%."
        analysis.append({
            "category": category,
            "spent": round(spent, 2),
            "percentage": pct,
            "status": status,
            "message": message,
        })

    savings_gap = max(desired_savings - savings_contribution, 0)
    top_overspend = sorted(
        [item for item in analysis if item["status"] == "overspending" and item["category"] != "savings"],
        key=lambda x: x["percentage"],
        reverse=True,
    )

    suggestions = []
    for item in top_overspend[:2]:
        threshold = CATEGORY_TIPS.get(item["category"], item["percentage"])
        target_amount = income * threshold / 100
        reduction = max(item["spent"] - target_amount, 0)
        if reduction > 0:
            suggestions.append({
                "title": f"Reduce {item['category'].replace('_', ' ')} spending",
                "amount": round(reduction, 2),
                "target": "monthly savings",
                "action": f"Move about ₹{reduction:,.0f} from this category into your {goal_label(goal).lower()} goal.",
            })

    if savings_gap > 0:
        suggestions.append({
            "title": "Increase monthly savings",
            "amount": round(savings_gap, 2),
            "target": goal_label(goal),
            "action": f"Set aside ₹{savings_gap:,.0f} more each month toward your {goal_label(goal).lower()} goal.",
        })

    if not suggestions:
        suggestions.append({
            "title": "Protect your savings rate",
            "amount": round(desired_savings, 2),
            "target": goal_label(goal),
            "action": f"Automate a monthly transfer of around ₹{desired_savings:,.0f} before discretionary spending.",
        })

    suggestions.extend([
        {
            "title": "Review subscriptions and impulse spending",
            "amount": round(max(income * 0.02, 100), 2),
            "target": "monthly buffer",
            "action": "Audit recurring charges and remove one low-value expense each month.",
        },
        {
            "title": "Keep an emergency reserve",
            "amount": round(max(total_expenses * 0.05, 500), 2),
            "target": "emergency fund",
            "action": "Direct a small fixed amount toward a separate emergency reserve.",
        },
    ])
    suggestions = suggestions[:5]

    estimated_savings = max(income - total_expenses, 0)
    summary = {
        "income": round(income, 2),
        "expenses": round(total_expenses, 2),
        "estimated_savings": round(estimated_savings, 2),
        "savings_rate": round((estimated_savings / income) * 100, 1) if income else 0,
        "goal": goal_label(goal),
        "headline": "Your current cash flow is positive." if estimated_savings > 0 else "Your expenses currently consume all or more of your income.",
    }
    return {"budget": base_budget, "analysis": analysis, "suggestions": suggestions, "summary": summary}


def build_prompt(income, expenses, goal):
    expense_lines = "\n".join(
        f"- {category.replace('_', ' ').title()}: ₹{amount:,.2f}"
        for category, amount in expenses.items()
    )
    tips = ", ".join(f"{k}: {v}%" for k, v in CATEGORY_TIPS.items())
    goal_description = GOAL_DESCRIPTIONS.get(goal, GOAL_DESCRIPTIONS["general_savings"])
    return f"""
You are Personal Finance Advisor Bot, an educational budgeting assistant for an individual user in India.
Do not provide regulated investment, tax, insurance, or lending advice. Do not claim guaranteed returns.
Use Indian rupee formatting conceptually, but return numeric values only in JSON fields.

Monthly income: ₹{income:,.2f}
Expense categories:
{expense_lines}

Financial goal: {goal_label(goal)}
Goal guidance: {goal_description}

Category guideline percentages used by this project:
{tips}

Create a practical monthly plan that respects essential expenses, identifies overspending, and encourages sustainable saving.
Return STRICT JSON with these keys only: budget, analysis, suggestions, summary.
- budget: array of objects with category, recommended_amount, percentage, reason.
- analysis: array of objects with category, spent, percentage, status, message. status must be on_track, review, or overspending.
- suggestions: 3 to 5 actionable objects with title, amount, target, action.
- summary: object with income, expenses, estimated_savings, savings_rate, goal, headline.
Keep arithmetic consistent with the supplied income and expenses.
""".strip()


def extract_json(text):
    """Robust JSON extractor: direct JSON, fenced JSON, then raw object extraction."""
    if not text:
        raise ValueError("The AI response was empty.")
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Unable to parse AI JSON: {exc}") from exc
    raise ValueError("No JSON object found in the AI response.")


def validate_result(data, income, expenses, goal):
    if not isinstance(data, dict):
        raise ValueError("AI result must be a JSON object.")
    for key in ("budget", "analysis", "suggestions", "summary"):
        if key not in data:
            raise ValueError(f"AI result is missing required key: {key}")
    # Ensure the core summary stays mathematically grounded even if the model is imprecise.
    total_expenses = round(sum(amount for category, amount in expenses.items() if category != "savings"), 2)
    savings_contribution = round(expenses.get("savings", 0), 2)
    estimated_savings = round(min(income - total_expenses, income), 2) if income >= total_expenses else 0
    data["summary"] = {
        "income": income,
        "expenses": total_expenses,
        "estimated_savings": estimated_savings,
        "savings_rate": round(estimated_savings / income * 100, 1) if income else 0,
        "goal": goal_label(goal),
        "headline": data.get("summary", {}).get("headline") or "Review your spending and savings plan below.",
    }
    return data


def get_gemini_client():
    if not GEMINI_API_KEY:
        return None
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)


def generate_financial_advice(income, expenses, goal):
    baseline = local_budget_plan(income, expenses, goal)
    client = get_gemini_client()
    if client is None or DEMO_MODE:
        baseline["summary"]["headline"] += " Demo/local mode is active; Gemini can be enabled with GEMINI_API_KEY."
        return baseline

    from google.genai import types

    prompt = build_prompt(income, expenses, goal)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=2048,
            response_mime_type="application/json",
            response_json_schema=BUDGET_SCHEMA,
        ),
    )
    parsed = extract_json(response.text)
    return validate_result(parsed, income, expenses, goal)


def current_month():
    return datetime.utcnow().strftime("%Y-%m")


def api_json_error(message, status=400):
    return jsonify({"success": False, "error": message}), status


def validate_auth_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid request body.")
    return payload


def ownership_required(model_cls):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            resource_id = kwargs.get("resource_id") or request.view_args.get("resource_id")
            resource = db.session.get(model_cls, resource_id)
            if not resource or resource.user_id != current_user.id:
                return api_json_error("Resource not found.", 404)
            request.resource = resource
            return func(*args, **kwargs)
        return wrapper
    return decorator


@app.context_processor
def inject_globals():
    return {"gemini_model": GEMINI_MODEL, "demo_mode": DEMO_MODE}


@app.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    return render_template("index.html", user=current_user)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "GET":
        return render_template("auth.html", mode="register")
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if len(name) < 2 or len(name) > 120:
        return api_json_error("Name must be between 2 and 120 characters.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return api_json_error("Please provide a valid email address.")
    if len(password) < 6:
        return api_json_error("Password must be at least 6 characters.")
    if db.session.scalar(db.select(User).where(User.email == email)):
        return api_json_error("An account with that email already exists.")
    user = User(name=name, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "GET":
        return render_template("auth.html", mode="login")
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    user = db.session.scalar(db.select(User).where(User.email == email))
    if not user or not user.check_password(password):
        return api_json_error("Invalid email or password.")
    login_user(user, remember=False)
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/analyse", methods=["POST"])
@login_required
def analyse():
    try:
        payload = validate_auth_payload(request.get_json(silent=True) or {})
        income = clean_amount(payload.get("income"), "Income", minimum=1)
        expenses = normalise_expenses(payload.get("expenses", {}))
        goal = str(payload.get("goal", "general_savings")).strip().lower()
        if goal not in GOAL_DESCRIPTIONS:
            goal = "general_savings"

        result = generate_financial_advice(income, expenses, goal)
        month = current_month()
        db.session.add(Income(user_id=current_user.id, amount=income, source="Analysis income", month=month))
        for category, amount in expenses.items():
            db.session.add(Expense(user_id=current_user.id, category=category, amount=amount, month=month))
        summary = result["summary"]
        record = AnalysisResult(
            user_id=current_user.id,
            month=month,
            goal=goal,
            income=income,
            expenses=summary["expenses"],
            estimated_savings=summary["estimated_savings"],
            savings_rate=summary["savings_rate"],
            payload_json=json.dumps(result),
        )
        db.session.add(record)
        db.session.commit()
        return jsonify({"success": True, **result})
    except ValueError as exc:
        db.session.rollback()
        return api_json_error(str(exc), 400)
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Financial analysis failed")
        return api_json_error("The advisor could not generate a response right now. Check your API configuration and try again.", 500)


@app.route("/generate", methods=["POST"])
@login_required
def generate_content():
    payload = request.get_json(silent=True) or {}
    product_info = str(payload.get("product_info", "")).strip()
    platform = str(payload.get("platform", "web")).strip() or "web"
    tone = str(payload.get("tone", "professional")).strip() or "professional"
    if not product_info:
        return api_json_error("product_info is required.")
    if len(product_info) > 2000:
        return api_json_error("product_info cannot exceed 2000 characters.")
    if not GEMINI_API_KEY or DEMO_MODE:
        return jsonify({
            "success": True,
            "content": f"{tone.title()} copy for {platform}: {product_info[:500]}",
            "demo_mode": True,
        })

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "Create concise, user-friendly content for a personal finance education product. "
            f"Platform: {platform}. Tone: {tone}. Product information: {product_info}. "
            "Avoid regulated financial claims, guarantees, or misleading promises."
        )
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=700),
        )
        return jsonify({"success": True, "content": response.text})
    except Exception:
        app.logger.exception("Generate route failed")
        return api_json_error("Unable to generate content right now.", 500)


@app.route("/api/summary")
@login_required
def api_summary():
    month = request.args.get("month", current_month())
    incomes = db.session.scalars(db.select(Income).where(Income.user_id == current_user.id, Income.month == month)).all()
    expenses = db.session.scalars(db.select(Expense).where(Expense.user_id == current_user.id, Expense.month == month)).all()
    income_total = round(sum(item.amount for item in incomes), 2)
    expense_total = round(sum(item.amount for item in expenses if item.category != "savings"), 2)
    savings_contribution = round(sum(item.amount for item in expenses if item.category == "savings"), 2)
    savings = max(round(income_total - expense_total, 2), 0)
    category_totals = {}
    for item in expenses:
        if item.category == "savings":
            continue
        category_totals[item.category] = round(category_totals.get(item.category, 0) + item.amount, 2)
    return jsonify({
        "success": True,
        "month": month,
        "income": income_total,
        "expenses": expense_total,
        "savings": savings,
        "savings_contribution": savings_contribution,
        "savings_rate": round(savings / income_total * 100, 1) if income_total else 0,
        "category_totals": category_totals,
    })


@app.route("/api/transactions", methods=["GET", "POST"])
@login_required
def transactions():
    if request.method == "GET":
        month = request.args.get("month", current_month())
        incomes = db.session.scalars(db.select(Income).where(Income.user_id == current_user.id, Income.month == month).order_by(Income.created_at.desc())).all()
        expenses = db.session.scalars(db.select(Expense).where(Expense.user_id == current_user.id, Expense.month == month).order_by(Expense.created_at.desc())).all()
        return jsonify({
            "success": True,
            "income": [
                {"id": i.id, "amount": i.amount, "source": i.source, "month": i.month} for i in incomes
            ],
            "expenses": [
                {"id": e.id, "category": e.category, "amount": e.amount, "note": e.note, "month": e.month} for e in expenses
            ],
        })

    payload = request.get_json(silent=True) or {}
    kind = payload.get("type")
    amount = clean_amount(payload.get("amount"), "Amount", minimum=0.01)
    month = str(payload.get("month", current_month()))
    if not re.match(r"^\d{4}-\d{2}$", month):
        return api_json_error("Month must use YYYY-MM format.")
    if kind == "income":
        source = str(payload.get("source", "Additional income")).strip()[:120] or "Additional income"
        db.session.add(Income(user_id=current_user.id, amount=amount, source=source, month=month))
    elif kind == "expense":
        category = str(payload.get("category", "other")).strip().lower().replace(" ", "_")[:60]
        note = str(payload.get("note", "")).strip()[:255]
        db.session.add(Expense(user_id=current_user.id, category=category, amount=amount, note=note, month=month))
    else:
        return api_json_error("type must be income or expense.")
    db.session.commit()
    return jsonify({"success": True, "message": "Transaction saved."})


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "service": "Personal Finance Advisor Bot",
        "gemini_configured": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
        "demo_mode": DEMO_MODE,
    })


def initialise_database():
    with app.app_context():
        db.create_all()


initialise_database()


if __name__ == "__main__":
    initialise_database()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
