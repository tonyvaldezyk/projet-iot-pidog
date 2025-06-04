from flask import Flask, render_template, request, jsonify
from math import atan2, sqrt, pi
import time
import signal
import sys
import os
import subprocess

# Libérer les GPIO avant toute initialisation
try:
    subprocess.run(['sudo', 'pkill', '-f', 'pigpiod'], check=False)
    time.sleep(1)
    subprocess.run(['sudo', 'killall', 'python3'], check=False)
    time.sleep(1)
    subprocess.run(['sudo', 'pigpiod'], check=True)
    time.sleep(1)
except Exception as e:
    print(f"[WARN] Impossible de libérer les GPIO automatiquement : {e}")

from pidog import Pidog

app = Flask(__name__)
my_dog = Pidog()
last_command = None

# Vitesse minimale et maximale pour les servos
MIN_SPEED = 85
MAX_SPEED = 98
DEADZONE = 0.35  # zone morte pour éviter les micro-mouvements

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

# Set up signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def calculate_direction(kx, ky):
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

@app.route('/')
def hello():
    return render_template('index.html')

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

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=8080, debug=True)
    finally:
        cleanup_gpio()