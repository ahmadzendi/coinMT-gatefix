import json
import time
from datetime import datetime, timezone, timedelta
import websocket
import threading
import urllib.request
import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

STATE_FILE = 'maintenance_state.json'
EXPORT_FILE = 'maintenance.txt'

previous_withdraw = {}
previous_deposit = {}
withdraw_times = {}
deposit_times = {}
ws_connected = False
reconnect_count = 0

def get_wib_time():
    wib = timezone(timedelta(hours=7))
    return datetime.now(wib).strftime('%Y-%m-%d %H:%M:%S WIB')

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"✅ Loaded state: {len(data.get('withdraw', {}))} entries")
                return data
        except Exception as e:
            print(f"⚠️ Error loading state: {e}")
    return None

def save_state():
    try:
        data = {
            'withdraw': previous_withdraw,
            'deposit': previous_deposit,
            'withdraw_times': withdraw_times,
            'deposit_times': deposit_times,
            'last_update': get_wib_time()
        }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving state: {e}")

def generate_export_file():
    wib = get_wib_time()
    
    content = "=" * 60 + "\n"
    content += "📊 GATE.IO MAINTENANCE REPORT\n"
    content += f"📅 Generated: {wib}\n"
    content += "=" * 60 + "\n\n"
    
    content += "📤 WITHDRAW MAINTENANCE\n"
    content += "-" * 60 + "\n"
    
    withdraw_list = []
    for key, disabled in previous_withdraw.items():
        if disabled:
            currency, chain = key.rsplit('_', 1)
            coin_time = withdraw_times.get(key, "Unknown")
            withdraw_list.append((currency, chain, coin_time))
    
    if withdraw_list:
        withdraw_list.sort(key=lambda x: x[0])
        for i, (currency, chain, coin_time) in enumerate(withdraw_list, 1):
            content += f"{i}. {currency} - {chain}\n"
            content += f"   Maintenance since: {coin_time}\n"
    else:
        content += "✅ Tidak ada coin dalam maintenance\n"
    
    content += f"\nTotal: {len(withdraw_list)} chains\n"
    content += "\n" + "=" * 60 + "\n\n"
    
    content += "📥 DEPOSIT MAINTENANCE\n"
    content += "-" * 60 + "\n"
    
    deposit_list = []
    for key, disabled in previous_deposit.items():
        if disabled:
            currency, chain = key.rsplit('_', 1)
            coin_time = deposit_times.get(key, "Unknown")
            deposit_list.append((currency, chain, coin_time))
    
    if deposit_list:
        deposit_list.sort(key=lambda x: x[0])
        for i, (currency, chain, coin_time) in enumerate(deposit_list, 1):
            content += f"{i}. {currency} - {chain}\n"
            content += f"   Maintenance since: {coin_time}\n"
    else:
        content += "✅ Tidak ada coin dalam maintenance\n"
    
    content += f"\nTotal: {len(deposit_list)} chains\n"
    content += "\n" + "=" * 60 + "\n"
    content += "🤖 Gate.io Maintenance Bot\n"
    content += "=" * 60 + "\n"
    
    with open(EXPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return EXPORT_FILE

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            return True
    except Exception as e:
        print(f"\n❌ Telegram error: {e}")
        return False

def send_telegram_to(chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode('utf-8')
        
        req = urllib.request.Request(url, data=data)
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            return True
    except:
        return False

def send_telegram_file(chat_id, filepath, caption=""):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
        
        with open(filepath, 'rb') as f:
            file_content = f.read()
        
        filename = os.path.basename(filepath)
        
        body = b''
        body += f'--{boundary}\r\n'.encode()
        body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode()
        body += f'--{boundary}\r\n'.encode()
        body += f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
        body += f'Content-Type: application/octet-stream\r\n\r\n'.encode()
        body += file_content
        body += f'\r\n--{boundary}\r\n'.encode()
        body += f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode()
        body += f'--{boundary}--\r\n'.encode()
        
        req = urllib.request.Request(url, data=body)
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        
        with urllib.request.urlopen(req, timeout=30) as response:
            return True
    except Exception as e:
        print(f"\n❌ Send file error: {e}")
        return False

def send_long_message(chat_id, header, coins_list):
    wib = get_wib_time()
    
    if not coins_list:
        msg = f"{header}\n📅 {wib}\n\n✅ Tidak ada coin dalam maintenance"
        send_telegram_to(chat_id, msg)
        return
    
    chunk_size = 50
    total_coins = len(coins_list)
    total_pages = (total_coins + chunk_size - 1) // chunk_size
    
    first_msg = f"{header}\n📅 {wib}\n📊 Total: {total_coins} chains\n\n"
    
    for i, (coin, coin_time) in enumerate(coins_list[:chunk_size], 1):
        first_msg += f"{i}. {coin} | {coin_time}\n"
    
    send_telegram_to(chat_id, first_msg)
    
    for page in range(1, total_pages):
        time.sleep(0.5)
        start = page * chunk_size
        end = min(start + chunk_size, total_coins)
        
        msg = ""
        for i, (coin, coin_time) in enumerate(coins_list[start:end], start + 1):
            msg += f"{i}. {coin} | {coin_time}\n"
        
        send_telegram_to(chat_id, msg)

def get_telegram_updates(offset=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?timeout=1"
        if offset:
            url += f"&offset={offset}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read())
            return data.get('result', [])
    except:
        return []

def check_maintenance_rest():
    url = "https://api.gateio.ws/api/v4/spot/currencies"
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    
    for attempt in range(5):
        try:
            print(f"\r📡 Fetching data... (attempt {attempt+1}/5)", end="", flush=True)
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
                print("\r✅ Data received!                         ")
                return json.loads(data)
        except KeyboardInterrupt:
            print("\n\n👋 Cancelled by user")
            return "exit"
        except Exception as e:
            print(f"\r⚠️ Attempt {attempt+1} failed: {str(e)[:40]}")
            if attempt < 4:
                print(f"🔄 Retrying in 3 seconds...")
                time.sleep(3)
    return None

def process_maintenance_data(currencies, loaded_state):
    global previous_withdraw, previous_deposit, withdraw_times, deposit_times
    
    wib_now = get_wib_time()
    
    old_withdraw = loaded_state.get('withdraw', {}) if loaded_state else {}
    old_deposit = loaded_state.get('deposit', {}) if loaded_state else {}
    old_withdraw_times = loaded_state.get('withdraw_times', {}) if loaded_state else {}
    old_deposit_times = loaded_state.get('deposit_times', {}) if loaded_state else {}
    
    print(f"\n🔴 CURRENT MAINTENANCE ({wib_now}):")
    print("="*60)
    
    current_withdraw = {}
    current_deposit = {}
    
    for coin in currencies:
        currency = coin.get('currency')
        for chain in coin.get('chains', []):
            chain_name = chain.get('name')
            key = f"{currency}_{chain_name}"
            current_withdraw[key] = chain.get('withdraw_disabled', False)
            current_deposit[key] = chain.get('deposit_disabled', False)
    
    changes = []
    all_keys = set(current_withdraw.keys()) | set(old_withdraw.keys())
    
    for key in all_keys:
        curr_w = current_withdraw.get(key, False)
        prev_w = old_withdraw.get(key, None)
        curr_d = current_deposit.get(key, False)
        prev_d = old_deposit.get(key, None)
        
        currency, chain_name = key.rsplit('_', 1)
        
        if prev_w is not None:
            if prev_w == False and curr_w == True:
                withdraw_times[key] = wib_now
                changes.append(('withdraw', 'masuk', currency, chain_name, key))
            elif prev_w == True and curr_w == False:
                changes.append(('withdraw', 'keluar', currency, chain_name, key))
            elif prev_w == True and curr_w == True:
                withdraw_times[key] = old_withdraw_times.get(key, wib_now)
        else:
            if curr_w == True:
                withdraw_times[key] = wib_now
        
        if prev_d is not None:
            if prev_d == False and curr_d == True:
                deposit_times[key] = wib_now
                changes.append(('deposit', 'masuk', currency, chain_name, key))
            elif prev_d == True and curr_d == False:
                changes.append(('deposit', 'keluar', currency, chain_name, key))
            elif prev_d == True and curr_d == True:
                deposit_times[key] = old_deposit_times.get(key, wib_now)
        else:
            if curr_d == True:
                deposit_times[key] = wib_now
    
    previous_withdraw = current_withdraw
    previous_deposit = current_deposit
    
    withdraw_count = sum(1 for v in current_withdraw.values() if v)
    deposit_count = sum(1 for v in current_deposit.values() if v)
    
    print(f"📤 Withdraw Disabled: {withdraw_count} chains")
    print(f"📥 Deposit Disabled: {deposit_count} chains")
    print(f"📊 Total Tracking: {len(current_withdraw)} chains")
    print("="*60)
    
    if loaded_state and changes:
        print(f"\n📊 Detected {len(changes)} changes:")
        
        for change_type, action, currency, chain_name, key in changes:
            emoji = "🟢" if action == 'masuk' else "🔴"
            
            if action == 'keluar':
                if change_type == 'withdraw' and key in withdraw_times:
                    del withdraw_times[key]
                if change_type == 'deposit' and key in deposit_times:
                    del deposit_times[key]
            
            type_text = "Withdraw" if change_type == 'withdraw' else "Deposit"
            action_text = "Masuk" if action == 'masuk' else "Keluar"
            
            print(f"   {emoji} {currency} - {chain_name} ({type_text} {action_text})")
            
            tg_msg = f"{emoji} <b>{action_text} {type_text} Maintenance</b>\n\n"
            tg_msg += f"💰 Coin  : <b>{currency} ({chain_name})</b>\n"
            tg_msg += f"📅 Time  : {wib_now}"
            send_telegram(tg_msg)
    elif loaded_state:
        print(f"\n✅ No changes since last run")
    else:
        print(f"\n📝 First run - state saved")
    
    save_state()

def get_withdraw_list():
    coins = []
    for key, disabled in previous_withdraw.items():
        if disabled:
            currency, chain = key.rsplit('_', 1)
            coin_time = withdraw_times.get(key, "Unknown")
            coins.append((f"{currency} - {chain}", coin_time))
    return coins

def get_deposit_list():
    coins = []
    for key, disabled in previous_deposit.items():
        if disabled:
            currency, chain = key.rsplit('_', 1)
            coin_time = deposit_times.get(key, "Unknown")
            coins.append((f"{currency} - {chain}", coin_time))
    return coins

def telegram_handler():
    print("📱 Telegram handler started")
    last_update_id = None
    
    while True:
        try:
            updates = get_telegram_updates(last_update_id)
            
            for update in updates:
                last_update_id = update['update_id'] + 1
                
                message = update.get('message', {})
                text = message.get('text', '')
                chat_id = message.get('chat', {}).get('id')
                
                if not text or not chat_id:
                    continue
                
                if text == '/start':
                    reply = "🤖 <b>Gate.io Maintenance Bot</b>\n\n"
                    reply += "📋 <b>Commands:</b>\n"
                    reply += "/withdraw - List withdraw maintenance\n"
                    reply += "/deposit - List deposit maintenance\n"
                    reply += "/export - Download maintenance.txt\n"
                    reply += "/export_json - Download state JSON\n"
                    reply += "/status - Bot status\n"
                    reply += "/reset - Reset state"
                    send_telegram_to(chat_id, reply)
                
                elif text == '/withdraw':
                    coins = get_withdraw_list()
                    send_long_message(chat_id, "📤 <b>WITHDRAW MAINTENANCE</b>", coins)
                
                elif text == '/deposit':
                    coins = get_deposit_list()
                    send_long_message(chat_id, "📥 <b>DEPOSIT MAINTENANCE</b>", coins)
                
                elif text == '/export':
                    send_telegram_to(chat_id, "⏳ Generating file...")
                    filepath = generate_export_file()
                    wib = get_wib_time()
                    w = sum(1 for v in previous_withdraw.values() if v)
                    d = sum(1 for v in previous_deposit.values() if v)
                    caption = f"📊 Maintenance Report\n📅 {wib}\n📤 Withdraw: {w} | 📥 Deposit: {d}"
                    
                    if send_telegram_file(chat_id, filepath, caption):
                        print(f"\n📄 Export sent to {chat_id}")
                    else:
                        send_telegram_to(chat_id, "❌ Gagal mengirim file")
                
                elif text == '/export_json':
                    save_state()
                    if os.path.exists(STATE_FILE):
                        wib = get_wib_time()
                        w = sum(1 for v in previous_withdraw.values() if v)
                        d = sum(1 for v in previous_deposit.values() if v)
                        caption = f"📊 State JSON\n📅 {wib}\n📤 Withdraw: {w} | 📥 Deposit: {d}"
                        
                        if send_telegram_file(chat_id, STATE_FILE, caption):
                            print(f"\n📄 JSON exported to {chat_id}")
                        else:
                            send_telegram_to(chat_id, "❌ Gagal mengirim file")
                    else:
                        send_telegram_to(chat_id, "❌ State file tidak ditemukan")
                
                elif text == '/status':
                    wib = get_wib_time()
                    status = "🟢 Connected" if ws_connected else "🔴 Disconnected"
                    w_count = sum(1 for v in previous_withdraw.values() if v)
                    d_count = sum(1 for v in previous_deposit.values() if v)
                    
                    reply = f"📊 <b>BOT STATUS</b>\n\n"
                    reply += f"📅 Time: {wib}\n"
                    reply += f"🔌 WebSocket: {status}\n"
                    reply += f"🔄 Reconnects: {reconnect_count}\n"
                    reply += f"📤 Withdraw: {w_count}\n"
                    reply += f"📥 Deposit: {d_count}\n"
                    reply += f"📊 Total: {len(previous_withdraw)} chains"
                    send_telegram_to(chat_id, reply)
                
                elif text == '/reset':
                    if os.path.exists(STATE_FILE):
                        os.remove(STATE_FILE)
                        send_telegram_to(chat_id, "✅ State reset! Restart bot.")
                    else:
                        send_telegram_to(chat_id, "ℹ️ No state file.")
            
            time.sleep(1)
        except:
            time.sleep(3)

def on_message(ws, message):
    global previous_withdraw, previous_deposit
    
    try:
        data = json.loads(message)
        
        if data.get('event') == 'update' and data.get('channel') == 'spot.currency_status':
            result = data.get('result', {})
            currency = result.get('currency', '')
            chains = result.get('chains', [])
            
            state_changed = False
            
            for chain in chains:
                chain_name = chain.get('name', '')
                withdraw_disabled = chain.get('withdraw_disabled', False)
                deposit_disabled = chain.get('deposit_disabled', False)
                key = f"{currency}_{chain_name}"
                
                prev_withdraw = previous_withdraw.get(key, None)
                prev_deposit = previous_deposit.get(key, None)
                wib = get_wib_time()
                
                if prev_withdraw == False and withdraw_disabled == True:
                    state_changed = True
                    withdraw_times[key] = wib
                    print(f"\n🟢 Masuk Withdraw Maintenance: {currency} ({chain_name})")
                    
                    tg_msg = f"🟢 <b>Masuk Withdraw Maintenance</b>\n\n"
                    tg_msg += f"💰 Coin  : <b>{currency} ({chain_name})</b>\n"
                    tg_msg += f"📅 Time  : {wib}"
                    send_telegram(tg_msg)
                
                elif prev_withdraw == True and withdraw_disabled == False:
                    state_changed = True
                    if key in withdraw_times:
                        del withdraw_times[key]
                    print(f"\n🔴 Keluar Withdraw Maintenance: {currency} ({chain_name})")
                    
                    tg_msg = f"🔴 <b>Keluar Withdraw Maintenance</b>\n\n"
                    tg_msg += f"💰 Coin  : <b>{currency} ({chain_name})</b>\n"
                    tg_msg += f"📅 Time  : {wib}"
                    send_telegram(tg_msg)
                
                elif prev_withdraw is None and withdraw_disabled == True:
                    state_changed = True
                    withdraw_times[key] = wib
                
                if prev_deposit == False and deposit_disabled == True:
                    state_changed = True
                    deposit_times[key] = wib
                    print(f"\n🟢 Masuk Deposit Maintenance: {currency} ({chain_name})")
                    
                    tg_msg = f"🟢 <b>Masuk Deposit Maintenance</b>\n\n"
                    tg_msg += f"💰 Coin  : <b>{currency} ({chain_name})</b>\n"
                    tg_msg += f"📅 Time  : {wib}"
                    send_telegram(tg_msg)
                
                elif prev_deposit == True and deposit_disabled == False:
                    state_changed = True
                    if key in deposit_times:
                        del deposit_times[key]
                    print(f"\n🔴 Keluar Deposit Maintenance: {currency} ({chain_name})")
                    
                    tg_msg = f"🔴 <b>Keluar Deposit Maintenance</b>\n\n"
                    tg_msg += f"💰 Coin  : <b>{currency} ({chain_name})</b>\n"
                    tg_msg += f"📅 Time  : {wib}"
                    send_telegram(tg_msg)
                
                elif prev_deposit is None and deposit_disabled == True:
                    state_changed = True
                    deposit_times[key] = wib
                
                previous_withdraw[key] = withdraw_disabled
                previous_deposit[key] = deposit_disabled
            
            if state_changed:
                save_state()
    
    except Exception as e:
        print(f"\n❌ Parse error: {e}")

def on_error(ws, error):
    print(f"\n❌ WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    global ws_connected, reconnect_count
    ws_connected = False
    reconnect_count += 1
    print(f"\n⚠️ Disconnected (#{reconnect_count})")

def on_open(ws):
    global ws_connected, reconnect_count
    ws_connected = True
    print(f"✅ WebSocket {'reconnected' if reconnect_count > 0 else 'connected'}!")
    
    subscribe_message = {
        "time": int(time.time()),
        "channel": "spot.currency_status",
        "event": "subscribe"
    }
    ws.send(json.dumps(subscribe_message))
    print("📡 Subscribed to currency status")

def start_websocket():
    while True:
        try:
            websocket.enableTrace(False)
            ws = websocket.WebSocketApp(
                "wss://api.gateio.ws/ws/v4/",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"\n❌ Exception: {e}")
        
        print("🔄 Reconnecting in 5s...")
        time.sleep(5)

def periodic_check():
    check_count = 0
    while True:
        try:
            time.sleep(30)
            check_count += 1
            
            wib = get_wib_time()
            status = "🟢" if ws_connected else "🔴"
            w = sum(1 for v in previous_withdraw.values() if v)
            d = sum(1 for v in previous_deposit.values() if v)
            print(f"\r🔄 {wib} | {status} | W:{w} D:{d}", end="", flush=True)
            
            if check_count % 10 == 0:
                save_state()
        except:
            break

def main():
    global previous_withdraw, previous_deposit, withdraw_times, deposit_times
    
    wib_now = get_wib_time()
    
    print("🤖 Gate.io Maintenance Monitor")
    print(f"📅 Started: {wib_now}")
    print("="*60)
    
    loaded_state = load_state()
    
    if loaded_state:
        withdraw_times = loaded_state.get('withdraw_times', {})
        deposit_times = loaded_state.get('deposit_times', {})
        print(f"📂 Last update: {loaded_state.get('last_update', 'Unknown')}")
    
    currencies = check_maintenance_rest()
    
    if currencies == "exit":
        return
    
    while not currencies:
        print("❌ Failed. Retrying...")
        try:
            time.sleep(5)
            currencies = check_maintenance_rest()
            if currencies == "exit":
                return
        except KeyboardInterrupt:
            return
    
    process_maintenance_data(currencies, loaded_state)
    
    print("\n👀 Starting WebSocket...")
    print("="*60)
    
    threading.Thread(target=telegram_handler, daemon=True).start()
    threading.Thread(target=start_websocket, daemon=True).start()
    threading.Thread(target=periodic_check, daemon=True).start()
    
    w = sum(1 for v in previous_withdraw.values() if v)
    d = sum(1 for v in previous_deposit.values() if v)
    
    startup_msg = f"🤖 <b>Bot Started</b>\n\n"
    startup_msg += f"📅 {wib_now}\n"
    startup_msg += f"📤 Withdraw: {w}\n"
    startup_msg += f"📥 Deposit: {d}\n"
    startup_msg += f"📊 Total: {len(previous_withdraw)}"
    if loaded_state:
        startup_msg += f"\n📂 <i>State restored</i>"
    send_telegram(startup_msg)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        wib = get_wib_time()
        print(f"\n\n👋 Stopped at {wib}")
        save_state()
        send_telegram(f"🛑 <b>Bot Stopped</b>\n\n📅 {wib}")

if __name__ == "__main__":
    main()
