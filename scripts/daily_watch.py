#!/usr/bin/env python3
"""Daily watcher: SE Asia -> SFO one-way economy, 2 adults, departing 2027-01-02.

Qualifying = total price for 2 adults <= $1,800 USD ($900 per person).
"""

import time

from fli.models import (
    Airport,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    TripType,
)
from search_utils import search_with_currency

DEPART_DATE = "2027-01-02"
DEST = "SFO"
ORIGINS = ["BKK", "SIN", "KUL", "HAN", "SGN", "CGK"]
TOP_N = 10
TOTAL_THRESHOLD = 1800.0  # USD, total for 2 adults
ADULTS = 2
MAX_RETRIES = 60
RETRY_SLEEP = 0.5


def build_filters(origin_code):
    origin = Airport[origin_code]
    destination = Airport[DEST]
    segments = [
        FlightSegment(
            departure_airport=[[origin, 0]],
            arrival_airport=[[destination, 0]],
            travel_date=DEPART_DATE,
        )
    ]
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=ADULTS),
        flight_segments=segments,
        seat_type=SeatType.ECONOMY,
        stops=MaxStops.ANY,
    )


def search_route(origin_code):
    """Search a route with aggressive retry on the gRPC-13 empty envelope.

    Returns (results, currency, attempts, ok). ok is False only when we
    exhausted all retries without ever getting data.
    """
    filters = build_filters(origin_code)
    for attempt in range(1, MAX_RETRIES + 1):
        results, currency = search_with_currency(filters, top_n=TOP_N)
        if results:
            return results, currency, attempt, True
        time.sleep(RETRY_SLEEP)
    return None, None, MAX_RETRIES, False


def fmt_duration(minutes):
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m"


def booking_url(token):
    if not token:
        return None
    import urllib.parse
    return "https://www.google.com/travel/flights/search?tfs=" + urllib.parse.quote(token)


def describe_flight(flight, token):
    airlines = sorted({leg.airline.name for leg in flight.legs})
    first = flight.legs[0]
    last = flight.legs[-1]
    dep = first.departure_datetime.strftime("%Y-%m-%d %H:%M")
    arr = last.arrival_datetime.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"      airlines: {', '.join(airlines)}",
        f"      depart {first.departure_airport.name} {dep} -> arrive {last.arrival_airport.name} {arr}",
        f"      stops: {flight.stops} | duration: {fmt_duration(flight.duration)}",
    ]
    url = booking_url(token)
    if url:
        lines.append(f"      book: {url}")
    return "\n".join(lines)


def main():
    qualifying = []  # (origin, total, flight, token, currency)
    cheapest_per_route = {}  # origin -> (total, flight, token, currency)
    failures = []  # origins with no data after retries
    nonusd = []  # (origin, currency)

    for origin in ORIGINS:
        print(f"\n{'='*64}\nSearching {origin} -> {DEST} on {DEPART_DATE} (2 adults, economy)...")
        results, currency, attempts, ok = search_route(origin)
        if not ok:
            print(f"  FAILURE: no data after {MAX_RETRIES} retries.")
            failures.append(origin)
            continue
        print(f"  Got data after {attempts} attempt(s). Currency: {currency}. {len(results)} result(s).")

        if currency != "USD":
            print(f"  WARNING: currency is {currency}, not USD. Not treating any of these as a USD match.")
            nonusd.append((origin, currency))

        for flight, token in results:
            if flight is None or flight.price is None:
                continue
            total = float(flight.price)  # price returned is total for the passenger_info given
            if origin not in cheapest_per_route or total < cheapest_per_route[origin][0]:
                cheapest_per_route[origin] = (total, flight, token, currency)
            if currency == "USD" and total <= TOTAL_THRESHOLD:
                qualifying.append((origin, total, flight, token, currency))

    # Build report
    print(f"\n\n{'#'*64}\nREPORT\n{'#'*64}")
    report_lines = []

    if qualifying:
        qualifying.sort(key=lambda x: x[1])
        report_lines.append(
            f"ALERT: {len(qualifying)} SE Asia -> SFO fare(s) at or below "
            f"$1,800 total for 2 adults (departing {DEPART_DATE}, one-way economy):\n"
        )
        for origin, total, flight, token, currency in qualifying:
            per_person = total / ADULTS
            report_lines.append(
                f"  * {origin} -> SFO  |  TOTAL ${total:,.0f} (2 adults)  |  ${per_person:,.0f} per person"
            )
            report_lines.append(describe_flight(flight, token))
            report_lines.append("")
    else:
        report_lines.append(
            f"No SE Asia -> SFO fares at or below $1,800 total (2 adults) today.\n"
        )
        report_lines.append("Cheapest total found per route:")
        for origin in ORIGINS:
            if origin in cheapest_per_route:
                total, flight, token, currency = cheapest_per_route[origin]
                per_person = total / ADULTS
                cur_note = "" if currency == "USD" else f" [{currency}, NOT USD]"
                report_lines.append(
                    f"  * {origin} -> SFO  |  total {total:,.0f} {currency}{cur_note} "
                    f"(2 adults) | {per_person:,.0f}/person"
                )
                report_lines.append(describe_flight(flight, token))
            elif origin in failures:
                report_lines.append(f"  * {origin} -> SFO  |  NO DATA after {MAX_RETRIES} retries (search failed)")
            else:
                report_lines.append(f"  * {origin} -> SFO  |  no priced flights returned")
            report_lines.append("")

    if failures:
        report_lines.append(
            f"NOTE: routes that failed to return data after {MAX_RETRIES} retries: "
            f"{', '.join(failures)}"
        )
    if nonusd:
        report_lines.append(
            "NOTE: non-USD routes (excluded from $ matching): "
            + ", ".join(f"{o}={c}" for o, c in nonusd)
        )

    report = "\n".join(report_lines)
    print(report)
    return qualifying, failures, report


if __name__ == "__main__":
    main()
