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

# Configuration détection d'obstacles
OBSTACLE_DISTANCE_THRESHOLD = 25  # Distance seuil en cm
SAFE_DISTANCE = 35  # Distance de sécurité en cm
SIDE_SCAN_ANGLES = [-45, -30, 0, 30, 45]  # Angles de scan pour détecter les obstacles
MOVEMENT_STEP_SIZE = 0.5  # Taille d'un pas en mètres (estimation)

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


def scan_obstacles():
    """
    Scanne les obstacles dans différentes directions
    Retourne un dictionnaire avec les distances mesurées
    """
    distances = {}
    current_head_yaw = head_yrp[0]

    try:
        for angle in SIDE_SCAN_ANGLES:
            # Orienter la tête vers l'angle de scan
            set_head(yaw=angle)
            sleep(0.2)  # Attendre que la tête se positionne

            # Mesurer la distance
            distance = my_dog.read_distance()
            if distance is not None:
                distances[angle] = distance
                print(f"[SCAN] Angle {angle}°: {distance:.1f}cm")
            else:
                distances[angle] = float('inf')  # Pas d'obstacle détecté

        # Remettre la tête en position centrale
        set_head(yaw=0)
        sleep(0.1)

    except Exception as e:
        print(f"Erreur lors du scan: {e}")
        distances = {angle: float('inf') for angle in SIDE_SCAN_ANGLES}

    return distances


def find_safe_direction():
    """
    Trouve la direction la plus sûre pour éviter les obstacles
    Retourne: ('turn_left'|'turn_right'|'backward'|None, priorité)
    """
    distances = scan_obstacles()

    # Analyser les distances pour chaque secteur
    left_distances = [distances.get(angle, float('inf')) for angle in [-45, -30]]
    center_distance = distances.get(0, float('inf'))
    right_distances = [distances.get(angle, float('inf')) for angle in [30, 45]]

    left_avg = sum(left_distances) / len(left_distances)
    right_avg = sum(right_distances) / len(right_distances)

    print(f"[OBSTACLE ANALYSIS] Gauche: {left_avg:.1f}cm, Centre: {center_distance:.1f}cm, Droite: {right_avg:.1f}cm")

    # Décision basée sur la distance moyenne
    if left_avg > SAFE_DISTANCE and left_avg > right_avg:
        return 'turn_left', left_avg
    elif right_avg > SAFE_DISTANCE:
        return 'turn_right', right_avg
    elif center_distance < OBSTACLE_DISTANCE_THRESHOLD:
        # Si tout est bloqué, reculer
        return 'backward', center_distance
    else:
        return None, center_distance


def safe_move_forward(duration=1.0, speed=90):
    """
    Avance en évitant les obstacles de manière intelligente
    """
    print(f"[SAFE MOVE] Début du mouvement sécurisé (durée: {duration}s)")

    start_time = time.time()
    obstacle_detected = False

    while time.time() - start_time < duration:
        # Vérifier la distance frontale
        front_distance = my_dog.read_distance()

        if front_distance is not None and front_distance < OBSTACLE_DISTANCE_THRESHOLD:
            print(f"[OBSTACLE] Obstacle détecté à {front_distance:.1f}cm")
            obstacle_detected = True

            # Arrêter le mouvement
            my_dog.legs_stop()
            my_dog.wait_all_done()

            # Trouver une direction sûre
            safe_direction, safe_distance = find_safe_direction()

            if safe_direction == 'turn_left':
                print("[AVOIDANCE] Contournement par la gauche")
                my_dog.do_action('turn_left', speed=85)
                my_dog.wait_all_done()
                sleep(0.8)  # Tourner pendant 0.8s

            elif safe_direction == 'turn_right':
                print("[AVOIDANCE] Contournement par la droite")
                my_dog.do_action('turn_right', speed=85)
                my_dog.wait_all_done()
                sleep(0.8)

            elif safe_direction == 'backward':
                print("[AVOIDANCE] Recul nécessaire")
                my_dog.do_action('backward', speed=80)
                my_dog.wait_all_done()
                sleep(1.0)
                # Essayer de tourner après avoir reculé
                turn_direction = random.choice(['turn_left', 'turn_right'])
                my_dog.do_action(turn_direction, speed=85)
                my_dog.wait_all_done()
                sleep(1.0)

            # Reprendre le mouvement vers l'avant après contournement
            my_dog.legs_stop()
            my_dog.wait_all_done()
            sleep(0.2)

        else:
            # Pas d'obstacle, continuer d'avancer
            if obstacle_detected:
                print("[SAFE MOVE] Reprise du mouvement après évitement")
                obstacle_detected = False

            my_dog.do_action('forward', speed=speed)

        sleep(0.1)  # Petite pause entre les vérifications

    # Arrêt final
    my_dog.legs_stop()
    my_dog.wait_all_done()
    print("[SAFE MOVE] Mouvement sécurisé terminé")


