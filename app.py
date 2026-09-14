import os
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd
import gspread
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# PAGE CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="CV Fit Screening",
    page_icon="📄",
    layout="wide",
)

st.title("📄 CV Fit Screening Dashboard")
st.caption("Upload CVs → Gemini screening → Fit Score → Google Sheets")


# ============================================================
# GEMINI RESPONSE SCHEMA
# ============================================================
class ScreeningResult(BaseModel):
    name: str = Field(
        description="Candidate's full name. Use an empty string if not found."
    )
    email: str = Field(
        description="Candidate's contact email. Use an empty string if not found."
    )
    phone: str = Field(
        description="Candidate's contact phone number. Use an empty string if not found."
    )
    fit_score: float = Field(
        description="Overall job fit score from 0 to 100."
    )
    rationale: str = Field(
        description="Short explanation of the most important reasons for the score."
    )


# ============================================================
# HELPERS
# ============================================================
def get_secret(name: str, default: str = "") -> str:
    """Read Streamlit Secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, default)
        if value:
            return str(value)
    except Exception:
        pass

    return os.getenv(name, default)


def get_gemini_client(api_key: str):
    return genai.Client(api_key=api_key)


def screen_cv(
    client,
    model_name: str,
    pdf_path: Path,
    job_description: str,
    instructions: str,
):
    """Upload one PDF to Gemini and return structured screening results."""
    uploaded = client.files.upload(file=pdf_path)

    prompt = f"""
You are an expert recruitment screening assistant.

JOB DESCRIPTION:
{job_description}

USER INSTRUCTIONS:
{instructions}

TASK:
Evaluate the attached CV against the job description.

SCORING RULES:
- Return a fit_score from 0 to 100.
- Base the score only on evidence in the CV and the supplied job description.
- Consider relevant skills, experience, education, responsibilities,
  tools/technologies, seniority and other explicit requirements.
- Mandatory requirements should have more weight than nice-to-have requirements.
- Do not invent missing information.
- Missing information should not automatically mean the candidate is unsuitable,
  but do not assume that an unstated qualification exists.
- Extract the candidate's name, email and phone number from the CV.
- Keep the rationale concise and evidence-based.
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


# ============================================================
# GOOGLE SHEETS
# ============================================================
def get_gsheet_client():
    """
    Use Streamlit Cloud Secrets.

    Expected Secrets structure:

    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = """..."""
    client_email = "..."
    client_id = "..."
    auth_uri = "https://accounts.google.com/o/oauth2/auth"
    token_uri = "https://oauth2.googleapis.com/token"
    auth_provider_x509_cert_url = "..."
    client_x509_cert_url = "..."
    universe_domain = "googleapis.com"
    """
    try:
        credentials = dict(st.secrets["gcp_service_account"])
    except Exception as e:
        raise ValueError(
            "Google service-account credentials are missing. "
            "Add the [gcp_service_account] section in "
            "Streamlit Cloud → Settings → Secrets."
        ) from e

    return gspread.service_account_from_dict(credentials)


def test_google_sheet(spreadsheet_url: str, worksheet_name: str):
    """Test whether the configured service account can access the sheet."""
    gc = get_gsheet_client()
    spreadsheet = gc.open_by_url(spreadsheet_url)
    worksheet = spreadsheet.worksheet(worksheet_name)
    return spreadsheet.title, worksheet.title


def save_to_google_sheet(
    spreadsheet_url: str,
    worksheet_name: str,
    candidate: dict,
):
    """Append one candidate to the configured Google Sheet."""
    gc = get_gsheet_client()

    spreadsheet = gc.open_by_url(spreadsheet_url)
    worksheet = spreadsheet.worksheet(worksheet_name)

    existing = worksheet.get_all_values()

    if not existing:
        worksheet.append_row(
            [
                "Name",
                "Email",
                "Phone",
                "Fit Score",
                "CV File",
            ]
        )

    worksheet.append_row(
        [
            candidate.get("name", ""),
            candidate.get("email", ""),
            candidate.get("phone", ""),
            candidate.get("fit_score", ""),
            candidate.get("file", ""),
        ]
    )


