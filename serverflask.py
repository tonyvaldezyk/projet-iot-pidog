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
last_manual_command_time = 0  # Pour éviter les conflits

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

def calculate_direction_from_kx_ky(kx, ky):
    """Fonction corrigée pour calculer la direction"""
    kr = sqrt(kx**2 + ky**2)
    if kr < DEADZONE:
        return "stop", 0
    
    # Calcul de l'angle en degrés
    ka = atan2(ky, kx) * 180 / pi
    
    # Logique de direction corrigée
    # kx > 0 = droite, kx < 0 = gauche
    # ky > 0 = avant, ky < 0 = arrière
    if ky > 0.5:  # Principalement vers l'avant
        return "forward", kr
    elif ky < -0.5:  # Principalement vers l'arrière
        return "backward", kr
    elif kx > 0.3:  # Principalement vers la droite
        return "turn_right", kr
    elif kx < -0.3:  # Principalement vers la gauche
        return "turn_left", kr
    else:
        return "stop", 0

def smooth_action(action_name, speed=90, step_count=3):
    """Action plus fluide sans attente forcée"""
    try:
        print(f"[AUTO] Executing {action_name} (speed={speed}, steps={step_count})")
        my_dog.do_action(action_name, speed=speed, step_count=step_count)
        return True
    except Exception as e:
        print(f"[AUTO] Erreur lors de {action_name}: {e}")
        return False

def check_obstacle_non_blocking():
    """Vérification d'obstacle sans blocage"""
    try:
        distance = my_dog.read_distance()
        if distance is not None and distance < 25:
            print(f"[AUTO] Obstacle détecté à {distance}cm")
            return True
        return False
    except Exception as e:
        print(f"[AUTO] Erreur lecture capteur: {e}")
        return False

def autonomous_behavior():
    """Mode autonome fluide et non-saccadé"""
    global autonomous_mode_enabled, last_manual_command_time
    
    def is_stopped():
        with autonomous_lock:
            return not autonomous_mode_enabled
    
    print("[AUTO] 🤖 Mode autonome démarré - Version fluide")
    
    # Initialisation : se lever
    smooth_action('stand', speed=75)
    sleep(2)  # Temps pour se lever complètement
    
    # Variables pour l'exploration fluide
    current_move_time = 0
    move_duration = 0
    current_action = "stop"
    obstacle_turn_time = 0
    last_direction_change = time.time()
    
    while not is_stopped():
        current_time = time.time()
        
        # Évitement d'obstacles en priorité
        if check_obstacle_non_blocking():
            if current_action != "avoiding":
                print("[AUTO] 🚨 Évitement d'obstacle")
                # Arrêt en douceur
                my_dog.legs_stop()
                sleep(0.3)
                
                # Tourner dans une direction aléatoire
                turn_direction = random.choice(['turn_left', 'turn_right'])
                smooth_action(turn_direction, speed=88, step_count=4)
                current_action = "avoiding"
                obstacle_turn_time = current_time
                last_direction_change = current_time
            
            # Continuer à tourner pendant 2 secondes
            elif current_time - obstacle_turn_time < 2.0:
                continue
            else:
                current_action = "stop"
                move_duration = 0
        
        # Exploration normale
        else:
            # Nouveau mouvement si nécessaire
            if current_action == "stop" or current_time - current_move_time > move_duration:
                if current_time - last_manual_command_time < 3:
                    # Pause si commande manuelle récente
                    sleep(0.5)
                    continue
                
                # Choisir une nouvelle action
                actions_weights = [
                    ("forward", 50, (3, 6)),      # 50% chance, 3-6 secondes
                    ("turn_left", 20, (1, 3)),    # 20% chance, 1-3 secondes  
                    ("turn_right", 20, (1, 3)),   # 20% chance, 1-3 secondes
                    ("explore_head", 5, (2, 4)),  # 5% chance, mouvement de tête
                    ("action_random", 5, (2, 3)), # 5% chance, action spéciale
                ]
                
                # Sélection pondérée
                total_weight = sum(w[1] for w in actions_weights)
                rand_val = random.randint(1, total_weight)
                cumulative = 0
                
                for action, weight, duration_range in actions_weights:
                    cumulative += weight
                    if rand_val <= cumulative:
                        current_action = action
                        move_duration = random.uniform(*duration_range)
                        current_move_time = current_time
                        last_direction_change = current_time
                        
                        if action == "forward":
                            speed = random.randint(87, 95)
                            step_count = random.randint(5, 10)  # Mouvements plus longs
                            smooth_action('forward', speed=speed, step_count=step_count)
                            print(f"[AUTO] 🔄 Avance pendant {move_duration:.1f}s")
                            
                        elif action in ["turn_left", "turn_right"]:
                            speed = random.randint(82, 90)
                            step_count = random.randint(2, 5)
                            smooth_action(action, speed=speed, step_count=step_count)
                            print(f"[AUTO] 🔄 Tourne {action} pendant {move_duration:.1f}s")
                            
                        elif action == "explore_head":
                            # Mouvement de tête tout en étant immobile
                            print(f"[AUTO] 👁️ Exploration visuelle pendant {move_duration:.1f}s")
                            
                        elif action == "action_random":
                            # Action spéciale occasionnelle
                            special_actions = ['wag_tail', 'bark', 'stretch']
                            special_action = random.choice(special_actions)
                            smooth_action(special_action, speed=random.randint(80, 100))
                            print(f"[AUTO] 🎭 Action spéciale: {special_action}")
                        
                        break
            
            # Exécution continue de l'action courante
            elif current_action == "explore_head":
                # Mouvement de tête aléatoire
                if random.random() < 0.3:  # 30% de chance par cycle
                    yaw = random.randint(-40, 40)
                    pitch = random.randint(-20, 20)
                    set_head(yaw=yaw, pitch=pitch)
        
        # Pause courte pour éviter la surcharge CPU
        sleep(0.2)
    
    # Arrêt propre
    print("[AUTO] 🛑 Mode autonome arrêté - Arrêt en douceur")
    try:
        my_dog.legs_stop()
        sleep(0.5)
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

