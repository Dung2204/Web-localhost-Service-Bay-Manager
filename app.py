import gspread
import json # THÊM THƯ VIỆN NÀY
import uuid
from flask import Flask, jsonify, request, abort, send_from_directory
from flask_cors import CORS
# Thêm 'date' để kiểm tra ngày
from datetime import datetime, date
from oauth2client.service_account import ServiceAccountCredentials
import os
import traceback # Để in lỗi chi tiết
import re # Thêm thư viện Regex để xử lý task_XX

# --- Lấy đường dẫn thư mục hiện tại của tệp App.py ---
script_dir = os.path.abspath(os.path.dirname(__file__))
print(f">>> Thư mục gốc của script: {script_dir}")

# --- Cấu hình Flask ---
app = Flask(__name__, template_folder=script_dir)
CORS(app) # Cho phép React (chạy trên trình duyệt) gọi API này

# --- Cấu hình Google Sheets ---
# KHÔNG CẦN DÒNG NÀY NỮA: CREDENTIALS_FILE = os.path.join(script_dir, "credentials.json")
SHEET_NAME = "ServiceAppDB"

# Biến toàn cục cho 2 tab
sheet_tasks = None
sheet_users = None

BAYS_TECHNICIANS_LIST = [
    {'id': 'bay_1', 'name': 'Khoang 1', 'technician': 'Lê Minh An'},
    {'id': 'bay_2', 'name': 'Khoang 2', 'technician': 'Trần Khánh Vy'},
    {'id': 'bay_3', 'name': 'Khoang 3', 'technician': 'Phạm Hoàng Nam'},
    {'id': 'bay_4', 'name': 'Khoang 4', 'technician': 'Nguyễn Thị Ngọc Anh'},
    {'id': 'bay_5', 'name': 'Khoang 5', 'technician': 'Huỳnh Tuấn Kiệt'},
    {'id': 'bay_6', 'name': 'Khoang 6', 'technician': 'Đỗ Phương Thảo'},
    {'id': 'bay_7', 'name': 'Khoang 7', 'technician': 'Lương Quang Huy'},
    {'id': 'bay_8', 'name': 'Khoang 8', 'technician': 'Đặng Thùy Linh'},
    {'id': 'bay_9', 'name': 'Khoang 9', 'technician': 'Trịnh Văn Đạt'},
    {'id': 'bay_10', 'name': 'Khoang 10', 'technician': 'Bùi Thị Kim Ngân'},
]
# Tạo danh sách ID theo thứ tự để quay vòng
BAY_IDS_ORDER = [bay['id'] for bay in BAYS_TECHNICIANS_LIST]

try:
    # 1. Lấy chuỗi JSON credentials từ Biến Môi Trường (trên Render: GOOGLE_CREDENTIALS)
    google_credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if not google_credentials_json:
        # Nếu không tìm thấy biến môi trường, báo lỗi và dừng
        print("LỖI: KHÔNG TÌM THẤY biến môi trường GOOGLE_CREDENTIALS.")
        print("Nếu chạy cục bộ, hãy đảm bảo bạn đã cấu hình biến môi trường này.")
        raise Exception("Thiếu thông tin xác thực Google Sheets.")
    
    # 2. Chuyển chuỗi JSON thành dictionary Python
    creds_dict = json.loads(google_credentials_json)
    
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    # 3. Sử dụng dictionary để tạo Credentials (thay thế from_json_keyfile_name)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    # 4. Mở cả 2 tab bằng tên
    sheet_tasks = client.open(SHEET_NAME).sheet1
    sheet_users = client.open(SHEET_NAME).worksheet("Users") 

    print(f">>> Đã kết nối 2 tab 'Tasks' ({sheet_tasks.title}) và 'Users' ({sheet_users.title}) của '{SHEET_NAME}' thành công!")

    # --- [UPDATE] TỰ ĐỘNG THÊM CỘT: paymentStatus, revenue, deletionStatus ---
    try:
        current_headers = sheet_tasks.row_values(1)
        new_columns_needed = []
        if 'paymentStatus' not in current_headers: new_columns_needed.append('paymentStatus')
        if 'revenue' not in current_headers: new_columns_needed.append('revenue')
        if 'deletionStatus' not in current_headers: new_columns_needed.append('deletionStatus') # Cột cho quy trình xóa
        
        if new_columns_needed:
            print(f">>> Đang tự động thêm cột mới {new_columns_needed} vào Google Sheet Tasks...")
            next_col_index = len(current_headers) + 1
            for i, col_name in enumerate(new_columns_needed):
                sheet_tasks.update_cell(1, next_col_index + i, col_name)
            print(">>> Đã cập nhật tiêu đề cột thành công.")
    except Exception as e:
        print(f"Cảnh báo: Không thể kiểm tra cột mới: {e}")
    # ----------------------------------------------------------------------

except gspread.exceptions.WorksheetNotFound:
    print(f"LỖI: Không tìm thấy tab 'Users' trong Google Sheet '{SHEET_NAME}'. Hãy kiểm tra lại tên tab.")
    sheet_tasks = None 
    sheet_users = None
