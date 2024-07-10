from __future__ import annotations
import asyncio
import logging
from typing import Tuple, List, Dict, Any, TYPE_CHECKING, Optional
from astropy.coordinates import SkyCoord
import astropy.units as u

from pyobs.events import FilterChangedEvent, OffsetsRaDecEvent
from pyobs.interfaces import IFocuser, IFitsHeaderBefore, IFilters, ITemperatures, IOffsetsRaDec
from pyobs.mixins.fitsnamespace import FitsNamespaceMixin
from pyobs.modules.telescope.basetelescope import BaseTelescope
from pyobs.modules import timeout
from pyobs.utils.enums import MotionStatus
from pyobs.utils.threads import LockWithAbort
from pyobs.utils.time import Time

### piggyback imports ###
from astropy.coordinates import EarthLocation
from astropy.time import Time
from datetime import datetime, timezone
import serial
import numpy as np
#import os ### might come handy again
import timeit
import json
import sys
#from threading import Lock, Event ### OLD VERSION FOR MULTIPROCESSING ###


log = logging.getLogger(__name__)


class piggyBackTelescope(BaseTelescope, FitsNamespaceMixin):
    """A dummy telescope for testing."""

    ### Variables ###
    park_mot1 = 90.0
    park_mot2 = 90.0

    ### RS232 ###
    #rs232_timeout = 0.05 # worked in windows, but seems to fast now
    rs232_timeout = 0.25
    #USB_HUB = "COM3" # windows
    USB_HUB = "/dev/ttyUSB0" # linux
    rs232_init = False

    tracking_rate_mot1 = 0.0
    tracking_rate_mot2 = 0.0
    
    az = 0.0
    alt = 0.0
    ra = 0.0
    dec = 0.0
    mot1 = 90.0
    mot2 = 90.0
    
    motion_level = 0
    
    ### Decision tree ###
    GOTO_IN_STOP = False
    GOTO_RUNNING = False
    RUNNING = True
    RS232_QUEUE = []
    identity = 0

    ##### Start Config #####
    START_CONFIG_COMMANDS = "/home/pyobs/Master/Piggyback-Telescope/TelescopeClasses/SetupFiles/InitTelescopeFile.json" #commands stored in json file

    ##### Quick Align #####
    QUICK_ALIGN_COMMANDS = "/home/pyobs/Master/Piggyback-Telescope/TelescopeClasses/SetupFiles/QuickAlignFile.json" #commands stored in json file
    
    ##### Motion ######
    MOTION_MOT1_s = "500210" # start of the command
    MOTION_MOT1_e = "000000" # end of the command
    MOTION_MOT2_s = "500211" # start of the command
    MOTION_MOT2_e = "000000" # end of the command
    
    ##### GOTO #####
    RA_GOTO_RUN = "5001101300000001"
    DEC_GOTO_RUN = "5001111300000001"
    GOTO_MOT1_SLOW = "50041017"
    GOTO_MOT1_FAST = "50041002"
    GOTO_MOT2_SLOW = "50041117"
    GOTO_MOT2_FAST = "50041102"
    GOTO_STOP = "4d"
    
    ##### TRACKING #####
    POS_MOT1_TRACKING = "50031006"
    NEG_MOT1_TRACKING = "50031007"
    POS_MOT2_TRACKING = "50031106"
    NEG_MOT2_TRACKING = "50031107"
    TRACKING_END_SEQUENCE = "0000"
    TRACKING_STOP = "0000"
    
    ##### FEEDBACK #####
    GET_MOT1_COMMAND = "5001100100000003"
    GET_MOT2_COMMAND = "5001110100000003"
    
    __module__ = "pyobs.modules.telescope"

    def __init__(self, USB_HUB = '/dev/ttyUSB0', latitude = (51, 32, 3.95), longitude = (9, 55, 56.21), height = 200, **kwargs: Any):
        """Creates a new dummy telescope.

        Args:
            world: Optional SimWorld object.
        """
        BaseTelescope.__init__(self, **kwargs, motion_status_interfaces=["ITelescope", "IFocuser", "IFilters"])
        FitsNamespaceMixin.__init__(self, **kwargs)
        
        ### initiate telescope parameter ###
        self.latitude = latitude
        self.longitude = longitude
        self.height = height
        self.observing_location = EarthLocation(lat = self.angleToDecimal(self.latitude) * u.deg, lon = self.angleToDecimal(self.longitude) * u.deg, height = self.height)
        #self.time_now = datetime.now(datetime.UTC) ### TODO should update to this everywhere, also deprecated in other pyobs code parts 
        self.time_now = datetime.utcnow()
        self.USB_HUB = USB_HUB

        # init RS232-Connection with the piggyback telescope
        #await self.init(USB_HUB)

        # automatically send status updates
        # init world and get telescope
        from pyobs.utils.simulation import SimWorld

        self._world =  self.add_child_object(SimWorld)
        self._telescope = self._world.telescope

        self._telescope.status_callback = self._change_motion_status

        # stuff
        self._lock_RS232_comm = asyncio.Lock()
        self._event_RS232_comm = asyncio.Event()

    async def open(self) -> None:
        """Open module."""
        await BaseTelescope.open(self)

        # subscribe to events
        if self.comm:
            await self.comm.register_event(FilterChangedEvent)
            await self.comm.register_event(OffsetsRaDecEvent)

        # init status
        await self._change_motion_status(MotionStatus.PARKED)

    ### TODO calculate mot1 and mot2
    ### TODO is RA given in degrees or in hour
    ### TODO change tracking after uses of ra dec or alt az
    async def _move_radec(self, ra: float, dec: float, abort_event: asyncio.Event) -> None:
        """Actually starts tracking on given coordinates. Must be implemented by derived classes.

        Args:
            ra: RA in deg to track.
            dec: Dec in deg to track.
            abort_event: Event that gets triggered when movement should be aborted.

        Raises:
            MoveError: If telescope cannot be moved.
        """
        
        await self._change_motion_status(MotionStatus.SLEWING)
        self.GOTO_RUNNING = True    
        ra = (ra / 15) % 24.0 # because intern pyobs uses degrees, and this uses hour angles ... >:
            
        self.ra = ra
        self.dec = dec
        
        #self.time_now = datetime.now(datetime.UTC)
        self.time_now = datetime.utcnow()
        observation_time = Time(self.time_now, scale='utc', location=self.observing_location)
        lst = observation_time.sidereal_time(kind = "apparent", longitude = self.angleToDecimal(self.longitude) * u.deg)
        lst = lst.hour
        tau = self.HourAngle(lst, ra)
        sign = np.sign(tau)
    
        if sign >= 0:
            mot2 = 180 - dec
        else:
            mot2 = dec     
        mot2 = mot2 % 360
        
        if sign >= 0:
            mot1 = tau
        else:
            mot1 = tau%180
        
        # start slewing
        await self.__move(mot1, mot2, abort_event)

    ### TODO calculate mot1 and mot2
    async def _move_altaz(self, alt: float, az: float, abort_event: asyncio.Event) -> None:
        """Actually moves to given coordinates. Must be implemented by derived classes.

        Args:
            alt: Alt in deg to move to.
            az: Az in deg to move to.
            abort_event: Event that gets triggered when movement should be aborted.

        Raises:
            MoveError: If telescope cannot be moved.
        """

        await self._change_motion_status(MotionStatus.SLEWING)
        self.GOTO_RUNNING = True 
        self.az = az
        self.alt = alt
        ##############################
        # alt/az coordinates to ra/dec
        coords = SkyCoord(
            alt=alt * u.degree, az=az * u.degree, obstime=Time.now(), location=self.location, frame="altaz"
        )
        icrs = coords.icrs
        ##############################
        ##############################
           
        ra = icrs.ra.degree
        dec = icrs.dec.degree
        
        await self._move_radec(ra, dec, abort_event)
            
        
    async def __move(self, mot1: float, mot2: float, abort_event: asyncio.Event) -> None:
        """Simulate move.

        Args:
            mot1: represents hour angle, deg from start position.
            mot2: represents declination, deg from start position.
            abort_event: Event that gets triggered when movement should be aborted.
        """
        log.info("Motor1 goes to: {} and Motor2 goes to: {}".format(mot1, mot2))
        log.info("Telescope is SLEWING to position...")
        await self._change_motion_status(MotionStatus.SLEWING)
        
        self.GOTO_RUNNING = True
        self.GOTO_IN_STOP = False
        mot2_fast = self.GOTO_MOT2(mot2, True)
        mot2_slow = self.GOTO_MOT2(mot2, False)
    
        mot1_fast = self.GOTO_MOT1(mot1, True)
        mot1_slow = self.GOTO_MOT1(mot1, False)
    
        data = await self.RS232_Talk(mot2_fast) # represent declination
        log.info(data)
    
        data = await self.RS232_Talk(mot1_fast) # represents right ascension
        log.info(data)
    
        test = False
        ra_running = False
        dec_running = False
        while test is False and abort_event.is_set() is False:
            
            if ra_running is False:
                data = await self.RS232_Talk(self.RA_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                #print("Stop Bits RA ", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    #print("Stopped RA fast")
                    ra_running = True
                else:
                    ra_running = False
            
            if dec_running is False:
                data = await self.RS232_Talk(self.DEC_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                #print("Stop Bits DEC ", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    #print("Stopped DEC fast")
                    dec_running = True
                else:
                    dec_running = False
            
            if dec_running and ra_running:
                test = True
                
        data = await self.RS232_Talk(mot2_slow) # represent declination
        log.info(data)
    
        data = await self.RS232_Talk(mot1_slow) # represents right ascension
        log.info(data)
    
        test = False
        ra_running = False
        dec_running = False
        while test is False and abort_event.is_set() is False:
            
            if ra_running is False:
                data = await self.RS232_Talk(self.RA_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                #print("Stop Bits DEC RA", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    #print("Stopped RA slow")
                    ra_running = True
                else:
                    ra_running = False
            
            if dec_running is False:
                data = await self.RS232_Talk(self.DEC_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                #print("Stop Bits DEC", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    dec_running = True
                    #print("Stopped DEC slow")
                else:
                    dec_running = False
            
            if dec_running and ra_running:
                test = True

        #print(self.GET_RA())
        #print(self.GET_DEC())
        self.GOTO_RUNNING = False
        await self._change_motion_status(MotionStatus.POSITIONED)
        log.info("Telescope is positioned at wished coordinate...")
            
            
    def encodeAngle(self, alpha: float):
        '''
            Encode a motor angle into a Hexadecimal number combination for communication purposes.
        '''
        alpha = alpha % 360
        integer = int((alpha/360) * 2**24)
        b = bin(integer)
        length = len(b[2:])
        add = 24 - length
        b = b[:2] + add*"0" + b[2:]
        b1 = b[2:10]
        b2 = b[10:18]
        b3 = b[18:26]
        b1 = int(b1, 2)
        b2 = int(b2, 2)
        b3 = int(b3, 2)
        h1 = hex(b1)[2:]
        h2 = hex(b2)[2:]
        h3 = hex(b3)[2:]
        if len(h1) < 2:
            h1 = "0" + h1
        if len(h2) < 2:
            h2 = "0" + h2
        if len(h3) < 2:
            h3 = "0" + h3
            
        return h1, h2, h3
    
    
    def decodeAngle(self, h1, h2, h3) -> float:
        '''
            Decode a Hexadecimal number combination of an angle from communication read.
        '''
        v1 = int(h1, 16)
        v2 = int(h2, 16)
        v3 = int(h3, 16)
        integer = 2**16 * v1 + 2**8 * v2 + v3
        angle = (integer/2**24) * 360 
        return angle
    
    
    ### Motor 1 represents RA und Azi ###
    def GOTO_MOT1(self, alpha: float, fast = True) -> str:
        '''
            Create command to move telescope to a given motor1 angle alpha.
            Set True for fast actuation. Set False for accurate actuation.
        '''
        h1, h2, h3 = self.encodeAngle(alpha)
        if fast is True:
            mot1 = self.GOTO_MOT1_FAST # fast
        else:
            mot1 = self.GOTO_MOT1_SLOW # slow
        mot1 += h1+h2+h3+"00"
        return mot1 
    
    
    ### Motor 2 represents DEC and Alt ###
    def GOTO_MOT2(self, alpha: float, fast = True) -> str:
        '''
            Create command to move telescope to a given motor2 angle alpha.
            Set True for fast actuation. Set False for accurate actuation.
        '''
        h1, h2, h3 = self.encodeAngle(alpha)
        if fast is True:
            mot2 = self.GOTO_MOT2_FAST # fast
        else:
            mot2 = self.GOTO_MOT2_SLOW # slow 
        mot2 += h1+h2+h3+"00"
        return mot2 
    

    ### TODO how will this work with the gui ?
    async def MOTION_MOT1(self, level = None) -> None:
        '''
            Set motor2 motion to a given angular speed level.
            Speed given as a integer from -9 until 9.
        '''
        if level is None:
            level = self.motion_level
        sign = np.sign(level)
        if sign >= 0:
            direction = "24"
        else:
            direction = "25"
        speed = "0" + str(np.abs(level))
        command = self.MOTION_MOT1_s + direction + speed + self.MOTION_MOT1_e
        data = await self.RS232_Talk(command)
        log.info(data)
        

    ### TODO how will this work with the gui ???  
    async def MOTION_MOT2(self, level = None) -> None:
        '''
            Set motor1 motion to a given angular speed level.
            Speed given as a integer from -9 until 9.
        '''
        if level is None:
            level = self.motion_level
        sign = np.sign(level)
        if sign >= 0:
            direction = "24"
        else:
            direction = "25"
        speed = "0" + str(np.abs(level))
        command = self.MOTION_MOT2_s + direction + speed + self.MOTION_MOT2_e
        data = await self.RS232_Talk(command)
        log.info(data)
            
            
    ### TODO Fix Errors, forcing long delays gave weird results (is this even still a problem ? might have fixed that with latest changes)
    ### TODO maybe convert everything into asyncio serial (RS232 Read and Write) ... 
    ### TODO Can the Event queue cause an deadlock ? ...maybe add a generel safety reset function for the telescope ...  
    ### TODO maybe solveable by using only lock acquire
    async def RS232_Talk(self, command: str, **kwargs: Any) -> str: 
        
        s = bytes.fromhex(command)
        
        ### go into sending and reading Queue ###
        #self.lock.acquire() # multithreading version
        await self._lock_RS232_comm.acquire() # asyncio version
        #print("Got lock")
        try:
            self.identity = (self.identity + 1) % 10000
            my_id = self.identity
            self.RS232_QUEUE.append(my_id)
            log.info("Length of RS232 QUEUE: {}".format(len(self.RS232_QUEUE)))
            
        except:
            log.error("SOME RESOURCE ACCESS ERROR OCURRED!")
            await self._change_motion_status(MotionStatus.ERROR)
        finally:
            #print("release Lock")
            #self.lock.release() # multithreading version
            self._lock_RS232_comm.release() # asyncio version

        self._event_RS232_comm.clear()

        ### WAIT UNTIL ID TURN IN RS232 COMMUNICATION QUEUE ###
        while self.RS232_QUEUE.index(my_id) != 0:
            #self.event.clear() # multithreading version
            #print("waiting for Event")
            #self.event.wait() # multithreading version
            await self._event_RS232_comm.wait()
            await asyncio.sleep(0.05) ## make sure every instance got the event, before setting it to zero again
            self._event_RS232_comm.clear()
            #print("Event happened, keep looping")
        
        ### READ AND WRITE ###
        self.ser.write(s)
        data = self.ser.readline()
        #self.lock.acquire() # multithreading version
        await self._lock_RS232_comm.acquire() # asyncio version
        try:
            self.RS232_QUEUE.pop(0)
        except:
            log.error("SOME RESOURCE ACCESS ERROR OCURRED!")
            await self._change_motion_status(MotionStatus.ERROR)
        finally:
            #self.lock.release() # multithreading version
            self._lock_RS232_comm.release() # asyncio version

        ### SET EVENT FOR THE NEXT ELEMENT IN THE QUEUE ###
        self._event_RS232_comm.set()
        return data


    @timeout(60)
    async def init(self, **kwargs: Any) -> None:
        """Initialize telescope.

        Raises:
            InitError: If device could not be initialized.
        """
        if self.rs232_init is False:
            # INIT, wait a little, then IDLE
            log.info("Initializing telescope...")
            await self._change_motion_status(MotionStatus.INITIALIZING)
            
            log.info("Initiate Celestron communication")
            try:
                self.ser = serial.Serial(self.USB_HUB, baudrate=9600, timeout=self.rs232_timeout, parity = serial.PARITY_NONE, stopbits = serial.STOPBITS_ONE)
                log.info("Got serial RS-232 connection!")
            except:
                log.error("InitError: RS232 Connection to CELESTRON CGEM not possible, shutdown programm !!!")
                await self._change_motion_status(MotionStatus.ERROR)
                sys.exit("InitError: RS232 Connection to CELESTRON CGEM not possible, shutdown programm !!!")
                
            log.info("Name of serial connection: {}".format(self.ser.name))
            
            await self.ReadClean()
            await self.StartConfig()
            await self.QuickAlign()
            
            
            await asyncio.sleep(5)
            await self._change_motion_status(MotionStatus.IDLE)
            self.rs232_init = True
            log.info("Telescope initialized.")
        else:
            await self._change_motion_status(MotionStatus.IDLE)
            log.warning("Telescope already initialized, just setting status of telescope to initialized again instead ...")
     
    
    async def ReadClean(self, **kwargs: Any) -> None:
        '''
            Clean RS232 reading input.
        '''
        
        loop = True
        while loop == True:
            try:
                data = self.ser.readline()
            except:
                await self._change_motion_status(MotionStatus.ERROR)
                sys.exit("RS232 connection error to CELESTRON CGEM!")
            
            if len(data) == 0:
                loop = False
    
    
    async def StartConfig(self, **kwargs: Any) -> None:
        '''
            Bring the telescope into the start configuration for further usage.
        '''
        
        try:
            with open(self.START_CONFIG_COMMANDS, 'r') as f:
                file = json.load(f)
        except:
            await self._change_motion_status(MotionStatus.ERROR)
            log.error("could not open initialization file.")
            
        keys = file.keys()
        for key in keys:
            data = await self.RS232_Talk(file[key])

        f.close()
    
    
    async def QuickAlign(self, **kwargs: Any) -> None:
        '''
            Start quick alignment of the telescope.
        '''
        try:
            with open(self.QUICK_ALIGN_COMMANDS, 'r') as f:
                file = json.load(f)
        except:
            log.error("could not open quick align file.")
            
        keys = file.keys()
        for key in keys:
            data = await self.RS232_Talk(file[key])

        f.close() 

    
    ### TODO maybe also add a start pose reset ..? 
    ### doesnt it need abort event?
    @timeout(60)
    async def park(self, **kwargs: Any) -> None:
        """Park telescope, set telescope back to starting position, hence mot1 = 90 degree and mot2 = 90 degree.

        Raises:
            ParkError: If telescope could not be parked.
        """

        # PARK, wait a little, then PARKED
        self.GOTO_RUNNING = True
        log.info("Parking telescope...")
        place_holder_event = asyncio.Event()
        await self._change_motion_status(MotionStatus.PARKING)
        await self.__move(self.park_mot1, self.park_mot2, place_holder_event)
        await asyncio.sleep(5)
        await self._change_motion_status(MotionStatus.PARKED)
        log.info("Telescope parked.")

        
    async def set_offsets_radec(self, dra: float, ddec: float, **kwargs: Any) -> None:
        """Move an RA/Dec offset.

        Args:
            dra: RA offset in degrees.
            ddec: Dec offset in degrees.

        Raises:
            MoveError: If telescope cannot be moved.
        """

        log.info("Moving offset dra=%.5f, ddec=%.5f", dra, ddec)
        await self.comm.send_event(OffsetsRaDecEvent(ra=dra, dec=ddec))
        self._telescope.set_offsets(dra, ddec)

        
    async def get_offsets_radec(self, **kwargs: Any) -> Tuple[float, float]:
        """Get RA/Dec offset.

        Returns:
            Tuple with RA and Dec offsets.
        """
        return self._telescope.offsets

    
    async def get_radec(self, **kwargs: Any) -> Tuple[float, float]:
        """Returns current RA and Dec.

        Returns:
            Tuple of current RA and Dec in degrees.
        """
        if self.rs232_init is True:
            mot1 = await self.GET_MOT1()
            mot2 = await self.GET_MOT2()
            #self.time_now = datetime.now(datetime.UTC)
            self.time_now = datetime.utcnow()
            observation_time = Time(self.time_now, scale='utc', location=self.observing_location)
            lst = observation_time.sidereal_time(kind = "apparent", longitude = self.angleToDecimal(self.longitude) * u.deg)
            lst = lst.hour

            mot2 = (mot2 + 90.0) % 360.0
            if mot2 >= 180.0 and mot2 < 360.0:
                sign = 1.0
                dec = 270.0 - mot2
            elif mot2 >= 0.0 and mot2 < 180.0:
                sign = -1.0
                dec = mot2 - 90.0
            else:
                log.info("somehing went wrong here! in GET_RADEC!!! Number MOT2 out of range")
            
            if sign >= 0:
                ra = -mot1/15.0
            else:
                ra = (180-mot1)/15.0
                
            ra += lst
            ra = ra % 24.0
            
            ### TODO is this float necessary?
            self.ra = float(ra)
            self.dec = (dec)
        
        return self.ra * 15.0, self.dec # because intern pyobs uses degrees and this uses hours angles >:
    
    ### TODO find out how to GET alt az from RA DEC
    async def get_altaz(self, **kwargs: Any) -> Tuple[float, float]:
        """Returns current Alt and Az.

        Returns:
            Tuple of current Alt and Az in degrees.
        """
        #if self.rs232_init is True:
        #    ra, dec = await self.get_radec()
        #    
        #    ####################################
        #    ### alt/az coordinates to ra/dec ###
        #    coords = SkyCoord(
        #        ra=ra * u.degree, dec=dec * u.degree, obstime=Time.now(), location=self.location, frame="radec"
        #    )
        #    icrs = coords.icrs
        #    ####################################
        #    ####################################
        #    
        #    self.az = icrs.az.degree
        #    self.alt = icrs.alt.degree
        self.az = 0.0
        self.alt = 0.0
        
        return self.alt, self.az
    
    
    async def GET_MOT1(self) -> float:
        '''
            Get the angle of motor1.
        '''
        data = await self.RS232_Talk(self.GET_MOT1_COMMAND)
        if len(data) == 4:
            log.info("MOT1 data is: {}, {}, {}: {}".format(data[0], data[1], data[2], len(data)))
            h1 = hex(data[0])[2:]
            h2 = hex(data[1])[2:]
            h3 = hex(data[2])[2:]
    
            if len(h1) < 2:
                h1 = "0" + h1
            if len(h2) < 2:
                h2 = "0" + h2
            if len(h3) < 2:
                h3 = "0" + h3
        
            self.mot1 = self.decodeAngle(h1, h2, h3)
        else:
            log.warning("RS232 reading feed incorrect answer in GET_MOT1, use last read answer instead")

        return self.mot1

    
    async def GET_MOT2(self) -> float:
        '''
            Get the angle of motor2.
        '''
        data = await self.RS232_Talk(self.GET_MOT2_COMMAND)
        if len(data) == 4:
            log.info("MOT2 data is: {}, {}, {}: {}".format(data[0], data[1], data[2], len(data)))
            h1 = hex(data[0])[2:]
            h2 = hex(data[1])[2:]
            h3 = hex(data[2])[2:]
            
            if len(h1) < 2:
                h1 = "0" + h1
            if len(h2) < 2:
                h2 = "0" + h2
            if len(h3) < 2:
                h3 = "0" + h3
            
            self.mot2 = self.decodeAngle(h1, h2, h3)
        else:
            log.warning("RS232 reading feed incorrect answer in GET_MOT2, use last read answer instead")
        return self.mot2

    
    async def stop_motion(self, device: Optional[str] = None, **kwargs: Any) -> None:
        """Stop the motion.

        Args:
            device: Name of device to stop, or None for all.
        """

        await self._change_motion_status(MotionStatus.ABORTING)
        
        ### STOP GOTO COMMAND ###
        self.GOTO_IN_STOP = True
        data = await self.RS232_Talk(self.GOTO_STOP)
        log.info(data)
        
        ### set motion of motor1 to zero ###
        await self.MOTION_MOT1(self, level = 0)
        ### set motion of motor2 to zero ###
        await self.MOTION_MOT2(self, level = 0)

        ### STOP TRACKING ###
        await self.stop_tracking() 
        await self._change_motion_status(MotionStatus.IDLE)

        
        
    ### TODO add tracking and save tracking rate somewhere
    ### TODO after using __move again, tracking is still on but MotionStatus will be off ...
    async def tracking(self, rate_mot1, rate_mot2, **kwargs: Any) -> None:
        """
            configure a constant tracking motion for an object to correct motion caused by the earth rotation,
            solarsystem, vision correction or empirical estimation. 
        """
        await self._change_motion_status(MotionStatus.TRACKING)
        self.tracking_rate_mot1 = rate_mot1
        self.tracking_rate_mot2 = rate_mot2

        sign_mot1 = np.sign(rate_mot1)
        sign_mot2 = np.sign(rate_mot2)

        rate_mot1 = np.abs(rate_mot1)
        rate_mot2 = np.abs(rate_mot2)

        encode_rate_mot1 = rate_mot1 * 4 
        h1_mot1 = encode_rate_mot1 // 256
        tmp = encode_rate_mot1 - h1_mot1 * 256
        h2_mot1 = int(tmp)
        
        encode_rate_mot2 = rate_mot2 * 4 
        h1_mot2 = encode_rate_mot2 // 256
        tmp = encode_rate_mot2 - h1_mot2 * 256
        h2_mot2 = int(tmp)

        ### hex representation mot1
        h1_mot1 = hex(h1_mot1)[2:]
        h2_mot1 = hex(h2_mot1)[2:]

        if len(h1_mot1) < 2:
            h1_mot1 = "0" + h1_mot1
        if len(h2_mot1) < 2:
            h2_mot1 = "0" + h2_mot1

        ### hex representation mot2
        h1_mot2 = hex(h1_mot2)[2:]  
        h2_mot2 = hex(h2_mot2)[2:]

        if len(h1_mot2) < 2:
            h1_mot2 = "0" + h1_mot2
        if len(h2_mot2) < 2:
            h2_mot2 = "0" + h2_mot2

        if sign_mot1 >= 0:
            MOT1_TRACKING_COMMAND = self.POS_MOT1_TRACKING + h1_mot1 + h2_mot1 + self.TRACKING_END_SEQUENCE
        else:
            MOT1_TRACKING_COMMAND = self.NEG_MOT1_TRACKING + h1_mot1 + h2_mot1 + self.TRACKING_END_SEQUENCE

        if sign_mot2 >= 0:
            MOT2_TRACKING_COMMAND = self.POS_MOT2_TRACKING + h1_mot2 + h2_mot2 + self.TRACKING_END_SEQUENCE
        else:
            MOT2_TRACKING_COMMAND = self.NEG_MOT2_TRACKING + h1_mot2 + h2_mot2 + self.TRACKING_END_SEQUENCE

        data = await self.RS232_Talk(MOT1_TRACKING_COMMAND)
        data = await self.RS232_Talk(MOT2_TRACKING_COMMAND)
        log.info(data)

        
    ### TOTO add stop tracking
    ### after using --> idle, but can also be still positioned??
    async def stop_tracking(self, **kwargs: Any) -> None:
        """
            turn off the constant tracking motion for any object.
            Turn of tracking by setting rotation rate to zero ...
        """

        self.tracking_rate_mot1 = 0.0
        self.tracking_rate_mot2 = 0.0

        MOT1_TRACKING_COMMAND = self.POS_MOT1_TRACKING + self.TRACKING_STOP + self.TRACKING_END_SEQUENCE
        MOT2_TRACKING_COMMAND = self.POS_MOT2_TRACKING + self.TRACKING_STOP + self.TRACKING_END_SEQUENCE

        data = await self.RS232_Talk(MOT1_TRACKING_COMMAND)
        log.info(data)
        data = await self.RS232_Talk(MOT2_TRACKING_COMMAND)
        log.info(data)
        await self.change_motion_status(MotionStatus.IDLE)
    
    
    # ## TODO WHAT IS THIS FOR??!
    # async def get_fits_header_before(self, namespaces: Optional[List[str]] = None, **kwargs: Any) -> Dict[str, Tuple[Any, str]]:
    #     """Returns FITS header for the current status of this module.
    
    #     Args:
    #         namespaces: If given, only return FITS headers for the given namespaces.

    #     Returns:
    #         Dictionary containing FITS headers.
    #     """

    #     # fetch from BaseTelescope
    #     hdr = await BaseTelescope.get_fits_header_before(self)

    #     # focus
    #     hdr["TEL-FOCU"] = (self._telescope.focus, "Focus position [mm]")

    #     # finished
    #     return self._filter_fits_namespace(hdr, namespaces=namespaces, **kwargs)
    
    
    ### TODO WHAT IS THIS USEFUL FOR?
    async def is_ready(self, **kwargs: Any) -> bool:
        log.error("Not implemented")
        return True
    

    ### TODO test if return data from telescope makes sense, otherwise clear read input, tryagain, or disconnect telescope 
    def testData(self, data: str) -> bool:
        pass
        
        
    ### TODO can ser.close give back a boolean value?
    def ReleaseRS232Connection(self, **kwargs: Any) -> None:
        
        log.info("Try to release RS232-communication")
        self.ser.close()
        log.info("Done releasing RS232-communication")
        
    
    ###########################################################################
    ############## Simple Conversion and calculation functions ################
    ###########################################################################
        
    
    def hourToAngle(self, hour, minute, second):
        hour = hour % 24
        minute = minute % 60
        second = second % 60
        hour = hour + minute * (1/60) + second * (1/3600)
        angle = (hour/24) * 360
        return angle

    def AngleToHour(self, alpha):
        alpha = (alpha / 360) * 24
        hour = int(alpha % 24)
        rest = alpha % 24 - hour
        minute = int(rest * 60)
        rest = rest * 60 - minute
        second = int(rest * 60)
        return hour, minute, second
    
    def timeToHour(self, hour, minute, second):
    
        hour = hour%24
        minute = minute%60
        second = second%60
        return hour + minute * (1/60) + second * (1/3600)
    
    def angleToDecimal(self, angle_tuple):
    
        degree = angle_tuple[0]%360
        minute = angle_tuple[1]%60
        second = angle_tuple[2]%60
        return degree + minute * (1/60) + second * (1/3600)

    def HourAngle(self, LST, RA):
        hourDiff = (LST-RA) % 24
        if hourDiff > 12:
            hourDiff = -24 + hourDiff
    
        convertAngle = hourDiff * 15    
        return convertAngle
    
    ###########################################################################
    ########## Close the serial connection when stopping processes ############
    ###########################################################################
    
    ### TODO make sure this makes also sense in PyObs.
    async def __del__(self):
        
        self.RUNNING = False
        await self.ReleaseRS232Connection()
        log.info("Cutted RS232-communication and closing this instance now")


__all__ = ["piggybackTelescope"]
