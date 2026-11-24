# winefinder

pip install -r requirements.txt

Start development

- python app.py

Start Prod:
.\.venv\Scripts\Activate.ps1
$env:FLASK_SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
waitress-serve --host=0.0.0.0 --port=5000 --threads=4 app:app

PW db test:
Camille: vin2026
