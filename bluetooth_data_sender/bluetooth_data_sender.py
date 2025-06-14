#!/usr/bin/env python3
import serial
import serial.tools.list_ports
import time
import json
import socket
import threading
import os
import sys
import signal

# Configuration
RFCOMM_PORT = '/dev/rfcomm0'
UNIX_SOCKET_PATH = '/tmp/bluetooth_sender.sock'
BUFFER_SIZE = 4096

# Global variables
ser = None
clients = []
exit_flag = False

def setup_serial_connection():
    """Establish serial connection to RFCOMM port"""
    global ser
    try:
        if is_rfcomm_available():
            if ser is None or not ser.is_open:
                ser = serial.Serial(RFCOMM_PORT, timeout=1)
                print(f"Connected to {RFCOMM_PORT}")
                return True
        else:
            print(f"{RFCOMM_PORT} not available")
            return False
    except Exception as e:
        print(f"Error connecting to {RFCOMM_PORT}: {e}")
        if ser and ser.is_open:
            ser.close()
        ser = None
        return False

def is_rfcomm_available():
    """Check if RFCOMM port is available"""
    ports = [port.device for port in serial.tools.list_ports.comports()]
    return RFCOMM_PORT in ports

def send_data(data):
    """Send data over RFCOMM"""
    global ser
    try:
        # Ensure there's a connection
        if ser is None or not ser.is_open:
            if not setup_serial_connection():
                print("Could not establish serial connection")
                return False
        
        # Send data
        if isinstance(data, str):
            data_bytes = data.encode()
        elif isinstance(data, bytes):
            data_bytes = data
        else:
            data_bytes = str(data).encode()
            
        # Ensure data ends with newline
        if not data_bytes.endswith(b'\n'):
            data_bytes += b'\n'
            
        ser.write(data_bytes)
        print(f"Sent data: {data_bytes.decode().strip()}")
        return True
    except Exception as e:
        print(f"Error sending data: {e}")
        # Reset connection
        if ser and ser.is_open:
            ser.close()
        ser = None
        return False

def cleanup():
    """Clean up resources"""
    global ser, clients, exit_flag
    exit_flag = True
    
    # Close socket connections
    for client in clients:
        try:
            client.close()
        except:
            pass
    clients = []
    
    # Close serial connection
    if ser and ser.is_open:
        ser.close()
        ser = None
    
    # Remove socket file
    if os.path.exists(UNIX_SOCKET_PATH):
        os.unlink(UNIX_SOCKET_PATH)
    
    print("Clean exit")

def handle_client(client_socket):
    """Handle communication with a client"""
    global clients, exit_flag
    clients.append(client_socket)
    
    try:
        while not exit_flag:
            data = client_socket.recv(BUFFER_SIZE)
            if not data:
                break
                
            # Process received data
            try:
                decoded_data = data.decode().strip()
                print(f"Received from client: {decoded_data}")
                success = send_data(decoded_data)
                
                # Send acknowledgment
                if success:
                    client_socket.send(b'ACK\n')
                else:
                    client_socket.send(b'NACK\n')
            except Exception as e:
                print(f"Error processing client data: {e}")
                client_socket.send(f"ERROR: {str(e)}\n".encode())
    except Exception as e:
        print(f"Client connection error: {e}")
    finally:
        try:
            client_socket.close()
        except:
            pass
        if client_socket in clients:
            clients.remove(client_socket)

def rfcomm_monitor():
    """Monitor RFCOMM connection status"""
    global ser, exit_flag
    
    while not exit_flag:
        if not is_rfcomm_available() or (ser and not ser.is_open):
            print("RFCOMM connection lost, trying to reconnect...")
            if ser and ser.is_open:
                ser.close()
            ser = None
            setup_serial_connection()
        time.sleep(5)

def main():
    global exit_flag
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, lambda sig, frame: cleanup())
    signal.signal(signal.SIGTERM, lambda sig, frame: cleanup())
    
    # Create the UNIX socket
    if os.path.exists(UNIX_SOCKET_PATH):
        os.unlink(UNIX_SOCKET_PATH)
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(UNIX_SOCKET_PATH)
    server.listen(5)
    os.chmod(UNIX_SOCKET_PATH, 0o777)  # Allow all users to connect
    
    print(f"Bluetooth data sender service started. Socket: {UNIX_SOCKET_PATH}")
    
    # Start RFCOMM monitor in a separate thread
    monitor_thread = threading.Thread(target=rfcomm_monitor, daemon=True)
    monitor_thread.start()
    
    # Initial connection attempt
    setup_serial_connection()
    
    try:
        # Set a timeout on the server socket so we can check exit_flag periodically
        server.settimeout(1.0)
        
        while not exit_flag:
            try:
                client_sock, _ = server.accept()
                client_thread = threading.Thread(target=handle_client, args=(client_sock,), daemon=True)
                client_thread.start()
            except socket.timeout:
                # This is expected due to the timeout we set
                pass
            except Exception as e:
                if not exit_flag:
                    print(f"Error accepting connection: {e}")
                    time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
        server.close()

if __name__ == "__main__":
    main()
