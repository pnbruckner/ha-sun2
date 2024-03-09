"""Test constants."""

HOME_CONFIG = {"unique_id": "home"}

NY_LOC = {
    "latitude": 40.68954412564642,
    "longitude": -74.04486696480146,
    "elevation": 0,
    "time_zone": "America/New_York",
}
NY_CONFIG = {
    "unique_id": "new_york",
    "location": "Statue of Liberty",
} | NY_LOC

TWINE_LOC = {
    "latitude": 39.50924426436838,
    "longitude": -98.43369506033378,
    "elevation": 10,
    "time_zone": "America/Chicago",
}
TWINE_CONFIG = {
    "unique_id": "twine",
    "location": "World's Largest Ball of Twine",
} | TWINE_LOC

HW_LOC = {
    "latitude": 34.134092337996336,
    "longitude": -118.32154780135669,
    "elevation": 391,
    "time_zone": "America/Los_Angeles",
}
HW_CONFIG = {
    "unique_id": "hollywood",
    "location": "Hollywood Sign",
} | HW_LOC
