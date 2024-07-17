
from astropy import units as u

def to_signed_degrees_and_minutes(angle):
    # Ensure the input is an astropy quantity in degrees
    angle = angle.to(u.deg)
    
    # Extract the value in degrees
    degrees = angle.value
    
    # Determine the sign
    sign = '-' if degrees < 0 else '+'
    
    # Absolute value for calculation
    abs_degrees = abs(degrees)
    
    # Get the degrees and the remaining fraction
    d = int(abs_degrees)
    m = (abs_degrees - d) * 60
    
    # Format the string

    return f"{sign}{d:02d}*{int(m):02d}"


print(to_signed_degrees_and_minutes((306* u.deg)))