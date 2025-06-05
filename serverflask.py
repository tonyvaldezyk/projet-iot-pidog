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
from queue import Queue, Empty
from enum import Enum

my_dog = Pidog()

# Constants
SIT_HEAD_PITCH = -40
STAND_HEAD_PITCH = 0
STATUS_STAND = 0
STATUS_SIT = 1
STATUS_LIE = 2

MIN_SPEED = 85
MAX_SPEED = 98
DEADZONE = 0.35

# État du robot
class RobotState(Enum):
    IDLE = "idle"
    MANUAL = "manual"
    AUTONOMOUS = "autonomous"
    TRANSITIONING = "transitioning"

# Variables globales
sleep(0.1)
head_yrp = [0, 0, 0]
head_origin_yrp = [0, 0, 0]
head_pitch_init = 0
current_status = STATUS_LIE

# Mode autonome amélioré
autonomous_mode_enabled = False
_autonomous_thread = None
autonomous_lock = threading.Lock()
command_queue = Queue(maxsize=10)
robot_state = RobotState.IDLE
last_action_time = 0
action_cooldown = 0.5  # Temps minimum entre actions

# Séquence d'actions prédéfinies pour le mode autonome
AUTONOMOUS_SEQUENCE = [
    # Phase 1: Réveil et étirement
    {"action": "stand", "duration": 2.0, "params": {"speed": 70}},
    {"action": "stretch", "duration": 3.0, "params": {"speed": 80}},
    {"action": "wag_tail", "duration": 2.0, "params": {"speed": 100}},
    
    # Phase 2: Exploration
    {"action": "forward", "duration": 3.0, "params": {"speed": 90, "step_count": 5}},
    {"action": "turn_left", "duration": 1.5, "params": {"speed": 85, "step_count": 3}},
    {"action": "forward", "duration": 2.0, "params": {"speed": 88, "step_count": 4}},
    {"action": "turn_right", "duration": 1.5, "params": {"speed": 85, "step_count": 3}},
    
    # Phase 3: Inspection
    {"action": "stop", "duration": 1.0, "params": {}},
    {"action": "head_scan", "duration": 3.0, "params": {"range": 60}},
    {"action": "bark", "duration": 1.0, "params": {"speed": 100}},
    
    # Phase 4: Mouvements avancés
    {"action": "backward", "duration": 2.0, "params": {"speed": 85, "step_count": 3}},
    {"action": "turn_left", "duration": 2.0, "params": {"speed": 90, "step_count": 4}},
    {"action": "shake_head", "duration": 2.0, "params": {"speed": 80}},
    
    # Phase 5: Repos
    {"action": "sit", "duration": 3.0, "params": {"speed": 70}},
    {"action": "wag_tail", "duration": 2.0, "params": {"speed": 90}},
    {"action": "stand", "duration": 2.0, "params": {"speed": 70}},
]

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
    stop_autonomous_mode()
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

def wait_for_action_completion(timeout=5):
    """Attendre que l'action soit terminée avec timeout"""
    start_time = time.time()
    while not my_dog.is_legs_done() and time.time() - start_time < timeout:
        sleep(0.1)
    return my_dog.is_legs_done()

def execute_action_safe(action_name, **params):
    """Exécuter une action de manière sûre"""
    global last_action_time
    
    # Vérifier le cooldown
    current_time = time.time()
    time_since_last = current_time - last_action_time
    if time_since_last < action_cooldown:
        sleep(action_cooldown - time_since_last)
    
    # Attendre que le robot soit prêt
    if not wait_for_action_completion(3):
        print(f"[WARN] Robot toujours occupé, forçage arrêt")
        my_dog.legs_stop()
        sleep(0.3)
    
    try:
        print(f"[ACTION] Exécution: {action_name} avec {params}")
        my_dog.do_action(action_name, **params)
        last_action_time = time.time()
        return True
    except Exception as e:
        print(f"[ERROR] Erreur lors de {action_name}: {e}")
        return False

