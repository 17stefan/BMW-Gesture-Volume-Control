# -*- coding: utf-8 -*-
import cv2
import mediapipe as mp
import numpy as np
import math
import subprocess
from pycaw.utils import AudioUtilities

# Inițializează Windows Audio API pentru control volum
try:
    # Obține dispozitivul audio implicit (speaker)
    devices = AudioUtilities.GetSpeakers()
    volume = devices.EndpointVolume
    AUDIO_API_AVAILABLE = True
    print("[INFO] Windows Audio API initialized successfully!")
except Exception as e:
    print(f"[WARNING] Windows Audio API not available: {e}")
    print("[INFO] Volume control disabled. Please ensure pycaw is installed correctly.")
    AUDIO_API_AVAILABLE = False
    volume = None

# Inițializează MediaPipe Hands
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.5
)

# Inițializează captura video din camera web
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

# Variabile pentru control prin rotație
current_volume = 50  # Volumul inițial (0-100)
last_angle = None  # Unghiul anterior pentru a detecta rotația
last_set_volume = -1  # Pentru a evita setări inutile
rotation_sensitivity = 8  # Câți grade de rotație = 1% volum (mai mare = mai lent)
angle_threshold = 3  # Pragul minim de rotație pentru a actualiza volumul (în grade)


def calculate_finger_angle(finger_base, finger_tip):
    """
    Calculează unghiul de orientare a degetului arătător în sine.
    
    Args:
        finger_base: Tuple (x_base, y_base) - baza degetului arătător (punct 5)
        finger_tip: Tuple (x_tip, y_tip) - vârful degetului arătător (punct 8)
    
    Returns:
        float: Unghiul de orientare a degetului în grade (0-360)
    """
    x_base, y_base = finger_base
    x_tip, y_tip = finger_tip
    
    # Calculează vectorul de la bază la vârf
    dx = x_tip - x_base
    dy = y_tip - y_base
    
    # Calculează unghiul (în radiani, apoi convertește în grade)
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    
    # Normalizează unghiul la intervalul [0, 360)
    if angle_deg < 0:
        angle_deg += 360
    
    return angle_deg


def detect_rotation_direction(current_angle, previous_angle):
    """
    Detectează direcția de rotație a degetului arătător (sens orar sau anti-orar).
    
    Args:
        current_angle: Unghiul actual al degetului (0-360)
        previous_angle: Unghiul anterior (0-360)
    
    Returns:
        tuple: (volume_change, rotation_degrees)
               volume_change: +N (orar/creștere), -N (anti-orar/scădere), 0 (niciun schimbare)
               rotation_degrees: gradul de rotație (pozitiv=orar, negativ=anti-orar)
    """
    if previous_angle is None:
        return 0, 0
    
    # Calculează diferența de unghi
    angle_diff = current_angle - previous_angle
    
    # Ajustează pentru unghiuri care trec granița 0/360
    if angle_diff > 180:
        angle_diff -= 360
    elif angle_diff < -180:
        angle_diff += 360
    
    # Determină direcția de rotație și schimbarea volumului
    # Sens orar (pozitiv) = creștere volum
    # Sens anti-orar (negativ) = scădere volum
    if abs(angle_diff) >= angle_threshold:
        volume_change = int(angle_diff / rotation_sensitivity)
        return volume_change, angle_diff
    
    return 0, angle_diff


def draw_volume_bar(frame, volume_percent, x, y, width=200, height=30):
    """
    Desenează o bară de volum pe cadru.
    
    Args:
        frame: Cadrul video (numpy array)
        volume_percent: Procentajul volumului (0-100)
        x, y: Coordonatele colțului superior-stâng al barei
        width: Lățimea barei în pixeli
        height: Înălțimea barei în pixeli
    """
    # Desenează dreptunghiul de fundal al barei
    cv2.rectangle(frame, (x, y), (x + width, y + height), (200, 200, 200), 2)
    
    # Calculează lățimea portiunii pline (volum actual)
    fill_width = int((volume_percent / 100) * width)
    
    # Desenează portiunea pline a barei
    # Culoare: roșu (volum mic), galben (mediu), verde (volum mare)
    if volume_percent < 33:
        color = (0, 0, 255)  # Roșu
    elif volume_percent < 66:
        color = (0, 255, 255)  # Galben
    else:
        color = (0, 255, 0)  # Verde
    
    cv2.rectangle(frame, (x, y), (x + fill_width, y + height), color, -1)
    
    # Desenează textul cu procentajul
    text = f"{volume_percent}%"
    cv2.putText(
        frame, text, (x + width + 10, y + height),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )


def set_system_volume_windows(volume_percent):
    """
    Setează nivelul volumului sistemului Windows folosind Windows Audio API.
    
    Args:
        volume_percent: Procentajul volumului dorit (0-100)
    """
    if not AUDIO_API_AVAILABLE:
        return
    
    try:
        # Convertește procentajul la interval 0.0-1.0
        volume_level = volume_percent / 100.0
        
        # Setează volumul folosind Windows Audio API
        volume.SetMasterVolumeLevelScalar(float(volume_level), None)
    except Exception as e:
        print(f"[ERROR] Failed to set volume: {e}")


