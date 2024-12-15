import struct

def serialize_header(datagram_type, operation, sequence, user, payload_length):
    """
    Serializes the SIMP header.
    Args:
        datagram_type (int): Type of the datagram (1 byte).
        operation (int): Operation code (1 byte).
        sequence (int): Sequence number (1 byte).
        user (str): Username (32 bytes, ASCII encoded).
        payload_length (int): Length of the payload (4 bytes).

    Returns:
        bytes: Serialized header.
    """
    if len(user) > 32:
        raise ValueError("Username must be at most 32 characters long.")

    # Pad the username to 32 bytes
    user_padded = user.ljust(32, '\x00').encode('ascii')

    # Pack the header using struct
    header = struct.pack('!BBB32sI', datagram_type, operation, sequence, user_padded, payload_length)
    return header

def deserialize_header(header_bytes):
    """
    Deserializes the SIMP header.
    Args:
        header_bytes (bytes): Serialized header (40 bytes).

    Returns:
        dict: Dictionary with header fields.
    """
    if len(header_bytes) != 40:
        raise ValueError("Header must be exactly 40 bytes.")

    # Unpack the header using struct
    datagram_type, operation, sequence, user_padded, payload_length = struct.unpack('!BBB32sI', header_bytes)

    # Decode the username and strip padding
    user = user_padded.decode('ascii').rstrip('\x00')

    return {
        'type': datagram_type,
        'operation': operation,
        'sequence': sequence,
        'user': user,
        'payload_length': payload_length
    }

# Example usage
if __name__ == "__main__":
    # Create a header
    header = serialize_header(
        datagram_type=0x01,
        operation=0x02,
        sequence=0x00,
        user="TestUser",
        payload_length=100
    )

    print("Serialized Header:", header)

    # Deserialize the header
    parsed_header = deserialize_header(header)
    print("Parsed Header:", parsed_header)
