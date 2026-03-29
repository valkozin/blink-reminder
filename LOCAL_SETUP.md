# Local Web Setup 🌐

To run the web version of **Blink Reminder** on your local machine, follow these steps.

## Prerequisites

- **Node.js**: You need Node.js installed (version 18 or higher is recommended).
  - Download it from [nodejs.org](https://nodejs.org/).

## Installation

1. **Download the source code**:
   Download the files from this project into a folder on your computer.

2. **Open a terminal**:
   Navigate to the project folder:
   ```bash
   cd path/to/blink-reminder
   ```

3. **Install dependencies**:
   Run the following command to install all required packages (React, MediaPipe, Tailwind, etc.):
   ```bash
   npm install
   ```

## Running the App

1. **Start the development server**:
   ```bash
   npm run dev
   ```

2. **Open your browser**:
   The terminal will show a URL (usually `http://localhost:5173`). Open this link in your browser.

3. **Grant Camera Permissions**:
   When prompted, allow the browser to access your camera so the AI can track your blinks.

## Building for Production

If you want to create a fast, optimized version of the app to host on a website:
```bash
npm run build
```
The production-ready files will be in the `dist/` folder.

## Troubleshooting

- **Camera not working**: Ensure no other application (like Zoom or Teams) is using your camera.
- **MediaPipe errors**: Make sure you have a stable internet connection the first time you run the app, as it needs to download the AI models (about 5MB).
