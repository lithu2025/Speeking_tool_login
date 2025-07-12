import os
import json
import bcrypt
from flask import Flask, render_template, request, redirect, url_for, flash, session
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = 'super_secret_key'  # Required for flash messages and sessions

UPLOAD_FOLDER = 'Uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Fetch Google credentials from environment variable
credentials_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Debugging: Check if credentials are found
if not credentials_json_str:
    print("Error: GOOGLE_CREDENTIALS_JSON is not set correctly in your environment variables")
else:
    print("GOOGLE_CREDENTIALS_JSON found, proceeding...")

# Load the credentials from JSON
creds = None
if credentials_json_str:
    try:
        credentials_info = json.loads(credentials_json_str)
        creds = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=['[invalid url, do not cite]
        )
        print("Successfully loaded credentials.")
    except Exception as e:
        print(f"Error loading credentials from JSON: {e}")
else:
    print("Unable to load credentials. Please ensure GOOGLE_CREDENTIALS_JSON is set correctly.")

# Ensure creds is set before trying to use it
if creds is None:
    raise ValueError("Google credentials are not set properly. Check your environment variables.")

# Google Sheets API service
service = build('sheets', 'v4', credentials=creds)

# Users Google Sheet ID
USERS_SHEET_ID = '16RkB_V1DVSJqdtmDqiqKGPfkHdBVFjAjyPYLeywsBf4'

def get_users_data():
    """
    Fetch user data (username, hashed password, sheet ID) from the Users Google Sheet.
    """
    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=USERS_SHEET_ID, range="Sheet1!A2:C").execute()
        values = result.get('values', [])
        return [{'username': row[0], 'password': row[1], 'sheet_id': row[2]} for row in values if len(row) >= 3]
    except HttpError as err:
        print(f"Error fetching users data: {err}")
        return []

def add_user_to_sheet(username, password, sheet_id):
    """
    Add a new user to the Users Google Sheet with hashed password.
    """
    try:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        sheet = service.spreadsheets()
        sheet.values().append(
            spreadsheetId=USERS_SHEET_ID,
            range="Sheet1!A2:C",
            valueInputOption="RAW",
            body={"values": [[username, hashed_password, sheet_id]]}
        ).execute()
        return True
    except HttpError as err:
        print(f"Error adding user to sheet: {err}")
        flash(f"Registration failed: {err}", 'error')
        return False

def get_pack_size_from_sku(sku):
    """
    Maps the SKU suffix to the corresponding pack size.
    """
    pack_code_map = {
        '2PK': 2, '3PK': 3, '4PK': 4, '5PK': 5, '6PK': 6,
        '7PK': 7, '8PK': 8, '9PK': 9, 'APK': 10, 'CPK': 20,
        'DPK': 30, 'EPK': 50, 'FPK': 100, 'NPK': 200, 'PPK': 300,
        'QPK': 500, 'RPK': 1000
    }
    suffix = sku[-3:].upper() if len(sku) >= 3 else ''
    return pack_code_map.get(suffix, 1)

@app.route('/')
def login():
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles user registration by adding credentials and Sheet ID to Users Google Sheet.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        sheet_id = request.form.get('sheet_id')

        if not username or not password or not sheet_id:
            flash('Please fill in all fields', 'error')
            return redirect(url_for('register'))

        users = get_users_data()
        if any(user['username'] == username for user in users):
            flash('Username already exists', 'error')
            return redirect(url_for('register'))

        if add_user_to_sheet(username, password, sheet_id):
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            return redirect(url_for('register'))  # Flash message set in add_user_to_sheet

    return render_template('register.html')

@app.route('/login', methods=['POST'])
def handle_login():
    """
    Handles login by validating against Users Google Sheet.
    Stores user-specific Sheet ID in session.
    """
    username = request.form.get('username')
    password = request.form.get('password')

    if not username or not password:
        flash('Please enter both username and password', 'error')
        return redirect(url_for('login'))

    users = get_users_data()
    for user in users:
        if user['username'] == username and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['username'] = username
            session['sheet_id'] = user['sheet_id']
            return redirect(url_for('index'))
    
    flash('Invalid username or password', 'error')
    return redirect(url_for('login'))

@app.route('/upload_page')
def index():
    if 'username' not in session:
        flash('Please log in to access this page', 'error')
        return redirect(url_for('login'))
    sheet_url = f"[invalid url, do not cite]
    return render_template('index.html', sheet_url=sheet_url)

@app.route('/upload', methods=['POST'])
def upload_file():
    """
    Handles file upload and writes data to the user's specific Google Sheet.
    """
    if 'username' not in session:
        flash('Please log in to access this page', 'error')
        return redirect(url_for('login'))

    files = request.files.getlist("file")
    if not files:
        flash('No files selected', 'error')
        return redirect(url_for('index'))

    filepaths = []
    for file in files:
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('index'))
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        filepaths.append(filepath)

    all_data = []
    for filepath in filepaths:
        all_data.extend(process_file_and_get_data(filepath))

    write_to_google_sheets(all_data, session['sheet_id'])
    flash('Files successfully uploaded and processed!', 'success')
    return redirect(url_for('index'))

