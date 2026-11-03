import bridge
DESCRIPTION = "Browser terminal channel"

def receive():
    return bridge.receive()

def send(message):
    bridge.send(str(message))
    return "sent"
