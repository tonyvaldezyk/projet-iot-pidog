from sunfounder_controller import SunFounderController
from pidog import Pidog
from time import sleep
from vilib import Vilib
from preset_actions import *
import os
from time import sleep
from math import pi, atan2, sqrt
from flask import Flask, render_template, request, jsonify
import signal
import sys

sc = SunFounderController()
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
command = None
current_status = STATUS_LIE

MIN_SPEED = 85
MAX_SPEED = 98
DEADZONE = 0.35  # zone morte pour éviter les micro-mouvements
face_detection_enabled = False

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

# Dictionnaire des actions pour l'interface web
WEB_ACTIONS = {
    "sit": lambda: my_dog.do_action('sit', speed=70),
    "stand_up": lambda: my_dog.do_action('stand', speed=70),
    "lie_down": lambda: my_dog.do_action('lie', speed=70),
    "bark": lambda: bark(my_dog, head_yrp, pitch_comp=head_pitch_init),
    "wag_tail": lambda: my_dog.do_action('wag_tail', speed=100),
    "pant": lambda: pant(my_dog, head_yrp, pitch_comp=head_pitch_init),
    "scratch": lambda: scratch(my_dog),
    "stretch": lambda: stretch(),
    "handshake": lambda: hand_shake(my_dog),
    "high_five": lambda: high_five(my_dog),
    "howling": lambda: howling(my_dog),
    "shake_head": lambda: shake_head(my_dog, head_yrp),
}

COMMANDS = {
    "forward": {
        "commands": ["forward"],
        "function": lambda: my_dog.do_action('forward', speed=98),
        "after": "forward",
        "status": STATUS_STAND,
        "head_pitch": STAND_HEAD_PITCH,
    },
    "backward": {
        "commands": ["backward"],
        "function": lambda: my_dog.do_action('backward', speed=98),
        "after": "backward",
        "status": STATUS_STAND,
        "head_pitch": STAND_HEAD_PITCH,
    },
    "turn left": {
        "commands": ["turn left"],
        "function": lambda: my_dog.do_action('turn_left', speed=98),
        "after": "turn left",
        "status": STATUS_STAND,
        "head_pitch": STAND_HEAD_PITCH,
    },
    "turn right": {
        "commands": ["turn right"],
        "function": lambda: my_dog.do_action('turn_right', speed=98),
        "after": "turn right",
        "status": STATUS_STAND,
        "head_pitch": STAND_HEAD_PITCH,
    },
    "trot": {
        "commands": ["trot", "run"],
        "function": lambda: my_dog.do_action('trot', speed=98),
        "after": "trot",
        "status": STATUS_STAND,
        "head_pitch": STAND_HEAD_PITCH,
    },
    "stop": {
        "commands": ["stop"],
    },
    # ... autres commandes ...
}

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

def run_command():
    global command, head_pitch_init
    if not my_dog.is_legs_done():
        return
    if command is None:
        return
    print(command)
    for name in COMMANDS:
        if command in COMMANDS[name]["commands"]:
            if "head_pitch" in COMMANDS[name]:
                set_head_pitch_init(COMMANDS[name]["head_pitch"])
            if "status" in COMMANDS[name]:
                if current_status != COMMANDS[name]["status"]:
                    change_status(COMMANDS[name]["status"])
            if "before" in COMMANDS[name]:
                before_command = COMMANDS[name]["before"]
                COMMANDS[before_command]["function"]()
            if "function" in COMMANDS[name]:
                COMMANDS[name]["function"]()
            if "after" in COMMANDS[name]:
                command = COMMANDS[name]["after"]
            else:
                command = None
            break