except Exception as e:
    # Bắt tất cả các lỗi khác (kết nối, định dạng JSON sai, v.v.)
    print(f"LỖI: Không thể kết nối Google Sheets.")
    print(f"Lỗi chi tiết: {e}")
    traceback.print_exc()
    sheet_tasks = None
    sheet_users = None

# --- HÀM HỖ TRỢ (PHẢI ĐỊNH NGHĨA TRƯỚC KHI SỬ DỤNG) ---

def get_headers(sheet):
    """Lấy danh sách tiêu đề cột (hàng 1) một cách an toàn"""
    if not sheet: return []
    try:
        headers = sheet.row_values(1)
        # Loại bỏ các ô trống cuối hàng tiêu đề (nếu có)
        while headers and not headers[-1]:
            headers.pop()
        return headers
    except Exception as e:
        print(f"Lỗi khi lấy headers từ sheet '{sheet.title}': {e}")
        return []

def find_user(user_id):
    """Tìm một user trong tab Users bằng userId"""
    if not sheet_users: return None
    try:
        # get_all_records() hiệu quả hơn khi sheet nhỏ/vừa
        user_records = sheet_users.get_all_records()
        for user in user_records:
            # So sánh dạng chuỗi để tránh lỗi kiểu dữ liệu
            if str(user.get('userId')) == str(user_id):
                return user # Trả về dictionary của user
        return None # Không tìm thấy
    except Exception as e:
        print(f"[LỖI] find_user({user_id}): {e}")
        traceback.print_exc()
        return None

# --- TỰ ĐỘNG TẠO ADMIN (ĐÃ BỔ SUNG) ---
# Đoạn code này sẽ chạy 1 lần khi máy chủ khởi động
# Nó kiểm tra xem user 'Admin' đã có chưa, nếu chưa, nó sẽ tự tạo
if sheet_users: # Chỉ chạy nếu kết nối tab Users thành công
    try:
        ADMIN_USER_ID = "Admin"
        ADMIN_PASSWORD = "admin"

        print(f">>> Kiểm tra tài khoản admin mặc định ('{ADMIN_USER_ID}')...")
        admin_user = find_user(ADMIN_USER_ID) # Dùng hàm find_user đã định nghĩa ở trên

        if not admin_user:
            print(f"    > Không tìm thấy '{ADMIN_USER_ID}'. Đang tiến hành tạo mới...")

            headers = get_headers(sheet_users) # Dùng hàm get_headers
            if not headers:
                print("    > LỖI: Không thể đọc headers từ tab Users. Bỏ qua tạo admin.")
            else:
                # Tạo dữ liệu cho admin
                admin_data = {
                    "userId": ADMIN_USER_ID,
                    "password": ADMIN_PASSWORD,
                    "hoTen": "Quản Trị Viên",
                    "role": "admin",
                    "sdt": "0900000000",
                    # Thêm các trường khác nếu cần (sẽ để trống nếu không có)
                }

                # Sắp xếp theo đúng thứ tự tiêu đề
                new_row = [admin_data.get(header, '') for header in headers]

                sheet_users.append_row(new_row, value_input_option='USER_ENTERED')
                print(f"    > Đã tạo tài khoản admin thành công: {ADMIN_USER_ID} / {ADMIN_PASSWORD}")
        else:
            print(f"    > Đã tìm thấy tài khoản '{ADMIN_USER_ID}'. Bỏ qua tạo mới.")

    except Exception as e:
        print(f"LỖI: Gặp sự cố khi tự động tạo admin: {e}")
        traceback.print_exc()
else:
    print(">>> CẢNH BÁO: Không kết nối được tab 'Users', không thể tự động tạo admin.")

# --- HÀM HỖ TRỢ (TIẾP TỤC) ---

def find_task_row(task_id):
    """Tìm một công việc trong tab Tasks bằng task_id và trả về số hàng (bắt đầu từ 1)"""
    if not sheet_tasks: return None
    try:
        # Lấy tất cả giá trị trong cột 'id' (cột 1)
        id_list = sheet_tasks.col_values(1)
        for i, id_val in enumerate(id_list):
            if id_val == task_id:
                # i là index (bắt đầu từ 0), số hàng trong sheet bắt đầu từ 1
                return i + 1
        return None # Không tìm thấy
    except Exception as e:
        print(f"[LỖI] find_task_row({task_id}): {e}")
        traceback.print_exc()
        return None

def is_today(task_date_str):
    """Kiểm tra xem chuỗi ngày tháng có phải là hôm nay không"""
    if not task_date_str: return False
    try:
        # Sử dụng hàm chuyển đổi đã được cải tiến
        task_date = parse_datetime(task_date_str)
        if not task_date: return False
        # So sánh phần ngày (không tính giờ)
        return task_date.date() == date.today()
    except Exception as e:
        print(f"Lỗi is_today('{task_date_str}'): {e}")
        return False

