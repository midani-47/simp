
#client.py
import socket
import threading
from utils import SIMPDatagram

# Client setup
daemon_address = ('127.0.0.1', 7778)
client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_socket.bind(('127.0.0.1', 0))  # Bind to a random available port
client_socket.settimeout(10)  # Increased timeout to 10 seconds


# Connect to the daemon
def connect_to_daemon():
    try:
        client_socket.sendto("connect".encode(), daemon_address)
        response, _ = client_socket.recvfrom(1024)
        response_text = response.decode()
        
        if response_text == "USERNAME_REQUEST":
            username = input("Enter your username: ").strip()
            client_socket.sendto(username.encode(), daemon_address)
            
            # Wait for connection confirmation
            response, _ = client_socket.recvfrom(1024)
            print(f"Daemon response: {response.decode()}")
        else:
            print(f"Daemon response: {response_text}")
    except socket.timeout:
        print("Error: Timeout. No response from daemon.")

# Send a chat request
def chat_with_user():
    username = input("Enter the username of the user to chat with: ").strip()
    chat_request = f"chat {username}"
    try:
        client_socket.sendto(chat_request.encode(), daemon_address)
        response, _ = client_socket.recvfrom(1024)
        print(f"Daemon response: {response.decode()}")
    except socket.timeout:
        print("Error: Timeout. No response from daemon.")

# In client.py
def send_message():
    try:
        message = input("Enter your message: ").strip()
        if message:
            # Send message to daemon
            client_socket.sendto(f"message {message}".encode(), daemon_address)
            
            # Wait for daemon response
            response, _ = client_socket.recvfrom(1024)
            print(f"Daemon response: {response.decode()}")
        else:
            print("Message cannot be empty.")
    except Exception as e:
        print(f"Error sending message: {e}")

def receive_messages():
    """
    Background thread to receive messages during an active chat
    """
    while True:
        try:
            client_socket.settimeout(1)  # Non-blocking with short timeout
            data, _ = client_socket.recvfrom(1024)
            
            # Deserialize and display message
            try:
                datagram = SIMPDatagram.deserialize(data)
                if datagram.type == SIMPDatagram.TYPE_CHAT:
                    print(f"\nReceived message from {datagram.user}: {datagram.payload}")
                    print("> ", end='', flush=True)
            except Exception as e:
                print(f"Error processing received message: {e}")
        
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Error in message receiving: {e}")
            break

def main():
    connect_to_daemon()
    
    # Start message receiving thread
    receive_thread = threading.Thread(target=receive_messages, daemon=True)
    receive_thread.start()
    
    while True:
        command = input("Enter command (chat, message, quit): ").strip().lower()
        if command == "chat":
            chat_with_user()
        elif command == "message":
            send_message()
        elif command == "quit":
            print("Exiting client.")
            break
        else:
            print("Invalid command. Please enter 'chat', 'message', or 'quit'.")

# Main loop
def main():
    connect_to_daemon()
    while True:
        command = input("Enter command (chat, quit): ").strip().lower()
        if command == "chat":
            chat_with_user()
        elif command == "quit":
            print("Exiting client.")
            break
        else:
            print("Invalid command. Please enter 'chat' or 'quit'.")

if __name__ == "__main__":
    main()
