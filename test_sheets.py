from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

creds = Credentials.from_service_account_file(
    r'C:\Users\digit\Desktop\lithu1\service-account-file.json',
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)
service = build('sheets', 'v4', credentials=creds)
USERS_SHEET_ID = '1sSa0_wAHLVIIABqyxQKlaoRTUwnV4Dlt6TneXH3V8H8'  # Your actual Sheet ID
try:
    result = service.spreadsheets().values().get(
        spreadsheetId=USERS_SHEET_ID, range="Sheet1!A1:C1"
    ).execute()
    print(result)
except Exception as e:
    print(f"Error: {e}")