def parse_datetime(date_str):
    """Hàm chuyển đổi ngày tháng (từ v2), xử lý nhiều định dạng hơn"""
    if not date_str or not isinstance(date_str, str): return None # Chỉ xử lý chuỗi

    # Ưu tiên định dạng ISO trước (vì đây là định dạng chuẩn)
    try:
        # THỬ 1: ISO chuẩn (YYYY-MM-DDTHH:MM:SS hoặc YYYY-MM-DD HH:MM:SS)
        # Thay T bằng dấu cách nếu có để fromisoformat xử lý được cả 2
        return datetime.fromisoformat(date_str.replace(" ", "T"))
    except ValueError:
        # THỬ 2: Định dạng Google Sheet VN (DD/MM/YYYY HH:MM:SS)
        try:
            return datetime.strptime(date_str, '%d/%m/%Y %H:%M:%S')
        except ValueError:
            # THỬ 3: Định dạng có dấu ' (VD: '2025-10-26T09:00:00)
            try:
                # Bỏ dấu ' và thử lại ISO
                return datetime.fromisoformat(date_str.strip("'").replace(" ", "T"))
            except ValueError:
                # THỬ 4: Định dạng VN chỉ có ngày (DD/MM/YYYY) - trả về đầu ngày
                try:
                    dt_obj = datetime.strptime(date_str, '%d/%m/%Y')
                    return dt_obj # Trả về 00:00:00 của ngày đó
                except ValueError:
                    # THỬ 5: Định dạng YYYY-MM-DD (chỉ ngày)
                    try:
                        dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        return dt_obj # Trả về 00:00:00 của ngày đó
                    except ValueError:
                        # Nếu tất cả đều thất bại
                        # print(f"Không thể parse datetime: '{date_str}'") # Bỏ comment nếu muốn debug
                        return None

# --- HÀM HỖ TRỢ MỚI ---
def get_next_task_id():
    """Đọc cột ID, tìm số lớn nhất trong định dạng task_XX, trả về task_XX+1"""
    if not sheet_tasks: return f"task_{uuid.uuid4()}" # Dự phòng nếu sheet lỗi
    try:
        id_list = sheet_tasks.col_values(1)[1:] # Lấy cột ID (cột 1), bỏ qua tiêu đề (hàng 1)
        max_num = 0
        for id_val in id_list:
            if isinstance(id_val, str): # Chỉ xử lý nếu là chuỗi
                match = re.match(r"task_(\d+)", id_val.strip()) # Tìm số trong "task_XX"
                if match:
                    try:
                        num = int(match.group(1))
                        if num > max_num:
                            max_num = num
                    except ValueError:
                        continue # Bỏ qua nếu không phải số
        next_id = f"task_{max_num + 1}"
        print(f"[AUTO ID] ID tiếp theo được tạo: {next_id}")
        return next_id
    except Exception as e:
        print(f"[LỖI] get_next_task_id: {e}")
        traceback.print_exc()
        return f"task_{uuid.uuid4()}" # Dự phòng nếu có lỗi

def get_next_bay_id():
    """Lấy bayId của dòng cuối cùng, trả về bayId tiếp theo (quay vòng)"""
    if not sheet_tasks: return BAY_IDS_ORDER[0] # Mặc định là bay_1 nếu sheet lỗi
    try:
        # Lấy tất cả giá trị để xử lý sheet trống hoặc chỉ có 1 dòng
        all_values = sheet_tasks.get_all_values()
        if len(all_values) <= 1: # Chỉ có tiêu đề hoặc trống
            print("[AUTO BAY] Sheet Tasks trống hoặc chỉ có tiêu đề. Gán bay_1.")
            return BAY_IDS_ORDER[0]

        # Lấy giá trị bayId của dòng cuối cùng (cột thứ 2 - index 1)
        last_row = all_values[-1]
        if len(last_row) > 1:
            last_bay_id = last_row[1].strip() # Lấy cột B, bỏ khoảng trắng thừa
            print(f"[AUTO BAY] Bay ID của dòng cuối cùng: '{last_bay_id}'")
        else:
            print("[AUTO BAY] Dòng cuối không có cột BayId. Gán bay_1.")
            return BAY_IDS_ORDER[0] # Dòng cuối không đủ cột

        if last_bay_id in BAY_IDS_ORDER:
            current_index = BAY_IDS_ORDER.index(last_bay_id)
            next_index = (current_index + 1) % len(BAY_IDS_ORDER) # Quay vòng
            next_bay_id = BAY_IDS_ORDER[next_index]
            print(f"[AUTO BAY] Bay ID tiếp theo: {next_bay_id}")
            return next_bay_id
        else:
            # Nếu giá trị cuối không hợp lệ (ví dụ: gõ nhầm), trả về bay_1
            print(f"[AUTO BAY] Bay ID cuối '{last_bay_id}' không hợp lệ. Gán bay_1.")
            return BAY_IDS_ORDER[0]
    except IndexError: # Sheet trống hoặc lỗi đọc cột
        print("[AUTO BAY] Lỗi IndexError khi đọc BayId cuối. Gán bay_1.")
        return BAY_IDS_ORDER[0]
    except Exception as e:
        print(f"[LỖI] get_next_bay_id: {e}")
        traceback.print_exc()
        return BAY_IDS_ORDER[0] # Mặc định là bay_1 nếu có lỗi khác

