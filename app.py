import os
import json
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
import gspread
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Page configuration
# -----------------------------
st.set_page_config(
    page_title="CV Fit Screening",
    page_icon="📄",
    layout="wide",
)

st.title("📄 CV Fit Screening Dashboard")
st.caption("Local PDF CVs → Gemini API → Fit Score → Google Sheets")

# -----------------------------
# Structured Gemini response
# -----------------------------
class ScreeningResult(BaseModel):
    name: str = Field(description="Candidate's full name. Use an empty string if not found.")
    email: str = Field(description="Candidate's contact email. Use an empty string if not found.")
    phone: str = Field(description="Candidate's contact phone number. Use an empty string if not found.")
    fit_score: float = Field(description="Overall job fit score from 0 to 100.")
    rationale: str = Field(description="Short explanation of the most important reasons for the score.")

# -----------------------------
# Helpers
# -----------------------------
def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)

def screen_cv(client, model_name: str, pdf_path: Path, job_description: str, instructions: str):
    uploaded = client.files.upload(file=pdf_path)

    prompt = f"""
You are an expert recruitment screening assistant.

JOB DESCRIPTION:
{job_description}

USER INSTRUCTIONS:
{instructions}

TASK:
Evaluate the attached CV against the job description.

Scoring rules:
- Return a fit_score from 0 to 100.
- Base the score only on evidence in the CV and the supplied job description.
- Consider relevant skills, experience, education, responsibilities, tools/technologies,
  seniority and other explicit requirements.
- Do not invent missing information.
- Missing information should not automatically mean the candidate is unsuitable,
  but do not assume that an unstated qualification exists.
- Extract the candidate's name, email and phone number from the CV.
- Keep the rationale concise.
"""

    response = client.models.generate_content(
        model=model_name,
        contents=[prompt, uploaded],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ScreeningResult,
            temperature=0.1,
        ),
    )

    result = ScreeningResult.model_validate_json(response.text)
    result.fit_score = max(0, min(100, float(result.fit_score)))
    return result

def get_gsheet_client(credentials_path: str):
    return gspread.service_account(filename=credentials_path)

def save_to_google_sheet(credentials_path: str, spreadsheet_url: str,
                          worksheet_name: str, candidate: dict):
    gc = get_gsheet_client(credentials_path)
    sh = gc.open_by_url(spreadsheet_url)
    ws = sh.worksheet(worksheet_name)

    # Create headers if the sheet is empty.
    existing = ws.get_all_values()
    if not existing:
        ws.append_row(["Name", "Email", "Phone", "Fit Score", "CV File"])

    ws.append_row([
        candidate.get("name", ""),
        candidate.get("email", ""),
        candidate.get("phone", ""),
        candidate.get("fit_score", ""),
        candidate.get("file", ""),
    ])

# -----------------------------
# Sidebar configuration
# -----------------------------
with st.sidebar:
    st.header("⚙️ Configuration")

    default_folder = os.getenv("CV_FOLDER", "")
    cv_folder = st.text_input(
        "Local CV folder",
        value=default_folder,
        placeholder=r"C:\CVs",
        help="Folder containing PDF CVs on the computer running Streamlit.",
    )

    api_key = st.text_input(
        "Gemini API key",
        value=os.getenv("GEMINI_API_KEY", ""),
        type="password",
    )

    model_name = st.text_input(
        "Gemini model",
        value=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    )

    threshold = st.number_input(
        "Shortlist threshold (%)",
        min_value=0,
        max_value=100,
        value=80,
        step=1,
    )

    st.divider()
    st.subheader("Google Sheets")

    credentials_path = st.text_input(
        "Service account JSON",
        value=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
        placeholder=r"C:\cv-screening\service_account.json",
    )

    spreadsheet_url = st.text_input(
        "Existing Google Sheet URL",
        value=os.getenv("GOOGLE_SHEET_URL", ""),
    )

    worksheet_name = st.text_input(
        "Worksheet name",
        value=os.getenv("GOOGLE_WORKSHEET", "Sheet1"),
    )

# -----------------------------
# Main inputs
# -----------------------------
col1, col2 = st.columns(2)

with col1:
    st.subheader("Job Description")
    job_description = st.text_area(
        "Paste the job description",
        height=300,
        placeholder="Paste the complete job description here...",
    )

with col2:
    st.subheader("Screening Instructions")
    instructions = st.text_area(
        "Additional instructions for Gemini",
        height=300,
        value=(
            "Prioritize mandatory requirements over nice-to-have requirements. "
            "Give the final score as a percentage from 0 to 100. "
            "Be conservative and evidence-based."
        ),
    )

