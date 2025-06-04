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

# ===== CONFIGURATION OPTIMISÉE =====
my_dog = Pidog()

class RobotState(Enum):
    IDLE = "idle"
    MOVING = "moving" 
    BUSY = "busy"
    AUTONOMOUS = "autonomous"

class CommandType(Enum):
    MOVE = "move"
    HEAD = "head"
    ACTION = "action"
    STOP = "stop"

# Variables globales optimisées
current_robot_state = RobotState.IDLE
command_queue = Queue(maxsize=3)  # Limite la queue pour éviter l'accumulation
last_command_time = 0
last_movement_params = (0, 0)  # Cache pour éviter commandes dupliquées
autonomous_mode = False
autonomous_thread = None
state_lock = threading.RLock()  # ReentrantLock pour éviter deadlocks

# Configuration des seuils
DEADZONE = 0.35
MIN_SPEED = 85
MAX_SPEED = 98
COMMAND_DEBOUNCE_TIME = 0.05  # 50ms minimum entre commandes similaires
MOVEMENT_THRESHOLD = 0.1      # Seuil de changement significatif

# ===== GESTION D'ÉTAT THREAD-SAFE =====
def set_robot_state(new_state):
    global current_robot_state
    with state_lock:
        if current_robot_state != new_state:
            print(f"[STATE] {current_robot_state.value} -> {new_state.value}")
            current_robot_state = new_state

def get_robot_state():
    with state_lock:
        return current_robot_state

def is_robot_available():
    state = get_robot_state()
    return state in [RobotState.IDLE, RobotState.AUTONOMOUS] and my_dog.is_all_done()

# ===== OPTIMISATION DES COMMANDES =====
def should_process_movement(kx, ky):
    """Détermine si une nouvelle commande de mouvement doit être traitée"""
    global last_movement_params, last_command_time
    
    current_time = time.time()
    
    # Debouncing temporel
    if current_time - last_command_time < COMMAND_DEBOUNCE_TIME:
        return False
    
    # Seuil de changement significatif
    last_kx, last_ky = last_movement_params
    if (abs(kx - last_kx) < MOVEMENT_THRESHOLD and 
        abs(ky - last_ky) < MOVEMENT_THRESHOLD):
        return False
    
    return True

def calculate_direction_optimized(kx, ky):
    """Version optimisée du calcul de direction"""
    kr = sqrt(kx*kx + ky*ky)
    
    if kr < DEADZONE:
        return "stop", 0
    
    # Logique simplifiée et plus robuste
    if abs(ky) > abs(kx):  # Mouvement principalement vertical
        direction = "forward" if ky > 0 else "backward"
    else:  # Mouvement principalement horizontal
        direction = "turn_right" if kx > 0 else "turn_left"
    
    speed = int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(kr, 1.0))
    return direction, speed

def execute_movement_command(direction, speed):
    """Exécution optimisée des commandes de mouvement"""
    try:
        set_robot_state(RobotState.MOVING)
        
        if direction == "stop":
            my_dog.legs_stop()
            set_robot_state(RobotState.IDLE)
        else:
            # Pas de wait_all_done() ici pour éviter le blocage
            my_dog.do_action(direction, speed=speed, step_count=1)
        
        return True
    except Exception as e:
        print(f"[ERROR] Mouvement {direction}: {e}")
        set_robot_state(RobotState.IDLE)
        return False

# ===== GESTIONNAIRE DE QUEUE DE COMMANDES =====
def command_processor():
    """Thread optimisé pour traiter les commandes en séquence"""
    global last_movement_params, last_command_time
    
    while True:
        try:
            # Timeout pour éviter blocage infini
            cmd_type, cmd_data = command_queue.get(timeout=1.0)
            
            current_time = time.time()
            
            if cmd_type == CommandType.MOVE:
                kx, ky = cmd_data
                direction, speed = calculate_direction_optimized(kx, ky)
                
                if execute_movement_command(direction, speed):
                    last_movement_params = (kx, ky)
                    last_command_time = current_time
            
            elif cmd_type == CommandType.HEAD:
                qx, qy = cmd_data
                # Contrôle tête non bloquant
                try:
                    yaw = (qx / 100.0) * 90
                    pitch = (qy / 100.0) * 30
                    my_dog.head_move([[yaw, 0, pitch]], immediately=True, speed=100)
                except:
                    pass
            
            elif cmd_type == CommandType.ACTION:
                action = cmd_data
                if is_robot_available():
                    set_robot_state(RobotState.BUSY)
                    try:
                        my_dog.do_action(action, speed=80)
                    finally:
                        set_robot_state(RobotState.IDLE)
            
            elif cmd_type == CommandType.STOP:
                my_dog.legs_stop()
                set_robot_state(RobotState.IDLE)
            
            command_queue.task_done()
            
        except Empty:
            # Timeout normal, on continue
            continue
        except Exception as e:
            print(f"[ERROR] Command processor: {e}")