# --- API Đăng nhập / Đăng ký ---
@app.route('/api/register', methods=['POST'])
def register_user():
    if not sheet_users: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Users)"}), 500
    data = request.json
    if not data or not data.get('userId') or not data.get('password'):
        abort(400, description="Thiếu userId hoặc password.")

    print(f"\n[API] POST /api/register cho user: {data.get('userId')}")
    # 1. Kiểm tra xem userId đã tồn tại chưa
    if find_user(data.get('userId')):
        print(f"[API] Đăng ký thất bại: User '{data.get('userId')}' đã tồn tại.")
        return jsonify({"error": f"Tên đăng nhập '{data.get('userId')}' đã tồn tại."}), 409 # 409 Conflict

    # 2. Lấy tiêu đề cột từ tab Users
    headers = get_headers(sheet_users)
    if not headers: return jsonify({"error": "Không thể đọc tiêu đề cột từ tab Users"}), 500
    print(f"[API] Tiêu đề tab Users: {headers}")

    # 3. Tạo hàng mới theo đúng thứ tự tiêu đề
    try:
        new_row = [data.get(header, '') for header in headers] # Lấy giá trị, nếu không có thì để trống ''
        print(f"[API] Dữ liệu hàng mới cho Users: {new_row}")
        sheet_users.append_row(new_row, value_input_option='USER_ENTERED') # USER_ENTERED để Sheets tự định dạng nếu cần

        print(f"[API] Đã đăng ký user mới: {data.get('userId')}")
        # Trả về dữ liệu user (trừ password)
        safe_data = data.copy()
        safe_data.pop('password', None) # Xóa mật khẩu trước khi gửi về client
        return jsonify(safe_data), 201 # 201 Created
    except Exception as e:
        print(f"[LỖI API] /api/register: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi đăng ký: {e}"}), 500

@app.route('/api/login', methods=['POST'])
def login_user():
    data = request.json
    user_id = data.get('userId')
    password = data.get('password')
    if not user_id or not password:
        abort(400, description="Thiếu userId hoặc password.")

    print(f"\n[API] POST /api/login cho user: {user_id}")
    user_data = find_user(user_id)

    if not user_data:
        print(f"[API] Đăng nhập thất bại: User '{user_id}' không tồn tại.")
        return jsonify({"error": "Tên đăng nhập không tồn tại."}), 404 # 404 Not Found

    # So sánh mật khẩu trực tiếp
    if user_data.get('password') == password:
        # Đăng nhập thành công!
        user_data.pop('password', None) # Xóa mật khẩu trước khi gửi về client
        print(f"[API] User '{user_id}' đăng nhập thành công. Role: {user_data.get('role')}")
        return jsonify(user_data), 200 # 200 OK
    else:
        print(f"[API] Đăng nhập thất bại: Sai mật khẩu cho user '{user_id}'.")
        return jsonify({"error": "Sai mật khẩu."}), 401 # 401 Unauthorized

# --- API Công việc (Tasks) ---

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500
    try:
        print("\n[API] GET /api/tasks. Đang đọc Google Sheet...")
        # get_all_records() tự động dùng hàng 1 làm key
        records = sheet_tasks.get_all_records()
        print(f"[API] Tìm thấy {len(records)} dòng dữ liệu thô từ Google Sheet.")
        tasks = []
        for i, rec in enumerate(records):
            task_data = rec.copy() # Tạo bản sao
            # Chuyển đổi ngày tháng sang ISO 8601 cho JavaScript
            for key in ['startTime', 'endTime']:
                original_value = task_data.get(key)
                if original_value: # Chỉ xử lý nếu có giá trị
                    dt_obj = parse_datetime(str(original_value)) # Đảm bảo là chuỗi
                    if dt_obj:
                        task_data[key] = dt_obj.isoformat() # Chuyển thành chuỗi ISO
                    else:
                        # Nếu không parse được, giữ nguyên giá trị gốc và báo lỗi
                        print(f"[CẢNH BÁO DÒNG {i+2}] Không thể đọc định dạng ngày: '{original_value}' (cột {key}). Giữ nguyên giá trị.")
                        task_data[key] = str(original_value) # Giữ dạng chuỗi
            
            # --- [UPDATE] BỔ SUNG TRƯỜNG MẶC ĐỊNH ---
            if 'paymentStatus' not in task_data: task_data['paymentStatus'] = 'unpaid'
            if 'revenue' not in task_data: task_data['revenue'] = 0
            if 'deletionStatus' not in task_data: task_data['deletionStatus'] = 'none'
            
            tasks.append(task_data)

        print(f"[API] Đã xử lý {len(tasks)} công việc. Trả về JSON.")
        return jsonify(tasks)
    except Exception as e:
        print(f"[LỖI API] /api/tasks (GET): {e}")
        traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi lấy danh sách công việc: {e}"}), 500