def clamp_volume(volume):
    """
    Limitează volumul în intervalul [0, 100].
    
    Args:
        volume: Volumul curent
    
    Returns:
        int: Volumul limitat
    """
    return max(0, min(100, volume))


print("=" * 60)
print("    VOLUME CONTROL - Hand Gesture Rotation")
print("             BMW STYLE GESTURE CONTROL")
print("="*60)
print()
print("INSTRUCTIONS:")
print("  * Show your INDEX FINGER to the camera")
print("  * Rotate CLOCKWISE (>) = INCREASE volume")
print("  * Rotate COUNTER-CLOCKWISE (<) = DECREASE volume")
print("  * Press 'q' to exit")
print()
print("=" * 60)
print()

# Loop principal
while True:
    # Citește un cadru din camera web
    ret, frame = cap.read()
    
    # Dacă nu s-a citit cadrul cu succes, ieșim
    if not ret:
        break
    
    # Redimensionează cadrul pentru performanță mai bună
    frame = cv2.resize(frame, (1280, 720))
    
    # Inversează cadrul pe orizontală pentru o mai bună experiență (oglindire)
    frame = cv2.flip(frame, 1)
    
    # Convertește culoarea din BGR la RGB (MediaPipe necesită RGB)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # Procesează cadrul cu MediaPipe Hands
    results = hands.process(frame_rgb)
    
    # Obține dimensiunile cadrului
    h, w, c = frame.shape
    
    # Dacă s-au detectat mâini
    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            # Extrage coordonatele degetului mare (Thumb tip - index 4)
            thumb_tip = hand_landmarks.landmark[4]
            thumb_x = int(thumb_tip.x * w)
            thumb_y = int(thumb_tip.y * h)
            
            # Extrage coordonatele degetului arătător (Index tip - index 8)
            index_tip = hand_landmarks.landmark[8]
            index_x = int(index_tip.x * w)
            index_y = int(index_tip.y * h)
            
            # Extrage baza degetului arătător (Index base - index 5)
            index_base = hand_landmarks.landmark[5]
            index_base_x = int(index_base.x * w)
            index_base_y = int(index_base.y * h)
            
            # Calculează unghiul de orientare a degetului arătător în sine
            current_angle = calculate_finger_angle((index_base_x, index_base_y), (index_x, index_y))
            
            # Detectează direcția de rotație și calculează schimbarea volumului
            volume_change, angle_diff = detect_rotation_direction(current_angle, last_angle)
            
            # Actualizează volumul pe baza rotației
            if volume_change != 0:
                current_volume = clamp_volume(current_volume + volume_change)
            
            # Setează volumul sistemului doar dacă s-a schimbat
            if abs(current_volume - last_set_volume) >= 1:
                try:
                    set_system_volume_windows(current_volume)
                    last_set_volume = current_volume
                except:
                    pass
            
            # Actualizează unghiul anterior pentru următoarea iterație
            last_angle = current_angle
            
            # ========= DESENARE PE CADRU =========
            
            # Desenează cercuri la bază și vârf degetului arătător
            cv2.circle(frame, (index_base_x, index_base_y), 8, (200, 100, 255), -1)  # Baza degetului
            cv2.circle(frame, (index_x, index_y), 12, (0, 255, 0), -1)  # Vârful degetului
            
            # Desenează linia care conectează baza și vârful degetului arătător
            cv2.line(frame, (index_base_x, index_base_y), (index_x, index_y), (0, 255, 255), 3)
            
            # Desenează o bară de volum pe ecran
            draw_volume_bar(frame, current_volume, 50, 50)
            
            # Desenează informații despre unghiul măsurat
            angle_text = f"Angle: {current_angle:.1f} deg"
            cv2.putText(
                frame, angle_text, (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
            )
            
            # Desenează indicatie de direcție de rotație
            if volume_change > 0:
                direction_text = "> VOLUME UP"
                direction_color = (0, 255, 0)
            elif volume_change < 0:
                direction_text = "< VOLUME DOWN"
                direction_color = (0, 0, 255)
            else:
                direction_text = "ROTATING FINGER"
                direction_color = (200, 200, 200)
            
            cv2.putText(
                frame, direction_text, (50, 140),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, direction_color, 2
            )
    else:
        # Dacă nu se detectează mână, afișează mesaj
        cv2.putText(
            frame, "No hand detected - Show your hand to camera!",
            (w // 2 - 250, h // 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2
        )
    
    # Adaugă text informativ în colțul superior-stâng
    info_text = "INDEX FINGER ROTATION VOLUME CONTROL"
    cv2.putText(
        frame, info_text, (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2
    )
    
    # Afișează cadrul procesat
    cv2.imshow("Volume Control - Finger Rotation", frame)
    
    # Asteapta 1ms pentru o tastă apăsată
    key = cv2.waitKey(1) & 0xFF
    
    
    # Dacă se apasă 'q', se închide aplicația
    if key == ord('q'):
        print("\nApplication closed.")
        break

# Eliberează resursele
cap.release()
cv2.destroyAllWindows()
hands.close()

print("Resources released successfully.")
