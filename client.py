# client.py
import socket

DAEMON_IP = "127.0.0.1"
DAEMON_PORT = 7778  # Daemon's client communication port


class Client:
    def __init__(self, daemon_ip):
        self.daemon_ip = daemon_ip
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_request(self, message):
        """Send a request to the daemon and wait for a response."""
        try:
            print(f"Sending message to daemon at {self.daemon_ip}:{DAEMON_PORT}: {message}")
            self.socket.sendto(message.encode(), (self.daemon_ip, DAEMON_PORT))

            # Set a timeout for recvfrom to avoid blocking indefinitely
            self.socket.settimeout(3)  # 3-second timeout
            response, addr = self.socket.recvfrom(1024)  # Receive response
            print(f"Received response from daemon {addr}: {response.decode()}")
            return response.decode()
        except socket.timeout:
            print("Timeout: No response from daemon")
            return "Timeout"
        except Exception as e:
            print(f"Error during communication with daemon: {e}")
            return "Error"

    def start(self):
        """Start the client interface for interacting with the daemon."""
        print("Connecting to daemon...")
        
        # Send a simple connect request
        response = self.send_request("connect")
        print(f"Daemon response: {response}")

        while True:
            command = input("Enter command (chat, quit): ").strip().lower()

            if command == "chat":
                # Start a chat session
                ip = input("Enter IP address of the user to chat with: ").strip()
                response = self.send_request(f"chat {ip}")
                print(f"Daemon response: {response}")

                # Enter chat loop if the chat was initiated successfully
                if response == "Chat request sent":
                    print(f"Chat session initiated with {ip}. Waiting for response...")
                    # Here you might want to add more sophisticated waiting/handling
                    # Depending on the full protocol implementation

            elif command == "quit":
                # Quit the client
                response = self.send_request("quit")
                print(f"Daemon response: {response}")
                break

            else:
                print("Unknown command. Please use 'chat' or 'quit'.")

# Example usage
if __name__ == "__main__":
    client = Client(DAEMON_IP)
    client.start()