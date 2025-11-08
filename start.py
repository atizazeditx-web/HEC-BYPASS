# start.py
import sys
import subprocess
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
# This is needed to get the PORT for logging
load_dotenv()
port = os.getenv("PORT", "1800")

print("--- [START.PY] ---")
print("Master Process Starter Initializing...")
print(f"Using Python executable: {sys.executable}")

# --- Start the app.py (Flask Server) ---
print(f"Starting Flask Server (app.py) on port {port}...")
app_process = subprocess.Popen(
    [sys.executable, "app.py"],
    stdout=sys.stdout, # Pipe output to main log
    stderr=sys.stderr  # Pipe errors to main log
)
print(f"Flask Server started with PID: {app_process.pid}")

# --- Start the rapidfire.py ---
print("Starting Rapidfire script (rapidfire.py)...")
rapidfire_process = subprocess.Popen(
    [sys.executable, "rapidfire.py"],
    stdout=sys.stdout, # Pipe output to main log
    stderr=sys.stderr  # Pipe errors to main log
)
print(f"Rapidfire script started with PID: {rapidfire_process.pid}")

print("--- [START.PY] ---")
print("Both processes are now running in parallel.")
print("Monitoring processes for crashes...")

try:
    # Monitor the processes. If one crashes, stop the other.
    while True:
        if app_process.poll() is not None:
            # app.py (Flask server) has crashed
            print("!!! ERROR: Flask Server (app.py) terminated unexpectedly.")
            print("Terminating rapidfire.py and shutting down container...")
            rapidfire_process.terminate()
            break # Exit loop to let container restart
            
        if rapidfire_process.poll() is not None:
            # rapidfire.py has crashed
            print("!!! ERROR: Rapidfire script (rapidfire.py) terminated unexpectedly.")
            print("Terminating Flask Server (app.py) and shutting down container...")
            app_process.terminate()
            break # Exit loop to let container restart
            
        # Both are running, sleep for a moment
        time.sleep(5)

except KeyboardInterrupt:
    # Handle manual stop (e.g., Ctrl+C)
    print("\n--- [START.PY] ---")
    print("Shutdown signal received. Terminating all processes...")
    app_process.terminate()
    rapidfire_process.terminate()
    
print("--- [START.PY] ---")
print("Main starter script exiting.")