from pidog import Pidog
from time import sleep
import os
from math import pi, atan2, sqrt, cos, sin
from flask import Flask, render_template, request, jsonify
import signal
import sys
import threading
import random
import time

my_dog = Pidog()

SIT_HEAD_PITCH = -40
STAND_HEAD_PITCH = 0
STATUS_STAND = 0
STATUS_SIT = 1
STATUS_LIE = 2

sleep(0.1)
head_yrp = [0, 0, 0]
head_origin_yrp = [0, 0, 0]
head_pitch_init = 0
current_status = STATUS_LIE

MIN_SPEED = 85
MAX_SPEED = 98
DEADZONE = 0.35

autonomous_mode_enabled = False
_autonomous_thread = None
autonomous_lock = threading.Lock()

def cleanup_gpio():
    global my_dog
    try:
        if my_dog is not None:
            my_dog.close()
            my_dog = None
    except Exception as e:
        print(f"Error during cleanup: {e}")

def signal_handler(sig, frame):
    print('\nExiting...')
    cleanup_gpio()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def map_value(x, in_min, in_max, out_min, out_max):
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def set_head(roll=None, pitch=None, yaw=None):
    global head_yrp
    if roll is not None:
        head_yrp[1] = roll + head_origin_yrp[1]
    if pitch is not None:
        head_yrp[2] = pitch + head_origin_yrp[2]
    if yaw is not None:
        head_yrp[0] = yaw + head_origin_yrp[0]
    my_dog.head_move([head_yrp], pitch_comp=head_pitch_init,
                     immediately=True, speed=100)

def getIP():
    wlan0 = os.popen(
        "ifconfig wlan0 |awk '/inet/'|awk 'NR==1 {print $2}'").readline().strip('\n')
    eth0 = os.popen(
        "ifconfig eth0 |awk '/inet/'|awk 'NR==1 {print $2}'").readline().strip('\n')

    if wlan0 == '':
        wlan0 = None
    if eth0 == '':
        eth0 = None

    return wlan0, eth0

def set_head_pitch_init(pitch):
    global head_pitch_init
    head_pitch_init = pitch
    my_dog.head_move([head_yrp], pitch_comp=pitch, immediately=True, speed=80)

def change_status(status):
    global current_status
    current_status = status
    if status == STATUS_STAND:
        set_head_pitch_init(STAND_HEAD_PITCH)
        my_dog.do_action('stand', speed=70)
    elif status == STATUS_SIT:
        set_head_pitch_init(SIT_HEAD_PITCH)
        my_dog.do_action('sit', speed=70)
    elif status == STATUS_LIE:
        set_head_pitch_init(STAND_HEAD_PITCH)
        my_dog.do_action('lie', speed=70)

def calculate_direction_from_angle(angle, intensity):
    if intensity < 0.25:
        return "stop", 0
    
    angle = angle % 360
    
    if (angle >= 315 or angle < 45):
        return "forward", intensity
    elif (angle >= 45 and angle < 135):
        return "turn_right", intensity
    elif (angle >= 135 and angle < 225):
        return "backward", intensity
    elif (angle >= 225 and angle < 315):
        return "turn_left", intensity
    else:
        return "stop", 0

def calculate_direction_from_kx_ky(kx, ky):
    kr = sqrt(kx**2 + ky**2)
    if kr < DEADZONE:
        return "stop", 0
    ka = atan2(ky, kx) * 180 / pi
    
    if (ka > 45 and ka < 135):
        return "forward", kr
    elif (ka > 135 or ka < -135):
        return "turn_left", kr
    elif (ka > -45 and ka < 45):
        return "turn_right", kr
    elif (ka > -135 and ka < -45):
        return "backward", kr
    else:
        return "stop", 0

def safe_action(action_name, speed=90, step_count=1):
    """Exécute une action et attend qu'elle se termine complètement"""
    try:
        print(f"[AUTO] Executing {action_name}")
        my_dog.do_action(action_name, speed=speed, step_count=step_count)
        my_dog.wait_all_done()  # Attend la fin COMPLÈTE de l'action
        sleep(0.5)  # Pause supplémentaire pour éviter les conflits
        return True
    except Exception as e:
        print(f"[AUTO] Erreur lors de {action_name}: {e}")
        return False