def safe_move_backward(duration=1.0, speed=90):
    """
    Recule en évitant les obstacles (version simplifiée)
    """
    print(f"[SAFE MOVE] Recul sécurisé (durée: {duration}s)")

    # Pour le recul, on fait un scan rapide derrière (approximatif)
    # Dans un vrai scénario, il faudrait un capteur arrière
    my_dog.do_action('backward', speed=speed)
    sleep(duration)
    my_dog.legs_stop()
    my_dog.wait_all_done()


def move_distance(distance_meters, direction='forward'):
    """
    Fait avancer/reculer le robot d'une distance approximative en mètres
    """
    if distance_meters <= 0:
        return False

    # Estimation du temps nécessaire basée sur la vitesse du robot
    # Ces valeurs doivent être calibrées selon votre robot
    estimated_speed_ms = 0.3  # mètres par seconde (à ajuster)
    duration = distance_meters / estimated_speed_ms

    print(f"[MOVE DISTANCE] {direction} de {distance_meters}m (durée estimée: {duration:.1f}s)")

    if direction == 'forward':
        safe_move_forward(duration=duration, speed=90)
    elif direction == 'backward':
        safe_move_backward(duration=duration, speed=90)

    return True


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
    if (angle >= 315 or angle < 45):  # Secteur nord
        return "forward", intensity
    elif (angle >= 45 and angle < 135):  # Secteur est
        return "turn_right", intensity
    elif (angle >= 135 and angle < 225):  # Secteur sud
        return "backward", intensity
    elif (angle >= 225 and angle < 315):  # Secteur ouest
        return "turn_left", intensity
    else:
        return "stop", 0


def calculate_direction_from_kx_ky(kx, ky):
    """
    Convertit kx/ky en direction - Compatible avec d'autres interfaces
    """
    kr = sqrt(kx ** 2 + ky ** 2)
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

        # 2. Marche sécurisée avec évitement d'obstacles
        print('[AUTO] Safe walking for 15s')
        if check_stop(): break
        safe_move_forward(duration=15, speed=random.randint(85, 98))
        if check_stop(): break

        # 3. Action statique aléatoire pendant 5s
        action = random.choice(static_actions)
        print(f'[AUTO] Static action for 5s')
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

        # 5. Marche sécurisée avec évitement d'obstacles
        walk_time = random.randint(10, 15)
        print(f'[AUTO] Safe walking for {walk_time}s')
        if check_stop(): break
        safe_move_forward(duration=walk_time, speed=random.randint(85, 98))
        if check_stop(): break

        # 6. Action statique aléatoire pendant 5s
        action = random.choice(static_actions)
        print(f'[AUTO] Static action for 5s')
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
    """
    ROUTE UNIVERSELLE avec détection d'obstacles intégrée
    """
    global last_command, autonomous_mode_enabled
    with autonomous_lock:
        if autonomous_mode_enabled:
            autonomous_mode_enabled = False

    if not my_dog.is_legs_done():
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})

    data = request.get_json()

    # Détection automatique du format
    if 'angle' in data and 'intensity' in data:
        angle = float(data.get('angle', 0))
        intensity = float(data.get('intensity', 0))
        direction, value = calculate_direction_from_angle(angle, intensity)
        print(f"HTML Format: angle={angle}°, intensity={intensity} → {direction}")

    elif 'kx' in data and 'ky' in data:
        kx = float(data.get('kx', 0))
        ky = float(data.get('ky', 0))
        direction, value = calculate_direction_from_kx_ky(kx, ky)
        print(f"KX/KY Format: kx={kx}, ky={ky} → {direction}")

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

        # Vérification d'obstacles pour les mouvements avant/arrière
        if direction == "forward":
            front_distance = my_dog.read_distance()
            if front_distance is not None and front_distance < OBSTACLE_DISTANCE_THRESHOLD:
                return jsonify({
                    'status': 'warning',
                    'message': f'Obstacle détecté à {front_distance:.1f}cm. Mouvement bloqué.',
                    'distance': front_distance
                })
            my_dog.do_action('forward', speed=speed)

        elif direction == "backward":
            # Pour le recul, on assume qu'il est généralement sûr
            # Dans un vrai scénario, il faudrait un capteur arrière
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


