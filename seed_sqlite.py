import sqlite3
import json

conn = sqlite3.connect('store_intelligence.db')
c = conn.cursor()

zones = [
    ('ENTRY_MAIN', 'Main Entrance', 'entry', 'CAM_01', json.dumps([{"x":0.0,"y":0.8},{"x":1.0,"y":0.8},{"x":1.0,"y":1.0},{"x":0.0,"y":1.0}]), 10),
    ('AISLE_A', 'Aisle A - Skincare', 'aisle', 'CAM_02', json.dumps([{"x":0.0,"y":0.5},{"x":0.5,"y":0.5},{"x":0.5,"y":0.8},{"x":0.0,"y":0.8}]), 15),
    ('AISLE_B', 'Aisle B - Makeup', 'aisle', 'CAM_03', json.dumps([{"x":0.5,"y":0.5},{"x":1.0,"y":0.5},{"x":1.0,"y":0.8},{"x":0.5,"y":0.8}]), 15),
    ('BEAUTY_BAR', 'Beauty Bar', 'beauty_bar', 'CAM_04', json.dumps([{"x":0.2,"y":0.2},{"x":0.8,"y":0.2},{"x":0.8,"y":0.5},{"x":0.2,"y":0.5}]), 8),
    ('CHECKOUT', 'Checkout Counter', 'checkout', 'CAM_05', json.dumps([{"x":0.0,"y":0.0},{"x":1.0,"y":0.0},{"x":1.0,"y":0.2},{"x":0.0,"y":0.2}]), 6),
    ('EXIT_MAIN', 'Main Exit', 'exit', 'CAM_01', json.dumps([{"x":0.0,"y":0.85},{"x":1.0,"y":0.85},{"x":1.0,"y":1.0},{"x":0.0,"y":1.0}]), 10)
]

c.executemany("INSERT OR IGNORE INTO zones (zone_id, name, zone_type, camera_id, polygon, capacity) VALUES (?, ?, ?, ?, ?, ?)", zones)

cameras = [
    ('CAM_01', 'Entrance Camera', 'Main Door', 'ENTRY_MAIN', '1920x1080', 25),
    ('CAM_02', 'Aisle A Camera', 'Skincare Aisle', 'AISLE_A', '1920x1080', 25),
    ('CAM_03', 'Aisle B Camera', 'Makeup Aisle', 'AISLE_B', '1920x1080', 25),
    ('CAM_04', 'Beauty Bar Camera', 'Beauty Station', 'BEAUTY_BAR', '1920x1080', 25),
    ('CAM_05', 'Checkout Camera', 'POS Counter', 'CHECKOUT', '1920x1080', 25)
]

c.executemany("INSERT OR IGNORE INTO cameras (camera_id, name, location, zone_id, resolution, fps) VALUES (?, ?, ?, ?, ?, ?)", cameras)

conn.commit()
conn.close()
