"""Helper functions for displaying information about a starmade entity"""

import math

def thrust_rating(thrust, total_mass):
    """ Calculate a 0%-100% thrust rating for a ship

    Given the thrust and mass of a ship, give it a rating between 0% and 100%.

    Args:
        thrust: A float that represents the thrust of a ship. See calc_thrust()
        total_mass: The total mass of the ship

    Returns:
        A float between 0.0 and 1.0 for how good the thrust of a ship is.
    """
    thrust_gauge = 0
    if thrust <= total_mass:
        thrust_gauge = thrust / total_mass * 0.5
    else:
        thrust_gauge = 1 - total_mass / thrust

    return thrust_gauge

def shield_rating(shield, max_shield):
    if shield < 1:
       return 0
    else:
       gauge_lowend = math.sin((shield/max_shield)*math.pi/2)
       gauge_highend = math.log(shield)/math.log(max_shield)
       return (gauge_lowend+gauge_highend)/2.0

def valid_power(power):
    try:
        power = float(power)
        if math.isnan(power) or math.isinf(power) or 0 < power > 99999999999:
            return 0;
        return power
    except ValueError:
        return 0
