#utils.py
import struct
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Detailed logging for debugging
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('daemon_debug.log')  # Log to file for persistent debugging
    ]
)
logger = logging.getLogger(__name__)

class SIMPError(Exception):
    """Custom exception for SIMP protocol errors."""
    pass

def validate_ascii(text, max_length):
    """
    Validate and prepare text for ASCII encoding.
    
    Args:
        text (str): Input text to validate
        max_length (int): Maximum allowed length
    
    Returns:
        str: Validated and truncated text
    
    Raises:
        SIMPError: If text contains non-ASCII characters
    """
    try:
        # Truncate to max length
        text = text[:max_length]
        
        # Validate ASCII encoding
        text.encode('ascii')
        return text
    except UnicodeEncodeError:
        logger.error(f"Non-ASCII characters in input: {text}")
        raise SIMPError(f"Input must contain only ASCII characters (max {max_length} chars)")

class SIMPDatagram:
    """
    Represents a datagram in the Simple IMC Messaging Protocol (SIMP)
    """
    # Control Datagram Types
    TYPE_CONTROL = 0x01
    TYPE_CHAT = 0x02
    # Operation Codes for Control Datagrams
    OP_ERROR = 0x01
    OP_SYN = 0x02
    OP_SYN_ACK = 0x03  # Added SYN_ACK explicitly
    OP_ACK = 0x04
    OP_FIN = 0x08
    OP_USER_REGISTER = 0x09 

    def __init__(self, datagram_type, operation, sequence, user, payload=''):
        """
        Initialize a SIMP Datagram
        
        Args:
            datagram_type (int): Type of datagram (control or chat)
            operation (int): Operation code
            sequence (int): Sequence number (0 or 1)
            user (str): Username (max 32 chars)
            payload (str, optional): Message payload
        """
        self.type = datagram_type
        self.operation = operation
        self.sequence = sequence
        
        # Validate and prepare user
        self.user = validate_ascii(user, 32)
        
        # Validate and prepare payload
        self.payload = validate_ascii(payload, 1024) if payload else ''

    def serialize(self):
        """
        Serialize the SIMPDatagram into a binary format.
        """
        try:
            # Ensure user field is 32 bytes (padded with null bytes)
            user_bytes = self.user.encode('ascii')[:32].ljust(32, b'\x00')

            # Encode payload (max 1024 bytes)
            payload_bytes = self.payload.encode('ascii')[:1024]
            payload_length = len(payload_bytes)

            # Pack the header (39 bytes: 1+1+4+32+1 for reserved byte)
            header = struct.pack(
                '!BBI32sB',  # Format: Type (1), Operation (1), Sequence (4), User (32), Reserved (1)
                self.type,
                self.operation,
                self.sequence,
                user_bytes,
                0  # Reserved byte, set to 0
            )

            # Log detailed serialization information
            logger.debug(f"Serialized datagram: type={self.type}, operation={self.operation}, "
                        f"user='{self.user}', payload_length={payload_length}")

            # Combine header and payload
            return header + payload_bytes
        except Exception as e:
            logger.error(f"Serialization error: {e}")
            raise SIMPError(f"Failed to serialize datagram: {e}")

    @staticmethod
    def deserialize(data):
        """
        Deserialize binary data into a SIMPDatagram object.
        """
        try:
            if len(data) < 39:  # Ensure the data is at least 39 bytes long
                raise SIMPError(f"Incomplete datagram: expected at least 39 bytes, got {len(data)}")

            # Unpack the header (39 bytes: 1+1+4+32+1 for reserved byte)
            datagram_type, operation, sequence, user_bytes, _ = struct.unpack('!BBI32sB', data[:39])
            user = user_bytes.decode('ascii').strip('\x00')  # Remove padding

            # Extract the payload (remaining bytes)
            payload = data[39:].decode('ascii') if len(data) > 39 else ""

            # Log deserialization details
            logger.debug(f"Deserialized datagram: type={datagram_type}, operation={operation}, "
                        f"sequence={sequence}, user='{user}', payload='{payload}'")

            return SIMPDatagram(datagram_type, operation, sequence, user, payload)
        except Exception as e:
            logger.error(f"Deserialization error: {e}")
            raise SIMPError(f"Failed to deserialize datagram: {e}")
        
    def test_serialization():
        datagram = SIMPDatagram(1, 2, 3, "client1", "Hello, client2!")
        serialized = datagram.serialize()
        deserialized = SIMPDatagram.deserialize(serialized)

        assert datagram.type == deserialized.type
        assert datagram.operation == deserialized.operation
        assert datagram.sequence == deserialized.sequence
        assert datagram.user == deserialized.user
        assert datagram.payload == deserialized.payload

        logger.info("Serialization/Deserialization test passed.")


    def __repr__(self):
        """
        String representation for debugging
        """
        return (f"SIMPDatagram(type={hex(self.type)}, "
                f"operation={hex(self.operation)}, "
                f"sequence={self.sequence}, "
                f"user='{self.user}', "
                f"payload='{self.payload}')")