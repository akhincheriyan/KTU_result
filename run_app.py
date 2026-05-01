from flaskwebgui import FlaskUI
from app import app, db
import os
import json
from datetime import datetime, timedelta

def cleanup_temp_files():
    """Automatically clean up old temporary files on startup"""
    try:
        upload_folder = app.config['UPLOAD_FOLDER']
        
        # Load active files from history
        active_files = set(['history.json'])
        history_file = os.path.join(upload_folder, 'history.json')
        
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history = json.load(f)
                    for entry in history:
                        if 'excel_filename' in entry:
                            active_files.add(entry['excel_filename'])
                            json_file = entry['excel_filename'].replace('.xlsx', '.json')
                            active_files.add(json_file)
            except:
                pass
        
        # Keep latest_* files
        for file in os.listdir(upload_folder):
            if file.startswith('latest_'):
                active_files.add(file)
        
        # Remove old temporary PDFs and orphaned files
        cleaned = 0
        for filename in os.listdir(upload_folder):
            filepath = os.path.join(upload_folder, filename)
            
            if os.path.isdir(filepath):
                continue
            
            # Remove temp PDFs
            if filename.startswith('temp_') and filename.endswith('.pdf'):
                try:
                    os.remove(filepath)
                    cleaned += 1
                except:
                    pass
            # Remove orphaned files not in history
            elif filename not in active_files and not filename.startswith('.'):
                try:
                    # Only remove if older than 1 day
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if datetime.now() - file_time > timedelta(days=1):
                        os.remove(filepath)
                        cleaned += 1
                except:
                    pass
        
        if cleaned > 0:
            print(f"✨ Cleaned up {cleaned} old temporary files")
    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")

def start_app():
    # Initialize database and folders
    with app.app_context():
        db.create_all()
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Run automatic cleanup
    print("Running startup cleanup...")
    cleanup_temp_files()

    import threading
    import time

    def run_flask():
        # Disable the internal Flask reloader for threaded mode
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Give the server a moment to start up
    time.sleep(1.5)

    # Use FlaskUI only to open the browser window pointing to localhost:5000
    # This works regardless of library version
    ui = FlaskUI(
        server=None,
        width=1200,
        height=800,
        port=5000
    )

    # Override the default URL to ensure it hits our server
    ui.url = "http://127.0.0.1:5000"
    ui.run()

if __name__ == "__main__":
    start_app()
