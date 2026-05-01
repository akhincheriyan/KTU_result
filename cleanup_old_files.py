"""
Cleanup script to remove old temporary and analysis files
This will speed up the application by reducing the uploads folder size
"""
import os
import json
from datetime import datetime, timedelta

UPLOAD_FOLDER = 'uploads'
HISTORY_FILE = os.path.join(UPLOAD_FOLDER, 'history.json')

def cleanup_old_files():
    """Remove old files not referenced in history"""
    print("🧹 Starting cleanup...")
    
    # Load active files from history
    active_files = set()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                history = json.load(f)
                for entry in history:
                    if 'excel_filename' in entry:
                        active_files.add(entry['excel_filename'])
                        # Also keep the JSON stats file
                        json_file = entry['excel_filename'].replace('.xlsx', '.json')
                        active_files.add(json_file)
        except Exception as e:
            print(f"⚠️  Warning: Could not load history: {e}")
    
    # Also keep latest_*.xlsx and latest_*.json files
    for file in os.listdir(UPLOAD_FOLDER):
        if file.startswith('latest_'):
            active_files.add(file)
    
    # Add history.json itself
    active_files.add('history.json')
    
    print(f"📋 Found {len(active_files)} active files in history")
    
    # Remove old files
    removed_count = 0
    removed_size = 0
    
    for filename in os.listdir(UPLOAD_FOLDER):
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        # Skip directories
        if os.path.isdir(filepath):
            continue
        
        # If not in active files, remove it
        if filename not in active_files:
            try:
                file_size = os.path.getsize(filepath)
                os.remove(filepath)
                removed_count += 1
                removed_size += file_size
                print(f"🗑️  Removed: {filename}")
            except Exception as e:
                print(f"❌ Could not remove {filename}: {e}")
    
    # Convert size to MB
    removed_mb = removed_size / (1024 * 1024)
    
    print(f"\n✅ Cleanup complete!")
    print(f"📊 Removed {removed_count} old files")
    print(f"💾 Freed {removed_mb:.2f} MB of space")
    print(f"🚀 Your app should load faster now!")

if __name__ == "__main__":
    cleanup_old_files()
