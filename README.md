# Flymebaby Python Backend

A Flask backend that powers the gimme.flights flight search application. This service provides real-time flight data through Server-Sent Events (SSE), enabling instant flight deal discovery. The core flight search functionality is powered by the [ryanair-py](https://github.com/cohaolain/ryanair-py) library.

## Disclaimer

This application is not affiliated, endorsed, or sponsored by Ryanair or any of its affiliates. All trademarks related to Ryanair and its affiliates are owned by the relevant companies. This application uses the `ryanair-py` library to interact with Ryanair's API for finding flights, which are ultimately purchased via Ryanair's website.

## Features

- Real-time flight data streaming using Server-Sent Events (SSE)
- Smart weekend trip detection and validation
- Flexible search modes:
  - One-way flights
  - Return flights
  - Weekend trips (Fri-Sun)
  - Long weekend trips (Thu-Mon)
- Multi-airport and multi-country support
- Dynamic price per passenger calculation
- Automatic flight deduplication
- Rate limiting for API protection
- CORS support for frontend integration
- Error handling and logging

## Technical Stack

- **Framework**: Flask
- **Language**: Python 3.x
- **Key Dependencies**:
  - `ryanair-py`: Core flight search functionality
  - `flask-cors`: Cross-origin resource sharing
  - `flask-limiter`: API rate limiting
  - `logging`: Rotating file logs

## API Documentation

### Main Endpoint

`GET /api/search-flights`

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| tripType | string | "oneWay", "return", "weekend", or "longWeekend" |
| startDate | string | Departure date (YYYY-MM-DD) |
| endDate | string | Return date (YYYY-MM-DD) - Required for return trips |
| maxPrice | number | Maximum total budget |
| minDays | number | Minimum trip duration (return trips) |
| maxDays | number | Maximum trip duration (return trips) |
| originAirports | string | Comma-separated airport codes (e.g., "KUN,VNO") |
| wantedCountries | string | Comma-separated country names |
| adults | number | Number of adult passengers |
| teens | number | Number of teen passengers |
| children | number | Number of child passengers |
| infants | number | Number of infant passengers |

### Rate Limits

The API implements the following rate limits per IP address:
- 400 requests per day
- 100 requests per hour
- 30 requests per minute

#### Response Format

Server-Sent Events stream with JSON payloads:

```json
{
  "outbound": {
    "origin": "DUB",
    "originFull": "Dublin",
    "destination": "BCN",
    "destinationFull": "Barcelona",
    "departureTime": "2024-03-15T06:30:00"
  },
  "inbound": {
    "origin": "BCN",
    "originFull": "Barcelona",
    "destination": "DUB",
    "destinationFull": "Dublin",
    "departureTime": "2024-03-17T10:15:00"
  },
  "totalPrice": 69.420
}
```

Each event represents a potential flight combination that matches the search criteria. The response includes:
- Full names for origin and destination airports with their countries
- Precise departure times in ISO 8601 format
- Total price for all passengers combined

## Status Events

The API sends special status events in certain cases:

```json
{
  "type": "NO_FLIGHTS",
  "message": "No flights found matching your criteria"
}
```

And a final event to indicate the end of the stream:

```
END
```

## Progress Updates

The API continuously streams results as they are found, with a small delay (10ms) between each flight for no good reason except it makes the frontend look more busy :p The results are automatically sorted by price and deduplicated to ensure unique flight combinations.

## Acknowledgments

This project is built upon the excellent work of [@cohaolain](https://github.com/cohaolain) and his [ryanair-py](https://github.com/cohaolain/ryanair-py) library, which provides the core functionality for interacting with the Ryanair API.
