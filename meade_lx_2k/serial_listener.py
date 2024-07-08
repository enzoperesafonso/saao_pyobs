import serial
import time

# Adjust the serial port and baud rate to match your setup
SERIAL_PORT = 'COM3'  # ls /dev/tty.*  e.g., 'COM3' on Windows or '/dev/ttyUSB0' on Linux
BAUD_RATE = 9600

try:
    # Open the serial port
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE)
    print(f"Listening on {SERIAL_PORT} at {BAUD_RATE} baud rate.")
    
    while True:
        # Check if there is data waiting in the buffer
        if ser.in_waiting > 0:
            # Read the data from the serial port
            line = ser.readline().decode('utf-8').rstrip()
            # Print the received data to the terminal
            print(f"Received: {line}")

        # Sleep for a short period to avoid high CPU usage
        time.sleep(0.1)

except serial.SerialException as e:
    print(f"Error: {e}")
except KeyboardInterrupt:
    print("Program terminated by user.")
finally:
    # Close the serial port
    if ser.is_open:
        ser.close()
        print(f"Closed serial port {SERIAL_PORT}.")