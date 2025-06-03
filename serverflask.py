import datetime
import os
import signal
import sys
from flask import Flask, render_template, request, jsonify
from pidog import Pidog
from math import pi, atan2, sqrt, cos, sin
import time
import subprocess
from gpiozero import Device
from gpiozero.pins.pigpio import PiGPIOFactory

app = Flask(__name__)
my_dog = None

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

try:
    # Try to use pigpio factory which handles GPIO better
    Device.pin_factory = PiGPIOFactory()
    my_dog = Pidog()
    print("Pidog initialized successfully!")
except Exception as e:
    print(f"Error initializing Pidog: {e}")
    print("Trying to kill any conflicting processes...")
    try:
        subprocess.run(['sudo', 'pkill', '-f', 'pigpiod'], check=False)
        time.sleep(1)
        subprocess.run(['sudo', 'pigpiod'], check=True)
        time.sleep(1)
        Device.pin_factory = PiGPIOFactory()
        my_dog = Pidog()
        print("Pidog initialized successfully after cleanup!")
    except Exception as e2:
        print(f"Failed to initialize Pidog after cleanup: {e2}")
        print("Please check if another program is using the GPIO pins.")
        print("You can try running 'sudo pkill -f pigpiod' and then restart the program.")

# Variables pour la gestion de la vitesse progressive
last_command = None
last_speed = 0
last_command_time = time.time()
SPEED_CHANGE_RATE = 0.2  # Vitesse de changement de la vitesse (0-1)

def map_value(x, in_min, in_max, out_min, out_max):
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def calculate_direction(angle, intensity):
    # Zone morte augmentée pour éviter les vibrations
    if intensity < 0.25:
        return "stop", 0
    
    # Convertir l'angle en radians
    angle_rad = angle * pi / 180
    
    # Calculer les composantes x et y
    x = intensity * cos(angle_rad)
    y = intensity * sin(angle_rad)
    
    # Déterminer la direction principale avec des zones de transition
    if abs(x) > abs(y):
        if x > 0:
            return "turn_right", intensity
        else:
            return "turn_left", intensity
    else:
        if y > 0:
            return "forward", intensity
        else:
            return "backward", intensity

def get_smooth_speed(target_speed, current_speed):
    """Calcule une vitesse progressive pour éviter les changements brusques"""
    if target_speed == 0:
        return 0
    
    # Calculer la nouvelle vitesse avec une transition douce
    new_speed = current_speed + (target_speed - current_speed) * SPEED_CHANGE_RATE
    return new_speed

@app.route('/')
def hello():
    return render_template('index.html')

@app.route('/command', methods=['POST'])
def handle_command():
    global last_command, last_speed, last_command_time
    
    # Vérifier que le robot n'est pas occupé (évite les vibrations)
    if my_dog and not my_dog.is_legs_done():
        return jsonify({
            'status': 'busy',
            'message': 'Robot occupé'
        })
    
    data = request.get_json()
    angle = data.get('angle', 0)
    intensity = data.get('intensity', 0)
    
    # Calculer la direction et la vitesse cible
    direction, target_speed = calculate_direction(angle, intensity)
    
    # Mapping vers des vitesses efficaces (75-98%) pour éviter les mouvements faibles
    if direction == "stop":
        smooth_speed = 0
    else:
        # Vitesses optimisées : 75-98% au lieu de 0-100%
        target_speed_optimal = int(75 + (target_speed * 23))  # 75 + (0-1 * 23) = 75-98%
        
        # Calculer la vitesse progressive
        current_time = time.time()
        last_command_time = current_time
        smooth_speed = int(get_smooth_speed(target_speed_optimal, last_speed))
        last_speed = smooth_speed
    
    # Liste des directions/actions valides
    valid_directions = ["forward", "backward", "turn_left", "turn_right", "stop"]
    
    # Exécuter la commande
    if direction not in valid_directions:
        return jsonify({
            'status': 'error',
            'message': f'Commande {direction} non reconnue.'
        })
    
    try:
        if direction != last_command and last_command not in [None, "stop"]:
            # Si la direction change, arrêter d'abord
            my_dog.body_stop()
            my_dog.wait_all_done()
            time.sleep(0.05)  # Délai réduit mais suffisant
        
        # Exécuter l'action
        if direction == "forward":
            my_dog.do_action('forward', speed=smooth_speed)
        elif direction == "backward":
            my_dog.do_action('backward', speed=smooth_speed)
        elif direction == "turn_left":
            my_dog.do_action('turn_left', speed=smooth_speed)
        elif direction == "turn_right":
            my_dog.do_action('turn_right', speed=smooth_speed)
        elif direction == "stop":
            my_dog.body_stop()
            my_dog.wait_all_done()
        
        last_command = direction
        
        return jsonify({
            'status': 'success',
            'message': f'{direction} - vitesse {smooth_speed}%'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur: {str(e)}'
        })

if __name__ == '__main__':
    if my_dog is None:
        print("Warning: Pidog initialization failed. The application will start but robot functions won't work.")
    try:
        app.run(host='0.0.0.0', port=8080, debug=True)
    finally:
        cleanup_gpio()