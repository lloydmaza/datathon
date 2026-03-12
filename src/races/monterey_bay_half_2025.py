from connectors.sve_timing import SVETimingConnector


class MontereyBayHalf2025(SVETimingConnector):
    race_key     = "monterey_bay_half_2025"
    display_name = "2025 Monterey Bay Half Marathon"
    distance_m   = 21_082
    search_url   = "https://results.svetiming.com/Big-Sur/events/2025/monterey-bay-half-marathon/search"
