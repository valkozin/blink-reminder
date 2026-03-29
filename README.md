# Blink Reminder 👁️

A lightweight, privacy-focused Python tool that monitors your blink rate via webcam and sends system notifications to remind you to blink. Designed to prevent digital eye strain (Computer Vision Syndrome).

## Features
- **Real-time Monitoring**: Uses MediaPipe Face Mesh for high-accuracy eye tracking.
- **Privacy-First**: All processing is done locally on your machine. No data is sent to the cloud.
- **Cross-Platform**: Works on Windows, macOS, and Linux.
- **Customizable**: Adjust sensitivity and reminder intervals via command-line arguments.
- **Lightweight**: Optimized to run in the background with minimal CPU usage.

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/blink-reminder.git
   cd blink-reminder
   ```

2. **Install dependencies**:
   It is recommended to use a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Usage

Run the script with default settings:
```bash
python blink_reminder.py
```

### Custom Settings
You can customize the detection threshold and reminder interval:
```bash
# Set reminder to trigger after 15 seconds of no blinking
# Set sensitivity to 0.25 (higher is more sensitive)
python blink_reminder.py --interval 15 --threshold 0.25
```

### Background Mode
To run without the camera preview window:
```bash
python blink_reminder.py --no-preview
```

## How it Works
The app calculates the **Eye Aspect Ratio (EAR)**. When the EAR drops below a certain threshold, it registers a blink. If the time between blinks exceeds your set interval, it triggers a system notification using the `plyer` library.

## Troubleshooting

### `AttributeError: module 'mediapipe.python.solutions' has no attribute 'face_mesh'`
This is a common issue on Windows when MediaPipe is not installed correctly or there is a version conflict. To fix it:
1.  **Uninstall existing packages**:
    ```bash
    pip uninstall mediapipe protobuf -y
    ```
2.  **Install a stable version**:
    ```bash
    pip install mediapipe==0.10.11 plyer opencv-python numpy
    ```
3.  **Check your Python version**: MediaPipe works best on Python 3.8 to 3.11. If you are using 3.12+, you may need to wait for a more stable release or use a virtual environment with 3.11.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
