from flask import Flask, request, jsonify, Response, redirect
from datetime import datetime, timedelta
from ryanair.ryanair import Ryanair
from flask_cors import CORS
import json
import time
import traceback
from os import environ
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import re
import logging
from logging.handlers import RotatingFileHandler
from enum import Enum
from typing import Optional
from ryanair.airport_utils import convert_local_to_utc, get_airport_by_iata, load_airports


app = Flask(__name__)

# Setup Flask application with logging configuration
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        RotatingFileHandler('api.log', maxBytes=100000, backupCount=3),
        logging.StreamHandler()
    ],
    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)

logger = logging.getLogger(__name__)

# Configure CORS settings from environment variables
# ALLOWED_ORIGINS should be a comma-separated list of allowed origins
ALLOWED_ORIGINS = environ.get('ALLOWED_ORIGINS', '').split(',')
CORS(app, 
     resources={
         r"/*": {
             "origins": ALLOWED_ORIGINS,
             "methods": ["GET", "OPTIONS"],
             "allow_headers": ["Content-Type"],
             "max_age": 3600
         }
     })

# Configure rate limiting to prevent API abuse
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["400 per day", "100 per hour"]
)

# Validation helper functions
@app.route('/search-flights', methods=['GET', 'OPTIONS'])
def redirect_search():
    return redirect(f"/api{request.full_path}", code=307)

def validate_date_format(date_str):
    """Validate if a string matches YYYY-MM-DD format"""
    try:
        return bool(datetime.strptime(date_str, '%Y-%m-%d'))
    except ValueError:
        return False

def validate_airport_code(code):
    """Validate if a string is a valid 3-letter airport code"""
    return bool(re.match(r'^[A-Z]{3}$', code))

class WeekendMode(Enum):
    DEFAULT = "weekend"
    RELAXED = "longWeekend"

def is_valid_weekend_day(date: datetime, mode: WeekendMode, is_outbound: bool) -> bool:
    """
    Check if a date is valid for weekend travel based on the mode and direction.
    
    Args:
        date: Flight date to check
        mode: WeekendMode (weekend or longWeekend)
        is_outbound: True for departure flights, False for return flights
    
    Returns:
        bool: True if date matches weekend criteria, False otherwise
    """
    weekday = date.weekday()  # Monday is 0, Sunday is 6
    
    if mode == WeekendMode.DEFAULT:  # weekend
        if is_outbound:
            return weekday in [4, 5]  # Friday or Saturday departures
        return weekday in [5, 6]      # Saturday or Sunday returns
    
    elif mode == WeekendMode.RELAXED:  # longWeekend
        if is_outbound:
            return weekday in [3, 4, 5]  # Thursday to Saturday departures
        return weekday in [6, 0]         # Sunday or Monday returns

def is_valid_weekend_trip(outbound_date: datetime, inbound_date: datetime, mode: WeekendMode) -> bool:
    """
    Validate that both flights form a valid weekend trip combination
    
    Args:
        outbound_date: Departure flight date
        inbound_date: Return flight date
        mode: WeekendMode for validation criteria
    
    Returns:
        bool: True if both flights form a valid weekend trip
    """
    return (is_valid_weekend_day(outbound_date, mode, True) and 
            is_valid_weekend_day(inbound_date, mode, False))

def calculate_duration(departure_time: datetime, arrival_time: datetime, origin_airport: str, destination_airport: str) -> int:
    """
    Calculate flight duration in minutes, accounting for timezone differences
    
    Args:
        departure_time: Local departure time
        arrival_time: Local arrival time
        origin_airport: IATA code of departure airport
        destination_airport: IATA code of arrival airport
    
    Returns:
        int: Flight duration in minutes
    """
    # Ensure airports are loaded
    load_airports()
    
    # Convert both times to UTC using the respective airport timezones
    departure_utc = convert_local_to_utc(departure_time.isoformat(), origin_airport)
    arrival_utc = convert_local_to_utc(arrival_time.isoformat(), destination_airport)
    
    # Calculate duration in minutes
    duration = int((arrival_utc - departure_utc).total_seconds() / 60)
    return duration

