import os
import socket
import json
import threading

SOCKET_PATH = '/tmp/cid_vault.sock'
VAULT = {
    'mattermost': 'MTc0N...secret_token_example',
    'irc': 'irc_pass_example',
}

class CIDDaemon:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        if os.path.exists(socket_path):
            os.remove(socket_path)

    def start(self):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        # Restrict access via filesystem permissions
        os.chmod(self.socket_path, 0o600) 
        server.listen(5)
        print(f"CID Daemon listening on {self.socket_path}")

        while True:
            conn, _ = server.accept()
            threading.Thread(target=self.handle_request, args=(conn,)).start()

    def handle_request(self, conn):
        try:
            data = conn.recv(1024).decode('utf-8')
            request = json.loads(data)
            
            if request.get('action') == 'get_credential':
                channel = request.get('channel')
                val = VAULT.get(channel, "ERROR: NOT_FOUND")
                response = {"status": "SUCCESS", "value": val} if val != "ERROR: NOT_FOUND" else {"status": "ERROR", "message": "NOT_FOUND"}
            else:
                response = {"status": "ERROR", "message": "UNKNOWN_ACTION"}
            
            conn.sendall(json.dumps(response).encode('utf-8'))
        except Exception as e:
            print(f"Daemon Error: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    import sys
    daemon = CIDDaemon(SOCKET_PATH)
    daemon.start()