@app.route('/move_distance', methods=['POST'])
def handle_move_distance():
    """
    Nouveau endpoint pour faire avancer le robot d'une distance précise
    """
    data = request.get_json()
    distance = float(data.get('distance', 1.0))  # Distance en mètres
    direction = data.get('direction', 'forward')  # 'forward' ou 'backward'

    if distance <= 0 or distance > 10:  # Limite de sécurité
        return jsonify({'status': 'error', 'message': 'Distance invalide (0-10m)'})

    if direction not in ['forward', 'backward']:
        return jsonify({'status': 'error', 'message': 'Direction invalide'})

    try:
        success = move_distance(distance, direction)
        if success:
            return jsonify({
                'status': 'success',
                'message': f'Mouvement de {distance}m vers {direction} terminé'
            })
        else:
            return jsonify({'status': 'error', 'message': 'Échec du mouvement'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur: {str(e)}'})


@app.route('/scan_obstacles', methods=['GET'])
def handle_scan_obstacles():
    """
    Endpoint pour effectuer un scan complet des obstacles
    """
    try:
        distances = scan_obstacles()
        safe_direction, safe_distance = find_safe_direction()

        return jsonify({
            'status': 'success',
            'distances': distances,
            'safe_direction': safe_direction,
            'safe_distance': safe_distance,
            'obstacle_threshold': OBSTACLE_DISTANCE_THRESHOLD
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur scan: {str(e)}'})


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

    # Actions simples disponibles
    actions_disponibles = {
        "sit": lambda: my_dog.do_action('sit', speed=70),
        "stand_up": lambda: my_dog.do_action('stand', speed=70),
        "lie_down": lambda: my_dog.do_action('lie', speed=70),
        "wag_tail": lambda: my_dog.do_action('wag_tail', speed=100),
        "stretch": lambda: my_dog.do_action('stretch', speed=80),
        "shake_head": lambda: my_dog.do_action('shake_head', speed=80),
    }

    if action not in actions_disponibles:
        return jsonify({'status': 'error', 'message': f'Action {action} non reconnue'})

    try:
        actions_disponibles[action]()
        return jsonify({'status': 'success', 'message': f'Action {action} exécutée'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur action: {str(e)}'})


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
            'obstacle_detected': distance < OBSTACLE_DISTANCE_THRESHOLD if distance else False
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
            'autonomous_mode': autonomous_mode_enabled
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/autonomous_mode', methods=['POST'])
def set_autonomous_mode():
    global autonomous_mode_enabled, _autonomous_thread
    data = request.get_json()
    enabled = bool(data.get('enabled', False))
    with autonomous_lock:
        if enabled and not autonomous_mode_enabled:
            autonomous_mode_enabled = True
            _autonomous_thread = threading.Thread(target=autonomous_behavior, daemon=True)
            _autonomous_thread.start()
        elif not enabled and autonomous_mode_enabled:
            autonomous_mode_enabled = False
    return jsonify({'status': 'success', 'enabled': autonomous_mode_enabled})


@app.route('/bark', methods=['POST'])
def bark_endpoint():
    try:
        my_dog.do_action('bark', speed=100)
        return jsonify({'status': 'success', 'message': 'Aboiement exécuté'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/pant', methods=['POST'])
def pant_endpoint():
    try:
        my_dog.do_action('pant', speed=100)
        return jsonify({'status': 'success', 'message': 'Halètement exécuté'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/scratch', methods=['POST'])
def scratch_endpoint():
    try:
        my_dog.do_action('scratch', speed=100)
        return jsonify({'status': 'success', 'message': 'Grattage exécuté'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


if __name__ == "__main__":
    try:
        print("🐕 Démarrage du serveur PiDog avec détection d'obstacles...")
        wlan0, eth0 = getIP()
        ip = wlan0 if wlan0 else eth0
        if ip:
            print(f"📡 Interface Web disponible sur : http://{ip}:5000")
            print(f"🎮 Interface Simple : http://{ip}:5000/simple")
            print(f"🚀 Interface Avancée : http://{ip}:5000/advanced")
        else:
            print("📡 Interface Web disponible sur : http://localhost:5000")

        print(f"🛡️ Détection d'obstacles activée (seuil: {OBSTACLE_DISTANCE_THRESHOLD}cm)")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur...")
    except Exception as e:
        print(f"\033[31mERROR: {e}\033[m")
    finally:
        cleanup_gpio()