#!/usr/bin/env python3
import pigpio
import time
import threading
import re
import numpy as np
import json
import socket
import os

# GPIO pins
RX_PIN = 16  # Connect to HC-05 TX
TX_PIN = 17  # Connect to HC-05 RX
BAUD_RATE = 38400  # For AT mode
BLUETOOTH_SENDER_SOCKET = '/tmp/bluetooth_sender.sock'

# Global variables
response_buffer = ""
scanning = False
scan_thread = None
iac = "9e8b33"
is_calibrating = False
sample_size = 100
collected_samples = []
calibration_result = 0  # rssi for when distance is 1m
mac_addr_to_calibrate = "2016:7:224034"
pi = None
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

def rssi_to_decimal(rssi):
     # Convert RSSI from hex 2's complement to decimal
    rssi_int = int(rssi, 16)
    
    # Apply 2's complement interpretation for values where the high bit is set
    if rssi_int & 0x8000:  # Check if the high bit is set (negative number)
        rssi_decimal = -((~rssi_int & 0xFFFF) + 1)  # 2's complement conversion
    else:
        rssi_decimal = rssi_int
    
    return rssi_decimal

def send_device_found(mac, device_class, rssi):
    try:
        # Convert RSSI to decimal
        rssi_decimal = rssi_to_decimal(rssi)
        
        # Prepare device data
        device_data = {
	    "subject": "beacon_detected",
            "mac": mac,
            "device_class": device_class,
            "rssi": rssi_decimal,
            "timestamp": time.time()
        }
        
        # Try to send via socket service
        if send_to_bluetooth(device_data):
            return True
        else:
            # Just log if sending fails
            print(f"DEVICE FOUND: MAC={mac}, Class={device_class}, RSSI={rssi_decimal} dBm")
            return False
    
    except Exception as e:
        print(f"Unexpected error in send_device_found: {e}")
        return False

def calibrate(rssi):
    global sample_size
    global collected_samples
    global calibration_result
    if (len(collected_samples) < sample_size):
        collected_samples.append(rssi)
    else:
        calibration_result = np.mean(np.array(collected_samples))
        collected_samples = []

def send_command(pi, command):
    """Send AT command using bit-banging serial"""
    full_command = command + "\r\n"
    
    # Initialize wave for transmission
    pi.wave_clear()
    pi.wave_add_serial(TX_PIN, BAUD_RATE, full_command.encode())
    wid = pi.wave_create()
    
    # Send the wave
    if wid >= 0:
        pi.wave_send_once(wid)
        # Wait for transmission to complete
        while pi.wave_tx_busy():
            time.sleep(0.1)
        pi.wave_delete(wid)
    
    # Wait for response
    time.sleep(0.5)

def read_responses(pi):
    """Thread to continuously read HC-05 responses"""
    global response_buffer
    global is_calibrating
    global calibration_result
    global mac_addr_to_calibrate
    # Open serial read on RX pin
    pi.bb_serial_read_open(RX_PIN, BAUD_RATE)
    
    try:
        while True:
            # Get any available data
            (count, data) = pi.bb_serial_read(RX_PIN)
            if count > 0:
                text = data.decode(errors='replace')
                print(text, end='', flush=True)
                
                response_buffer += text
                
                # Process complete lines
                if '\r' in response_buffer or '\n' in response_buffer:
                    lines = response_buffer.splitlines()
                    for line in lines:
                        if "+INQ:" in line:
                            # Process device found
                            # Format: +INQ:xxxx:xx:xxxxxx,device_class,rssi
                            match = re.search(r'\+INQ:([0-9A-F:]+),([0-9A-F]+),([0-9A-F]+)', line)
                            if match:
                                mac = match.group(1)
                                device_class = match.group(2)
                                rssi = match.group(3)
                                if is_calibrating and mac_addr_to_calibrate == mac:
                                    calibrate(rssi_to_decimal(rssi))
                                    if calibration_result:
                                        print(f"RSSI of beacon {mac} 1 meter away from the tag is is: {calibration_result}")
                                        calibration_result = 0
                                        stop_scanning()
                                        return
                                elif not is_calibrating:
                                    send_device_found(mac, device_class, rssi)
                    
                    # Keep only incomplete last line
                    if response_buffer.endswith('\r') or response_buffer.endswith('\n'):
                        response_buffer = ""
                    else:
                        lines = response_buffer.splitlines()
                        response_buffer = lines[-1] if lines else ""
            
            time.sleep(0.1)
    except Exception as e:
        print(f"Reader error: {e}")
    finally:
        pi.bb_serial_read_close(RX_PIN)

def continuous_scan(pi):
    """Continuously scan for Bluetooth devices"""
    global scanning
    
    try:
        while scanning:
            # Start inquiry
            send_command(pi, "AT+INQ")
            
            # Wait for inquiry to complete (based on timeout)
            time.sleep(6)  # Slightly longer than the inquiry timeout
    except Exception as e:
        print(f"Scan error: {e}")
    finally:
        print("Scanning stopped")

def start_scanning(pi):
    """Start the scanning process"""
    global scanning, scan_thread, iac
    
    if not scanning:
        scanning = True

        # Initialize Bluetooth
        send_command(pi, "AT+INIT")
        time.sleep(0.5)

        # set Inquery Access Code
        print(f"AT+IAC={iac}")
        send_command(pi, f"AT+IAC={iac}")
        time.sleep(0.5)

        # Set inquiry mode (1,9,5) - 1:Standard, 9:Max devices, 5:Timeout in seconds
        send_command(pi, "AT+INQM=1,9,5")
        time.sleep(0.5)

        scan_thread = threading.Thread(target=continuous_scan, args=(pi,), daemon=True)
        scan_thread.start()
        print("Continuous scanning started")
    else:
        print("Scanning already in progress")

def stop_scanning():
    """Stop the scanning process"""
    global scanning
    
    if scanning:
        scanning = False
        print("Stopping scan...")
        if scan_thread:
            scan_thread.join(timeout=10)
        print("Scan stopped")
    else:
        print("No active scan to stop")

def main():
    global pi, sender_socket
    # Connect to pigpio daemon
    pi = pigpio.pi()
    if not pi.connected:
        print("Failed to connect to pigpio daemon")
        return
    
    try:
        # Set up pins
        pi.set_mode(RX_PIN, pigpio.INPUT)
        pi.set_mode(TX_PIN, pigpio.OUTPUT)
        
        # Connect to the Bluetooth sender service
        connect_to_sender()
        
        # Start reader thread
        reader = threading.Thread(target=read_responses, args=(pi,), daemon=True)
        reader.start()
        
        # Start scanning
        start_scanning(pi)
        
        # Keep the main thread alive to continue scanning
        while True:
            time.sleep(10)
            # Try to reconnect to sender if needed
            if sender_socket is None:
                connect_to_sender()
    
    except KeyboardInterrupt:
        print("\nProgram terminated")
    
    finally:
        stop_scanning()
        if sender_socket:
            sender_socket.close()
        pi.stop()
        print("Connection closed")

if __name__ == "__main__":
    main()
