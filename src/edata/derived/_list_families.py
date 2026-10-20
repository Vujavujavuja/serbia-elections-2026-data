"""Which list on one ballot continues which list on another. A judgment, written by hand
from the list names (coalitions change names and partners between elections); used only to
ask "did this station already vote this way last time?". Lists with no counterpart are left
out on purpose. Keys: RIK round id -> {ballot number: family}.
"""
FAMILIES = {
    "341140": {  # parliamentary, 17 Dec 2023
        1: "SNS", 2: "SPS", 3: "SRS", 4: "ZAVETNICI_DVERI", 5: "NADA", 6: "VMSZ", 7: "OPPOSITION_SPN",
        8: "ZUKORLIC", 9: "SDA", 10: "BUDUCNOST_RAZVOJ", 11: "NARODNA_STRANKA", 12: "DJB_SDS",
        13: "ALBANIAN", 14: "MI_GLAS", 15: "SRBIJA_NA_ZAPADU", 16: "RUSSIAN", 17: "LDP", 18: "ALBANIAN",
    },
    "341143": {  # Vojvodina provincial, same day
        1: "SNS", 2: "SPS", 3: "SRS", 4: "RUSSIAN", 5: "NADA", 6: "VMSZ", 7: "OPPOSITION_SPN",
        8: "ZUKORLIC", 9: "LDP", 10: "NARODNA_STRANKA", 11: "ZAVETNICI_DVERI", 12: "DJB_SDS",
    },
    "680072": {  # parliamentary, 25 Oct 2026
        1: "SNS", 2: "SPS", 5: "VMSZ", 6: "ZUKORLIC", 7: "RUSSIAN", 8: "NADA", 9: "OPPOSITION_SPN",
        10: "SDA", 13: "BUDUCNOST_RAZVOJ", 16: "NARODNA_STRANKA", 17: "ALBANIAN",
    },
}
# Which earlier round to compare each round with, through derived/station_links.
PREVIOUS = {"680072": "341140", "341140": "341143"}
