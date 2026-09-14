# CV Gemini Streamlit Screening App

This app does:

Local PDF CV folder
→ Gemini API screening
→ Fit score 0–100
→ Candidates >= 80% shown on dashboard
→ Name / email / phone / score displayed
→ "Save to file" appends the candidate to an existing Google Sheet

## 1. Install Python

Use Python 3.10+.

## 2. Install dependencies

Open PowerShell in this folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Get a Gemini API key

Create a Gemini API key through Google AI Studio and put it in the sidebar when the app starts, or put it in `.env`.

The app uses the Google GenAI Python SDK and Gemini structured JSON output so the application receives predictable fields for name, email, phone, fit score and rationale.

## 4. Google Sheets setup

The app uses a Google service account for writing to the existing spreadsheet.

1. Create/select a Google Cloud project.
2. Enable Google Sheets API and Google Drive API.
3. Create a service account.
4. Create/download its JSON key.
5. Put the JSON file somewhere safe on the PC.
6. Open your existing Google Sheet.
7. Share the sheet with the service account's `client_email` as an Editor.
8. Put the Sheet URL, JSON path and worksheet name into the sidebar.

The first save creates headers if the worksheet is empty:

Name | Email | Phone | Fit Score | CV File

## 5. Run

```powershell
streamlit run app.py
```

The browser dashboard will open.

## 6. Use

1. Enter the local folder containing PDF CVs.
2. Paste the job description.
3. Add any extra screening instructions.
4. Enter the Gemini API key.
5. Click **Scan and Screen All CVs**.
6. Candidates at or above the threshold are shown.
7. Click **Save to file** for a candidate to append that candidate to Google Sheets.

## Important

- This app processes CVs on the computer where Streamlit is running.
- Gemini receives the CV content/file for screening.
- Do not commit `.env` or service-account JSON credentials to Git.
- For production recruitment use, review GDPR/data-processing requirements before sending applicant CVs to an external AI API.
