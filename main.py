import os
import io
import json
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import PyPDF2
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Google Drive ChatGPT Connector",
    description="FastAPI service that connects ChatGPT to Google Drive for file access",
    version="1.0.0"
)

security = HTTPBearer()

class FileInfo(BaseModel):
    id: str
    name: str

class FileContent(BaseModel):
    id: str
    name: str
    content: str

class DriveService:
    def __init__(self):
        self.service = None
        self.folder_id = os.getenv('GDRIVE_FOLDER_ID')
        if not self.folder_id:
            raise ValueError("GDRIVE_FOLDER_ID environment variable is required")

    def authenticate(self) -> None:
        """Authenticate with Google Drive API using service account credentials"""
        try:
            # Try service account authentication first
            credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if credentials_path and os.path.exists(credentials_path):
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
                self.service = build('drive', 'v3', credentials=credentials)
                logger.info("Authenticated using service account")
                return

            # Try service account JSON from environment variable
            credentials_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
            if credentials_json:
                credentials_info = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info,
                    scopes=['https://www.googleapis.com/auth/drive.readonly']
                )
                self.service = build('drive', 'v3', credentials=credentials)
                logger.info("Authenticated using service account JSON")
                return

            raise ValueError("No valid Google credentials found. Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON")

        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

    def list_files(self) -> List[FileInfo]:
        """List all files in the specified Google Drive folder"""
        if not self.service:
            self.authenticate()

        try:
            query = f"'{self.folder_id}' in parents and trashed=false"
            logger.info(f"Searching with query: {query}")
            results = self.service.files().list(
                q=query,
                fields="files(id, name, mimeType)"
            ).execute()

            files = results.get('files', [])
            logger.info(f"Found {len(files)} files: {files}")
            return [FileInfo(id=file['id'], name=file['name']) for file in files]

        except HttpError as e:
            logger.error(f"Error listing files: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Error listing files: {str(e)}")

    def get_file_content(self, file_id: str) -> FileContent:
        """Get the content of a specific file as text"""
        if not self.service:
            self.authenticate()

        try:
            # Get file metadata
            file_metadata = self.service.files().get(fileId=file_id).execute()
            file_name = file_metadata['name']
            mime_type = file_metadata['mimeType']

            content = ""

            if mime_type == 'application/vnd.google-apps.document':
                # Google Docs - export as plain text
                content = self._export_google_doc(file_id)
            elif mime_type == 'application/vnd.google-apps.spreadsheet':
                # Google Sheets - export as CSV
                content = self._export_google_sheet(file_id)
            elif mime_type == 'application/vnd.google-apps.presentation':
                # Google Slides - export as plain text
                content = self._export_google_slides(file_id)
            elif mime_type == 'application/pdf':
                # PDF - extract text
                content = self._extract_pdf_text(file_id)
            elif mime_type.startswith('text/'):
                # Plain text files
                content = self._download_text_file(file_id)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {mime_type}"
                )

            return FileContent(id=file_id, name=file_name, content=content)

        except HttpError as e:
            logger.error(f"Error getting file content: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Error getting file content: {str(e)}")

    def _export_google_doc(self, file_id: str) -> str:
        """Export Google Doc as plain text"""
        request = self.service.files().export_media(
            fileId=file_id,
            mimeType='text/plain'
        )
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        return fh.getvalue().decode('utf-8')

    def _export_google_sheet(self, file_id: str) -> str:
        """Export Google Sheet as CSV"""
        request = self.service.files().export_media(
            fileId=file_id,
            mimeType='text/csv'
        )
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        return fh.getvalue().decode('utf-8')

    def _export_google_slides(self, file_id: str) -> str:
        """Export Google Slides as plain text"""
        request = self.service.files().export_media(
            fileId=file_id,
            mimeType='text/plain'
        )
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        return fh.getvalue().decode('utf-8')

    def _extract_pdf_text(self, file_id: str) -> str:
        """Extract text from PDF using PyPDF2"""
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        fh.seek(0)
        pdf_reader = PyPDF2.PdfReader(fh)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"

        return text.strip()

    def _download_text_file(self, file_id: str) -> str:
        """Download plain text file"""
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

        return fh.getvalue().decode('utf-8')

# Initialize the Drive service
drive_service = DriveService()

@app.on_event("startup")
async def startup_event():
    """Initialize the Google Drive service on startup"""
    try:
        drive_service.authenticate()
        logger.info("Google Drive service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Google Drive service: {str(e)}")

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Google Drive ChatGPT Connector is running"}

@app.get("/files", response_model=List[FileInfo])
async def list_files():
    """List all files in the configured Google Drive folder"""
    try:
        files = drive_service.list_files()
        return files
    except Exception as e:
        logger.error(f"Error in list_files endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/{file_id}", response_model=FileContent)
async def get_file(file_id: str):
    """Get the content of a specific file as text"""
    try:
        file_content = drive_service.get_file_content(file_id)
        return file_content
    except Exception as e:
        logger.error(f"Error in get_file endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "google-drive-connector"}

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)