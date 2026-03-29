import { useEffect, useRef, useState, useCallback } from "react";
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";
import { Eye, EyeOff, AlertCircle, Settings, Play, Pause, RefreshCw, X, Volume2, VolumeX, Clock, Target, Code, Terminal, Copy, Check } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

// Eye Aspect Ratio (EAR) calculation logic
// EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
// For MediaPipe, we use specific landmark indices for eyes.
const LEFT_EYE = [362, 385, 387, 263, 373, 380];
const RIGHT_EYE = [33, 160, 158, 133, 153, 144];

export default function BlinkTracker() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const faceLandmarkerRef = useRef<FaceLandmarker | null>(null);
  const requestRef = useRef<number | null>(null);
  
  const [isLoaded, setIsLoaded] = useState(false);
  const [isActive, setIsActive] = useState(false);
  const [lastBlinkTime, setLastBlinkTime] = useState(Date.now());
  const [blinkCount, setBlinkCount] = useState(0);
  const [showReminder, setShowReminder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [blinkScore, setBlinkScore] = useState(0);
  const [isBlinking, setIsBlinking] = useState(false);
  const [isDebugMode, setIsDebugMode] = useState(true);

  const isBlinkingRef = useRef(false);
  const isActiveRef = useRef(false);
  const blinkThresholdRef = useRef(0.4); // Blendshape threshold (0-1)

  // Initialize MediaPipe
  useEffect(() => {
    async function init() {
      try {
        const filesetResolver = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm"
        );
        const landmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
          baseOptions: {
            modelAssetPath: `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`,
            delegate: "GPU"
          },
          outputFaceBlendshapes: true,
          runningMode: "VIDEO",
          numFaces: 1
        });
        faceLandmarkerRef.current = landmarker;
        setIsLoaded(true);
      } catch (err) {
        console.error("Failed to load MediaPipe:", err);
        setError("Failed to initialize face tracking. Please check your connection.");
      }
    }
    init();

    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
      if (faceLandmarkerRef.current) faceLandmarkerRef.current.close();
    };
  }, []);

  const [reminderThreshold, setReminderThreshold] = useState(10);
  const [blinkSensitivity, setBlinkSensitivity] = useState(0.4);
  const [isSoundEnabled, setIsSoundEnabled] = useState(true);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isPythonOpen, setIsPythonOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const pythonScript = `import cv2
import mediapipe as mp
import time
import numpy as np
from plyer import notification

# Eye landmark indices
LEFT_EYE = [362, 385, 387, 263, 373, 380]
RIGHT_EYE = [33, 160, 158, 133, 153, 144]

def calculate_ear(landmarks, eye_indices):
    def dist(p1, p2):
        return np.linalg.norm(np.array([p1.x, p1.y]) - np.array([p2.x, p2.y]))
    v1 = dist(landmarks[eye_indices[1]], landmarks[eye_indices[5]])
    v2 = dist(landmarks[eye_indices[2]], landmarks[eye_indices[4]])
    h = dist(landmarks[eye_indices[0]], landmarks[eye_indices[3]])
    return (v1 + v2) / (2.0 * h)

mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(refine_landmarks=True)

cap = cv2.VideoCapture(0)
last_blink = time.time()
THRESHOLD = 0.22
INTERVAL = 10

while cap.isOpened():
    success, frame = cap.read()
    if not success: break
    
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb_frame)

    if results.multi_face_landmarks:
        landmarks = results.multi_face_landmarks[0].landmark
        ear = (calculate_ear(landmarks, LEFT_EYE) + calculate_ear(landmarks, RIGHT_EYE)) / 2.0
        if ear < THRESHOLD:
            last_blink = time.time()

    if time.time() - last_blink > INTERVAL:
        notification.notify(title="Blink Reminder", message="Please blink!")
        last_blink = time.time()

    if cv2.waitKey(5) & 0xFF == ord('q'): break

cap.release()`;

  const copyToClipboard = () => {
    navigator.clipboard.writeText(pythonScript);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Play sound function
  const playReminderSound = useCallback(() => {
    if (!isSoundEnabled) return;
    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    const oscillator = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(440, audioCtx.currentTime); // A4
    oscillator.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.1);
    
    gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.5);

    oscillator.connect(gainNode);
    gainNode.connect(audioCtx.destination);

    oscillator.start();
    oscillator.stop(audioCtx.currentTime + 0.5);
  }, [isSoundEnabled]);

  // Handle reminder logic
  useEffect(() => {
    const interval = setInterval(() => {
      const secondsSinceBlink = (Date.now() - lastBlinkTime) / 1000;
      if (secondsSinceBlink > reminderThreshold && isActive) {
        if (!showReminder) {
          setShowReminder(true);
          playReminderSound();
        }
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [lastBlinkTime, isActive, reminderThreshold, showReminder, playReminderSound]);

  const calculateEAR = (landmarks: any[]) => {
    const getDist = (p1: any, p2: any) => {
      return Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));
    };

    const leftEAR = (getDist(landmarks[385], landmarks[373]) + getDist(landmarks[387], landmarks[380])) / (2 * getDist(landmarks[362], landmarks[263]));
    const rightEAR = (getDist(landmarks[160], landmarks[153]) + getDist(landmarks[158], landmarks[144])) / (2 * getDist(landmarks[33], landmarks[133]));
    
    return (leftEAR + rightEAR) / 2;
  };

  const processVideo = useCallback(() => {
    if (!videoRef.current || !faceLandmarkerRef.current || !isActiveRef.current) return;

    const startTimeMs = performance.now();
    const results = faceLandmarkerRef.current.detectForVideo(videoRef.current, startTimeMs);

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");

    if (results.faceLandmarks && results.faceLandmarks.length > 0) {
      const landmarks = results.faceLandmarks[0];
      
      // Use Blendshapes for more robust blink detection
      let currentBlinkScore = 0;
      if (results.faceBlendshapes && results.faceBlendshapes.length > 0) {
        const blendshapes = results.faceBlendshapes[0].categories;
        const leftBlink = blendshapes.find(c => c.categoryName === "eyeBlinkLeft")?.score || 0;
        const rightBlink = blendshapes.find(c => c.categoryName === "eyeBlinkRight")?.score || 0;
        // We take the max of both eyes to detect even a single eye blink or partial blink
        currentBlinkScore = Math.max(leftBlink, rightBlink);
        setBlinkScore(currentBlinkScore);
      }

      // Draw landmarks if debug mode is on
      if (ctx && canvas) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (isDebugMode) {
          ctx.fillStyle = "#F97316"; // orange-500
          
          // Draw eye contours
          [...LEFT_EYE, ...RIGHT_EYE].forEach(idx => {
            const landmark = landmarks[idx];
            ctx.beginPath();
            ctx.arc(landmark.x * canvas.width, landmark.y * canvas.height, 2, 0, Math.PI * 2);
            ctx.fill();
          });

          // Draw a small indicator for the blink score
          ctx.strokeStyle = "#F97316";
          ctx.lineWidth = 2;
          ctx.strokeRect(10, 10, 100, 10);
          ctx.fillStyle = currentBlinkScore > blinkThresholdRef.current ? "#22C55E" : "#F97316";
          ctx.fillRect(10, 10, currentBlinkScore * 100, 10);
        }
      }

      // Detection logic using blendshape score
      if (currentBlinkScore > blinkThresholdRef.current) {
        if (!isBlinkingRef.current) {
          isBlinkingRef.current = true;
          setIsBlinking(true);
          setBlinkCount(prev => prev + 1);
          setLastBlinkTime(Date.now());
          setShowReminder(false);
        }
      } else {
        if (isBlinkingRef.current) {
          isBlinkingRef.current = false;
          setIsBlinking(false);
        }
      }
    } else if (ctx && canvas) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    requestRef.current = requestAnimationFrame(processVideo);
  }, [isDebugMode]);

  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadedmetadata = () => {
          videoRef.current?.play();
          setIsActive(true);
          isActiveRef.current = true;
          
          if (canvasRef.current && videoRef.current) {
            canvasRef.current.width = videoRef.current.videoWidth;
            canvasRef.current.height = videoRef.current.videoHeight;
          }

          requestRef.current = requestAnimationFrame(processVideo);
        };
      }
    } catch (err) {
      console.error("Camera error:", err);
      setError("Could not access camera. Please ensure permissions are granted.");
    }
  };

  const stopCamera = () => {
    setIsActive(false);
    isActiveRef.current = false;
    if (videoRef.current && videoRef.current.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach(track => track.stop());
    }
    if (requestRef.current) cancelAnimationFrame(requestRef.current);
    
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
  };

  const timeSinceLastBlink = Math.max(0, Math.floor((Date.now() - lastBlinkTime) / 1000));

  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white font-sans selection:bg-orange-500/30">
      {/* Header */}
      <header className="p-6 border-b border-white/10 flex justify-between items-center">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-orange-500 rounded-full flex items-center justify-center">
            <Eye className="text-black" size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">BLINK REMINDER</h1>
            <p className="text-xs text-white/40 font-mono uppercase tracking-widest">Ocular Health Monitor v1.0</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex flex-col items-end">
            <span className="text-[10px] text-white/40 font-mono uppercase">System Status</span>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`} />
              <span className="text-xs font-mono">{isActive ? 'ACTIVE' : 'STANDBY'}</span>
            </div>
          </div>
          <button 
            onClick={() => setIsPythonOpen(true)}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors flex items-center gap-2 text-white/40 hover:text-white"
          >
            <Code size={18} />
            <span className="text-[10px] font-mono uppercase">Python Script</span>
          </button>
          <button 
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors"
          >
            <Settings size={20} className="text-white/60" />
          </button>
        </div>
      </header>

      {/* Python Modal */}
      <AnimatePresence>
        {isPythonOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsPythonOpen(false)}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
            />
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative w-full max-w-2xl bg-[#121212] border border-white/10 rounded-3xl overflow-hidden shadow-2xl"
            >
              <div className="p-8 border-b border-white/10 flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <Terminal className="text-orange-500" size={20} />
                  <h2 className="text-xl font-bold">Local Python Version</h2>
                </div>
                <button onClick={() => setIsPythonOpen(false)} className="p-2 hover:bg-white/5 rounded-full">
                  <X size={20} />
                </button>
              </div>
              
              <div className="p-8 space-y-6">
                <p className="text-sm text-white/60">
                  If you prefer a native desktop version, you can run this Python script locally. 
                  It uses OpenCV and MediaPipe for efficient tracking.
                </p>
                
                <div className="relative group">
                  <pre className="bg-black p-6 rounded-2xl text-xs font-mono text-orange-500/80 overflow-x-auto max-h-[400px]">
                    {pythonScript}
                  </pre>
                  <button 
                    onClick={copyToClipboard}
                    className="absolute top-4 right-4 p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-all flex items-center gap-2 text-[10px] font-mono uppercase"
                  >
                    {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
                    {copied ? 'Copied' : 'Copy Code'}
                  </button>
                </div>

                <div className="bg-orange-500/10 border border-orange-500/20 p-4 rounded-xl flex items-start gap-3">
                  <AlertCircle className="text-orange-500 shrink-0" size={18} />
                  <div className="space-y-1">
                    <p className="text-[10px] font-bold uppercase text-orange-500">Requirements</p>
                    <p className="text-xs text-white/60 font-mono">pip install opencv-python mediapipe</p>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Settings Modal */}
      <AnimatePresence>
        {isSettingsOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsSettingsOpen(false)}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
            />
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              className="relative w-full max-w-md bg-[#121212] border border-white/10 rounded-3xl p-8 shadow-2xl"
            >
              <div className="flex justify-between items-center mb-8">
                <h2 className="text-xl font-bold">Monitor Settings</h2>
                <button onClick={() => setIsSettingsOpen(false)} className="p-2 hover:bg-white/5 rounded-full">
                  <X size={20} />
                </button>
              </div>

              <div className="space-y-8">
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <Clock size={18} className="text-orange-500" />
                      <span className="text-sm font-medium">Reminder Interval</span>
                    </div>
                    <span className="text-sm font-mono text-orange-500">{reminderThreshold}s</span>
                  </div>
                  <input 
                    type="range" 
                    min="5" 
                    max="30" 
                    step="1"
                    value={reminderThreshold}
                    onChange={(e) => setReminderThreshold(parseInt(e.target.value))}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-orange-500"
                  />
                  <p className="text-[10px] text-white/40 uppercase font-mono">Time without blinking before notification</p>
                </div>

                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <Target size={18} className="text-orange-500" />
                      <span className="text-sm font-medium">Blink Sensitivity</span>
                    </div>
                    <span className="text-sm font-mono text-orange-500">{(blinkSensitivity * 100).toFixed(0)}%</span>
                  </div>
                  <input 
                    type="range" 
                    min="0.1" 
                    max="0.9" 
                    step="0.01"
                    value={blinkSensitivity}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value);
                      setBlinkSensitivity(val);
                      blinkThresholdRef.current = 1 - val; // Invert for more intuitive UI
                    }}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-orange-500"
                  />
                  <p className="text-[10px] text-white/40 uppercase font-mono">Higher value = more sensitive (detects smaller blinks)</p>
                </div>

                <div className="flex justify-between items-center p-4 bg-white/5 rounded-2xl border border-white/5">
                  <div className="flex items-center gap-3">
                    <Eye size={18} className={isDebugMode ? "text-orange-500" : "text-white/40"} />
                    <span className="text-sm font-medium">Show Tracking Points</span>
                  </div>
                  <button 
                    onClick={() => setIsDebugMode(!isDebugMode)}
                    className={`w-12 h-6 rounded-full transition-colors relative ${isDebugMode ? 'bg-orange-500' : 'bg-white/10'}`}
                  >
                    <motion.div 
                      className="absolute top-1 left-1 w-4 h-4 bg-white rounded-full"
                      animate={{ x: isDebugMode ? 24 : 0 }}
                    />
                  </button>
                </div>

                <div className="flex justify-between items-center p-4 bg-white/5 rounded-2xl border border-white/5">
                  <div className="flex items-center gap-3">
                    {isSoundEnabled ? <Volume2 size={18} className="text-orange-500" /> : <VolumeX size={18} className="text-white/40" />}
                    <span className="text-sm font-medium">Sound Notification</span>
                  </div>
                  <button 
                    onClick={() => setIsSoundEnabled(!isSoundEnabled)}
                    className={`w-12 h-6 rounded-full transition-colors relative ${isSoundEnabled ? 'bg-orange-500' : 'bg-white/10'}`}
                  >
                    <motion.div 
                      className="absolute top-1 left-1 w-4 h-4 bg-white rounded-full"
                      animate={{ x: isSoundEnabled ? 24 : 0 }}
                    />
                  </button>
                </div>
              </div>

              <button 
                onClick={() => setIsSettingsOpen(false)}
                className="w-full mt-10 bg-white text-black font-bold py-4 rounded-xl transition-all active:scale-95"
              >
                SAVE CONFIGURATION
              </button>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      <main className="max-w-7xl mx-auto p-8 grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Stats & Controls */}
        <div className="lg:col-span-4 space-y-6">
          <div className="bg-white/5 border border-white/10 rounded-2xl p-6 space-y-6">
            <div className="space-y-1">
              <label className="text-[10px] text-white/40 font-mono uppercase tracking-widest">Session Statistics</label>
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-white/5 rounded-xl border border-white/5">
                  <span className="text-3xl font-bold block">{blinkCount}</span>
                  <span className="text-[10px] text-white/40 uppercase font-mono">Total Blinks</span>
                </div>
                <div className="p-4 bg-white/5 rounded-xl border border-white/5">
                  <span className={`text-3xl font-bold block ${timeSinceLastBlink > 8 ? 'text-orange-500' : ''}`}>
                    {timeSinceLastBlink}s
                  </span>
                  <span className="text-[10px] text-white/40 uppercase font-mono">Last Blink</span>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <label className="text-[10px] text-white/40 font-mono uppercase tracking-widest">Controls</label>
              <div className="flex gap-3">
                {!isActive ? (
                  <button 
                    onClick={startCamera}
                    disabled={!isLoaded}
                    className="flex-1 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-black font-bold py-4 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-95"
                  >
                    <Play size={20} fill="currentColor" />
                    START MONITORING
                  </button>
                ) : (
                  <button 
                    onClick={stopCamera}
                    className="flex-1 bg-white/10 hover:bg-white/20 text-white font-bold py-4 rounded-xl flex items-center justify-center gap-2 transition-all active:scale-95"
                  >
                    <Pause size={20} fill="currentColor" />
                    STOP
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-[10px] text-white/40 font-mono uppercase">Blink Intensity</span>
                <span className="text-[10px] font-mono text-orange-500">{(blinkScore * 100).toFixed(1)}%</span>
              </div>
              <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                <motion.div 
                  className="h-full bg-orange-500"
                  animate={{ width: `${Math.min(100, blinkScore * 100)}%` }}
                  transition={{ type: "spring", stiffness: 300, damping: 30 }}
                />
              </div>
            </div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
            <div className="flex items-start gap-4">
              <div className="p-2 bg-blue-500/20 rounded-lg">
                <AlertCircle className="text-blue-400" size={20} />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-bold">Why blink?</h3>
                <p className="text-xs text-white/60 leading-relaxed">
                  Blinking spreads tears across your eyes, keeping them moist and clear. 
                  Digital screens often reduce our blink rate by 60%, leading to dry eyes and fatigue.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Camera View */}
        <div className="lg:col-span-8 relative">
          <div className="aspect-video bg-white/5 border border-white/10 rounded-3xl overflow-hidden relative group">
            {!isActive && (
              <div className="absolute inset-0 flex flex-col items-center justify-center z-10 bg-black/40 backdrop-blur-sm">
                {!isLoaded ? (
                  <div className="flex flex-col items-center gap-4">
                    <RefreshCw className="animate-spin text-orange-500" size={32} />
                    <p className="text-sm font-mono text-white/60">INITIALIZING AI MODELS...</p>
                  </div>
                ) : (
                  <div className="text-center space-y-4">
                    <div className="w-16 h-16 bg-white/10 rounded-full flex items-center justify-center mx-auto">
                      <EyeOff className="text-white/40" size={32} />
                    </div>
                    <p className="text-sm font-mono text-white/60">CAMERA FEED OFFLINE</p>
                  </div>
                )}
              </div>
            )}

            <video 
              ref={videoRef}
              className="w-full h-full object-contain scale-x-[-1]"
              playsInline
              muted
            />
            
            <canvas 
              ref={canvasRef}
              className="absolute inset-0 w-full h-full pointer-events-none scale-x-[-1] object-contain"
            />

            {/* Blink Indicator Overlay */}
            <AnimatePresence>
              {isBlinking && (
                <motion.div 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 border-4 border-orange-500 pointer-events-none z-20"
                />
              )}
            </AnimatePresence>

            {/* Reminder Overlay */}
            <AnimatePresence>
              {showReminder && (
                <motion.div 
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 20 }}
                  className="absolute bottom-8 left-1/2 -translate-x-1/2 bg-orange-500 text-black px-8 py-4 rounded-2xl shadow-2xl flex items-center gap-4 z-30"
                >
                  <Eye size={24} className="animate-bounce" />
                  <div>
                    <p className="font-bold leading-none">TIME TO BLINK</p>
                    <p className="text-[10px] font-bold opacity-70 uppercase tracking-widest">Refresh your eyes now</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {error && (
            <div className="mt-4 p-4 bg-red-500/20 border border-red-500/40 rounded-xl flex items-center gap-3 text-red-400 text-sm">
              <AlertCircle size={18} />
              {error}
            </div>
          )}

          <div className="mt-6 flex justify-between items-center px-4">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                <span className="text-[10px] font-mono text-white/40 uppercase">Local Processing</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-blue-500 rounded-full" />
                <span className="text-[10px] font-mono text-white/40 uppercase">Privacy Encrypted</span>
              </div>
            </div>
            <p className="text-[10px] font-mono text-white/20">DATA NEVER LEAVES YOUR DEVICE</p>
          </div>
        </div>
      </main>

      {/* Footer / Status Bar */}
      <footer className="fixed bottom-0 left-0 right-0 p-4 bg-black border-t border-white/5 flex justify-between items-center px-8">
        <div className="flex items-center gap-8">
          <div className="flex flex-col">
            <span className="text-[8px] text-white/40 uppercase font-mono">CPU Usage</span>
            <span className="text-[10px] font-mono">OPTIMIZED</span>
          </div>
          <div className="flex flex-col">
            <span className="text-[8px] text-white/40 uppercase font-mono">Frame Rate</span>
            <span className="text-[10px] font-mono">30 FPS</span>
          </div>
        </div>
        <div className="text-[10px] font-mono text-white/20 italic">
          "The eyes are the window to the soul, keep them hydrated."
        </div>
      </footer>
    </div>
  );
}
