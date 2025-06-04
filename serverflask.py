from flask import Flask, render_template, request, jsonify
from pidog import Pidog
from math import pi, cos, sin
import time

app = Flask(__name__)
my_dog = Pidog()
last_command = None

# Seuil d'intensité pour éviter les micro-mouvements
MIN_INTENSITY = 0.4
# Vitesse minimale et maximale pour les servos
MIN_SPEED = 85
MAX_SPEED = 98

# Mapping angle/intensité vers action Pidog
def calculate_direction(angle, intensity):
    if intensity < MIN_INTENSITY:
        return "stop", 0
    angle_rad = angle * pi / 180
    x = intensity * cos(angle_rad)
    y = intensity * sin(angle_rad)
    if abs(x) > abs(y):
        return ("turn_right", intensity) if x > 0 else ("turn_left", intensity)
    else:
        return ("forward", intensity) if y > 0 else ("backward", intensity)

@app.route('/')
def hello():
    return render_template('index.html')

@app.route('/command', methods=['POST'])
def handle_command():
    global last_command
    if not my_dog.is_legs_done():
        return jsonify({'status': 'busy', 'message': 'Robot occupé'})
    data = request.get_json()
    angle = data.get('angle', 0)
    intensity = data.get('intensity', 0)
    direction, value = calculate_direction(angle, intensity)
    # Calcul de la vitesse réelle
    speed = 0 if direction == "stop" else int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * value)
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
    app.run(host='0.0.0.0', port=8080, debug=True)