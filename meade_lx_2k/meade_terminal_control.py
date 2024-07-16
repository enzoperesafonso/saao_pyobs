import serial
import threading
import time

# Define the serial port and baud rate
serial_port = "/dev/tty.usbserial-A7003N9w"  # Replace with serial port
baud_rate = 9600

# Open the serial port with the specified parameters
ser = serial.Serial(serial_port, baud_rate, timeout=1)

# Global variables
command_sent = False
command_response = None
command_event = threading.Event()


# Function to send a command to the serial port
def send_command(command):
    global command_sent, command_response
    ser.write((command + "\r\n").encode())
    print(f"Sent command: {command}")
    command_sent = True
    command_response = None


# Function to read from the serial port and set command_response
def read_serial():
    global command_sent, command_response
    while True:
        if ser.in_waiting > 0:
            try:
                received_data = ser.readline()
                print(f"Received (raw): {received_data}")
                received_data = received_data.decode("utf-8", errors="replace")
                print(f"Received (decoded): {received_data}")
                command_response = received_data
                command_event.set()
                return
            except Exception as e:
                print(f"Error decoding: {e}")


# Function to handle command timeouts
def handle_timeout():
    global command_sent
    print("Timeout occurred: No response received within 3 seconds.")
    command_sent = False


# Main loop to interact with the user
if __name__ == "__main__":
    print("Type commands to send over serial (Ctrl+C to exit):")
    try:
        while True:
            user_input = input("> ")
            send_command(user_input)
            command_event.clear()
            threading.Thread(target=read_serial).start()

            # Wait for response or timeout
            if command_event.wait(3):
                print(f"Response received: {command_response}")
            else:
                handle_timeout()

            # If no response or timeout, continue to next command
            command_sent = False
            command_response = None
            time.sleep(0.1)  # Small delay before accepting next input
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        ser.close()

    # Set Dec :Sd sDD*MM#     :Sd +15*38#     :Sd +30*00#
    # Set RA: :Sr HH:MM.T#    :Sr 10:38.0#    :Sr 08:53.0#
    # Goto set Ra Dec: :MS#
    # Cancel Slew: :Q#

    # Get Ra: :GR#
    # Get Dec: :GD#
    # Get Sidereal Time: :GS#