def check_obstacle():
    """Vérifie s'il y a un obstacle et évite si nécessaire"""
    try:
        distance = my_dog.read_distance()
        if distance is not None and distance < 20:
            print(f"[AUTO] Obstacle détecté à {distance}cm - Évitement")
            # Arrêt immédiat
            my_dog.legs_stop()
            my_dog.wait_all_done()
            sleep(0.5)
            
            # Turn aléatoire pour éviter
            turn_direction = random.choice(['turn_left', 'turn_right'])
            safe_action(turn_direction, speed=85, step_count=2)
            return True
        return False
    except Exception as e:
        print(f"[AUTO] Erreur lecture capteur: {e}")
        return False

def autonomous_behavior():
    """Mode autonome optimisé - Une seule action à la fois"""
    global autonomous_mode_enabled
    
    def is_stopped():
        with autonomous_lock:
            return not autonomous_mode_enabled
    
    print("[AUTO] 🤖 Mode autonome démarré")
    
    # Séquence d'actions autonomes
    actions_sequence = [
        # (action, durée_max_secondes, description)
        ('stand', 3, 'Se lever'),
        ('bark', 5, 'Aboyer'),
        ('explore', 20, 'Explorer et éviter obstacles'),
        ('wag_tail', 3, 'Remuer la queue'),
        ('sit', 3, 'S\'asseoir'),
        ('stretch', 5, 'S\'étirer'),
        ('lie', 3, 'Se coucher'),
        ('rest', 5, 'Se reposer'),
    ]
    
    while not is_stopped():
        for action_name, max_duration, description in actions_sequence:
            if is_stopped():
                break
                
            print(f"[AUTO] 📋 Phase: {description}")
            start_time = time.time()
            
            if action_name == 'explore':
                # Mode exploration avec évitement d'obstacles
                while time.time() - start_time < max_duration and not is_stopped():
                    if check_obstacle():
                        continue  # L'évitement a été fait, on continue
                    
                    # Mouvement aléatoire
                    move_choice = random.choices(
                        ['forward', 'turn_left', 'turn_right'], 
                        weights=[70, 15, 15]  # 70% chance d'aller tout droit
                    )[0]
                    
                    safe_action(move_choice, speed=random.randint(85, 95), step_count=1)
                    
                    if is_stopped():
                        break
                        
            elif action_name == 'rest':
                # Phase de repos - petits mouvements de tête
                for _ in range(max_duration):
                    if is_stopped():
                        break
                    # Petit mouvement de tête aléatoire
                    try:
                        yaw = random.randint(-30, 30)
                        set_head(yaw=yaw)
                        sleep(1)
                    except:
                        pass
                        
            else:
                # Action standard
                safe_action(action_name, speed=random.randint(80, 95))
                
                # Attendre le reste de la durée
                elapsed = time.time() - start_time
                remaining = max_duration - elapsed
                if remaining > 0:
                    sleep(min(remaining, 2))  # Max 2s d'attente supplémentaire
            
            if is_stopped():
                break
    
    # Arrêt propre
    print("[AUTO] 🛑 Mode autonome arrêté")
    try:
        my_dog.legs_stop()
        my_dog.wait_all_done()
        set_head(yaw=0, pitch=0)  # Recentrer la tête
    except:
        pass

# Flask App
app = Flask(__name__)
last_command = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/simple')
def simple():
    return render_template('simple.html')

@app.route('/advanced')
def advanced():
    return render_template('advanced.html')

