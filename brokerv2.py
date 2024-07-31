import paho.mqtt.client as mqtt_client  
import json  
import sqlite3  
import time  
import os  
from datetime import datetime  
import threading  
import logging  
from detect import generate_recognized_image  
from constants import *  

# Initialize global variables  
last_id = None  
date_format = None  

# Configure logging  
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  

# Function called when the client connects to the MQTT broker  
def on_connect(client, userdata, flags, rc):  
    global last_id, date_format  
    last_id = None  
    logging.info("Connected with result code " + str(rc))  
    client.subscribe(MQTT_TOPIC)  

# Function called when a message is received from the MQTT broker  
def on_message(client, userdata, msg):  
    global last_id, date_format  
    payload = msg.payload.decode()  
    try:  
        data = json.loads(payload)  
        event_id = data.get('before', {}).get('id', None)  
        if event_id and ('person' in data.get('before', {}).get('label', None)):  
            if event_id != last_id:  
                last_id = event_id  
                logging.info(f"{datetime.fromtimestamp(data['before']['frame_time'])}: Person detected!")  
                date_format = str(datetime.fromtimestamp(data['before']['frame_time']))  
                logging.info(f"Event_id: {event_id}")  
            else:  
                logging.info("Event is processing")  
            if data['type'] == 'end':  
                event_length = data['after']['end_time'] - data['after']['start_time']  
                logging.info("Event is finished.(%.1fs)" % event_length)  
                logging.info("Processing snapshots.")  
                thread = threading.Thread(target=process_event, args=(data['after'],))  
                thread.start()  
    except json.JSONDecodeError:  
        logging.error("Payload is not in JSON format")  

# Function to process the event and handle face recognition  
def process_event(event_data):  
    event_id = event_data['id']  
    path = os.path.join(CLIPS_PATH, f"GarageCamera-{event_id}-clean.png")  
    if wait_for_file_creation(path):  
        start_time = time.time()  
        recognized_name, out_image_path, video_path = generate_recognized_image(event_data, date_format)  
        logging.info(f"Processing event {event_id} finished in {time.time()-start_time} seconds. Recognized name: {recognized_name}")  

        start_time = time.time()  
        while True:  
            try:  
                with sqlite3.connect(FRIGATE_DB_PATH) as frigate_db_con:  
                    cursor = frigate_db_con.cursor()  
                    cursor.execute("SELECT id, label, camera, start_time, end_time, thumbnail FROM event WHERE id = ?", (event_id,))  
                    event_data = cursor.fetchone()  
                    if event_data and len(event_data) == 6:  
                        break  
            except sqlite3.Error as e:  
                logging.error(f"Error accessing Frigate database: {e}")  
            if time.time() - start_time > 30:  
                return  
            time.sleep(1)  

        if event_data and len(event_data) == 6:  
            start_time = time.time()  
            while True:  
                try:  
                    with sqlite3.connect(EVENTS_DB_PATH) as events_db_con:  
                        setup_database(events_db_con)  
                        cursor = events_db_con.cursor()  
                        cursor.execute(   
                            "INSERT OR REPLACE INTO event (id, label, camera, start_time, end_time, thumbnail, sub_label, snapshot_path, video_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",  
                            (event_data[0], event_data[1], event_data[2], event_data[3], event_data[4], event_data[5], recognized_name, out_image_path, video_path))   
                        events_db_con.commit()  
                        break  
                except sqlite3.Error as e:  
                    logging.error(f"Error accessing Events database: {e}")  
                if time.time() - start_time > 30:  
                    return  
                time.sleep(1)  
    else:  
        logging.error("File was not created in time.")  

# Enhanced function to wait for file creation and ensure it's ready to be read  
def wait_for_file_creation(file_path, timeout=10, check_interval=0.5):  
    start_time = time.time()  
    while time.time() - start_time < timeout:  
        if os.path.exists(file_path):  
            try:  
                with open(file_path, 'rb') as f:  
                    f.read()  
                return True  
            except IOError:  
                pass  
        time.sleep(check_interval)  
    logging.error(f"Timeout reached. File not found or not ready: {file_path}")  
    return False  

# Function to set up the database tables if they do not exist  
def setup_database(connection):  
    cursor = connection.cursor()  
    cursor.execute(EVENT_TABLE_SCHEMA)  
    connection.commit()  

if __name__ == "__main__":  
    client = mqtt_client.Client()  
    client.on_connect = on_connect  
    client.on_message = on_message  

    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)  
    client.connect(BROKER_HOST, BROKER_PORT, 60)  

    logging.info("Starting MQTT client loop")  
    client.loop_forever()