def process_file_and_get_data(filepath):
    """
    Processes the uploaded file and extracts order details, including status.
    """
    data = []
    merge_order_counter = 1
    previous_merge_order = ""

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        orders = soup.select("li.bg-white")

        for order in orders:
            # Extract status from div.ps-3.text-danger.text-upper.text-uppercase.fw-bold
            status = ""
            status_elem = order.select_one("div.ps-3.text-danger.text-upper.text-uppercase.fw-bold")
            if status_elem:
                text = status_elem.get_text(strip=True).lower()
                if text in ["firstclass", "international"]:
                    status = text

            # Extract set status
            set_status = ""
            set_elem = order.select_one("div.bg-warning.border.border-white.mt-1.ps-3.rounded-2.rounded-pill")
            if set_elem:
                set_text = set_elem.get_text(strip=True)
                if "zzzmerge_order" in set_text.lower():
                    set_status = "combo"
                elif "multi_line" in set_text.lower() or "merged" in set_text.lower():
                    if previous_merge_order == "merge order":
                        merge_order_counter += 1
                    set_status = f"merge order {merge_order_counter}"
                    previous_merge_order = "merge order"

            # Extract other order details
            customer_blocks = order.select("div.col-2.small")
            customer = customer_blocks[1].get_text(" ", strip=True) if len(customer_blocks) > 1 else ""
            address_elem = order.select_one("div.fs-6")
            address = address_elem.get_text(" ", strip=True) if address_elem else ""
            platform_elem = order.select_one("div.bg-light.border")
            platform = platform_elem.get_text(" ", strip=True) if platform_elem else ""

            price_elem = order.select_one("div.text-end span span:nth-child(2)")
            price = price_elem.get_text(strip=True) if price_elem else ""

            # Product info extraction
            product_divs = order.select("div.p-1[id$='-li']")
            for product_div in product_divs:
                try:
                    title_elem = product_div.select_one("div.fw-bold.border-bottom span, div.fw-bold.border-bottom a span")
                    title = title_elem.get_text(strip=True) if title_elem else ""

                    sku_elem = product_div.select_one("span[onclick^='copyText']")
                    sku = sku_elem.get_text(strip=True) if sku_elem else ""

                    pack_size = get_pack_size_from_sku(sku)

                    qty_text = product_div.find(string=lambda t: "Quantity:" in t)
                    qty = int(qty_text.find_next(string=True).strip()) if qty_text else 1

                    adjusted_qty = qty * pack_size

                    link_elem = product_div.select_one("div.fw-bold.border-bottom a")
                    link = link_elem['href'] if link_elem and link_elem.has_attr('href') else ""

                    img_tags = product_div.select("img")
                    main_img_elem = img_tags[-1] if img_tags else None
                    main_img_url = main_img_elem['src'].strip() if main_img_elem and main_img_elem.has_attr('src') else ""

                    combo_items = product_div.select("label.col-3.mb-3")
                    has_combo = False
                    component_data = []

                    if combo_items:
                        for item in combo_items:
                            combo_texts = item.select("div.text-center div.small")
                            combo_qty_elem = item.select_one("span.alert")

                            combo_sku = combo_texts[0].text.strip() if len(combo_texts) > 0 else ""
                            combo_color = combo_texts[1].text.strip() if len(combo_texts) > 1 else ""
                            combo_qty = combo_qty_elem.text.replace("x", "").strip() if combo_qty_elem else ""

                            img_elem = item.select_one("img")
                            img_url = img_elem['src'].strip() if img_elem and img_elem.has_attr('src') else ""

                            has_combo = True
                            component_data.append(f"component")

                            data.append([title, sku, adjusted_qty, combo_sku, combo_color, combo_qty,
                                         price, link, customer, address, platform, status,
                                         img_url, set_status, ", ".join(component_data)])

                    if not has_combo:
                        component_info = sku if set_status == "merge order" else ""
                        data.append([title, sku, adjusted_qty, "", "", "",
                                     price, link, customer, address, platform, status,
                                     main_img_url, set_status, component_info])

                except Exception as e:
                    print(f"Error parsing a product in {filepath}: {e}")
                    continue

    except Exception as e:
        print(f"Failed to process file {filepath}: {e}")

    return data

def write_to_google_sheets(data, sheet_id):
    """
    Writes scraped data to the user's specific Google Sheet.
    """
    try:
        header = [["Title", "Combo SKU", "Quantity", "SKU", "Combo Color", "Combo Quantity",
                   "Price", "Link", "Customer Info", "Address", "Selling Platform", "Status", "Image URLs", "Merge Order", "Component"]]

        sheet = service.spreadsheets()

        sheet.values().update(
            spreadsheetId=sheet_id,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": header}
        ).execute()

        sheet.values().update(
            spreadsheetId=sheet_id,
            range="Sheet1!A2",
            valueInputOption="RAW",
            body={"values": data}
        ).execute()

        print(f"✅ Data successfully uploaded to Google Sheet ID: {sheet_id}")

    except HttpError as err:
        print(f"❌ Google Sheets API error for Sheet ID {sheet_id}: {err}")
        flash('Failed to upload data to Google Sheet', 'error')

if __name__ == '__main__':
    app.run(debug=True)