def calculate_direction_from_kx_ky(kx, ky):
    """Fonction corrigée pour calculer la direction"""
    kr = sqrt(kx**2 + ky**2)
    if kr < DEADZONE:
        return "stop", 0
    
    if ky > 0.5:
        return "forward", kr
    elif ky < -0.5:
        return "backward", kr
    elif kx > 0.3:
        return "turn_right", kr
    elif kx < -0.3:
        return "turn_left", kr
    else:
        return "stop", 0

def head_scan_movement(range_degrees=60, duration=3):
    """Mouvement de balayage de la tête"""
    start_time = time.time()
    while time.time() - start_time < duration:
        if not autonomous_mode_enabled:
            break
        
        progress = (time.time() - start_time) / duration
        angle = sin(progress * 2 * pi) * range_degrees
        set_head(yaw=angle, pitch=0)
        sleep(0.1)
    
    # Recentrer la tête
    set_head(yaw=0, pitch=0)

def check_obstacle_async():
    """Vérification d'obstacle non-bloquante"""
    try:
        distance = my_dog.read_distance()
        return distance is not None and distance < 30
    except:
        return False

def autonomous_sequence_runner():
    """Exécuteur de séquence autonome amélioré"""
    global autonomous_mode_enabled, robot_state
    
    print("[AUTO] 🤖 Démarrage du mode autonome séquencé")
    
    with autonomous_lock:
        robot_state = RobotState.AUTONOMOUS
    
    sequence_index = 0
    current_action_start = None
    obstacle_detected = False
    
    try:
        while autonomous_mode_enabled:
            # Vérifier les obstacles
            if check_obstacle_async():
                if not obstacle_detected:
                    print("[AUTO] 🚨 Obstacle détecté - Évitement")
                    obstacle_detected = True
                    my_dog.legs_stop()
                    sleep(0.3)
                    execute_action_safe("turn_right", speed=90, step_count=4)
                    sleep(1.5)
                    continue
            else:
                obstacle_detected = False
            
            # Récupérer l'action courante
            current_sequence = AUTONOMOUS_SEQUENCE[sequence_index]
            
            # Démarrer une nouvelle action
            if current_action_start is None:
                print(f"[AUTO] Phase {sequence_index + 1}/{len(AUTONOMOUS_SEQUENCE)}: {current_sequence['action']}")
                
                if current_sequence["action"] == "stop":
                    my_dog.legs_stop()
                elif current_sequence["action"] == "head_scan":
                    # Lancer le scan de tête dans un thread séparé
                    threading.Thread(
                        target=head_scan_movement, 
                        args=(current_sequence["params"].get("range", 60), current_sequence["duration"]),
                        daemon=True
                    ).start()
                else:
                    execute_action_safe(current_sequence["action"], **current_sequence["params"])
                
                current_action_start = time.time()
            
            # Vérifier si l'action est terminée
            elapsed_time = time.time() - current_action_start
            if elapsed_time >= current_sequence["duration"]:
                # Passer à l'action suivante
                sequence_index = (sequence_index + 1) % len(AUTONOMOUS_SEQUENCE)
                current_action_start = None
                
                # Pause entre les actions
                sleep(0.5)
            
            # Petite pause pour éviter la surcharge CPU
            sleep(0.1)
    
    except Exception as e:
        print(f"[AUTO] Erreur: {e}")
    
    finally:
        print("[AUTO] 🛑 Arrêt du mode autonome")
        with autonomous_lock:
            robot_state = RobotState.IDLE
        
        # Arrêt propre
        my_dog.legs_stop()
        set_head(yaw=0, pitch=0)

def stop_autonomous_mode():
    """Arrêter proprement le mode autonome"""
    global autonomous_mode_enabled, _autonomous_thread
    
    autonomous_mode_enabled = False
    if _autonomous_thread and _autonomous_thread.is_alive():
        _autonomous_thread.join(timeout=2)

