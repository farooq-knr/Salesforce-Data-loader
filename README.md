# Salesforce DataLoader (Python)

This simple Python data loader reads tabular data (CSV/Excel), maps columns to Salesforce fields using a JSON mapping file, and upserts/inserts records into Salesforce via the REST API.

Features:
- Read .xlsx or .csv files (pandas)
- Mapping file (JSON) that maps input column names to Salesforce object field API names
- Supports insert and upsert (external Id) using simple-salesforce or REST
- Configured via environment variables or .env file
- Logs successes and failures to CSV

Getting started:
1. Create a Python virtualenv and install dependencies:
   pip install -r requirements.txt

2. Copy `.env.example` to `.env` and fill in credentials:
   - SF_USERNAME
   - SF_PASSWORD
   - SF_SECURITY_TOKEN (if required)
   - SF_DOMAIN (login or test)
   - SF_CLIENT_ID (optional for OAuth flow)

3. Prepare your mapping JSON (see sample_mapping.json).

4. Run the loader:
   python loader.py --input sample.csv --mapping sample_mapping.json --object Account --operation insert

Notes:
- For production use, prefer OAuth connected app and more robust error handling.