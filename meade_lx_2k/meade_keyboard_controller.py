import tkinter as tk
import serial

# Open the serial port with the specified parameters
# ser = serial.Serial('COM1', 9600, timeout=1)


def send_command(command):
    """Send a command to the serial port."""
    # ser.write(command.encode())
    print(f"Sent command to telescope: {command}")


def on_key_press(event):
    if event.keysym == "Escape":
        root.destroy()
    elif event.keysym == "Up":
        label.config(text="Slewing North ...", fg="red")
        send_command("#:Mn#")
    elif event.keysym == "Down":
        label.config(text="Slewing South ...", fg="red")
        send_command("#:Ms#")
    elif event.keysym == "Left":
        label.config(text="Slewing West ...", fg="red")
        send_command("#:Mw#")
    elif event.keysym == "Right":
        label.config(text="Slewing East ...", fg="red")
        send_command("#:Me#")
    elif event.keysym == "space":
        label.config(text="STOPPED SLEW !!!", fg="red")
        send_command("#:Q#")
    elif event.keysym == "2":
        label.config(text="Set Slew Rate to 2 degrees/second", fg="orange")
        send_command("#:Sw 2#")
    elif event.keysym == "3":
        label.config(text="Set Slew Rate to 3 degrees/second", fg="orange")
        send_command("#:Sw 3#")
    elif event.keysym == "4":
        label.config(text="Set Slew Rate to 4 degrees/second", fg="orange")
        send_command("#:Sw 4#")
    elif event.keysym == "h":
        label.config(text="Sending Telescope Home ...", fg="purple")
    else:
        label.config(text=f"Key {event.keysym} pressed", fg="black")

    # Reset the idle timer
    reset_idle_timer()


def reset_idle_timer():
    # Cancel the previous timer
    global idle_timer
    if idle_timer:
        root.after_cancel(idle_timer)
    # Start a new timer to update the label after 5 seconds
    idle_timer = root.after(500, show_tracking_message)


def show_tracking_message():
    label.config(text="Tracking at Sidereal Rate ...", fg="green")


# Create the main window
root = tk.Tk()
root.title("Meade LX 2k Keyboard Controller")

# Create a label to display the key press information
label = tk.Label(root, text="Move the Meade :)", font=("Helvetica", 24))
label.pack(pady=20)

# Initialize the idle timer
idle_timer = None

# Bind the key press event to the handler
root.bind("<KeyPress>", on_key_press)

# Start the main event loop
root.mainloop()
