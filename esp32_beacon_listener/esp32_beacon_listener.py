import serial
import time
import os
import socket
import json


PORT_CANDIDATES = ["/dev/ttyACM1"]
BAUD_RATE = 230400
RECONNECT_DELAY = 2  # seconds
BLUETOOTH_SENDER_SOCKET = '/tmp/bluetooth_sender.sock'


sender_socket = None

def connect_to_sender():
    """Connect to the Bluetooth data sender service"""
    global sender_socket
    try:
        if sender_socket is not None:
            try:
                sender_socket.close()
            except:
                pass
        
        sender_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sender_socket.connect(BLUETOOTH_SENDER_SOCKET)
        print("Connected to Bluetooth data sender service")
        return True
    except Exception as e:
        print(f"Failed to connect to Bluetooth data sender: {e}")
        sender_socket = None
        return False


def send_to_bluetooth(data):
    """Send data using the Bluetooth data sender service"""
    global sender_socket
    try:
        if sender_socket is None:
            if not connect_to_sender():
                print("Could not connect to Bluetooth data sender")
                return False
        
        # Convert dict to JSON if needed
        if isinstance(data, dict):
            data_str = json.dumps(data) + '\n'
        else:
            data_str = str(data)
            if not data_str.endswith('\n'):
                data_str += '\n'
        
        # Send the data
        sender_socket.send(data_str.encode())
        
        # Wait for acknowledgment
        response = sender_socket.recv(1024).decode().strip()
        if response == "ACK":
            print(f"Successfully sent: {data_str.strip()}")
            return True
        else:
            print(f"Failed to send data: {response}")
            return False
    except Exception as e:
        print(f"Error sending to Bluetooth service: {e}")
        sender_socket = None
        return False



def send_device_found(mac, device_name, rssi):
    try:
        # Convert RSSI to decimal
        rssi_decimal = rssi
        
        # Prepare device data
        device_data = {
            "subject": "beacon_detected",
            "mac": mac,
            "device_name": device_name,
            "rssi": rssi_decimal,
            "timestamp": time.time()
        }
        
        # Try to send via socket service
        if send_to_bluetooth(device_data):
            return True
        else:
            # Just log if sending fails
            print(f"DEVICE FOUND: MAC={mac}, Class={device_name}, RSSI={rssi_decimal} dBm")
            return False
    
    except Exception as e:
        print(f"Unexpected error in send_device_found: {e}")
        return False



def on_beacon_detected(mac, name, rssi):
    print(f"🔍 Beacon detected -> MAC: {mac}, Name: {name}, RSSI: {rssi}")
    send_device_found(mac, name, rssi)

def find_serial_port():
    """Try to find an available ESP32 serial port."""
    for port in PORT_CANDIDATES:
        if os.path.exists(port):
            try:
                ser = serial.Serial(port, BAUD_RATE, timeout=1)
                print(f"✅ Connected to {port}")
                return ser
            except serial.SerialException:
                pass
    return None

def listen_for_beacons():
    ser = None

    while True:
        if ser is None or not ser.is_open:
            print("🔌 Waiting for ESP32 connection...")
            while ser is None:
                ser = find_serial_port()
                if ser is None:
                    time.sleep(RECONNECT_DELAY)

        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue

            try:
                mac, name, rssi = line.split("|")
                on_beacon_detected(mac, name, int(rssi))
            except ValueError:
                print(f"⚠️ Invalid data: {line}")
        except (serial.SerialException, OSError) as e:
            print(f"❌ Serial error: {e}")
            try:
                ser.close()
            except:
                pass
            ser = None
            time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    try:
        listen_for_beacons()
    except KeyboardInterrupt:
        print("🛑 Stopped by user.")
