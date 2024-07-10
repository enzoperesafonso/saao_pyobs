from astropy.coordinates import EarthLocation
from astropy.time import Time
from astropy import units as u
from datetime import datetime, timezone
import serial
import numpy as np
import os
import timeit
import json
import sys
from threading import Lock, Event

class TelescopeComm():
    
    ### Threading ###
    lock = Lock() # make sure two threads write on same variable
    event = Event() # wait until new step in queue goes forward
    event.clear()
    
    ### Constants ###
    timeout = 0.25
    latitude = 51.559315 # Göttingen altitude
    longitude = 9.945265 # Göttingen longitude
    height = 200 # Göttingen average height
    
    ### Variables ###
    motion_level = 0 # Motion has 10 levels: 0-9, 0 being no motion and 9 being fast motion.
    tracking_rate = 0.0 # Tracking speed in arcsec/sec
    
    ### coordinates
    az = 0.0
    alt = 0.0
    ra = 0.0
    dec = 0.0
    mot1 = 90.0
    mot2 = 90.0
    
    ### Decision tree ###
    GOTO_IN_STOP = False
    GOTO_RUNNING = False
    RUNNING = True
    RS232_QUEUE = []
    identity = 0
    
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
    TRACKING_RUN = ""
    TRACKING_STOP = ""
    
    ##### FEEDBACK #####
    GET_MOT1_COMMAND = "5001100100000003"
    GET_MOT2_COMMAND = "5001110100000003"
    
        
    def __init__(self, USB_HUB = 'COM3', latitude = (51, 32, 3.95), longitude = (9, 55, 56.21), height = 200):
        '''
            Initialize Telescope RS-232 connection for the CELESTRON CGEM. 
            Give USB_HUB or connection input and output of the USB/PIN Cable. Windows USB hub standard is COM.
            Give global observing position in latitude and altitude from Greenwich as tuples of "(degree, minutes, seconds)". 
            And give height of observation over the sea level.
            The standard settings are for an observation in Göttingen
        '''
        self.latitude = latitude
        self.longitude = longitude
        self.height = height
        self.observing_location = EarthLocation(lat = self.angleToDecimal(self.latitude) * u.deg, lon = self.angleToDecimal(self.longitude) * u.deg, height = self.height)
        #self.time_now = datetime.now(datetime.UTC)
        self.time_now = datetime.utcnow()
    
        print("Initiate Celestron communication! (with port: ", USB_HUB, ")")
        try:
            self.ser = serial.Serial(USB_HUB, baudrate=9600, timeout=self.timeout, parity = serial.PARITY_NONE, stopbits = serial.STOPBITS_ONE)
        except:
            sys.exit("RS232 Connection to CELESTRON CGEM not possible !!!")
        print(self.ser.name)
        
        self.readClean()
        self.InitTelescope()
        self.QuickAlign()
     
    ### TODO Fix Errors ###
    def RS232_Talk(self, command): 
        
        s = bytes.fromhex(command)
        
        ### go into sending and reading Queue ###
        #print("waiting for Lock")
        self.lock.acquire()
        #print("Got lock")
        try:
            self.identity = (self.identity + 1) % 1000
            my_id = self.identity
            self.RS232_QUEUE.append(my_id)
            
        except:
            print("SOME RESOURCE ACCESS ERROR OCURRED!")
        finally:
            #print("release Lock")
            self.lock.release()
        
        #print(self.RS232_QUEUE)
        self.event.clear()
        while self.RS232_QUEUE.index(my_id) != 0:
            #print("waiting for Event")
            self.event.wait()
            self.event.clear()
            #print("Event happened, keep looping")
            
        self.ser.write(s)
        data = self.ser.readline()
        self.lock.acquire()
        try:
            self.RS232_QUEUE.pop(0)
        except:
            print("SOME RESOURCE ACCESS ERROR OCURRED!")
        finally:
            self.lock.release()

        self.event.set()

        return data
        
    def InitTelescope(self):
        '''
            Bring the telescope into the start configuration for further usage.
        '''
        #print(os.listdir())
        try:
            with open("C:/Users/lennx/Documents/Python Uni/Master/Teleskop/TelescopeClasses/SetupFiles/InitTelescopeFile.json", 'r') as f:
                file = json.load(f)
        except:
            print("could not open initialization file.")
            
        keys = file.keys()
        for key in keys:
            data = self.RS232_Talk(file[key])

        f.close()
        
    def QuickAlign(self):
        '''
            Start quick alignment of the telescope.
        '''
        try:
            with open("C:/Users/lennx/Documents/Python Uni/Master/Teleskop/TelescopeClasses/SetupFiles/QuickAlignTrackFile.json", 'r') as f:
                file = json.load(f)
        except:
            print("could not open quick align file.")
            
        keys = file.keys()
        for key in keys:
            data = self.RS232_Talk(file[key])

        f.close()
        
    def readClean(self):
        '''
            Clean reading input.
        '''
        
        loop = True
        while loop == True:
            try:
                data = self.ser.readline()
            except:
                sys.exit("RS232 connection error to CELESTRON CGEM!")
            
            if len(data) == 0:
                loop = False
                            
    def GOTO_MOT1MOT2(self, angle1, angle2):
        '''
            Move motor1 to angle1 and motor2 to angle2.
        '''
        self.GOTO_RUNNING = True
        self.GOTO_IN_STOP = False
        mot2_fast = self.GOTO_MOT2(angle2, True)
        mot2_slow = self.GOTO_MOT2(angle2, False)
    
        mot1_fast = self.GOTO_MOT1(angle1, True)
        mot1_slow = self.GOTO_MOT1(angle1, False)
    
        data = self.RS232_Talk(mot2_fast) # represent declination
        print(data)
    
        data = self.RS232_Talk(mot1_fast) # represents right ascension
        print(data)
    
        test = False
        ra_running = False
        dec_running = False
        while not test and self.GOTO_IN_STOP == False:
            
            if ra_running is False:
                data = self.RS232_Talk(self.RA_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                print("Stop Bits RA ", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    print("Stopped RA fast")
                    ra_running = True
                else:
                    ra_running = False
            
            if dec_running is False:
                data = self.RS232_Talk(self.DEC_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                print("Stop Bits DEC ", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    print("Stopped DEC fast")
                    dec_running = True
                else:
                    dec_running = False
            
            if dec_running and ra_running:
                test = True
            
        data = self.RS232_Talk(mot2_slow) # represent declination
        print(data)
    
        data = self.RS232_Talk(mot1_slow) # represents right ascension
        print(data)
    
        test = False
        ra_running = False
        dec_running = False
        while not test and self.GOTO_IN_STOP == False:
            
            if ra_running is False:
                data = self.RS232_Talk(self.RA_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                print("Stop Bits DEC RA", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    print("Stopped RA slow")
                    ra_running = True
                else:
                    ra_running = False
            
            if dec_running is False:
                data = self.RS232_Talk(self.DEC_GOTO_RUN)
                h1 = hex(data[0])
                h2 = hex(data[1])
                #print(h1, h2, end="\r")
                print("Stop Bits DEC", h1, h2, self.GOTO_IN_STOP)
                if h1 == hex(255):
                    dec_running = True
                    print("Stopped DEC slow")
                else:
                    dec_running = False
            
            if dec_running and ra_running:
                test = True

        #print(self.GET_RA())
        #print(self.GET_DEC())
        self.GOTO_RUNNING = False
        return 0
    
    
    def STOP_GOTO(self):
        '''
            This function stop the motion of the mount, when the telescope is in a GOTO phase!
        '''
        self.GOTO_IN_STOP = True
        data = self.RS232_Talk(self.GOTO_STOP)
        print(data)

    
    ### TODO test what happens at negative DEC left and right ### Last time it didnt work anymore!!!
    def GOTO_RADEC(self, RA, DEC):
        '''
            Move the telescope to a given RA DEC coordinate.
        '''
        self.GOTO_RUNNING = True
        
        if type(RA) is tuple:
            RA = RA[0] + (1/60) * RA[1] + (1/3600) * RA[2]
        elif type(RA) is float:
            pass
        else:
            print("Type error with RA!")
            
        RA = RA%24.0
        
        if type(DEC) is tuple:
            DEC = DEC[0] + (1/60) * DEC[1] + (1/3600) * DEC[2]
        elif type(DEC) is float:
            pass
        else:
            print("Type error with DEC")
            
        self.ra = RA
        self.dec = DEC
        
        self.time_now = datetime.utcnow()
        observation_time = Time(self.time_now, scale='utc', location=self.observing_location)
        LST = observation_time.sidereal_time(kind = "apparent", longitude = self.angleToDecimal(self.longitude) * u.deg)
        LST = LST.hour
        angle = self.AngleDiff(LST, RA)
        sign = np.sign(angle)
    
        if sign >= 0:
            angle2 = 180 - DEC
        else:
            angle2 = DEC     
        angle2 = angle2 % 360
        
        if sign >= 0:
            angle1 = angle
        else:
            angle1 = angle%180
    
        print("Motor1 goes to: ", angle1, " and Motor2 goes to: ", angle2)
        self.GOTO_MOT1MOT2(angle1, angle2)
        
        
    def GET_RADEC(self):
        '''
            Get the RA and DEC coordinate of the current telescope motor positions.
        '''
        MOT1 = self.GET_MOT1()
        MOT2 = self.GET_MOT2()
        self.time_now = datetime.utcnow()
        observation_time = Time(self.time_now, scale='utc', location=self.observing_location)
        LST = observation_time.sidereal_time(kind = "apparent", longitude = self.angleToDecimal(self.longitude) * u.deg)
        LST = LST.hour

        MOT2 = (MOT2 + 90.0) % 360.0
        if MOT2 >= 180.0 and MOT2 < 360.0:
            sign = 1.0
            DEC = 270.0 - MOT2
        elif MOT2 >= 0.0 and MOT2 < 180.0:
            sign = -1.0
            DEC = MOT2 - 90.0
        else:
            print("somehing went wrong here! in GET_RADEC!!! Number MOT2 out of range")
        
        if sign >= 0:
            RA = -MOT1/15.0
        else:
            RA = (180-MOT1)/15.0
        RA += LST
        RA = RA % 24
        
        ### TODO is this necessary?
        self.ra = (RA)
        self.dec = (DEC)
        print("Telescope RA: ", RA, "and DEC: ", DEC)
        return 0
         
     
    ### Motor 1 represents RA und Azi ###
    def GOTO_MOT1(self, alpha, fast = True):
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
    def GOTO_MOT2(self, alpha, fast = True):
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
    
    def GET_MOT1(self):
        '''
            Get the angle of motor1.
        '''
        data = self.RS232_Talk(self.GET_MOT1_COMMAND)
        h1 = hex(data[0])[2:]
        h2 = hex(data[1])[2:]
        h3 = hex(data[2])[2:]
    
        if len(h1) < 2:
            h1 = "0" + h1
        if len(h2) < 2:
            h2 = "0" + h2
        if len(h3) < 2:
            h3 = "0" + h3
        
        angle = self.decodeAngle(h1, h2, h3)
        return angle

    def GET_MOT2(self):
        '''
            Get the angle of motor2.
        '''
        data = self.RS232_Talk(self.GET_MOT2_COMMAND)
        h1 = hex(data[0])[2:]
        h2 = hex(data[1])[2:]
        h3 = hex(data[2])[2:]
        
        if len(h1) < 2:
            h1 = "0" + h1
        if len(h2) < 2:
            h2 = "0" + h2
        if len(h3) < 2:
            h3 = "0" + h3
        
        angle = self.decodeAngle(h1, h2, h3)
        return angle
    
    def GET_MOT1MOT2(self):
        self.mot1 = self.GET_MOT1()
        self.mot2 = self.GET_MOT2()
        print("Motor1 is at/goesto:", self.mot1, "and Motor2 is at/goesto:", self.mot2)
    
    def encodeAngle(self, alpha):
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
    
    def decodeAngle(self, h1, h2, h3):
        '''
            Decode a Hexadecimal number combination of an angle from communication read.
        '''
        v1 = int(h1, 16)
        v2 = int(h2, 16)
        v3 = int(h3, 16)
        integer = 2**16 * v1 + 2**8 * v2 + v3
        angle = (integer/2**24) * 360 
        return angle
    
        
    def MOTION_MOT1(self, level = None):
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
        data = self.RS232_Talk(command)
        print(data)
        return 0
        
        
    def MOTION_MOT2(self, level = None):
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
        data = self.RS232_Talk(command)
        print(data)
        return 0
        
    
    ### TODO add a function for tracking!
    def TRACKING(self, rate_mot1, rate_mot2):
        '''
            Turn on a consisten motion with rate_mot1 and rate_mot2, to track the sun, the moon, stars or other objects of interest
        '''
        pass
    
    ### TODO add a function to stop tracking motion!
    def STOP_TRACKING(self):
        '''
            STOP tracking motion
        '''
        pass
    
    ### TODO add a function to point at a given azi and alt coordinate!
    def GOTO_AZIALT(self, AZI, ALT):
        
        pass
    
    ### TODO add a function to give the azi and alt coordinates the telescope is looking at! 
    def GET_AZIALT(self):
        
        pass
        
        
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
        second = rest * 60
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

    def AngleDiff(self, LST, RA):
        hourDiff = (LST-RA) % 24
        if hourDiff > 12:
            hourDiff = -24 + hourDiff
    
        convertAngle = hourDiff * 15    
        return convertAngle
    
    ###########################################################################
    ########## Close the serial connection when stopping processes ############
    ###########################################################################
    
    def __del__(self):
        
        self.RUNNING = False
        try:
            self.ser.close()
        except:
            print("Could not close serial connection, probably because it was never open ...")
        finally:
            print("Cutted RS232-communication and closing this instance now")

   