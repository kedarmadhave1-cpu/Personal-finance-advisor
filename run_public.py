import os
import threading
import time
import webbrowser

from dotenv import load_dotenv
from pyngrok import ngrok

load_dotenv()

PORT = int(os.getenv("PORT", "5000"))
AUTH_TOKEN = os.getenv("NGROK_AUTHTOKEN", "").strip()

if not AUTH_TOKEN:
    raise SystemExit(
        "Missing NGROK_AUTHTOKEN. Add it to your .env file before running run_public.py."
    )

# Import after env loading so app configuration is ready.
from app import app, initialise_database  # noqa: E402

initialise_database()

ngrok.set_auth_token(AUTH_TOKEN)


def start_flask():
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(1.5)

    tunnel = ngrok.connect(PORT, "http")
    public_url = tunnel.public_url
    print("\n===============================================")
    print("YOUR PERSONAL FINANCE ADVISOR IS LIVE!")
    print(f"PUBLIC URL: {public_url}")
    print("===============================================\n")
    print("Keep this terminal and Flask process running while your mentor tests the demo.")

    try:
        webbrowser.open(public_url)
    except Exception:
        pass

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping public tunnel...")
        ngrok.disconnect(public_url)
        ngrok.kill()
