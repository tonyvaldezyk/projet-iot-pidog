"""
PiDog Robot FastAPI Backend
===========================

API REST complète pour contrôler le robot PiDog
- Contrôle de mouvement (joystick virtuel)
- Contrôle de la tête
- Actions spéciales
- Mode autonome
- Données des capteurs
- Documentation Swagger automatique

Auteur: Expert Dev Full Stack
Version: 1.0.0
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Literal, Union
import threading
import signal
import sys
import os
import time
import random
from math import pi, atan2, sqrt
import uvicorn

# Import du SDK PiDog (remplacez par votre SDK réel)
try:
    from pidog import Pidog
    PIDOG_AVAILABLE = True
except ImportError:
    print("⚠️  SDK PiDog non disponible - Mode simulation activé")
    PIDOG_AVAILABLE = False
    
    # Classe simulée pour les tests
    class Pidog:
        def __init__(self):
            pass
        def close(self):
            pass
        def is_legs_done(self):
            return True
        def is_all_done(self):
            return True
        def do_action(self, action, speed=100):
            time.sleep(0.1)  # Simulation
        def legs_stop(self):
            pass
        def wait_all_done(self):
            pass
        def head_move(self, *args, **kwargs):
            pass
        def read_distance(self):
            return random.uniform(10, 100)

# ================================
# Configuration et constantes
# ================================

# Constantes du robot
SIT_HEAD_PITCH = -40
STAND_HEAD_PITCH = 0
STATUS_STAND = 0
STATUS_SIT = 1
STATUS_LIE = 2

MIN_SPEED = 85
MAX_SPEED = 98
DEADZONE = 0.35  # Zone morte pour éviter les micro-mouvements

# Variables globales
my_dog = Pidog() if PIDOG_AVAILABLE else Pidog()
head_yrp = [0, 0, 0]
head_origin_yrp = [0, 0, 0]
head_pitch_init = 0
current_status = STATUS_LIE
last_command = None
autonomous_mode_enabled = False
_autonomous_thread = None
autonomous_lock = threading.Lock()

# ================================
# Modèles Pydantic
# ================================

class MovementCommand(BaseModel):
    """Modèle pour les commandes de mouvement - Format universel"""
    
    # Format HTML (angle/intensity)
    angle: Optional[float] = Field(None, ge=0, le=360, description="Angle en degrés (0=haut, 90=droite, 180=bas, 270=gauche)")
    intensity: Optional[float] = Field(None, ge=0, le=1, description="Intensité du mouvement (0-1)")
    
    # Format alternatif (kx/ky)
    kx: Optional[float] = Field(None, ge=-1, le=1, description="Composante X du mouvement")
    ky: Optional[float] = Field(None, ge=-1, le=1, description="Composante Y du mouvement")
    
    class Config:
        schema_extra = {
            "examples": [
                {
                    "angle": 0,
                    "intensity": 0.8,
                    "description": "Format HTML - Avancer"
                },
                {
                    "kx": 0.5,
                    "ky": 0.8,
                    "description": "Format KX/KY - Mouvement diagonal"
                }
            ]
        }

class HeadControl(BaseModel):
    """Modèle pour le contrôle de la tête"""
    qx: float = Field(..., ge=-100, le=100, description="Position horizontale (yaw) de la tête")
    qy: float = Field(..., ge=-100, le=100, description="Position verticale (pitch) de la tête")
    
    class Config:
        schema_extra = {
            "example": {
                "qx": 45,
                "qy": -20
            }
        }

class ActionCommand(BaseModel):
    """Modèle pour les actions spéciales"""
    action: Literal["sit", "stand_up", "lie_down", "wag_tail", "stretch", "shake_head"] = Field(
        ..., description="Action à exécuter"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "action": "sit"
            }
        }

class AutonomousMode(BaseModel):
    """Modèle pour le mode autonome"""
    enabled: bool = Field(..., description="Activer ou désactiver le mode autonome")
    
    class Config:
        schema_extra = {
            "example": {
                "enabled": True
            }
        }

class APIResponse(BaseModel):
    """Modèle de réponse générique"""
    status: Literal["success", "error", "busy"]
    message: str
    data: Optional[dict] = None

class SensorData(BaseModel):
    """Modèle pour les données des capteurs"""
    distance: Optional[float] = Field(None, description="Distance mesurée par le capteur ultrason (cm)")
    status: int = Field(..., description="Statut du robot (0=debout, 1=assis, 2=couché)")

class RobotStatus(BaseModel):
    """Modèle pour l'état du robot"""
    status: Literal["connected", "error"]
    robot_status: int = Field(..., description="Statut du robot (0=debout, 1=assis, 2=couché)")
    is_busy: bool = Field(..., description="Indique si le robot est occupé")
    autonomous_mode: bool = Field(..., description="Indique si le mode autonome est actif")