# ===== MODE AUTONOME OPTIMISÉ =====
def autonomous_behavior_optimized():
    """Mode autonome non-bloquant et respectueux des commandes manuelles"""
    global autonomous_mode
    
    set_robot_state(RobotState.AUTONOMOUS)
    print("[AUTO] Mode autonome optimisé démarré")
    
    # Séquences d'actions plus courtes et efficaces
    actions = ["forward", "turn_left", "turn_right", "wag_tail", "bark"]
    action_durations = [2.0, 1.0, 1.0, 1.5, 1.0]
    
    while autonomous_mode and get_robot_state() == RobotState.AUTONOMOUS:
        for action, duration in zip(actions, action_durations):
            if not autonomous_mode:
                break
                
            start_time = time.time()
            
            # Évitement d'obstacles simple
            try:
                distance = my_dog.read_distance()
                if distance and distance < 25:
                    action = random.choice(["turn_left", "turn_right"])
                    duration = 1.5
            except:
                pass
            
            # Exécution non-bloquante
            if action.startswith("turn") or action == "forward":
                kx = 0.8 if action == "turn_right" else (-0.8 if action == "turn_left" else 0)
                ky = 0.8 if action == "forward" else 0
                try:
                    command_queue.put_nowait((CommandType.MOVE, (kx, ky)))
                except:
                    pass
            else:
                try:
                    command_queue.put_nowait((CommandType.ACTION, action))
                except:
                    pass
            
            # Attente non-bloquante
            while time.time() - start_time < duration and autonomous_mode:
                sleep(0.2)
    
    set_robot_state(RobotState.IDLE)
    print("[AUTO] Mode autonome arrêté")

# ===== INITIALISATION =====
def cleanup_gpio():
    global my_dog
    try:
        if my_dog:
            my_dog.close()
    except:
        pass

def signal_handler(sig, frame):
    cleanup_gpio()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Démarrage du processeur de commandes
processor_thread = threading.Thread(target=command_processor, daemon=True)
processor_thread.start()

# ===== FLASK ROUTES OPTIMISÉES =====
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/advanced')
def advanced():
    return render_template('advanced.html')

@app.route('/command', methods=['POST'])
def handle_command_optimized():
    global autonomous_mode, last_movement_params
    
    # Arrêt du mode autonome si commande manuelle
    if autonomous_mode:
        autonomous_mode = False
        set_robot_state(RobotState.IDLE)
    
    data = request.get_json()
    
    try:
        if 'kx' in data and 'ky' in data:
            kx = float(data['kx'])
            ky = float(data['ky'])
            
            # Vérification de la nécessité de traitement
            if not should_process_movement(kx, ky):
                return jsonify({
                    'status': 'cached', 
                    'message': 'Commande identique ignorée'
                })
            
            # Ajout à la queue (non-bloquant)
            try:
                command_queue.put_nowait((CommandType.MOVE, (kx, ky)))
                direction, speed = calculate_direction_optimized(kx, ky)
                return jsonify({
                    'status': 'queued',
                    'message': f'{direction} @ {speed}%'
                })
            except:
                return jsonify({
                    'status': 'busy',
                    'message': 'Queue pleine, réessayez'
                })
        
        else:
            return jsonify({'status': 'error', 'message': 'Données invalides'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/head_control', methods=['POST'])
def handle_head_control_optimized():
    data = request.get_json()
    
    try:
        qx = float(data.get('qx', 0))
        qy = float(data.get('qy', 0))
        
        # Ajout non-bloquant à la queue
        try:
            command_queue.put_nowait((CommandType.HEAD, (qx, qy)))
            return jsonify({'status': 'success'})
        except:
            return jsonify({'status': 'busy'})
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/action', methods=['POST'])
def handle_action_optimized():
    global autonomous_mode
    
    if autonomous_mode:
        autonomous_mode = False
        set_robot_state(RobotState.IDLE)
    
    data = request.get_json()
    action = data.get('action', '')
    
    if not action:
        return jsonify({'status': 'error', 'message': 'Action manquante'})
    
    try:
        command_queue.put_nowait((CommandType.ACTION, action))
        return jsonify({'status': 'queued', 'message': f'Action {action} en queue'})
    except:
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})

@app.route('/autonomous_mode', methods=['POST'])
def set_autonomous_mode_optimized():
    global autonomous_mode, autonomous_thread
    
    data = request.get_json()
    enabled = bool(data.get('enabled', False))
    
    if enabled and not autonomous_mode:
        autonomous_mode = True
        autonomous_thread = threading.Thread(target=autonomous_behavior_optimized, daemon=True)
        autonomous_thread.start()
        
    elif not enabled and autonomous_mode:
        autonomous_mode = False
        try:
            command_queue.put_nowait((CommandType.STOP, None))
        except:
            pass
    
    return jsonify({
        'status': 'success',
        'enabled': autonomous_mode,
        'message': f"Mode autonome {'ON' if autonomous_mode else 'OFF'}"
    })

@app.route('/status', methods=['GET'])
def get_status_optimized():
    try:
        state = get_robot_state()
        return jsonify({
            'status': 'connected',
            'robot_state': state.value,
            'autonomous_mode': autonomous_mode,
            'queue_size': command_queue.qsize(),
            'is_available': is_robot_available()
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/sensor_data', methods=['GET'])
def get_sensor_data_optimized():
    try:
        distance = my_dog.read_distance()
        return jsonify({
            'distance': round(distance, 1) if distance else None,
            'robot_state': get_robot_state().value,
            'autonomous_mode': autonomous_mode
        })
    except:
        return jsonify({'distance': None})

# ===== UTILITAIRES =====
def getIP():
    try:
        import socket
        # Méthode plus fiable que parsing ifconfig
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

if __name__ == "__main__":
    try:
        print("🐕 PiDog Server Optimisé - Démarrage")
        ip = getIP()
        print(f"📡 Server: http://{ip}:5000")
        print(f"🚀 Advanced: http://{ip}:5000/advanced")
        
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
        
    except KeyboardInterrupt:
        print("\n🛑 Arrêt serveur")
    finally:
        cleanup_gpio()