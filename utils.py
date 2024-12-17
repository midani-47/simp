import json
import logging
import socket
import base64

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SIMPError(Exception):
    """Custom exception for SIMP protocol errors."""
    pass

class SIMPDatagram:
    # Control Datagram Types
    TYPE_CONTROL = 0x01
    TYPE_CHAT = 0x02

    # Operation Codes for Control Datagrams
    OP_ERROR = 0x01
    OP_SYN = 0x02
    OP_SYN_ACK = 0x03
    OP_ACK = 0x04
    OP_FIN = 0x08

    def __init__(self, datagram_type, operation, sequence, user, payload=''):
        """
        Initialize a SIMP Datagram with JSON-based serialization
        """
        self.type = datagram_type
        self.operation = operation
        self.sequence = sequence
        self.user = user
        self.payload = payload

    def serialize(self):
        """
        Serialize the datagram to a JSON string and then to base64
        """
        try:
            # Create a dictionary representation of the datagram
            datagram_dict = {
                'type': self.type,
                'operation': self.operation,
                'sequence': self.sequence,
                'user': self.user,
                'payload': self.payload
            }
            
            # Convert to JSON string
            json_str = json.dumps(datagram_dict)
            
            # Encode to base64 for safe transmission
            return base64.b64encode(json_str.encode('utf-8'))
        
        except Exception as e:
            logger.error(f"Serialization error: {e}")
            raise SIMPError(f"Failed to serialize datagram: {e}")

    @staticmethod
    def deserialize(data):
        """
        Deserialize from base64 encoded JSON string
        """
        try:
            # Decode from base64
            json_str = base64.b64decode(data).decode('utf-8')
            
            # Parse JSON
            datagram_dict = json.loads(json_str)
            
            # Create and return SIMPDatagram
            return SIMPDatagram(
                datagram_type=datagram_dict['type'],
                operation=datagram_dict['operation'],
                sequence=datagram_dict['sequence'],
                user=datagram_dict['user'],
                payload=datagram_dict['payload']
            )
        
        except Exception as e:
            logger.error(f"Deserialization error: {e}")
            raise SIMPError(f"Failed to deserialize datagram: {e}")

    def __repr__(self):
        """
        String representation for debugging
        """
        return (f"SIMPDatagram(type={hex(self.type)}, "
                f"operation={hex(self.operation)}, "
                f"sequence={self.sequence}, "
                f"user='{self.user}', "
                f"payload='{self.payload}')")