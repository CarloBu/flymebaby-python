from flask import Flask, request, jsonify, Response, redirect
from datetime import datetime, timedelta
from ryanair import Ryanair
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


app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        RotatingFileHandler('api.log', maxBytes=100000, backupCount=3),
        logging.StreamHandler()
    ],
    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
)



# Replace print statements with logging
logger = logging.getLogger(__name__)

            # "origins": [
            #     "http://localhost:4321",
            #     "http://192.168.1.149:4321",
            #     "http://127.0.0.1:4321"
            # ],
# Enable CORS with specific settings
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

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Add a redirect for the old path
@app.route('/search-flights', methods=['GET', 'OPTIONS'])
def redirect_search():
    return redirect(f"/api{request.full_path}", code=307)

def validate_date_format(date_str):
    try:
        return bool(datetime.strptime(date_str, '%Y-%m-%d'))
    except ValueError:
        return False

def validate_airport_code(code):
    return bool(re.match(r'^[A-Z]{3}$', code))

def format_flight_data(trip, total_passengers):
    """Format flight data in a more readable structure"""
    formatted_data = {
        'outbound': {
            'origin': {
                'code': trip.origin,
                'name': trip.originFull
            },
            'destination': {
                'code': trip.destination,
                'name': trip.destinationFull
            },
            'departure': {
                'datetime': trip.departureTime.isoformat(),
                'formatted': trip.departureTime.strftime("%d %b %Y %H:%M")
            }
        },
        'inbound': None,  # Will be populated for return flights
        'price': {
            'perPerson': trip.price,
            'total': trip.price * total_passengers,
            'formatted': f"€{(trip.price * total_passengers):.2f}"
        }
    }
    return formatted_data

def format_return_flight_data(trip, total_passengers):
    """Format return flight data in a more readable structure"""
    formatted_data = {
        'outbound': {
            'origin': {
                'code': trip.outbound.origin,
                'name': trip.outbound.originFull
            },
            'destination': {
                'code': trip.outbound.destination,
                'name': trip.outbound.destinationFull
            },
            'departure': {
                'datetime': trip.outbound.departureTime.isoformat(),
                'formatted': trip.outbound.departureTime.strftime("%d %b %Y %H:%M")
            }
        },
        'inbound': {
            'origin': {
                'code': trip.inbound.origin,
                'name': trip.inbound.originFull
            },
            'destination': {
                'code': trip.inbound.destination,
                'name': trip.inbound.destinationFull
            },
            'departure': {
                'datetime': trip.inbound.departureTime.isoformat(),
                'formatted': trip.inbound.departureTime.strftime("%d %b %Y %H:%M")
            }
        },
        'price': {
            'perPerson': trip.totalPrice,
            'total': trip.totalPrice * total_passengers,
            'formatted': f"€{(trip.totalPrice * total_passengers):.2f}"
        }
    }
    return formatted_data

@app.route('/api/search-flights', methods=['GET', 'OPTIONS'])
@limiter.limit("30 per minute")
def search_flights():
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
            children = int(request.args.get('children', 0))
            
            if max_price < 0 or adults < 1 or children < 0:
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
            'children': request.args.get('children')
        }

        required_fields = ['tripType', 'startDate', 'maxPrice', 'originAirports', 'wantedCountries', 'adults', 'children']
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
        
        total_passengers = int(data['adults']) + int(data['children'])
        maximum_price = float(data['maxPrice']) / total_passengers  # Price per person

        # Now print the processed parameters
        logger.info(f"Search request received: {data}")
        logger.info(f"Search parameters after processing:")
        logger.info(f"Start date: {start_date}")
        logger.info(f"End date: {end_date}")
        logger.info(f"Maximum price per person: {maximum_price}")
        logger.info(f"Origin airports: {origin_codes}")
        logger.info(f"Wanted countries: {wanted_countries}")
        logger.info(f"Total passengers: {total_passengers}")

        api = Ryanair("EUR")
        
        def generate_results():
            if data['tripType'] == 'oneWay':
                seen_flights = set()
                current_date = start_date
                while current_date <= end_date:
                    for origin_code in origin_codes:
                        try:
                            trips = api.get_cheapest_flights(
                                origin_code,
                                current_date,
                                current_date + timedelta(days=1)
                            )

                            filtered_trips = [
                                trip for trip in trips 
                                if trip.price <= maximum_price 
                                and any(country in trip.destinationFull for country in wanted_countries)
                            ]

                            for trip in sorted(filtered_trips, key=lambda x: x.price):
                                flight_id = f"{trip.origin}-{trip.destination}-{trip.departureTime.isoformat()}"
                                
                                if flight_id in seen_flights:
                                    continue
                                    
                                seen_flights.add(flight_id)
                                
                                time.sleep(0.01)
                                flight_json = format_flight_data(trip, total_passengers)
                                yield f"data: {json.dumps(flight_json)}\n\n"
                        except Exception as e:
                            logger.error(f"Error fetching flights for {origin_code}: {str(e)}", exc_info=True)
                            continue
                    current_date += timedelta(days=1)
            else:
                # Return flight logic
                current_date = start_date
                while current_date <= end_date:
                    for origin_code in origin_codes:
                        try:
                            trips = api.get_cheapest_return_flights(
                                origin_code,
                                current_date,
                                current_date,
                                current_date + timedelta(days=min_days),
                                current_date + timedelta(days=max_days)
                            )
                            
                            filtered_trips = [
                                trip for trip in trips 
                                if trip.totalPrice <= maximum_price 
                                and any(country in trip.outbound.destinationFull for country in wanted_countries)
                            ]
                            
                            for trip in sorted(filtered_trips, key=lambda x: x.totalPrice):
                                time.sleep(0.01)
                                flight_json = format_return_flight_data(trip, total_passengers)
                                yield f"data: {json.dumps(flight_json)}\n\n"
                        except Exception as e:
                            logger.error(f"Error fetching flights for {origin_code}: {str(e)}", exc_info=True)
                            continue
                    current_date += timedelta(days=1)
            
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