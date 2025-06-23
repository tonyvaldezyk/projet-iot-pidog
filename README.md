# PiDog Control Project

This project provides a web-based interface to control a PiDog robot. It allows for manual control of the robot's movements and head, as well as an autonomous mode where the robot can navigate on its own.

## Features

- **Web-Based Control:** A responsive web interface with simple and advanced control modes.
- **Manual Control:** Use on-screen joysticks to control the robot's movement and head.
- **Autonomous Mode:** The robot can move autonomously, avoiding obstacles using its distance sensor.
- **Real-time Sensor Data:** View real-time data from the robot's sensors.
- **API Endpoints:** A set of API endpoints to control the robot programmatically.

## Technologies Used

- **Python:** The core language for the backend server.
- **Flask:** A lightweight web framework for Python.
- **Pidog Library:** The official library for controlling the PiDog robot.
- **HTML/CSS/JavaScript:** For the frontend web interface.
- **WebSockets:** For real-time communication between the client and server for vocal commands.
- **OpenAI (optional):** The project is set up to potentially use OpenAI for vocal commands.

## Getting Started

### Prerequisites

- A Raspberry Pi with a PiDog robot attached.
- Python 3.x installed on the Raspberry Pi.

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/tonyvaldezyk/projet-iot-pidog.git
   cd projet-iot-pidog
   ```

2. **Install the dependencies:**
   ```bash
   pip install -r requirement.txt
   ```

### Running the Project

To start the web server, run the following command:

```bash
python serverflask.py
```

The server will start on port 5000. You can access the web interface by navigating to `http://<your-raspberry-pi-ip>:5000` in your web browser.

## Deployment

The frontend of this application is deployed on AWS Lightsail, providing a publicly accessible and stable interface. The backend server, which directly controls the PiDog, runs on the Raspberry Pi.

The Lightsail-hosted frontend communicates with the Raspberry Pi backend by using the Pi's IP address, which must be correctly configured in the frontend application for the system to work.

## Web Interface

The project provides three web interfaces:

- **`/` or `/index.html`:** The main page with links to the simple and advanced interfaces.
- **`/simple`:** A simplified interface for basic control.
- **`/advanced`:** An advanced interface with more controls and real-time data.

## API Endpoints

The following API endpoints are available for programmatic control:

- `POST /command`
  - Controls the robot's movement. Accepts `angle` and `intensity` or `kx` and `ky` values.
- `POST /head_control`
  - Controls the robot's head. Accepts `qx` and `qy` values.
- `POST /action`
  - Executes a specific action. Accepts an `action` name (e.g., `sit`, `stand_up`).
- `GET /get_ip`
  - Returns the IP address of the Raspberry Pi.
- `GET /sensor_data`
  - Returns real-time sensor data (distance).
- `GET /status`
  - Returns the current status of the robot.
- `POST /autonomous_mode`
  - Enables or disables the autonomous mode. Accepts `enabled: true/false`.

## Vocal Commands

The project includes a vocal command interface, which can be accessed at `/vocal`. This interface allows you to control the robot using your voice.

### How it Works

1.  **WebSocket Connection:** The web page establishes a WebSocket connection to a server (the IP address can be configured on the page).
2.  **Audio Streaming:** When you start recording, your browser captures audio from your microphone and streams it to the server through the WebSocket connection.
3.  **Server-Side Processing:** The server receives the audio data, processes it to recognize commands, and then controls the PiDog accordingly.

To use this feature, you need to have a separate WebSocket server running that can handle the audio data and translate it into commands for the PiDog.

## Testing

Currently, there are no automated tests for this project. To test the functionality, you can manually interact with the web interface and the API endpoints.

## Future Work

- Add more autonomous behaviors.
- Create a more comprehensive test suite.