@app.route('/command', methods=['POST'])
def handle_command():
    global last_command, autonomous_mode_enabled
    
    # Désactiver le mode autonome si commande manuelle
    with autonomous_lock:
        if autonomous_mode_enabled:
            autonomous_mode_enabled = False
            print("[AUTO] Mode autonome désactivé par commande manuelle")
    
    if not my_dog.is_legs_done():
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    
    data = request.get_json()
    
    if 'angle' in data and 'intensity' in data:
        angle = float(data.get('angle', 0))
        intensity = float(data.get('intensity', 0))
        direction, value = calculate_direction_from_angle(angle, intensity)
        
    elif 'kx' in data and 'ky' in data:
        kx = float(data.get('kx', 0))
        ky = float(data.get('ky', 0))
        direction, value = calculate_direction_from_kx_ky(kx, ky)
        
    else:
        return jsonify({'status': 'error', 'message': 'Format de données invalide'})

    speed = 0 if direction == "stop" else int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(value, 1.0))
    
    valid_directions = ["forward", "backward", "turn_left", "turn_right", "stop"]
    if direction not in valid_directions:
        return jsonify({'status': 'error', 'message': f'Commande {direction} non reconnue.'})
    
    try:
        if direction != last_command and last_command not in [None, "stop"]:
            my_dog.legs_stop()
            my_dog.wait_all_done()
        
        if direction == "forward":
            my_dog.do_action('forward', speed=speed)
        elif direction == "backward":
            my_dog.do_action('backward', speed=speed)
        elif direction == "turn_left":
            my_dog.do_action('turn_left', speed=speed)
        elif direction == "turn_right":
            my_dog.do_action('turn_right', speed=speed)
        elif direction == "stop":
            my_dog.legs_stop()
            my_dog.wait_all_done()
        
        last_command = direction
        return jsonify({'status': 'success', 'message': f'{direction} - vitesse {speed}%'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur: {str(e)}'})

@app.route('/head_control', methods=['POST'])
def handle_head_control():
    data = request.get_json()
    qx = float(data.get('qx', 0))
    qy = float(data.get('qy', 0))
    
    try:
        if abs(qx) > 5 or abs(qy) > 5:
            yaw = map_value(qx, -100, 100, -90, 90)
            pitch = map_value(qy, -100, 100, -30, 30)
            set_head(yaw=yaw, pitch=pitch)
        else:
            set_head(yaw=0, pitch=0)
        
        return jsonify({'status': 'success', 'message': f'Tête: yaw={qx:.1f}, pitch={qy:.1f}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur tête: {str(e)}'})

@app.route('/action', methods=['POST'])
def handle_action():
    data = request.get_json()
    action = data.get('action', '')
    
    actions_disponibles = {
        "sit": lambda: my_dog.do_action('sit', speed=70),
        "stand_up": lambda: my_dog.do_action('stand', speed=70),
        "lie_down": lambda: my_dog.do_action('lie', speed=70),
        "wag_tail": lambda: my_dog.do_action('wag_tail', speed=100),
        "stretch": lambda: my_dog.do_action('stretch', speed=80),
        "shake_head": lambda: my_dog.do_action('shake_head', speed=80),
        "bark": lambda: my_dog.do_action('bark', speed=100),
    }
    
    if action not in actions_disponibles:
        return jsonify({'status': 'error', 'message': f'Action {action} non reconnue'})
    
    try:
        actions_disponibles[action]()
        return jsonify({'status': 'success', 'message': f'Action {action} exécutée'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur action: {str(e)}'})

@app.route('/autonomous_mode', methods=['POST'])
def set_autonomous_mode():
    global autonomous_mode_enabled, _autonomous_thread
    
    data = request.get_json()
    enabled = bool(data.get('enabled', False))
    
    with autonomous_lock:
        if enabled and not autonomous_mode_enabled:
            print("[AUTO] 🚀 Activation du mode autonome")
            autonomous_mode_enabled = True
            _autonomous_thread = threading.Thread(target=autonomous_behavior, daemon=True)
            _autonomous_thread.start()
            
        elif not enabled and autonomous_mode_enabled:
            print("[AUTO] 🛑 Désactivation du mode autonome")
            autonomous_mode_enabled = False
            # Arrêt immédiat
            try:
                my_dog.legs_stop()
                my_dog.wait_all_done()
            except:
                pass
    
    return jsonify({
        'status': 'success', 
        'enabled': autonomous_mode_enabled,
        'message': f"Mode autonome {'activé' if autonomous_mode_enabled else 'désactivé'}"
    })

@app.route('/get_ip', methods=['GET'])
def get_ip():
    wlan0, eth0 = getIP()
    ip = wlan0 if wlan0 else eth0
    return jsonify({'ip': ip})

@app.route('/sensor_data', methods=['GET'])
def get_sensor_data():
    try:
        distance = round(my_dog.read_distance(), 2)
        return jsonify({
            'distance': distance,
            'status': current_status,
            'autonomous_mode': autonomous_mode_enabled
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/status', methods=['GET'])
def get_status():
    try:
        return jsonify({
            'status': 'connected',
            'robot_status': current_status,
            'is_busy': not my_dog.is_all_done(),
            'autonomous_mode': autonomous_mode_enabled
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == "__main__":
    try:
        print("🐕 Démarrage du serveur PiDog avec mode autonome optimisé...")
        wlan0, eth0 = getIP()
        ip = wlan0 if wlan0 else eth0
        if ip:
            print(f"📡 Interface Web disponible sur : http://{ip}:5000")
            print(f"🎮 Interface Simple : http://{ip}:5000/simple")
            print(f"🚀 Interface Avancée : http://{ip}:5000/advanced")
        else:
            print("📡 Interface Web disponible sur : http://localhost:5000")
        
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur...")
    except Exception as e:
        print(f"\033[31mERROR: {e}\033[m")
    finally:
        cleanup_gpio()