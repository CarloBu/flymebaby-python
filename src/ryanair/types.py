from dataclasses import dataclass
from datetime import datetime


@dataclass
class Airport:
    IATA_code: str
    lat: float
    lng: float
    location: str
    timezone: str = ""  # Timezone string for pytz


@dataclass
class Flight:
    departureTime: datetime
    arrivalTime: datetime
    flightNumber: str
    price: float
    currency: str
    origin: str
    originFull: str
    destination: str
    destinationFull: str


@dataclass
class Trip:
    totalPrice: float
    outbound: Flight
    inbound: Flight
