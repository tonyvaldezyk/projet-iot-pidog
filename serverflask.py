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
DEADZONE = 0.35  # zone morte pour éviter les micro-mouvements

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

def stretch():
    my_dog.do_action('stretch', speed=10)
    my_dog.wait_all_done()

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
    """
    Convertit angle/intensity en direction - Compatible avec l'HTML
    angle: 0-360 (0 = haut, 90 = droite, 180 = bas, 270 = gauche)
    intensity: 0-1
    """
    if intensity < 0.25:  # Zone morte
        return "stop", 0
    
    # Normaliser l'angle
    angle = angle % 360
    
    # Déterminer la direction selon les secteurs
    if (angle >= 315 or angle < 45):           # Secteur nord
        return "forward", intensity
    elif (angle >= 45 and angle < 135):       # Secteur est
        return "turn_right", intensity
    elif (angle >= 135 and angle < 225):      # Secteur sud
        return "backward", intensity
    elif (angle >= 225 and angle < 315):      # Secteur ouest
        return "turn_left", intensity
    else:
        return "stop", 0

def calculate_direction_from_kx_ky(kx, ky):
    """
    Convertit kx/ky en direction - Compatible avec d'autres interfaces
    """
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

def autonomous_behavior():
    global autonomous_mode_enabled
    def check_stop():
        with autonomous_lock:
            return not autonomous_mode_enabled

    # Actions statiques (non déplacement)
    static_actions = [
        lambda: my_dog.do_action('bark', speed=100),
        lambda: my_dog.do_action('lie', speed=70),
        lambda: my_dog.do_action('stretch', speed=80),
        lambda: my_dog.do_action('wag_tail', speed=100),
        lambda: my_dog.do_action('shake_head', speed=80),
    ]

    while True:
        # 1. Aboyer pendant 30 secondes
        if check_stop(): break
        print('[AUTO] Barking for 30s')
        my_dog.do_action('bark', speed=100)
        for _ in range(3):
            if check_stop(): break
            sleep(1)
        if check_stop(): break

        # 2. Marche avant, évite les obstacles, pendant 10s
        print('[AUTO] Walking forward for 10s')
        t0 = time.time()
        while time.time() - t0 < 15:
            if check_stop(): break
            dist = my_dog.read_distance()
            if dist is not None and dist < 20:
                print('[AUTO] Obstacle detected, avoiding')
                turn = random.choice(['turn_left', 'turn_right'])
                my_dog.do_action(turn, speed=random.randint(85, 98))
                my_dog.wait_all_done()
                my_dog.do_action('forward', speed=random.randint(85, 98))
            else:
                my_dog.do_action('forward', speed=random.randint(85, 98))
            my_dog.wait_all_done()
            sleep(0.5)
        if check_stop(): break

        # 3. Action statique aléatoire pendant 5s
        action = random.choice(static_actions)
        print(f'[AUTO] Static action for 5s: {action.__name__}')
        action()
        for _ in range(5):
            if check_stop(): break
            sleep(1)
        if check_stop(): break

        # 4. Se lever
        print('[AUTO] Standing up')
        my_dog.do_action('stand', speed=70)
        my_dog.wait_all_done()
        if check_stop(): break

        # 5. Marche avant (10-15s), évite les obstacles
        walk_time = random.randint(10, 15)
        print(f'[AUTO] Walking forward for {walk_time}s')
        t0 = time.time()
        while time.time() - t0 < walk_time:
            if check_stop(): break
            dist = my_dog.read_distance()
            if dist is not None and dist < 20:
                print('[AUTO] Obstacle detected, avoiding')
                turn = random.choice(['turn_left', 'turn_right'])
                my_dog.do_action(turn, speed=random.randint(85, 98))
                my_dog.wait_all_done()
                my_dog.do_action('forward', speed=random.randint(85, 98))
            else:
                my_dog.do_action('forward', speed=random.randint(85, 98))
            my_dog.wait_all_done()
            sleep(0.5)
        if check_stop(): break

        # 6. Action statique aléatoire pendant 5s
        action = random.choice(static_actions)
        print(f'[AUTO] Static action for 5s: {action.__name__}')
        action()
        for _ in range(5):
            if check_stop(): break
            sleep(1)
        if check_stop(): break

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
    try:
        data = request.get_json()
        kx = float(data.get('kx', 0))
        ky = float(data.get('ky', 0))
        
        # Calcul de la direction et de la vitesse
        kr = sqrt(kx*kx + ky*ky)
        if kr < DEADZONE:
            my_dog.stop()
            return jsonify({'status': 'success', 'message': 'Arrêt'})
        
        # Calcul de l'angle en degrés
        ka = atan2(ky, kx) * 180 / pi
        
        # Détermination de la direction
        if ka > 45 and ka < 135:
            direction = "forward"
        elif ka > 135 or ka < -135:
            direction = "turn_left"
        elif ka > -45 and ka < 45:
            direction = "turn_right"
        elif ka > -135 and ka < -45:
            direction = "backward"
        else:
            direction = "stop"
        
        # Calcul de la vitesse
        speed = int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(kr, 1.0))
        
        # Exécution de la commande
        if direction == "forward":
            my_dog.forward(speed)
        elif direction == "backward":
            my_dog.backward(speed)
        elif direction == "turn_left":
            my_dog.turn_left(speed)
        elif direction == "turn_right":
            my_dog.turn_right(speed)
        else:
            my_dog.stop()
        
        return jsonify({
            'status': 'success',
            'message': f'{direction} à {speed}%',
            'direction': direction,
            'speed': speed
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/head_control', methods=['POST'])
def control_head():
    try:
        data = request.get_json()
        qx = float(data.get('qx', 0))  # Rotation horizontale (-100 à 100)
        qy = float(data.get('qy', 0))  # Rotation verticale (-100 à 100)
        
        # Conversion des valeurs -100/100 en angles
        head_x = int((qx / 100) * 30)  # -30° à +30° horizontal
        head_y = int((qy / 100) * 30)  # -30° à +30° vertical
        
        # Appliquer les mouvements de tête
        my_dog.head_move(head_x, head_y)
        
        return jsonify({'status': 'success', 'message': f'Tête déplacée à X:{head_x}° Y:{head_y}°'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/action', methods=['POST'])
def handle_action():
    try:
        data = request.get_json()
        action = data.get('action')
        
        if action == 'bark':
            my_dog.do_action('bark', speed=100)
        elif action == 'sit':
            my_dog.do_action('sit', speed=70)
        elif action == 'stand_up':
            my_dog.do_action('stand', speed=70)
        elif action == 'lie_down':
            my_dog.do_action('lie', speed=70)
        elif action == 'stretch':
            my_dog.do_action('stretch', speed=80)
        elif action == 'wag_tail':
            my_dog.do_action('wag_tail', speed=100)
        elif action == 'pant':
            my_dog.do_action('pant', speed=100)
        elif action == 'scratch':
            my_dog.do_action('scratch', speed=100)
        else:
            return jsonify({'status': 'error', 'message': 'Action non reconnue'})
        
        return jsonify({'status': 'success', 'message': f'Action {action} exécutée'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_ip', methods=['GET'])
def get_ip():
    """Retourne l'IP pour le streaming"""
    wlan0, eth0 = getIP()
    ip = wlan0 if wlan0 else eth0
    return jsonify({'ip': ip})

@app.route('/sensor_data', methods=['GET'])
def get_sensor_data():
    """Données des capteurs en temps réel"""
    try:
        distance = round(my_dog.read_distance(), 2)
        return jsonify({
            'distance': distance,
            'status': current_status
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/status', methods=['GET'])
def get_status():
    """État général du robot"""
    try:
        return jsonify({
            'status': 'connected',
            'robot_status': current_status,
            'is_busy': not my_dog.is_all_done()
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/autonomous_mode', methods=['POST'])
def toggle_autonomous_mode():
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        
        if enabled:
            autonomous_thread = threading.Thread(target=autonomous_behavior)
            autonomous_thread.daemon = True
            autonomous_thread.start()
            return jsonify({'status': 'success', 'message': 'Mode autonome activé'})
        else:
            # Arrêter le mode autonome
            global autonomous_running
            autonomous_running = False
            return jsonify({'status': 'success', 'message': 'Mode autonome désactivé'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == "__main__":
    try:
        print("🐕 Démarrage du serveur PiDog...")
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