class IPResponse(BaseModel):
    """Modèle pour la réponse IP"""
    ip: Optional[str] = Field(None, description="Adresse IP du robot")

# ================================
# Fonctions utilitaires
# ================================

def cleanup_gpio():
    """Nettoyage des ressources GPIO"""
    global my_dog
    try:
        if my_dog is not None:
            my_dog.close()
            my_dog = None
        print("🧹 Nettoyage GPIO terminé")
    except Exception as e:
        print(f"❌ Erreur lors du nettoyage: {e}")

def signal_handler(sig, frame):
    """Gestionnaire de signaux pour arrêt propre"""
    print('\n🛑 Arrêt du serveur...')
    cleanup_gpio()
    sys.exit(0)

# Configuration des signaux
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def map_value(x: float, in_min: float, in_max: float, out_min: float, out_max: float) -> float:
    """Mapper une valeur d'une plage à une autre"""
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

def set_head(roll: Optional[float] = None, pitch: Optional[float] = None, yaw: Optional[float] = None):
    """Contrôler la position de la tête du robot"""
    global head_yrp
    try:
        if roll is not None:
            head_yrp[1] = roll + head_origin_yrp[1]
        if pitch is not None:
            head_yrp[2] = pitch + head_origin_yrp[2]
        if yaw is not None:
            head_yrp[0] = yaw + head_origin_yrp[0]
        
        my_dog.head_move([head_yrp], pitch_comp=head_pitch_init, immediately=True, speed=100)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur contrôle tête: {str(e)}")

def get_network_ip() -> tuple[Optional[str], Optional[str]]:
    """Obtenir les adresses IP réseau"""
    try:
        wlan0 = os.popen("ifconfig wlan0 |awk '/inet/'|awk 'NR==1 {print $2}'").readline().strip('\n')
        eth0 = os.popen("ifconfig eth0 |awk '/inet/'|awk 'NR==1 {print $2}'").readline().strip('\n')
        
        wlan0 = wlan0 if wlan0 else None
        eth0 = eth0 if eth0 else None
        
        return wlan0, eth0
    except Exception:
        return None, None

def calculate_direction_from_angle(angle: float, intensity: float) -> tuple[str, float]:
    """
    Convertir angle/intensity en direction - Compatible avec l'HTML
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

def calculate_direction_from_kx_ky(kx: float, ky: float) -> tuple[str, float]:
    """
    Convertir kx/ky en direction - Compatible avec d'autres interfaces
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
    """Comportement autonome du robot"""
    global autonomous_mode_enabled
    
    def check_stop():
        with autonomous_lock:
            return not autonomous_mode_enabled

    # Actions statiques (non déplacement)
    static_actions = [
        ("bark", lambda: my_dog.do_action('bark', speed=100)),
        ("lie", lambda: my_dog.do_action('lie', speed=70)),
        ("stretch", lambda: my_dog.do_action('stretch', speed=80)),
        ("wag_tail", lambda: my_dog.do_action('wag_tail', speed=100)),
        ("shake_head", lambda: my_dog.do_action('shake_head', speed=80)),
    ]

    print("🤖 Mode autonome démarré")
    
    while not check_stop():
        try:
            # 1. Aboyer pendant 3 secondes
            if check_stop(): break
            print('[AUTO] Barking for 3s')
            my_dog.do_action('bark', speed=100)
            for _ in range(3):
                if check_stop(): break
                time.sleep(1)

            # 2. Marche avant, évite les obstacles, pendant 10s
            if check_stop(): break
            print('[AUTO] Walking forward for 10s')
            t0 = time.time()
            while time.time() - t0 < 10:
                if check_stop(): break
                
                try:
                    dist = my_dog.read_distance()
                    if dist is not None and dist < 20:
                        print('[AUTO] Obstacle detected, avoiding')
                        turn = random.choice(['turn_left', 'turn_right'])
                        my_dog.do_action(turn, speed=random.randint(85, 98))
                        my_dog.wait_all_done()
                        my_dog.do_action('forward', speed=random.randint(85, 98))
                    else:
                        my_dog.do_action('forward', speed=random.randint(85, 98))
                except Exception:
                    # En cas d'erreur capteur, continue à avancer
                    my_dog.do_action('forward', speed=random.randint(85, 98))
                
                my_dog.wait_all_done()
                time.sleep(0.5)

            # 3. Action statique aléatoire pendant 5s
            if check_stop(): break
            action_name, action_func = random.choice(static_actions)
            print(f'[AUTO] Static action for 5s: {action_name}')
            action_func()
            for _ in range(5):
                if check_stop(): break
                time.sleep(1)

            # 4. Se lever
            if check_stop(): break
            print('[AUTO] Standing up')
            my_dog.do_action('stand', speed=70)
            my_dog.wait_all_done()

        except Exception as e:
            print(f"[AUTO] Erreur dans le comportement autonome: {e}")
            time.sleep(1)
    
    print("🤖 Mode autonome arrêté")