@app.route('/api/search-flights', methods=['GET', 'OPTIONS'])
@limiter.limit("30 per minute")
def search_flights():
    """
    Main flight search endpoint supporting:
    - One-way flights
    - Return flights
    - Weekend trips
    - Long weekend trips
    
    Returns a server-sent events stream of matching flights
    """
    # Handle preflight requests
    if request.method == 'OPTIONS':
        response = app.make_default_options_response()
        return response

    try:
        # Validate dates
        start_date = request.args.get('startDate')
        end_date = request.args.get('endDate')
        
        if not validate_date_format(start_date) or \
           (end_date and not validate_date_format(end_date)):
            return jsonify({'error': 'Invalid date format'}), 400

        # Validate airport codes
        origin_airports = request.args.get('originAirports', '').split(',')
        if not all(validate_airport_code(code) for code in origin_airports if code):
            return jsonify({'error': 'Invalid airport code'}), 400

        # Validate numeric values
        try:
            max_price = float(request.args.get('maxPrice', 0))
            adults = int(request.args.get('adults', 0))
            teens = int(request.args.get('teens', 0))
            children = int(request.args.get('children', 0))
            
            if max_price < 0 or adults < 1 or teens < 0 or children < 0:
                raise ValueError
        except ValueError:
            return jsonify({'error': 'Invalid numeric values'}), 400

        data = {
            'tripType': request.args.get('tripType'),
            'startDate': request.args.get('startDate'),
            'endDate': request.args.get('endDate'),
            'maxPrice': request.args.get('maxPrice'),
            'minDays': request.args.get('minDays'),
            'maxDays': request.args.get('maxDays'),
            'originAirports': request.args.get('originAirports', '').split(','),
            'wantedCountries': request.args.get('wantedCountries', '').split(','),
            'adults': request.args.get('adults'),
            'teens': request.args.get('teens'),
            'children': request.args.get('children')
        }

        required_fields = ['tripType', 'startDate', 'maxPrice', 'originAirports', 'wantedCountries', 'adults', 'teens', 'children']
        if data.get('tripType') == 'return':
            required_fields.extend(['endDate', 'minDays', 'maxDays'])

        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        # Process dates first
        try:
            start_date = datetime.strptime(data['startDate'], '%Y-%m-%d')
            end_date = datetime.strptime(data['endDate'], '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

        # Process numeric values
        try:
            maximum_price = float(data['maxPrice'])
            min_days = int(data['minDays'])
            max_days = int(data['maxDays'])
        except ValueError:
            return jsonify({'error': 'Invalid numeric value'}), 400

        origin_codes = data['originAirports']
        wanted_countries = data['wantedCountries']

        if not origin_codes or not wanted_countries:
            return jsonify({'error': 'Origin airports and wanted countries cannot be empty'}), 400
        
        total_passengers = int(data['adults']) + int(data['teens']) + int(data['children'])
        maximum_price = float(data['maxPrice'])  # Total price for all passengers

        # Log a single concise line for the search request
        logger.info(f"Search request: {data['tripType']} from {','.join(origin_codes)} to {','.join(wanted_countries)} ({start_date} - {end_date})")

        api = Ryanair("EUR")
        
        def generate_results():
            flights_found = False
            
            if data['tripType'] == 'oneWay':
                seen_flights = set()
                current_date = start_date
                while current_date <= end_date:
                    for origin_code in origin_codes:
                        try:
                            try:
                                trips = api.get_cheapest_flights(
                                    origin_code,
                                    current_date,
                                    current_date + timedelta(days=1),
                                    adult_count=int(data['adults']),
                                    teen_count=int(data['teens']),
                                    child_count=int(data['children'])
                                )
                            except Exception as api_error:
                                logger.error(f"API Error for {origin_code}: {str(api_error)}", exc_info=True)
                                traceback.print_exc()
                                continue

                            if not trips:
                                continue
                            
                            filtered_trips = [
                                trip for trip in trips 
                                if (trip.price * total_passengers) <= maximum_price 
                                and any(country in trip.destinationFull for country in wanted_countries)
                            ]
                            
                            if filtered_trips:
                                flights_found = True
                            
                            for trip in sorted(filtered_trips, key=lambda x: x.price):
                                # Create a unique identifier for the flight
                                flight_id = f"{trip.origin}-{trip.destination}-{trip.departureTime.isoformat()}"
                                
                                # Skip if we've already seen this flight
                                if flight_id in seen_flights:
                                    continue
                                    
                                # Add to seen flights
                                seen_flights.add(flight_id)
                                
                                time.sleep(0.01)
                                flight_json = {
                                    'outbound': {
                                        'origin': trip.origin,
                                        'originFull': trip.originFull,
                                        'destination': trip.destination,
                                        'destinationFull': trip.destinationFull,
                                        'departureTime': trip.departureTime.isoformat(),
                                    },
                                    'inbound': {
                                        'origin': trip.destination,
                                        'originFull': trip.destinationFull,
                                        'destination': trip.origin,
                                        'destinationFull': trip.originFull,
                                        'departureTime': trip.departureTime.isoformat(),
                                    },
                                    'totalPrice': trip.price * total_passengers
                                }
                                logger.info(f"Sending flight: {flight_json}")
                                yield f"data: {json.dumps(flight_json)}\n\n"
                        except Exception as e:
                            logger.error(f"Error fetching flights for {origin_code}: {str(e)}", exc_info=True)
                            traceback.print_exc()
                            continue
                    current_date += timedelta(days=1)
            else:  # return, weekend, or longWeekend flights
                current_date = start_date
                weekend_mode = None
                if data['tripType'] in ['weekend', 'longWeekend']:
                    weekend_mode = WeekendMode(data['tripType'])
                
                # Calculate the latest possible outbound date
                # It should be end_date minus minimum trip duration
                latest_outbound_date = end_date - timedelta(days=min_days)
                
                while current_date <= latest_outbound_date:
                    # Skip non-weekend days for weekend trips
                    if weekend_mode and not is_valid_weekend_day(current_date, weekend_mode, True):
                        current_date += timedelta(days=1)
                        continue

                    for origin_code in origin_codes:
                        try:
                            trips = api.get_cheapest_return_flights(
                                origin_code,
                                current_date,
                                current_date,
                                current_date + timedelta(days=min_days),
                                min(end_date, current_date + timedelta(days=max_days)),
                                adult_count=int(data['adults']),
                                teen_count=int(data['teens']),
                                child_count=int(data['children'])
                            )
                            
                            filtered_trips = [
                                trip for trip in trips 
                                if (trip.totalPrice * total_passengers) <= maximum_price 
                                and any(country in trip.outbound.destinationFull for country in wanted_countries)
                                and (not weekend_mode or 
                                     is_valid_weekend_trip(
                                         trip.outbound.departureTime,
                                         trip.inbound.departureTime,
                                         weekend_mode
                                     ))
                                and trip.inbound.departureTime.date() <= end_date.date()
                            ]
                            
                            if filtered_trips:
                                flights_found = True
                            
                            for trip in sorted(filtered_trips, key=lambda x: x.totalPrice):
                                time.sleep(0.01)
                                flight_json = {
                                    'outbound': {
                                        'origin': trip.outbound.origin,
                                        'originFull': trip.outbound.originFull,
                                        'destination': trip.outbound.destination,
                                        'destinationFull': trip.outbound.destinationFull,
                                        'departureTime': trip.outbound.departureTime.isoformat(),
                                        'arrivalTime': trip.outbound.arrivalTime.isoformat(),
                                        'flightDuration': 0,
                                        #'flightDuration': calculate_duration(trip.outbound.departureTime, trip.outbound.arrivalTime, trip.outbound.origin, trip.outbound.destination),
                                        'flightNumber': trip.outbound.flightNumber,
                                        'price': trip.outbound.price,
                                        'currency': trip.outbound.currency,
                                        'origin': trip.outbound.origin,
                                        'originFull': trip.outbound.originFull,
                                        'destination': trip.outbound.destination,
                                        'destinationFull': trip.outbound.destinationFull,
                                    },
                                    'inbound': {
                                        'origin': trip.inbound.origin,
                                        'originFull': trip.inbound.originFull,
                                        'destination': trip.inbound.destination,
                                        'destinationFull': trip.inbound.destinationFull,
                                        'departureTime': trip.inbound.departureTime.isoformat(),
                                        'arrivalTime': trip.inbound.arrivalTime.isoformat(),
                                        'flightDuration': 0,
                                        #'flightDuration': calculate_duration(trip.inbound.departureTime, trip.inbound.arrivalTime, trip.inbound.origin, trip.inbound.destination),
                                        'flightNumber': trip.inbound.flightNumber,
                                        'price': trip.inbound.price,
                                        'currency': trip.inbound.currency,
                                        'origin': trip.inbound.origin,
                                        'originFull': trip.inbound.originFull,
                                        'destination': trip.inbound.destination,
                                        'destinationFull': trip.inbound.destinationFull,
                                    },
                                    'totalPrice': trip.totalPrice * total_passengers
                                }
                                yield f"data: {json.dumps(flight_json)}\n\n"
                        except Exception as e:
                            logger.error(f"Error fetching flights for {origin_code}: {str(e)}", exc_info=True)
                            continue
                    current_date += timedelta(days=1)
                
                # Move these outside both search loops
                if not flights_found:
                    no_flights_message = {
                        "type": "NO_FLIGHTS",
                        "message": "No flights found matching your criteria"
                    }
                    yield f"data: {json.dumps(no_flights_message)}\n\n"
                
                # Always send end message
                yield "data: END\n\n"

        return Response(
            generate_results(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': request.headers.get('Origin'),
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type'
            }
        )

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'Internal server error',
            'type': type(e).__name__
        }), 500

if __name__ == '__main__':
    # Keep SSL settings only for local development
    if environ.get('FLASK_ENV') == 'development':
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=True,
            threaded=True,
            ssl_context=None
        )
    else:
        # In production, let Gunicorn handle the server
        app.run(host='0.0.0.0') 