# -----------------------------
# Scan / analyze
# -----------------------------
if "results" not in st.session_state:
    st.session_state.results = []

if "screening_errors" not in st.session_state:
    st.session_state.screening_errors = []

if st.button("🚀 Scan and Screen All CVs", type="primary", use_container_width=True):
    st.session_state.results = []
    st.session_state.screening_errors = []

    if not cv_folder:
        st.error("Please enter the local CV folder path.")
        st.stop()

    folder = Path(cv_folder)
    if not folder.exists() or not folder.is_dir():
        st.error(f"Folder does not exist: {folder}")
        st.stop()

    if not api_key:
        st.error("Please enter your Gemini API key.")
        st.stop()

    if not job_description.strip():
        st.error("Please enter the job description.")
        st.stop()

    pdf_files = sorted(folder.glob("*.pdf"))
    if not pdf_files:
        st.warning("No PDF files were found in the selected folder.")
        st.stop()

    client = get_gemini_client(api_key)

    progress = st.progress(0)
    status = st.empty()

    for i, pdf_path in enumerate(pdf_files, start=1):
        status.write(f"Screening {i}/{len(pdf_files)}: `{pdf_path.name}`")

        try:
            result = screen_cv(
                client=client,
                model_name=model_name,
                pdf_path=pdf_path,
                job_description=job_description,
                instructions=instructions,
            )

            st.session_state.results.append({
                "file": pdf_path.name,
                "path": str(pdf_path),
                "name": result.name,
                "email": result.email,
                "phone": result.phone,
                "fit_score": round(result.fit_score, 1),
                "rationale": result.rationale,
            })

        except Exception as e:
            st.session_state.screening_errors.append({
                "file": pdf_path.name,
                "error": str(e),
            })

        progress.progress(i / len(pdf_files))

    status.success(f"Finished screening {len(pdf_files)} PDF(s).")

# -----------------------------
# Dashboard
# -----------------------------
if st.session_state.results:
    st.divider()

    all_df = pd.DataFrame(st.session_state.results)
    shortlisted_df = all_df[all_df["fit_score"] >= threshold].copy()
    shortlisted_df = shortlisted_df.sort_values("fit_score", ascending=False)

    m1, m2, m3 = st.columns(3)
    m1.metric("CVs screened", len(all_df))
    m2.metric("Shortlisted", len(shortlisted_df))
    m3.metric("Threshold", f"{threshold:.0f}%")

    st.subheader(f"✅ Shortlisted Candidates (≥ {threshold:.0f}%)")

    if shortlisted_df.empty:
        st.info("No candidates reached the configured threshold.")
    else:
        st.caption("Click **Save to file** to append the candidate to the configured Google Sheet.")

        for idx, row in shortlisted_df.reset_index(drop=True).iterrows():
            c1, c2, c3, c4, c5, c6 = st.columns([2.1, 2.3, 1.7, 1.0, 2.8, 1.3])

            c1.write(row["name"] or "Not found")
            c2.write(row["email"] or "Not found")
            c3.write(row["phone"] or "Not found")
            c4.metric("Fit", f'{row["fit_score"]:.1f}%')
            c5.write(row["file"])

            if c6.button("Save to file", key=f"save_{row['file']}_{idx}"):
                if not credentials_path:
                    st.error("Add the Google service-account JSON path in the sidebar.")
                elif not spreadsheet_url:
                    st.error("Add the existing Google Sheet URL in the sidebar.")
                else:
                    try:
                        save_to_google_sheet(
                            credentials_path=credentials_path,
                            spreadsheet_url=spreadsheet_url,
                            worksheet_name=worksheet_name,
                            candidate=row.to_dict(),
                        )
                        st.success(f"Saved {row['name'] or row['file']} to Google Sheets.")
                    except Exception as e:
                        st.error(f"Could not save to Google Sheets: {e}")

            with st.expander("View screening rationale"):
                st.write(row["rationale"])

    st.subheader("All screened CVs")
    display_df = all_df[["file", "name", "email", "phone", "fit_score", "rationale"]].copy()
    display_df = display_df.sort_values("fit_score", ascending=False)
    display_df["fit_score"] = display_df["fit_score"].map(lambda x: f"{x:.1f}%")
    display_df.columns = ["CV", "Name", "Email", "Phone", "Fit Score", "Rationale"]
    st.dataframe(display_df, use_container_width=True, hide_index=True)

if st.session_state.screening_errors:
    st.warning(f"{len(st.session_state.screening_errors)} CV(s) could not be screened.")
    with st.expander("Show errors"):
        st.json(st.session_state.screening_errors)

st.divider()
st.caption("Tip: Keep API keys and Google service-account credentials out of Git repositories.")