# ================================
# Configuration FastAPI
# ================================

app = FastAPI(
    title="PiDog Robot API",
    description="""
    🐕 **API REST complète pour contrôler le robot PiDog**
    
    Cette API permet de contrôler tous les aspects du robot PiDog via des endpoints REST.
    
    ## Fonctionnalités principales:
    
    * **🎮 Contrôle de mouvement** - Déplacement dans toutes les directions
    * **🎯 Contrôle de la tête** - Orientation yaw/pitch
    * **🎭 Actions spéciales** - Assis, debout, étirements, etc.
    * **🤖 Mode autonome** - Comportement automatique
    * **📊 Capteurs** - Lecture des données en temps réel
    * **ℹ️ Statut** - État du robot et connectivité
    
    ## Formats supportés:
    
    * **Format HTML**: `{angle, intensity}` - Compatible interface web
    * **Format KX/KY**: `{kx, ky}` - Compatible joysticks
    
    ## Utilisation:
    
    1. Vérifiez l'état avec `/status`
    2. Contrôlez les mouvements avec `/command`
    3. Orientez la tête avec `/head_control`
    4. Exécutez des actions avec `/action`
    5. Activez le mode autonome avec `/autonomous_mode`
    """,
    version="1.0.0",
    contact={
        "name": "PiDog API Support",
        "email": "support@pidog.local",
    },
    license_info={
        "name": "MIT",
    },
)

# Configuration CORS pour permettre les appels depuis un frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, spécifiez les domaines autorisés
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================
# Endpoints API
# ================================

@app.get("/", 
         summary="Informations API",
         description="Retourne les informations de base de l'API",
         response_model=dict,
         tags=["Info"])
async def root():
    """
    🏠 **Endpoint racine de l'API**
    
    Retourne les informations de base et les liens utiles.
    """
    return {
        "message": "🐕 PiDog Robot API",
        "version": "1.0.0",
        "status": "active",
        "documentation": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "status": "/status",
            "movement": "/command", 
            "head_control": "/head_control",
            "actions": "/action",
            "autonomous": "/autonomous_mode",
            "sensors": "/sensor_data",
            "network": "/get_ip"
        }
    }

@app.post("/command",
          summary="Contrôle de mouvement",
          description="Contrôle universel du robot - accepte les formats angle/intensity et kx/ky",
          response_model=APIResponse,
          tags=["Mouvement"])