# --- API THÊM TASK (Đã sửa) ---
@app.route('/api/tasks', methods=['POST'])
def add_task():
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500

    print("\n[API] POST /api/tasks. Đang thêm dữ liệu...")
    data = request.json
    if not data: abort(400, description="Không có dữ liệu JSON.")

    try:
        # --- THAY ĐỔI 1: TỰ ĐỘNG LẤY ID VÀ BAY ID ---
        new_id = get_next_task_id()
        assigned_bay_id = get_next_bay_id() # Tự động chọn bay tiếp theo
        print(f"[API] ID mới tự động: {new_id}, Bay được gán tự động: {assigned_bay_id}")

        headers = get_headers(sheet_tasks)
        if not headers: return jsonify({"error": "Không thể đọc tiêu đề cột từ tab Tasks"}), 500
        print(f"[API] Tiêu đề tab Tasks: {headers}")

        new_row_dict = data.copy() # Lấy dữ liệu từ client
        new_row_dict['id'] = new_id # Ghi đè ID tự động
        new_row_dict['bayId'] = assigned_bay_id # Ghi đè Bay ID tự động

        # --- [UPDATE] THÊM TRẠNG THÁI MẶC ĐỊNH ---
        new_row_dict['paymentStatus'] = 'unpaid'
        new_row_dict['revenue'] = 0
        new_row_dict['deletionStatus'] = 'none'

        # Xử lý ngày tháng startTime và endTime (ghi dưới dạng ISO có dấu ' để ép text)
        for key in ['startTime', 'endTime']:
            if new_row_dict.get(key):
                # Đảm bảo đây là chuỗi ISO hợp lệ trước khi thêm dấu '
                try:
                    datetime.fromisoformat(new_row_dict[key].replace('Z','+00:00')) # Kiểm tra xem có phải ISO không
                    new_row_dict[key] = f"'{new_row_dict[key]}"
                    print(f"[API] Đã thêm dấu nháy đơn cho {key}: {new_row_dict[key]}")
                except ValueError:
                    print(f"[CẢNH BÁO] Giá trị {key} từ client không phải ISO: '{new_row_dict[key]}'. Sẽ ghi nguyên giá trị.")
                    # Không thêm dấu nháy đơn nếu không phải ISO

        # Tạo list theo đúng thứ tự headers để append_row
        new_row_list = [new_row_dict.get(header, '') for header in headers]
        print(f"[API] Dữ liệu hàng mới cho Tasks: {new_row_list}")

        sheet_tasks.append_row(new_row_list, value_input_option='USER_ENTERED')
        print(f"[API] Đã thêm công việc mới vào Google Sheet, ID: {new_id}")

        # Trả về task đã tạo (dùng ID và Bay ID mới nhất) cho client cập nhật UI
        new_task_data_for_client = data.copy()
        new_task_data_for_client['id'] = new_id
        new_task_data_for_client['bayId'] = assigned_bay_id
        new_task_data_for_client['paymentStatus'] = 'unpaid'
        new_task_data_for_client['revenue'] = 0
        new_task_data_for_client['deletionStatus'] = 'none'
        # startTime/endTime đã là ISO từ client, giữ nguyên
        return jsonify(new_task_data_for_client), 201

    except Exception as e:
        print(f"[LỖI API] /api/tasks (POST): {e}"); traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi thêm công việc: {e}"}), 500

