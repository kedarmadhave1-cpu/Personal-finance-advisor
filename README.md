# Personal Finance Advisor Bot

An AI-powered personal finance planning assistant built for the **SkillWallet · AI Specialist – BFSI** capstone.

The application combines:

- Flask backend + Jinja2 templates
- SQLAlchemy + SQLite persistence
- Flask-Login authentication
- Gemini AI for structured financial analysis
- Responsive HTML/CSS/JavaScript UI
- AJAX `POST /analyse` workflow
- Robust JSON parsing and validation
- Optional Ngrok public deployment

> **Model note:** The original SkillWallet instructions reference `gemini-2.0-flash`. Google lists that model as shut down, so this implementation defaults to the configurable `GEMINI_MODEL=gemini-3.8-flash`. Change the environment variable if Google makes a different model available to your account.

## Project structure

```text
personal_finance_advisor_bot/
├── app.py
├── run_public.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── docs/
│   ├── architecture.md
│   └── demo_script.md
├── templates/
│   ├── auth.html
│   └── index.html
├── static/
│   ├── css/style.css
│   ├── js/main.js
│   └── img/favicon.svg
└── tests/
    └── test_app.py
```

## 1. Create the environment

Windows Command Prompt:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure the environment

Copy `.env.example` to `.env`.

```text
GEMINI_API_KEY=your_real_key
GEMINI_MODEL=gemini-3.8-flash
FLASK_SECRET_KEY=your_long_random_secret
```

For a completely local UI test without Gemini, temporarily set:

```text
DEMO_MODE=true
```

**Never commit `.env`.** It is ignored by `.gitignore`.

## 3. Run locally

```bat
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Create an account, enter income and at least one expense, choose a goal, and click **Analyse My Finances**.

## 4. Public demo with Ngrok

Put your Ngrok token in `.env`:

```text
NGROK_AUTHTOKEN=your_ngrok_authtoken
```

Then run:

```bat
python run_public.py
```

The terminal prints a public URL similar to:

```text
https://xxxx-xxxx.ngrok-free.app
```

Use that URL as the **Demo Link** in SkillWallet while the script is running.

## 5. GitHub submission

Create a GitHub repository such as `Personal_Finance_Advisor_Bot` and upload the project files.

Submit in SkillWallet:

- **Demo Link:** the live Ngrok URL from `run_public.py`
- **GitHub Link:** the repository URL

## Core endpoints

- `GET /` — dashboard
- `GET|POST /register` — account registration
- `GET|POST /login` — account login
- `POST /logout` — secure logout
- `POST /analyse` — financial analysis + Gemini response
- `POST /generate` — structured AI content generation endpoint required by the project workflow
- `GET /api/summary` — current month's stored totals
- `GET|POST /api/transactions` — transaction storage/listing
- `GET /api/health` — simple deployment health check

## Financial logic

The app uses deterministic budget rules as a grounding layer and passes the same inputs and guideline percentages to Gemini. A `savings` entry is tracked separately from actual living/discretionary spending so the dashboard does not count money set aside as an expense. That prevents the model from becoming the sole calculator for basic arithmetic while still letting the model produce personalised narrative analysis.

SkillWallet project thresholds included in the implementation:

| Category | Guideline |
|---|---:|
| Rent | ≤ 30% |
| Food | < 15% |
| Transport | ≤ 10% |
| Entertainment | 5–8% |
| Savings | ≥ 20% |

Other categories are handled with practical project-level defaults.

## Security notes

- Gemini and Ngrok credentials are loaded from environment variables.
- Passwords are hashed using Werkzeug.
- Protected endpoints require login.
- User records are scoped by `user_id`.
- `.env` and SQLite database files are excluded from Git.
- Financial output includes an educational-use disclaimer.

## Optional PostgreSQL

The application accepts a normal SQLAlchemy `DATABASE_URL`, so you can point it to PostgreSQL later without changing the route logic.

## SkillWallet workflow mapping

**Epic 1 — Model Selection & Architecture**
- Gemini API configuration
- Current-model selection via environment variable
- Architecture documentation
- Virtual environment and dependencies

**Epic 2 — Core Functionalities**
- Budget generation
- Spending analysis
- Savings suggestions
- Flask backend

**Epic 3 — app.py**
- `/`, `/analyse`, `/generate`
- `CATEGORY_TIPS`
- `GOAL_DESCRIPTIONS`
- `build_prompt()`
- `extract_json()`
- required-key validation

**Epic 4 — Frontend**
- Responsive single-page dashboard
- Budget cards and progress bars
- Spending analysis chips
- Saving suggestions list
- Fetch API + animated loading state + smooth scroll

**Epic 5 — Deployment**
- Local Flask launch
- local testing
- Ngrok public deployment via `run_public.py`
