import dbus, dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import dbus.service
import json
import os.path
import logging
import datetime

BUS_NAME = "org.bluez"
AGENT_INTERFACE = "org.bluez.Agent1"
AGENT_PATH = "/test/agent"
CONFIG_FILE = "/etc/bluetooth/authorized_devices.json"
LOG_FILE = "/var/log/bluetooth-auto-pair.log"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()  # Also output to console
    ]
)
logger = logging.getLogger('bluetooth-agent')

class BluetoothAgent(dbus.service.Object):
    def __init__(self):
        # Get the system bus
        self.bus = dbus.SystemBus()
        
        # Load authorized addresses from config file
        self.authorized_addresses = self.load_authorized_addresses()
        logger.info(f"Authorized addresses: {self.authorized_addresses}")
        
        # Register the agent object on the bus
        dbus.service.Object.__init__(self, self.bus, AGENT_PATH)
        
        # Register the agent
        self.agent_manager = dbus.Interface(
            self.bus.get_object(BUS_NAME, "/org/bluez"),
            "org.bluez.AgentManager1"
        )
        self.agent_manager.RegisterAgent(AGENT_PATH, "NoInputNoOutput")
        self.agent_manager.RequestDefaultAgent(AGENT_PATH)
        
        logger.info("Bluetooth Auto-Pairing Agent Started...")

    def load_authorized_addresses(self):
        """Load authorized MAC addresses from config file"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    addresses = config.get('authorized_addresses', [])
                    
                    # Normalize all addresses to standardized format
                    normalized_addresses = [self.normalize_mac_address(addr) for addr in addresses]
                    return normalized_addresses
            else:
                logger.warning(f"Config file {CONFIG_FILE} not found. Using empty list.")
                # Create an empty config file as a template
                self.create_default_config()
                return []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading authorized addresses from config file: {e}")
            return []

    def create_default_config(self):
        """Create a default config file if it doesn't exist"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            
            default_config = {
                "authorized_addresses": [
                    "AA:BB:CC:DD:EE:FF",  # Example address
                    "11:22:33:44:55:66"   # Example address
                ]
            }
            
            with open(CONFIG_FILE, 'w') as f:
                json.dump(default_config, f, indent=4)
                
            logger.info(f"Created default config file at {CONFIG_FILE}")
        except IOError as e:
            logger.error(f"Error creating default config file: {e}")

    def normalize_mac_address(self, mac_address):
        """Normalize MAC address by removing colons and converting to uppercase"""
        # Remove colons if present
        mac = mac_address.replace(':', '').upper()
        
        # Remove leading zeros in each octet if MAC address is in XX:XX:XX format
        if ':' in mac_address:
            parts = mac_address.split(':')
            normalized_parts = [part.lstrip('0') or '0' for part in parts]  # Keep at least one '0' if all zeros
            return ':'.join(normalized_parts).upper()
        
        return mac

    def is_device_authorized(self, device_path):
        """Check if the device is in the authorized list"""
        try:
            # Get the device address
            device_obj = self.bus.get_object(BUS_NAME, device_path)
            device_props = dbus.Interface(device_obj, "org.freedesktop.DBus.Properties")
            device_addr = device_props.Get("org.bluez.Device1", "Address")
            
            # Normalize the device address
            normalized_addr = self.normalize_mac_address(device_addr)
            
            # Check if the device is in the authorized list
            authorized = normalized_addr in self.authorized_addresses or device_addr in self.authorized_addresses
            
            if authorized:
                logger.info(f"Device {device_addr} (normalized: {normalized_addr}) is authorized")
            else:
                logger.warning(f"Device {device_addr} (normalized: {normalized_addr}) is NOT authorized")
            
            return authorized
        except Exception as e:
            logger.error(f"Error checking device authorization: {e}")
            return False

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        logger.info(f"Authorizing service {uuid} for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting service authorization.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        # Automatically authorize all service requests
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        logger.info(f"Authorization requested for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting authorization request.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        # Automatically authorize all devices
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        logger.info(f"Pairing with PIN: {pincode} for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting pairing.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def DisplayPasskey(self, device, passkey):
        logger.info(f"Pairing with passkey: {passkey} for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting pairing.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        logger.info(f"Confirming passkey {passkey} for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting confirmation.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        # Auto-confirm all pairing requests
        return

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        logger.info(f"PIN code requested for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting PIN request.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        return "0000"  # Default PIN

    @dbus.service.method(AGENT_INTERFACE, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        logger.info(f"Passkey requested for device {device}")
        
        if not self.is_device_authorized(device):
            logger.warning(f"Device {device} not authorized. Rejecting passkey request.")
            raise dbus.DBusException(
                "org.bluez.Error.Rejected", "Device not authorized"
            )
        
        # Set device as trusted
        self.set_device_trusted(device)
        
        return 0000  # Default passkey

    @dbus.service.method(AGENT_INTERFACE, in_signature="", out_signature="")
    def Cancel(self):
        logger.info("Request canceled.")
        return
    
    def set_device_trusted(self, device_path):
        """Set the device as trusted"""
        try:
            device_props = dbus.Interface(
                self.bus.get_object(BUS_NAME, device_path),
                "org.freedesktop.DBus.Properties"
            )
            
            # Set the Trusted property to True
            device_props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))
            
            # Get device address for logging
            device_obj = self.bus.get_object(BUS_NAME, device_path)
            device_info_props = dbus.Interface(device_obj, "org.freedesktop.DBus.Properties")
            device_addr = device_info_props.Get("org.bluez.Device1", "Address")
            
            logger.info(f"Device {device_addr} is now trusted")
            
            # Alternative method using bluetoothctl (as a backup)
            subprocess.run(["bluetoothctl", "trust", device_addr])
            
        except Exception as e:
            logger.error(f"Error setting device as trusted: {e}")

if __name__ == "__main__":
    # Create log directory if it doesn't exist
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    # Log startup information
    logger.info("=" * 50)
    logger.info(f"Starting Bluetooth Auto-Pairing Agent at {datetime.datetime.now()}")
    logger.info("=" * 50)
    
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    agent = BluetoothAgent()
    loop = GLib.MainLoop()
    
    # Make sure devices are discoverable
    subprocess.run(["bluetoothctl", "discoverable", "on"])
    
    logger.info("Agent registered. Waiting for connections...")
    loop.run()
