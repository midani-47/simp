# # utils.py

# import struct
# def serialize_header(datagram_type, operation, sequence, user, payload_length):
#     """
#     Serialize the header of a datagram into bytes.
#     - datagram_type: 1 byte
#     - operation: 1 byte
#     - sequence: 4 bytes (unsigned int)
#     - user: 32 bytes (padded/truncated ASCII)
#     - payload_length: 2 bytes (unsigned short)
#     """
#     user_encoded = user.encode('ascii')[:32]  # Truncate to 32 bytes
#     user_padded = user_encoded.ljust(32, b'\x00')  # Pad with null bytes
#     return struct.pack(
#         "!BBII32s",  # Changed to use I (4-byte int) for payload_length
#         datagram_type,
#         operation,
#         sequence,
#         payload_length,
#         user_padded
#     )

# def deserialize_header(header_bytes):
#     """
#     Deserialize a header from bytes.
#     Returns a dictionary with header fields.
#     """
#     datagram_type, operation, sequence, payload_length, user_padded = struct.unpack(
#         "!BBII32s", header_bytes
#     )
#     user = user_padded.decode('ascii').rstrip('\x00')
#     return {
#         'type': datagram_type,
#         'operation': operation,
#         'sequence': sequence,
#         'user': user,
#         'payload_length': payload_length
#     }

# class SIMPDatagram:
#     # Control Datagram Types
#     TYPE_CONTROL = 0x01
#     TYPE_CHAT = 0x02

#     # Operation Codes for Control Datagrams
#     OP_ERROR = 0x01
#     OP_SYN = 0x02
#     OP_ACK = 0x04
#     OP_FIN = 0x08

#     def __init__(self, datagram_type, operation, sequence, user, payload=''):
#         self.type = datagram_type
#         self.operation = operation
#         self.sequence = sequence
#         self.user = user
#         self.payload = payload

#     def serialize(self):
#         header = serialize_header(
#             datagram_type=self.type,
#             operation=self.operation,
#             sequence=self.sequence,
#             user=self.user,
#             payload_length=len(self.payload)  # This will now use a 4-byte int
#         )
#         return header + self.payload.encode('ascii')

#     @classmethod
#     def deserialize(cls, data):
#         header_bytes = data[:40]  # Updated to match new header size
#         header_info = deserialize_header(header_bytes)
#         payload_bytes = data[40:40+header_info['payload_length']]
#         payload = payload_bytes.decode('ascii')

#         return cls(
#             datagram_type=header_info['type'],
#             operation=header_info['operation'],
#             sequence=header_info['sequence'],
#             user=header_info['user'],
#             payload=payload
#         )


import struct
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')
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
        Serialize the entire datagram: header + payload
        
        Returns:
            bytes: Serialized datagram
        """
        try:
            # Encode user and payload
            user_bytes = self.user.encode('ascii').ljust(32, b'\x00')
            payload_bytes = self.payload.encode('ascii')
            
            # Pack header
            header = struct.pack(
                '!BBBI32sI',  # Updated format string
                self.type,        # Datagram type (1 byte)
                self.operation,   # Operation (1 byte)
                self.sequence,    # Sequence (1 byte)
                0,                # Reserved byte
                user_bytes,       # User (32 bytes)
                len(payload_bytes)  # Payload length (4 bytes)
            )
            
            return header + payload_bytes
        except Exception as e:
            logger.error(f"Serialization error: {e}")
            raise SIMPError(f"Failed to serialize datagram: {e}")

    @classmethod
    def deserialize(cls, data):
        """
        Deserialize a datagram from raw bytes
        
        Args:
            data (bytes): Raw datagram bytes
        
        Returns:
            SIMPDatagram: Deserialized datagram
        
        Raises:
            SIMPError: If deserialization fails
        """
        try:
            # Unpack header
            header_format = '!BBBI32sI'
            header_size = struct.calcsize(header_format)
            
            if len(data) < header_size:
                raise SIMPError("Incomplete datagram")
            
            datagram_type, operation, sequence, _, user_bytes, payload_length = struct.unpack(
                header_format, data[:header_size]
            )
            
            # Decode user (remove null padding)
            user = user_bytes.decode('ascii').rstrip('\x00')
            
            # Extract payload
            payload_start = header_size
            payload_end = payload_start + payload_length
            
            if len(data) < payload_end:
                raise SIMPError("Payload length exceeds datagram size")
            
            payload = data[payload_start:payload_end].decode('ascii') if payload_length > 0 else ''
            
            return cls(
                datagram_type=datagram_type,
                operation=operation,
                sequence=sequence,
                user=user,
                payload=payload
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