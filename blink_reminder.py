import cv2
import mediapipe as mp
import time
import numpy as np
from plyer import notification
import argparse
import sys

# --- CONFIGURATION ---
# Eye landmark indices (MediaPipe Face Mesh)
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]

def calculate_ear(landmarks, eye_indices):
    """Calculate Eye Aspect Ratio (EAR)"""
    def dist(p1, p2):
        return np.linalg.norm(np.array([p1.x, p1.y]) - np.array([p2.x, p2.y]))
    
    # Vertical distances
    v1 = dist(landmarks[eye_indices[1]], landmarks[eye_indices[5]])
    v2 = dist(landmarks[eye_indices[2]], landmarks[eye_indices[4]])
    # Horizontal distance
    h = dist(landmarks[eye_indices[0]], landmarks[eye_indices[3]])
    
    ear = (v1 + v2) / (2.0 * h)
    return ear

def main():
    parser = argparse.ArgumentParser(description="Blink Reminder - Prevent Digital Eye Strain")
    parser.add_argument("--threshold", type=float, default=0.22, help="EAR threshold for blink detection (default: 0.22)")
    parser.add_argument("--interval", type=int, default=10, help="Seconds without blinking before reminder (default: 10)")
    parser.add_argument("--no-preview", action="store_true", help="Disable camera preview window")
    args = parser.parse_args()

    # Initialize MediaPipe
    try:
        from mediapipe.python.solutions import face_mesh as mp_face_mesh
    except ImportError:
        import mediapipe as mp
        mp_face_mesh = mp.solutions.face_mesh
    
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not access camera.")
        sys.exit(1)

    last_blink_time = time.time()
    blink_count = 0
    is_blinking = False
    
    print(f"Blink Reminder Active!")
    print(f"Threshold: {args.threshold} | Interval: {args.interval}s")
    print("Press 'q' in the preview window to quit.")

    try:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            # Flip for mirror effect and convert to RGB
            frame = cv2.flip(frame, 1)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb_frame)

            current_time = time.time()
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark
                
                # Calculate EAR for both eyes
                left_ear = calculate_ear(landmarks, LEFT_EYE)
                right_ear = calculate_ear(landmarks, RIGHT_EYE)
                avg_ear = (left_ear + right_ear) / 2.0

                # Blink detection logic
                if avg_ear < args.threshold:
                    if not is_blinking:
                        is_blinking = True
                        blink_count += 1
                        last_blink_time = current_time
                else:
                    is_blinking = False

                # Visual feedback on frame
                if not args.no_preview:
                    h, w, _ = frame.shape
                    for idx in LEFT_EYE + RIGHT_EYE:
                        p = landmarks[idx]
                        cv2.circle(frame, (int(p.x * w), int(p.y * h)), 2, (0, 165, 255), -1)
                    
                    cv2.putText(frame, f"Blinks: {blink_count}", (30, 50), 
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 165, 255), 2)
                    cv2.putText(frame, f"EAR: {avg_ear:.2f}", (30, 90), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

            # Reminder logic
            time_since_blink = current_time - last_blink_time
            if time_since_blink > args.interval:
                print("Reminder: Please blink!")
                notification.notify(
                    title="Blink Reminder",
                    message="You haven't blinked in a while. Refresh your eyes!",
                    app_name="BlinkReminder",
                    timeout=5
                )
                # Reset timer to avoid spamming notifications
                last_blink_time = current_time

            if not args.no_preview:
                cv2.imshow('Blink Reminder - Press Q to Quit', frame)
                if cv2.waitKey(5) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        face_mesh.close()

if __name__ == "__main__":
    main()