# --- API SỬA TASK ---
@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500
    print(f"\n[API] PUT /api/tasks/{task_id}. Đang cập nhật...")
    data = request.json # Dữ liệu mới từ client
    if not data: abort(400, description="Không có dữ liệu JSON.")

    # 1. Tìm hàng của task cần sửa
    row_number = find_task_row(task_id)
    if not row_number:
        print(f"[API] Cập nhật thất bại: Không tìm thấy task ID '{task_id}'.")
        return jsonify({"error": "Không tìm thấy công việc này."}), 404

    # 2. Lấy dữ liệu task hiện tại để kiểm tra quyền
    try:
        headers = get_headers(sheet_tasks)
        if not headers: return jsonify({"error": "Không đọc được tiêu đề cột Tasks"}), 500
        current_task_data = sheet_tasks.row_values(row_number)
        current_task_dict = dict(zip(headers, current_task_data))
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu task hiện tại (ID: {task_id}, Row: {row_number}): {e}")
        traceback.print_exc()
        return jsonify({"error": "Không thể đọc dữ liệu task hiện tại."}), 500

    # 3. Kiểm tra quyền (Permission Check) - Lấy thông tin user yêu cầu từ payload
    user_id = data.get('currentUserId')
    user_role = data.get('currentUserRole')
    
    # --- [UPDATE] Cờ đặc biệt ---
    is_payment_request = data.get('isPaymentRequest', False)
    is_delete_request = data.get('isDeleteRequest', False) # Cờ cho phép user thường yêu cầu xóa
    
    if not user_id or not user_role:
        return jsonify({"error": "Thiếu thông tin xác thực trong yêu cầu (currentUserId, currentUserRole)."}), 401

    task_owner_id = current_task_dict.get('userId')
    task_start_time_str = current_task_dict.get('startTime') # Lấy chuỗi thời gian gốc từ sheet

    is_admin = user_role == 'admin'
    # So sánh ID dạng chuỗi
    is_owner = str(task_owner_id).strip() == str(user_id).strip()
    is_task_today = is_today(task_start_time_str) # Kiểm tra ngày của task

    # --- [UPDATE] CHẶN SỬA NẾU ĐÃ THANH TOÁN (TRỪ ADMIN) ---
    if current_task_dict.get('paymentStatus') == 'paid' and not is_admin:
         return jsonify({"error": "Hóa đơn đã thanh toán, không thể chỉnh sửa."}), 403

    print(f"[API CHECK QUYỀN SỬA] User: {user_id}, Role: {user_role}, Task Owner: {task_owner_id}, Task Time: {task_start_time_str}, Is Admin: {is_admin}, Is Owner: {is_owner}, Is Today: {is_task_today}")

    # --- [UPDATE] LOGIC QUYỀN: BỔ SUNG QUYỀN THANH TOÁN VÀ YÊU CẦU XÓA ---
    # Cho phép Admin HOẶC Chủ xe (hôm nay) HOẶC User đang yêu cầu thanh toán HOẶC User đang yêu cầu xóa
    if not (is_admin or (is_owner and is_task_today) or (is_payment_request and is_owner) or (is_delete_request and is_owner)):
        print(f"[API] CẬP NHẬT BỊ TỪ CHỐI. User '{user_id}' không có quyền sửa task '{task_id}'.")
        return jsonify({"error": "Bạn không có quyền sửa công việc này (chỉ admin hoặc chủ sở hữu trong ngày)."}), 403 # 403 Forbidden

    # 4. Có quyền -> Tiến hành cập nhật
    try:
        update_cells_list = [] # List các ô cần cập nhật
        updated_data_for_client = current_task_dict.copy() # Dữ liệu để trả về client

        for i, header in enumerate(headers):
            # Nếu trường đó có trong dữ liệu gửi lên (data) VÀ không phải là 'id'
            if header in data and header != 'id':
                new_value = data[header] # Giá trị mới từ client

                # Xử lý đặc biệt cho ngày tháng trước khi ghi vào Sheet
                if header == 'startTime' or header == 'endTime':
                    if new_value: # Nếu client gửi giá trị mới
                        # Kiểm tra xem có phải ISO không
                        try:
                            datetime.fromisoformat(new_value.replace('Z','+00:00'))
                            new_value_for_sheet = f"'{new_value}" # Thêm dấu ' để ép text
                            updated_data_for_client[header] = new_value # Giữ ISO cho client
                        except ValueError:
                            print(f"[CẢNH BÁO] Giá trị {header} mới không phải ISO: '{new_value}'. Sẽ ghi nguyên giá trị.")
                            new_value_for_sheet = new_value # Ghi nguyên giá trị
                            updated_data_for_client[header] = new_value # Giữ nguyên cho client
                    else: # Nếu client gửi giá trị rỗng (muốn xóa ngày)
                        new_value_for_sheet = '' # Ghi rỗng vào sheet
                        updated_data_for_client[header] = None # Trả về null cho client
                else:
                    # Các trường khác ghi bình thường
                    new_value_for_sheet = new_value
                    updated_data_for_client[header] = new_value # Cập nhật cho client

                # Tạo đối tượng Cell để cập nhật hàng loạt
                update_cells_list.append(gspread.Cell(row_number, i + 1, new_value_for_sheet))

        if update_cells_list:
            print(f"[API] Đang cập nhật {len(update_cells_list)} ô cho hàng {row_number}...")
            sheet_tasks.update_cells(update_cells_list, value_input_option='USER_ENTERED')
            print(f"[API] Đã cập nhật thành công task ID: {task_id}")

            # Đảm bảo startTime/endTime trả về client là ISO hợp lệ
            if updated_data_for_client.get('startTime'):
                dt = parse_datetime(updated_data_for_client['startTime'])
                updated_data_for_client['startTime'] = dt.isoformat() if dt else None
            if updated_data_for_client.get('endTime'):
                dt = parse_datetime(updated_data_for_client['endTime'])
                updated_data_for_client['endTime'] = dt.isoformat() if dt else None

            return jsonify({"message": "Cập nhật thành công", "data": updated_data_for_client}), 200
        else:
            print(f"[API] Không có trường nào cần cập nhật cho task ID: {task_id}")
            return jsonify({"message": "Không có gì để cập nhật"}), 200 # Hoặc 304 Not Modified

    except Exception as e:
        print(f"[LỖI API] /api/tasks (PUT) ID {task_id}: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi cập nhật công việc: {e}"}), 500