def calculate_direction(kx, ky):
    kr = sqrt(kx**2 + ky**2)
    if kr < DEADZONE:
        return "stop", 0
    ka = atan2(ky, kx) * 180 / pi
    # Logique identique au SunFounder Controller
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
    global last_command
    if not my_dog.is_legs_done():
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    
    data = request.get_json()
    kx = float(data.get('kx', 0))
    ky = float(data.get('ky', 0))

    direction, value = calculate_direction(kx, ky)
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
    """Contrôle de la tête via joystick droit"""
    data = request.get_json()
    qx = float(data.get('qx', 0))
    qy = float(data.get('qy', 0))
    
    try:
        if abs(qx) > 5 or abs(qy) > 5:  # Zone morte pour la tête
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
    """Exécution d'actions spéciales via boutons"""
    data = request.get_json()
    action = data.get('action', '')
    
    if action not in WEB_ACTIONS:
        return jsonify({'status': 'error', 'message': f'Action {action} non reconnue'})
    
    try:
        WEB_ACTIONS[action]()
        return jsonify({'status': 'success', 'message': f'Action {action} exécutée'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur action: {str(e)}'})

@app.route('/face_detection', methods=['POST'])
def handle_face_detection():
    """Contrôle de la détection de visage"""
    global face_detection_enabled
    data = request.get_json()
    enabled = data.get('enabled', False)
    
    try:
        face_detection_enabled = enabled
        Vilib.face_detect_switch(enabled)
        status = "activée" if enabled else "désactivée"
        return jsonify({'status': 'success', 'message': f'Détection visage {status}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur détection: {str(e)}'})

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
            'status': current_status,
            'face_detection': face_detection_enabled
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
            'is_busy': not my_dog.is_all_done(),
            'face_detection': face_detection_enabled
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def main():
    global command
    sc.set_name('Mydog')
    sc.set_type('Pidog')
    sc.start()

    wlan0, eth0 = getIP()
    if wlan0 != None:
        ip = wlan0
    else:
        ip = eth0
    print('ip : %s' % ip)
    sc.set('video', 'http://'+ip+':9000/mjpg')

    Vilib.camera_start(vflip=False, hflip=False)
    Vilib.display(local=False, web=True)

    print("Voice Command: ")
    for command_name in COMMANDS:
        print(command_name)

    last_kx = 0
    last_ky = 0
    last_qx = 0
    last_qy = 0

    # Démarrage du serveur Flask dans un thread séparé
    import threading
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    print(f"Interface Web disponible sur : http://{ip}:5000")
    print("Interface Simple : http://{ip}:5000/simple")
    print("Interface Avancée : http://{ip}:5000/advanced")

    while True:
        # Logique SunFounder Controller existante
        sc.set("A", round(my_dog.read_distance(),2))

        # Left Joystick move
        k_value = sc.get('K')
        if k_value != None:
            kx, ky = k_value
            if last_ky != ky or last_kx != kx:
                last_ky = ky
                last_kx = kx
                if kx != 0 or ky != 0:
                    ka = atan2(ky, kx) * 180 / pi
                    kr = sqrt(kx**2 + ky**2)
                    if kr > 100:
                        if (ka > 45 and ka < 135):
                            command = "forward"
                        elif (ka > 135 or ka < -135):
                            command = "turn left"
                        elif (ka > -45 and ka < 45):
                            command = "turn right"
                        elif (ka > -135 and ka < -45):
                            command = "backward"
                else:
                    command = None

        # Right Joystick move head
        q_value = sc.get('Q')
        if q_value != None:
            qx, qy = q_value
            if last_qx != qx or last_qy != qy:
                last_qx = qx
                last_qy = qy
                if qx != 0 or qy != 0:
                    yaw = map_value(qx, 100, -100, -90, 90)
                    pitch = map_value(qy, -100, 100, -30, 30)
                else:
                    yaw = 0
                    pitch = 0
                set_head(yaw=yaw, pitch=pitch)

        d_value = sc.get('D')
        if d_value != None:
            set_head(roll=d_value)

        # Voice Control
        voice_command = sc.get('J')
        if voice_command != None:
            print(f'voice command: {voice_command}')
            if voice_command in COMMANDS:
                command = voice_command
            else:
                print("\033[0;31m no this voice command\033[m")

        # Bark
        n_value = sc.get('N')
        if n_value:
            command = 'bark'

        # Wag tail
        O_value = sc.get('O')
        if O_value:
            command = 'wag tail'
        elif command == 'wag tail':
            command = None

        # pant
        P_value = sc.get('P')
        if P_value:
            command = 'pant'

        # Scratch
        I_value = sc.get('I')
        if I_value:
            command = 'scratch'

        # Sit
        E_value = sc.get('E')
        if E_value:
            command = 'sit'

        # Stand
        F_value = sc.get('F')
        if F_value:
            command = 'stand up'

        # Lie
        G_value = sc.get('G')
        if G_value:
            command = 'lie down'

        # Face detection
        C_value = sc.get('C')
        if C_value:
            Vilib.face_detect_switch(True)
            face_detection_enabled = True
        else:
            Vilib.face_detect_switch(False)
            face_detection_enabled = False

        run_command()
        sleep(0.008)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\033[31mERROR: {e}\033[m")
    finally:
        sc.close()
        Vilib.camera_close()
        cleanup_gpio()