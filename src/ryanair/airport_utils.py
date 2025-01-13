import os
import csv
from typing import Any, Dict
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder
from .types import Airport

AIRPORTS: Dict[str, Airport] = None
tf = TimezoneFinder()

def load_airports():
    global AIRPORTS
    if AIRPORTS is not None:
        return AIRPORTS

    AIRPORTS = {}
    try:
        with open(
            os.path.join(os.path.dirname(__file__), "airports.csv"),
            newline="",
            encoding="utf8",
        ) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                row: dict[str, Any] = row

                iata_code = row["iata_code"]
                location = ",".join((row["iso_region"], row["iso_country"]))
                lat = float(row["latitude_deg"])
                lng = float(row["longitude_deg"])
                
                # Find timezone based on coordinates
                timezone = tf.timezone_at(lat=lat, lng=lng)

                AIRPORTS[iata_code] = Airport(
                    IATA_code=iata_code, 
                    lat=lat, 
                    lng=lng, 
                    location=location,
                    timezone=timezone
                )
    except Exception as e:
        print(f"Error loading airports data: {e}")
    return AIRPORTS

def get_airport_by_iata(iata_code: str):
    """Get airport information by IATA code."""
    global AIRPORTS
    if AIRPORTS is None:
        load_airports()
    return AIRPORTS.get(iata_code)

def convert_local_to_utc(local_time: str, airport_code: str) -> datetime:
    """Convert local time at an airport to UTC time."""
    local_dt = datetime.fromisoformat(local_time)
    airport = get_airport_by_iata(airport_code)
    if not airport or not airport.timezone:
        return local_dt.astimezone(pytz.UTC)
    
    local_tz = pytz.timezone(airport.timezone)
    local_dt = local_tz.localize(local_dt)
    return local_dt.astimezone(pytz.UTC)