# --- API XÓA TASK ---
@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500
    print(f"\n[API] DELETE /api/tasks/{task_id}. Đang xóa...")

    # 1. Lấy thông tin user yêu cầu (từ query params)
    user_id = request.args.get('userId')
    user_role = request.args.get('role')
    if not user_id or not user_role:
        return jsonify({"error": "Yêu cầu thiếu thông tin xác thực (userId, role)."}), 401

    # --- [UPDATE] LOGIC XÓA NGHIÊM NGẶT: CHỈ ADMIN MỚI ĐƯỢC QUYỀN ---
    if user_role != 'admin':
        return jsonify({"error": "Truy cập bị từ chối. Chỉ Admin mới có quyền duyệt xóa vĩnh viễn."}), 403

    # 2. Tìm hàng của task cần xóa
    row_number = find_task_row(task_id)
    if not row_number:
        print(f"[API] Xóa thất bại: Không tìm thấy task ID '{task_id}'.")
        return jsonify({"error": "Không tìm thấy công việc này."}), 404

    # 5. Có quyền -> Tiến hành xóa
    try:
        print(f"[API] Đang xóa hàng {row_number} (Task ID: {task_id})...")
        sheet_tasks.delete_rows(row_number)
        print(f"[API] Đã xóa thành công task ID: {task_id}")
        return jsonify({"message": "Deleted"}), 200 # 200 OK
    except Exception as e:
        print(f"[LỖI API] /api/tasks (DELETE) ID {task_id}: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi xóa công việc: {e}"}), 500

# --- API ADMIN ---

@app.route('/api/users', methods=['GET'])
def get_users():
    """(Chỉ Admin) Lấy danh sách user"""
    if not sheet_users: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Users)"}), 500
    print("\n[API] GET /api/users (Admin). Đang đọc tab Users...")

    # Kiểm tra quyền Admin (lấy userId từ query param)
    user_id = request.args.get('userId')
    user = find_user(user_id) # Tìm thông tin user yêu cầu trong DB
    if not user or user.get('role') != 'admin':
        print(f"[API] /api/users BỊ TỪ CHỐI. User yêu cầu: '{user_id}' không phải admin.")
        return jsonify({"error": "Truy cập bị từ chối. Cần quyền Admin."}), 403

    try:
        users = sheet_users.get_all_records()
        # **QUAN TRỌNG**: Loại bỏ mật khẩu khỏi danh sách trước khi gửi về client
        safe_users = []
        for u in users:
            u.pop('password', None) # Xóa trường password nếu có
            safe_users.append(u)
        print(f"[API] Lấy thành công {len(safe_users)} user (đã loại bỏ password).")
        return jsonify(safe_users)
    except Exception as e:
        print(f"[LỖI API] /api/users (GET): {e}"); traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi lấy danh sách người dùng: {e}"}), 500

@app.route('/api/report', methods=['GET'])
def get_report():
    """(Chỉ Admin) Lấy báo cáo công việc theo ngày"""
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500
    print("\n[API] GET /api/report (Admin). Đang lọc dữ liệu...")
    # 1. Kiểm tra quyền Admin
    admin_id = request.args.get('userId')
    admin_user = find_user(admin_id)
    if not admin_user or admin_user.get('role') != 'admin':
        print(f"[API] /api/report BỊ TỪ CHỐI. User yêu cầu: '{admin_id}' không phải admin.")
        return jsonify({"error": "Truy cập bị từ chối. Cần quyền Admin."}), 403
    # 2. Lấy ngày từ query param (ví dụ: ?date=2025-10-26)
    report_date_str = request.args.get('date')
    if not report_date_str:
        return jsonify({"error": "Vui lòng cung cấp ngày báo cáo theo định dạng YYYY-MM-DD (ví dụ: ?date=2025-10-26)."}), 400

    # 3. Chuyển đổi ngày và lọc dữ liệu
    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
        print(f"[API] Lọc báo cáo cho ngày: {report_date}")
    except ValueError:
        return jsonify({"error": "Định dạng ngày không hợp lệ. Vui lòng dùng YYYY-MM-DD."}), 400

    try:
        all_tasks = sheet_tasks.get_all_records()
        report_tasks = []
        
        # --- [UPDATE] BIẾN TÍNH TỔNG DOANH THU ---
        total_revenue = 0
        
        for task in all_tasks:
            task_start_time_str = task.get('startTime')
            dt_obj = parse_datetime(task_start_time_str)
            # Chỉ lấy task có startTime thuộc ngày báo cáo
            if dt_obj and dt_obj.date() == report_date:
                # Lấy thêm thông tin người tạo (họ tên) từ tab Users
                task_owner_info = find_user(task.get('userId'))
                # Thêm trường 'nguoiTao' vào task để hiển thị trên báo cáo
                task['nguoiTao'] = task_owner_info.get('hoTen') if task_owner_info else task.get('userId', 'N/A')

                # Chuyển đổi ngày tháng về ISO cho báo cáo để nhất quán
                if task.get('startTime'): task['startTime'] = parse_datetime(task['startTime']).isoformat() if parse_datetime(task['startTime']) else None
                if task.get('endTime'): task['endTime'] = parse_datetime(task['endTime']).isoformat() if parse_datetime(task['endTime']) else None
                
                # --- [UPDATE] TÍNH TỔNG DOANH THU ---
                rev = task.get('revenue')
                if rev:
                    try:
                        # Loại bỏ dấu phẩy hoặc chấm nếu có
                        rev_clean = str(rev).replace(',', '').replace('.', '')
                        rev_int = int(rev_clean)
                        total_revenue += rev_int
                        task['revenue'] = rev_int
                    except: 
                        task['revenue'] = 0
                else:
                    task['revenue'] = 0
                
                report_tasks.append(task)

        print(f"[API] Đã tìm thấy {len(report_tasks)} công việc cho báo cáo ngày {report_date_str}")
        
        # --- [UPDATE] TRẢ VỀ CẤU TRÚC MỚI CÓ TOTAL REVENUE ---
        return jsonify({
            "tasks": report_tasks,
            "totalRevenue": total_revenue
        })

    except Exception as e:
        print(f"[LỖI API] /api/report (GET) cho ngày {report_date_str}: {e}"); traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi tạo báo cáo: {e}"}), 500