# Flask App
app = Flask(__name__)
last_command = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/command', methods=['POST'])
def handle_command():
    global last_command, robot_state
    
    # Arrêter le mode autonome si actif
    if autonomous_mode_enabled:
        stop_autonomous_mode()
    
    with autonomous_lock:
        robot_state = RobotState.MANUAL
    
    # Vérifier si le robot est prêt
    if not wait_for_action_completion(1):
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    
    data = request.get_json()
    
    # Traitement des coordonnées
    if 'kx' in data and 'ky' in data:
        kx = float(data.get('kx', 0))
        ky = float(data.get('ky', 0))
        direction, value = calculate_direction_from_kx_ky(kx, ky)
        
        print(f"[CMD] kx={kx:.2f}, ky={ky:.2f} -> {direction} (force={value:.2f})")
    else:
        return jsonify({'status': 'error', 'message': 'Format de données invalide'})

    # Calcul de la vitesse
    speed = 0 if direction == "stop" else int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(value, 1.0))
    
    try:
        if direction != last_command and last_command not in [None, "stop"]:
            my_dog.legs_stop()
            sleep(0.1)
        
        if direction == "stop":
            my_dog.legs_stop()
        else:
            execute_action_safe(direction, speed=speed, step_count=2)
        
        last_command = direction
        return jsonify({'status': 'success', 'message': f'{direction} - vitesse {speed}%'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur: {str(e)}'})

@app.route('/action', methods=['POST'])
def handle_action():
    # Arrêter le mode autonome
    if autonomous_mode_enabled:
        stop_autonomous_mode()
    
    data = request.get_json()
    action = data.get('action', '')
    
    if not wait_for_action_completion(1):
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    
    actions_map = {
        "sit": {"speed": 70},
        "stand_up": {"speed": 70},
        "lie_down": {"speed": 70},
        "wag_tail": {"speed": 100},
        "stretch": {"speed": 80},
        "shake_head": {"speed": 80},
        "bark": {"speed": 100},
    }
    
    action_name = action.replace("_up", "").replace("_down", "").replace("stand_up", "stand").replace("lie_down", "lie")
    
    if action not in actions_map:
        return jsonify({'status': 'error', 'message': f'Action {action} non reconnue'})
    
    try:
        execute_action_safe(action_name, **actions_map[action])
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
            stop_autonomous_mode()  # S'assurer qu'aucun thread ne tourne
            autonomous_mode_enabled = True
            _autonomous_thread = threading.Thread(target=autonomous_sequence_runner, daemon=True)
            _autonomous_thread.start()
            
        elif not enabled and autonomous_mode_enabled:
            print("[AUTO] 🛑 Désactivation du mode autonome")
            stop_autonomous_mode()
    
    return jsonify({
        'status': 'success', 
        'enabled': autonomous_mode_enabled,
        'message': f"Mode autonome {'activé' if autonomous_mode_enabled else 'désactivé'}"
    })

@app.route('/status', methods=['GET'])
def get_status():
    try:
        with autonomous_lock:
            state = robot_state.value
        
        return jsonify({
            'status': 'connected',
            'robot_state': state,
            'is_busy': not my_dog.is_legs_done(),
            'autonomous_mode': autonomous_mode_enabled
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/head_control', methods=['POST'])
def handle_head_control():
    if autonomous_mode_enabled:
        return jsonify({'status': 'blocked', 'message': 'Mode autonome actif'})
    
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
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == "__main__":
    try:
        print("🐕 Démarrage du serveur PiDog - Version corrigée")
        wlan0, eth0 = getIP()
        ip = wlan0 if wlan0 else eth0
        if ip:
            print(f"📡 Interface Web disponible sur : http://{ip}:5000")
        else:
            print("📡 Interface Web disponible sur : http://localhost:5000")
        
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur...")
    except Exception as e:
        print(f"\033[31mERROR: {e}\033[m")
    finally:
        stop_autonomous_mode()
        cleanup_gpio()