@app.route('/voice')
def advanced():
    return render_template('advanced.html')

@app.route('/command', methods=['POST'])
def handle_command():
    global last_command, autonomous_mode_enabled, last_manual_command_time
    
    # Marquer le timestamp de la commande manuelle
    last_manual_command_time = time.time()
    
    # Désactiver le mode autonome si commande manuelle
    with autonomous_lock:
        if autonomous_mode_enabled:
            autonomous_mode_enabled = False
            print("[AUTO] Mode autonome désactivé par commande manuelle")
    
    if not my_dog.is_legs_done():
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    
    data = request.get_json()
    
    # Traitement des coordonnées kx, ky (interface joystick)
    if 'kx' in data and 'ky' in data:
        kx = float(data.get('kx', 0))
        ky = float(data.get('ky', 0))
        direction, value = calculate_direction_from_kx_ky(kx, ky)
        
        print(f"[CMD] kx={kx:.2f}, ky={ky:.2f} -> {direction} (force={value:.2f})")
        
    # Traitement de l'angle et intensité (interface alternative)
    elif 'angle' in data and 'intensity' in data:
        angle = float(data.get('angle', 0))
        intensity = float(data.get('intensity', 0))
        # Conversion angle -> kx, ky pour utiliser la même logique
        angle_rad = angle * pi / 180
        kx = intensity * cos(angle_rad)
        ky = intensity * sin(angle_rad)
        direction, value = calculate_direction_from_kx_ky(kx, ky)
        
    else:
        return jsonify({'status': 'error', 'message': 'Format de données invalide'})

    # Calcul de la vitesse
    speed = 0 if direction == "stop" else int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(value, 1.0))
    
    valid_directions = ["forward", "backward", "turn_left", "turn_right", "stop"]
    if direction not in valid_directions:
        return jsonify({'status': 'error', 'message': f'Commande {direction} non reconnue.'})
    
    try:
        # Gestion améliorée des transitions
        if direction != last_command:
            if last_command not in [None, "stop"]:
                my_dog.legs_stop()
                # Attente plus courte pour des transitions plus fluides
                sleep(0.1)
        
        # Exécution de la commande
        if direction == "forward":
            my_dog.do_action('forward', speed=speed, step_count=2)
        elif direction == "backward":
            my_dog.do_action('backward', speed=speed, step_count=2)
        elif direction == "turn_left":
            my_dog.do_action('turn_left', speed=speed, step_count=2)
        elif direction == "turn_right":
            my_dog.do_action('turn_right', speed=speed, step_count=2)
        elif direction == "stop":
            my_dog.legs_stop()
        
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
    global last_manual_command_time
    last_manual_command_time = time.time()
    
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
            print("[AUTO] 🚀 Activation du mode autonome fluide")
            autonomous_mode_enabled = True
            _autonomous_thread = threading.Thread(target=autonomous_behavior, daemon=True)
            _autonomous_thread.start()
            
        elif not enabled and autonomous_mode_enabled:
            print("[AUTO] 🛑 Désactivation du mode autonome")
            autonomous_mode_enabled = False
            # Arrêt en douceur
            try:
                my_dog.legs_stop()
                sleep(0.2)
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
        print("🐕 Démarrage du serveur PiDog - Version optimisée")
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