# ============================================================
# TEMPORARY PDF FILE
# ============================================================
def save_uploaded_pdf(uploaded_file) -> Path:
    """Save a Streamlit uploaded PDF temporarily for Gemini."""
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf",
    ) as tmp:
        tmp.write(uploaded_file.getvalue())
        return Path(tmp.name)


# ============================================================
# SESSION STATE
# ============================================================
if "results" not in st.session_state:
    st.session_state.results = []

if "screening_errors" not in st.session_state:
    st.session_state.screening_errors = []


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.header("⚙️ Configuration")

    api_key = st.text_input(
        "Gemini API key",
        value=get_secret("GEMINI_API_KEY"),
        type="password",
        help="On Streamlit Cloud, store this in Secrets.",
    )

    model_name = st.text_input(
        "Gemini model",
        value=get_secret(
            "GEMINI_MODEL",
            "gemini-2.5-flash",
        ),
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

    spreadsheet_url = st.text_input(
        "Existing Google Sheet URL",
        value=get_secret("GOOGLE_SHEET_URL"),
        placeholder="https://docs.google.com/spreadsheets/d/...",
    )

    worksheet_name = st.text_input(
        "Worksheet name",
        value=get_secret("GOOGLE_WORKSHEET", "Sheet1"),
    )

    if st.button(
        "🔗 Test Google Sheets Connection",
        use_container_width=True,
    ):
        if not spreadsheet_url:
            st.error("Add the Google Sheet URL first.")
        else:
            try:
                spreadsheet_title, worksheet_title = test_google_sheet(
                    spreadsheet_url,
                    worksheet_name,
                )

                st.success(
                    f"Connected to '{spreadsheet_title}' → "
                    f"'{worksheet_title}'"
                )
            except Exception as e:
                st.error(f"Connection failed: {e}")


# ============================================================
# CV UPLOAD
# ============================================================
st.subheader("📤 Upload CVs")

uploaded_files = st.file_uploader(
    "Select all PDF CVs you want to screen",
    type=["pdf"],
    accept_multiple_files=True,
    help=(
        "Open your local CV folder and select multiple PDFs at once. "
        "On Windows, press Ctrl+A to select all PDFs."
    ),
)

if uploaded_files:
    total_size_mb = sum(
        len(file.getvalue()) for file in uploaded_files
    ) / (1024 * 1024)

    st.success(
        f"{len(uploaded_files)} PDF(s) selected • "
        f"{total_size_mb:.1f} MB total"
    )

    with st.expander("📄 View selected CVs"):
        for file in uploaded_files:
            st.write(f"• {file.name}")


# ============================================================
# JOB DESCRIPTION + INSTRUCTIONS
# ============================================================
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


# ============================================================
# SCREEN BUTTON
# ============================================================
if st.button(
    "🚀 Scan and Screen All Uploaded CVs",
    type="primary",
    use_container_width=True,
):
    st.session_state.results = []
    st.session_state.screening_errors = []

    if not uploaded_files:
        st.error("Please upload at least one PDF CV.")
        st.stop()

    if not api_key:
        st.error("Please configure your Gemini API key.")
        st.stop()

    if not job_description.strip():
        st.error("Please enter the job description.")
        st.stop()

    try:
        client = get_gemini_client(api_key)
    except Exception as e:
        st.error(f"Could not initialize Gemini: {e}")
        st.stop()

    progress = st.progress(0)
    status = st.empty()

    for i, uploaded_file in enumerate(uploaded_files, start=1):
        status.write(
            f"Screening {i}/{len(uploaded_files)}: "
            f"`{uploaded_file.name}`"
        )

        temp_path = None

        try:
            temp_path = save_uploaded_pdf(uploaded_file)

            result = screen_cv(
                client=client,
                model_name=model_name,
                pdf_path=temp_path,
                job_description=job_description,
                instructions=instructions,
            )

            st.session_state.results.append(
                {
                    "file": uploaded_file.name,
                    "name": result.name,
                    "email": result.email,
                    "phone": result.phone,
                    "fit_score": round(result.fit_score, 1),
                    "rationale": result.rationale,
                }
            )

        except Exception as e:
            st.session_state.screening_errors.append(
                {
                    "file": uploaded_file.name,
                    "error": str(e),
                }
            )

        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

        progress.progress(i / len(uploaded_files))

    status.success(
        f"Finished screening {len(uploaded_files)} PDF(s)."
    )


# ============================================================
# RESULTS DASHBOARD
# ============================================================
if st.session_state.results:
    st.divider()

    all_df = pd.DataFrame(st.session_state.results)

    shortlisted_df = all_df[
        all_df["fit_score"] >= threshold
    ].copy()

    shortlisted_df = shortlisted_df.sort_values(
        "fit_score",
        ascending=False,
    )

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------
    m1, m2, m3 = st.columns(3)

    m1.metric(
        "CVs screened",
        len(all_df),
    )

    m2.metric(
        "Shortlisted",
        len(shortlisted_df),
    )

    m3.metric(
        "Threshold",
        f"{threshold:.0f}%",
    )

    # --------------------------------------------------------
    # Shortlisted candidates
    # --------------------------------------------------------
    st.subheader(
        f"✅ Shortlisted Candidates (≥ {threshold:.0f}%)"
    )

    if shortlisted_df.empty:
        st.info(
            "No candidates reached the configured threshold."
        )

    else:
        st.caption(
            "Click **Save to Google Sheets** to add a candidate "
            "to the configured worksheet."
        )

        for idx, row in shortlisted_df.reset_index(drop=True).iterrows():

            c1, c2, c3, c4, c5, c6 = st.columns(
                [2.1, 2.3, 1.7, 1.0, 2.8, 1.6]
            )

            c1.write(row["name"] or "Not found")
            c2.write(row["email"] or "Not found")
            c3.write(row["phone"] or "Not found")
            c4.metric(
                "Fit",
                f'{row["fit_score"]:.1f}%',
            )
            c5.write(row["file"])

            if c6.button(
                "Save to Google Sheets",
                key=f"save_{row['file']}_{idx}",
            ):
                if not spreadsheet_url:
                    st.error(
                        "Add the Google Sheet URL in the sidebar."
                    )
                else:
                    try:
                        save_to_google_sheet(
                            spreadsheet_url=spreadsheet_url,
                            worksheet_name=worksheet_name,
                            candidate=row.to_dict(),
                        )

                        st.success(
                            f"Saved {row['name'] or row['file']} "
                            "to Google Sheets."
                        )

                    except Exception as e:
                        st.error(
                            f"Could not save to Google Sheets: {e}"
                        )

            with st.expander("View screening rationale"):
                st.write(row["rationale"])

    # --------------------------------------------------------
    # All screened CVs
    # --------------------------------------------------------
    st.subheader("All Screened CVs")

    display_df = all_df[
        [
            "file",
            "name",
            "email",
            "phone",
            "fit_score",
            "rationale",
        ]
    ].copy()

    display_df = display_df.sort_values(
        "fit_score",
        ascending=False,
    )

    display_df["fit_score"] = display_df[
        "fit_score"
    ].map(lambda x: f"{x:.1f}%")

    display_df.columns = [
        "CV",
        "Name",
        "Email",
        "Phone",
        "Fit Score",
        "Rationale",
    ]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# SCREENING ERRORS
# ============================================================
if st.session_state.screening_errors:
    st.warning(
        f"{len(st.session_state.screening_errors)} CV(s) "
        "could not be screened."
    )

    with st.expander("Show errors"):
        st.json(st.session_state.screening_errors)


st.divider()

st.caption(
    "API keys and Google service-account credentials are stored "
    "outside the application code."
)
