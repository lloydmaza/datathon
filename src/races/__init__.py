from races.la_marathon_2026 import LAMarathon2026
from races.la_marathon_2025 import LAMarathon2025
from races.sf_marathon_2025 import SFMarathon2025
from races.sf_1st_half_2025 import SF1stHalf2025
from races.sf_2nd_half_2025 import SF2ndHalf2025
from races.monterey_bay_half_2025 import MontereyBayHalf2025

REGISTRY: dict[str, type] = {
    "la_marathon_2026":       LAMarathon2026,
    "la_marathon_2025":       LAMarathon2025,
    "sf_marathon_2025":       SFMarathon2025,
    "sf_1st_half_2025":       SF1stHalf2025,
    "sf_2nd_half_2025":       SF2ndHalf2025,
    "monterey_bay_half_2025": MontereyBayHalf2025,
}
