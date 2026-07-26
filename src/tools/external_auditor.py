"""
Standalone Affinda ATS parser API integration client.
This module is strictly decoupled from the core CV-generation pipeline.
"""

import os
import time
import logging
import json
import requests
from pathlib import Path
from typing import Any, Dict

from utils import validate_path

logger = logging.getLogger(__name__)

AFFINDA_API_URL = "https://api.eu1.affinda.com/v3/documents"
AFFINDA_JD_URL = "https://api.eu1.affinda.com/v3/job_descriptions"
APPLICATION_JSON = "application/json"


class AffindaError(Exception):
    """Custom exception for Affinda API operations."""
    pass


class AffindaParserClient:
    """Client for interacting with Affinda's resume parsing and scoring API."""

    def __init__(self, api_key: str | None = None, workspace_id: str | None = None, collection_id: str | None = None, document_type: str | None = None, document_type_jd: str | None = None) -> None:
        self.api_key = api_key or os.getenv("AFFINDA_API_KEY")
        self.workspace_id = workspace_id or os.getenv("AFFINDA_WORKSPACE")
        self.collection_id = collection_id or os.getenv("AFFINDA_COLLECTION")
        self.document_type = document_type or os.getenv("AFFINDA_DOC_TYPE")
        self.document_type_jd = document_type_jd or os.getenv("AFFINDA_JD_DOC_TYPE", "ueDuQHvt")
        if not self.api_key:
            logger.warning("No AFFINDA_API_KEY found. Running in MOCK Mode.")

    def _upload_doc_payload(self, file_path: Path, doc_type_val: str | None, is_jd: bool) -> Dict[str, Any]:
        """Send the file upload POST request to Affinda API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": APPLICATION_JSON
        }

        data = {}
        if self.workspace_id:
            data["workspace"] = self.workspace_id
        if self.collection_id and not is_jd:
            data["collection"] = self.collection_id
        if doc_type_val:
            data["documentType"] = doc_type_val

        safe_path = validate_path(file_path)
        with open(safe_path, "rb") as f:
            files = {"file": (safe_path.name, f, "application/octet-stream")}
            response = requests.post(AFFINDA_API_URL, headers=headers, files=files, data=data)

        if response.status_code not in (200, 201):
            raise AffindaError(f"Affinda Upload Failed ({response.status_code}): {response.text}")

        return response.json()

    def _poll_doc_status(self, identifier: str, headers: dict[str, str]) -> Dict[str, Any]:
        """Poll the Affinda API until the document is processed or failed."""
        poll_url = f"{AFFINDA_API_URL}/{identifier}?compact=true"
        max_attempts = 20
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            time.sleep(10)
            poll_resp = requests.get(poll_url, headers=headers)
            
            if poll_resp.status_code != 200:
                logger.warning(f"Failed to poll Affinda: {poll_resp.status_code}. Retrying...")
                continue

            doc_data = poll_resp.json()
            meta_obj = doc_data.get("meta", {})
            is_ready = doc_data.get("ready") or meta_obj.get("ready")
            is_failed = doc_data.get("failed") or meta_obj.get("failed")
            status = doc_data.get("status") or meta_obj.get("status")

            if is_failed:
                raise AffindaError("Affinda report generation failed on the server.")
            if (status == "completed") or (is_ready is True):
                return doc_data

            logger.info(f"⏳ Processing: ready={is_ready}, status='{status}'. Polling in 10 seconds (Attempt {attempt}/{max_attempts})...")

        raise TimeoutError("Affinda parsing timed out before completion.")

    def _upload_and_poll_document(
        self,
        file_path: Path,
        doc_type_val: str | None,
        debug_filename: str,
        is_jd: bool = False
    ) -> Dict[str, Any]:
        """Helper to upload and poll a document from Affinda API, keeping complexity extremely low."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found at: {file_path}")

        document_data = self._upload_doc_payload(file_path, doc_type_val, is_jd)
        
        try:
            debug_path = validate_path(Path("ai-generated-cvs") / debug_filename)
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_path, "w") as f_debug:
                json.dump(document_data, f_debug, indent=2)
        except Exception as ex:
            logger.warning(f"Could not dump debug file: {ex}")

        identifier = document_data.get("identifier") or document_data.get("meta", {}).get("identifier")
        if not identifier:
            raise AffindaError("No document identifier returned from Affinda upload.")

        meta_obj = document_data.get("meta", {})
        is_ready = document_data.get("ready") or meta_obj.get("ready")
        is_failed = document_data.get("failed") or meta_obj.get("failed")
        status = document_data.get("status") or meta_obj.get("status")

        if is_failed:
            raise AffindaError("Affinda report generation failed on the server.")
        if (status == "completed") or (is_ready is True):
            logger.info("✨ Affinda parsing completed successfully!")
            return document_data

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": APPLICATION_JSON
        }
        res = self._poll_doc_status(identifier, headers)
        logger.info("✨ Affinda parsing completed successfully!")
        return res

    def parse_resume(self, file_path: Path) -> Dict[str, Any]:
        """Upload a PDF/DOCX resume file to Affinda, poll for completion, and return structured JSON."""
        if not self.api_key:
            return self._get_mock_parse_response(file_path)
        return self._upload_and_poll_document(file_path, self.document_type, "affinda_debug_response.json")

    def parse_job_description(self, file_path: Path) -> Dict[str, Any]:
        """Upload a job description file to Affinda, poll for completion, and return structured JSON."""
        if not self.api_key:
            return {
                "meta": {"identifier": "mock-jd-98765", "status": "completed"},
                "data": {"name": "Mock Job Description"}
            }
        return self._upload_and_poll_document(file_path, self.document_type_jd, "affinda_jd_debug_response.json", is_jd=True)

    def get_native_match(self, resume_id: str, jd_id: str) -> Dict[str, Any]:
        """Fetch the native resume-to-job matching score and breakdown from Affinda."""
        if not self.api_key:
            # Provide a beautiful mocked native match response for offline mode
            return {
                "score": 0.82,
                "details": {
                    "jobTitle": {"label": "Job Title", "value": "Senior Software Engineering Manager", "score": 0.95},
                    "experience": {"label": "Experience", "value": "Strong management background", "score": 0.88},
                    "skills": {"label": "Skills", "value": "Excellent skill overlap", "score": 0.92},
                    "languages": {"label": "Languages", "value": None, "score": None},
                    "location": {"label": "Location", "value": "Limerick, Ireland", "score": 0.90},
                    "education": {"label": "Education", "value": "CS Degree", "score": 0.85},
                    "managementLevel": {"label": "Management Level", "value": "Manager/Director", "score": 0.95},
                    "occupationGroup": {"label": "Occupation Group", "value": "Technology", "score": 0.90},
                    "searchExpression": {"label": "Search Expression", "value": None, "score": None}
                }
            }

        logger.info("🔍 Requesting native match score from Affinda Search & Match API...")
        match_url = "https://api.eu1.affinda.com/v3/resume_search/match"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": APPLICATION_JSON
        }
        params = {
            "resume": resume_id,
            "job_description": jd_id,
            "skills_weight": "1.0",
            "years_experience_weight": "1.0",
            "job_titles_weight": "1.0",
            "management_level_weight": "1.0"
        }

        response = requests.get(match_url, headers=headers, params=params)
        if response.status_code != 200:
            logger.warning(f"⚠️ Native match API request failed ({response.status_code}): {response.text}")
            return {}

        return response.json()

    def add_to_index(self, resume_id: str, index_name: str = "Resume-Search-Demo") -> Dict[str, Any]:
        """Index a resume document into a specific search index."""
        if not self.api_key:
            logger.info(f"🔧 [MOCK MODE] Simulating indexing document {resume_id} into {index_name}")
            return {"document": resume_id, "index": index_name}

        logger.info(f"⚡ Indexing resume {resume_id} into index '{index_name}'...")
        url = f"https://api.eu1.affinda.com/v3/index/{index_name}/documents"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": APPLICATION_JSON,
            "Accept": APPLICATION_JSON
        }
        payload = {
            "document": resume_id
        }

        response = requests.post(url, headers=headers, json=payload)
        if response.status_code not in (200, 201):
            logger.warning(f"⚠️ Indexing document failed ({response.status_code}): {response.text}")
            if "does not exist" in response.text or response.status_code == 404:
                logger.info(f"🏗️ Index '{index_name}' does not exist. Creating it...")
                create_url = "https://api.eu1.affinda.com/v3/index"
                create_payload = {
                    "name": index_name,
                    "docType": "resumes"
                }
                create_resp = requests.post(create_url, headers=headers, json=create_payload)
                if create_resp.status_code in (200, 201):
                    logger.info(f"✅ Index '{index_name}' created successfully. Retrying indexing...")
                    response = requests.post(url, headers=headers, json=payload)
                else:
                    logger.error(f"❌ Failed to create index '{index_name}': {create_resp.text}")

        if response.status_code in (200, 201):
            logger.info(f"✅ Successfully indexed resume {resume_id} in '{index_name}'!")
            return response.json()
        else:
            raise AffindaError(f"Failed to add resume to search index: {response.text}")

    def _get_mock_parse_response(self, file_path: Path) -> Dict[str, Any]:
        """Provides a realistic mocked Affinda parsed response for testing and offline modes."""
        logger.info(f"🔧 [MOCK MODE] Generating simulated parsing results for {file_path.name}")
        return {
            "meta": {
                "identifier": "mock-document-12345",
                "status": "completed",
                "fileName": file_path.name
            },
            "data": {
                "name": {
                    "raw": "Mock Candidate",
                    "first": "Mock",
                    "last": "Candidate"
                },
                "emails": ["mock@example.com"],
                "phones": ["+1234567890"],
                "skills": [
                    {"name": "Python", "type": "hard_skill"},
                    {"name": "Kubernetes", "type": "hard_skill"},
                    {"name": "CI/CD", "type": "hard_skill"},
                    {"name": "GitOps", "type": "hard_skill"},
                    {"name": "Platform Engineering", "type": "hard_skill"},
                    {"name": "Observability", "type": "hard_skill"},
                    {"name": "Agile", "type": "soft_skill"},
                    {"name": "Technical Architecture", "type": "hard_skill"},
                    {"name": "Management", "type": "soft_skill"}
                ],
                "workExperience": [
                    {
                        "jobTitle": "Senior Software Engineering Manager",
                        "organization": "Virgin Media",
                        "startDate": "2020-01-01",
                        "endDate": None,
                        "jobDescription": "Managed AI platform engineering and cloud infrastructure automation."
                    },
                    {
                        "jobTitle": "Lead Architect",
                        "organization": "Intel Corporation",
                        "startDate": "2016-05-01",
                        "endDate": "2019-12-31",
                        "jobDescription": "Designed global high-performance microservices and cloud infrastructure."
                    }
                ],
                "education": [
                    {
                        "degree": "Bachelor of Science in Computer Science",
                        "organization": "Tech University",
                        "startDate": "2010-09-01",
                        "endDate": "2014-06-01"
                    }
                ]
            }
        }
