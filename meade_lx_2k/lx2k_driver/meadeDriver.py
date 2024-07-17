import serial
import threading
from astroplan import Observer
from astropy import units as u
from astropy.coordinates import SkyCoord, Longitude
from astropy.time import Time
from LX2000_COMMAND_SET import MEADE_COMMAND_SET


class MeadeTelescope:
    def __init__(self, port: str, observer: Observer):
        self.observer = observer
        self.port = port
        self._serial_port = None
        self._command_lock = threading.Lock()
        self._moving_lock = threading.Lock()
        self._abort_move = threading.Event()

    def connect_telescope(self):
        try:
            self._serial_port = serial.Serial(port=self.port, baudrate=9600, timeout=1)
            print(f"Connected to telescope on {self.port}")
        except serial.SerialException as e:
            print(f"Failed to connect to telescope: {e}")

    def send_command_to_telescope(
        self, command: str, parameters: str, parse_parameters=True
    ): 

        if parse_parameters:
            if command not in MEADE_COMMAND_SET:
                print(f"Unknown Command: {command}")
                return None

            if MEADE_COMMAND_SET[command]["command"] is not None:
                command_string = MEADE_COMMAND_SET[command]["command"]
                +MEADE_COMMAND_SET[command]["parameter"].format(*parse_parameters)
            else:
                command_string = command

        self._serial_port(command_string)

        if MEADE_COMMAND_SET[command]["return"] is not None:
            res = ""
            while True:
                byte = self._serial_port.read(1)  # Read one byte from serial
                if byte == b"#":  # Stop reading when '#' is encountered
                    break
                if byte:
                    res += byte.decode(
                        "utf-8"
                    )  # Append byte to result string (assuming UTF-8 encoding)
            response = (
                res.strip()
            )  # Return accumulated text, stripping any leading/trailing whitespace
        else:
            response = None

        return response

    def set_telescope_site_coordinates():
        
        pass

    def get_telescope_site_coordinates():
        pass

    def set_telescope_local_time_and_date():
        pass

    def get_telescope_local_time_and_date():
        pass

    def get_telescope_gmt_offset():
        pass

    def set_telescope_gmt_offset():
        pass

    def start_telescope_motion_in_direction():
        pass

    def stop_telescope_motion_in_direction():
        pass

    def slew_telescope_to_target_ra_dec():
        pass

    def abort_slew_to_target_ra_dec():
        pass

    def set_telescope_motion_rate():
        pass

    def set_telescope_maximum_slew_rate():
        pass

    def set_telescope_alignment_type():
        pass