async def handle_command(command: MovementCommand):
    """
    🎮 **Contrôle de mouvement universel**
    
    Accepte deux formats de données:
    
    ### Format HTML (angle/intensity):
    - `angle`: 0-360° (0=avant, 90=droite, 180=arrière, 270=gauche)
    - `intensity`: 0-1 (force du mouvement)
    
    ### Format KX/KY:
    - `kx`: -1 à 1 (composante horizontale)
    - `ky`: -1 à 1 (composante verticale)
    
    ### Directions possibles:
    - `forward`: Avancer
    - `backward`: Reculer  
    - `turn_left`: Tourner à gauche
    - `turn_right`: Tourner à droite
    - `stop`: Arrêter
    """
    global last_command, autonomous_mode_enabled
    
    # Désactiver le mode autonome si une commande manuelle arrive
    with autonomous_lock:
        if autonomous_mode_enabled:
            autonomous_mode_enabled = False
            print("🤖 Mode autonome désactivé par commande manuelle")
    
    # Vérifier si le robot est occupé
    if not my_dog.is_legs_done():
        return APIResponse(
            status="busy",
            message="Robot occupé, commande ignorée"
        )
    
    # Détection automatique du format
    if command.angle is not None and command.intensity is not None:
        # Format HTML: {angle, intensity}
        direction, value = calculate_direction_from_angle(command.angle, command.intensity)
        print(f"📱 Format HTML: angle={command.angle}°, intensity={command.intensity} → {direction}")
        
    elif command.kx is not None and command.ky is not None:
        # Format alternatif: {kx, ky}
        direction, value = calculate_direction_from_kx_ky(command.kx, command.ky)
        print(f"🕹️  Format KX/KY: kx={command.kx}, ky={command.ky} → {direction}")
        
    else:
        raise HTTPException(
            status_code=400, 
            detail="Format de données invalide. Utilisez soit {angle, intensity} soit {kx, ky}"
        )

    # Calcul de la vitesse
    speed = 0 if direction == "stop" else int(MIN_SPEED + (MAX_SPEED - MIN_SPEED) * min(value, 1.0))
    
    try:
        # Arrêter le mouvement précédent si différent
        if direction != last_command and last_command not in [None, "stop"]:
            my_dog.legs_stop()
            my_dog.wait_all_done()
        
        # Exécuter la nouvelle commande
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
        
        return APIResponse(
            status="success",
            message=f"Commande {direction} exécutée - vitesse {speed}%",
            data={
                "direction": direction,
                "speed": speed,
                "format": "html" if command.angle is not None else "kx_ky"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur exécution commande: {str(e)}")

@app.post("/head_control",
          summary="Contrôle de la tête", 
          description="Contrôle la position de la tête du robot (yaw/pitch)",
          response_model=APIResponse,
          tags=["Contrôle"])
async def handle_head_control(head: HeadControl):
    """
    🎯 **Contrôle de la tête du robot**
    
    ### Paramètres:
    - `qx`: Position horizontale (yaw) -100 à 100
    - `qy`: Position verticale (pitch) -100 à 100
    
    ### Zone morte:
    Les valeurs entre -5 et 5 remettent la tête au centre.
    """
    try:
        if abs(head.qx) > 5 or abs(head.qy) > 5:  # Zone morte pour la tête
            yaw = map_value(head.qx, -100, 100, -90, 90)
            pitch = map_value(head.qy, -100, 100, -30, 30)
            set_head(yaw=yaw, pitch=pitch)
        else:
            set_head(yaw=0, pitch=0)
        
        return APIResponse(
            status="success",
            message=f"Tête orientée: yaw={head.qx:.1f}, pitch={head.qy:.1f}",
            data={
                "qx": head.qx,
                "qy": head.qy,
                "yaw_mapped": map_value(head.qx, -100, 100, -90, 90) if abs(head.qx) > 5 else 0,
                "pitch_mapped": map_value(head.qy, -100, 100, -30, 30) if abs(head.qy) > 5 else 0
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur contrôle tête: {str(e)}")

@app.post("/action",
          summary="Actions spéciales",
          description="Exécute des actions prédéfinies du robot",
          response_model=APIResponse,
          tags=["Actions"])
async def handle_action(action: ActionCommand):
    """
    🎭 **Actions spéciales du robot**
    
    ### Actions disponibles:
    - `sit`: S'asseoir
    - `stand_up`: Se lever
    - `lie_down`: Se coucher
    - `wag_tail`: Remuer la queue
    - `stretch`: S'étirer
    - `shake_head`: Secouer la tête
    """
    try:
        if action.action == "sit":
            my_dog.do_action('sit', speed=70)
        elif action.action == "stand_up":
            my_dog.do_action('stand', speed=70)
        elif action.action == "lie_down":
            my_dog.do_action('lie', speed=70)
        elif action.action == "wag_tail":
            my_dog.do_action('wag_tail', speed=100)
        elif action.action == "stretch":
            my_dog.do_action('stretch', speed=80)
        elif action.action == "shake_head":
            my_dog.do_action('shake_head', speed=80)
        
        return APIResponse(
            status="success",
            message=f"Action '{action.action}' exécutée avec succès",
            data={"action": action.action}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur exécution action: {str(e)}")

@app.post("/autonomous_mode",
          summary="Mode autonome",
          description="Active/désactive le mode autonome du robot",
          response_model=APIResponse,
          tags=["Autonome"])
async def set_autonomous_mode(mode: AutonomousMode, background_tasks: BackgroundTasks):
    """
    🤖 **Contrôle du mode autonome**
    
    ### Fonctionnalités du mode autonome:
    - Aboiements périodiques
    - Marche avec évitement d'obstacles
    - Actions aléatoires (étirements, remuer la queue, etc.)
    - Changements de position automatiques
    
    ### Comportement:
    - **Activé**: Lance un thread en arrière-plan
    - **Désactivé**: Arrête le comportement autonome
    - Les commandes manuelles désactivent automatiquement ce mode
    """
    global autonomous_mode_enabled, _autonomous_thread
    
    with autonomous_lock:
        if mode.enabled and not autonomous_mode_enabled:
            # Activer le mode autonome
            autonomous_mode_enabled = True
            background_tasks.add_task(autonomous_behavior)
            message = "Mode autonome activé"
            
        elif not mode.enabled and autonomous_mode_enabled:
            # Désactiver le mode autonome
            autonomous_mode_enabled = False
            message = "Mode autonome désactivé"
            
        else:
            # Pas de changement
            message = f"Mode autonome déjà {'activé' if autonomous_mode_enabled else 'désactivé'}"
    
    return APIResponse(
        status="success",
        message=message,
        data={
            "enabled": autonomous_mode_enabled,
            "previous_state": not mode.enabled if mode.enabled != autonomous_mode_enabled else mode.enabled
        }
    )

@app.get("/get_ip",
         summary="Adresse IP",
         description="Retourne l'adresse IP du robot pour le streaming",
         response_model=IPResponse,
         tags=["Réseau"])
async def get_ip():
    """
    📡 **Obtenir l'adresse IP du robot**
    
    Retourne l'adresse IP disponible pour la connexion réseau.
    Priorité: WiFi (wlan0) puis Ethernet (eth0).
    """
    wlan0, eth0 = get_network_ip()
    ip = wlan0 if wlan0 else eth0
    
    return IPResponse(ip=ip)

@app.get("/sensor_data",
         summary="Données des capteurs",
         description="Retourne les données des capteurs en temps réel",
         response_model=Union[SensorData, dict],
         tags=["Capteurs"])
async def get_sensor_data():
    """
    📊 **Données des capteurs en temps réel**
    
    ### Capteurs disponibles:
    - **Distance**: Capteur ultrason (cm)
    - **Status**: Position du robot (0=debout, 1=assis, 2=couché)
    """
    try:
        distance = round(my_dog.read_distance(), 2)
        return SensorData(
            distance=distance,
            status=current_status
        )
    except Exception as e:
        return {"error": f"Erreur lecture capteurs: {str(e)}"}

@app.get("/status",
         summary="État du robot",
         description="Retourne l'état général du robot",
         response_model=RobotStatus,
         tags=["État"])
async def get_status():
    """
    ℹ️ **État général du robot**
    
    ### Informations retournées:
    - **Status**: Connectivité (connected/error)
    - **Robot Status**: Position (0=debout, 1=assis, 2=couché)
    - **Is Busy**: Occupation du robot
    - **Autonomous Mode**: État du mode autonome
    """
    try:
        return RobotStatus(
            status="connected",
            robot_status=current_status,
            is_busy=not my_dog.is_all_done(),
            autonomous_mode=autonomous_mode_enabled
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lecture statut: {str(e)}")

# ================================
# Point d'entrée principal
# ================================

if __name__ == "__main__":
    print("🐕 Démarrage du serveur PiDog FastAPI...")
    
    # Affichage des informations réseau
    wlan0, eth0 = get_network_ip()
    ip = wlan0 if wlan0 else eth0
    
    if ip:
        print(f"📡 API disponible sur :")
        print(f"   🌐 Réseau: http://{ip}:8000")
        print(f"   📚 Documentation: http://{ip}:8000/docs")
        print(f"   📖 ReDoc: http://{ip}:8000/redoc")
    else:
        print(f"📡 API disponible sur :")
        print(f"   🏠 Local: http://localhost:8000")
        print(f"   📚 Documentation: http://localhost:8000/docs")
        print(f"   📖 ReDoc: http://localhost:8000/redoc")
    
    print(f"🎮 Mode SDK: {'Réel' if PIDOG_AVAILABLE else 'Simulation'}")
    
    try: 
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,  # Désactivé pour la production
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur...")
    except Exception as e:
        print(f"\033[31m❌ ERREUR: {e}\033[m")
    finally:
        cleanup_gpio()