# --- API TRA CỨU LỊCH SỬ (MỚI) ---
@app.route('/api/search_history', methods=['GET'])
def search_history():
    """(Chỉ Admin) Tìm kiếm lịch sử theo biển số hoặc tên khách"""
    if not sheet_tasks: return jsonify({"error": "Máy chủ chưa kết nối được với Google Sheet (Tasks)"}), 500
    
    # 1. Kiểm tra quyền Admin
    user_id = request.args.get('userId')
    query = request.args.get('query', '').lower().strip() # Lấy từ khóa, chuyển về chữ thường
    
    if not user_id:
        return jsonify({"error": "Thiếu thông tin userId"}), 400
        
    admin_user = find_user(user_id)
    if not admin_user or admin_user.get('role') != 'admin':
        return jsonify({"error": "Truy cập bị từ chối. Chỉ Admin mới được tra cứu lịch sử."}), 403

    if not query:
        return jsonify([]) # Trả về rỗng nếu không có từ khóa

    print(f"\n[API] Admin '{user_id}' đang tìm kiếm lịch sử với từ khóa: '{query}'")

    try:
        # Lấy toàn bộ dữ liệu
        all_tasks = sheet_tasks.get_all_records()
        results = []
        
        for task in all_tasks:
            # Lấy biển số và tên khách, chuyển về chuỗi thường để so sánh
            license_plate = str(task.get('licensePlate', '')).lower()
            customer_name = str(task.get('customerName', '')).lower()
            
            # Kiểm tra xem từ khóa có nằm trong biển số HOẶC tên khách không
            if query in license_plate or query in customer_name:
                # Xử lý ngày tháng để hiển thị đẹp
                if task.get('startTime'): 
                    dt = parse_datetime(str(task['startTime']))
                    task['startTime'] = dt.isoformat() if dt else None
                if task.get('endTime'): 
                    dt = parse_datetime(str(task['endTime']))
                    task['endTime'] = dt.isoformat() if dt else None
                
                results.append(task)

        # Sắp xếp kết quả: Ngày mới nhất lên đầu
        # Dùng lambda để xử lý trường hợp startTime bị None
        results.sort(key=lambda x: x.get('startTime') or '', reverse=True)
        
        print(f"[API] Tìm thấy {len(results)} kết quả.")
        return jsonify(results)

    except Exception as e:
        print(f"[LỖI API] /api/search_history: {e}")
        traceback.print_exc()
        return jsonify({"error": f"Lỗi máy chủ khi tìm kiếm: {e}"}), 500

# --- Phục vụ Frontend ---
@app.route('/')
def serve_app():
    """Phục vụ tệp index.html"""
    print(f"\n[SERVER] Nhận yêu cầu '/', gửi tệp: {os.path.join(script_dir, 'index.html')}")
    return send_from_directory(script_dir, "index.html")

# --- Chạy máy chủ ---
if __name__ == '__main__':
    # Kiểm tra biến môi trường $PORT (do Render cung cấp)
    port = int(os.environ.get("PORT", 5000))
    print("-----------------------------------------------------")
    print(">>> Máy chủ Python Flask (v3.2 - Auto-Create Admin) đang khởi động...")
    print(f">>> Thư mục gốc: {script_dir}")
    print(">>> PHƯƠNG THỨC XÁC THỰC: Biến môi trường GOOGLE_CREDENTIALS")
    print(f">>> Tệp Template (index.html): {script_dir}")
    print(">>>")
    if sheet_tasks and sheet_users:
        print(">>> Kết nối Google Sheet OK.")
    else:
        print(">>> CẢNH BÁO: Không kết nối được Google Sheet!")
    print(">>>")
    print(f">>> Khởi động Flask trên cổng {port}...")
    print(">>> Nhấn CTRL+C để dừng máy chủ (nếu chạy cục bộ).")
    print("-----------------------------------------------------")
    # Sử dụng gunicorn khi triển khai Render, nhưng để đảm bảo tính chạy cục bộ
    # tôi sẽ giữ app.run, nhưng lưu ý khi triển khai Render nên dùng gunicorn
    app.run(debug=True, host='0.0.0.0', port=port)

