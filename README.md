# Sun2 Sensor

Creates sensors that provide information about various sun related events.

Follow the installation instructions below.
Then add the desired configuration. Here is an example of a typical configuration:
```yaml
sensor:
  - platform: sun2
    monitored_conditions:
      - sunrise
      - sunset
      - sun_phase
binary_sensor:
  - platform: sun2
    monitored_conditions:
      - elevation
```

## Installation
### With HACS
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

You can use HACS to manage the installation and provide update notifications.

1. Add this repo as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/):

```text
https://github.com/pnbruckner/ha-sun2
```

2. Install the integration using the appropriate button on the HACS Integrations page. Search for "sun2".

### Manual

Place a copy of:

[`__init__.py`](custom_components/sun2/__init__.py) at `<config>/custom_components/sun2/__init__.py`  
[`binary_sensor.py`](custom_components/sun2/binary_sensor.py) at `<config>/custom_components/sun2/binary_sensor.py`  
[`helpers.py`](custom_components/sun2/helpers.py) at `<config>/custom_components/sun2/helpers.py`  
[`sensor.py`](custom_components/sun2/sensor.py) at `<config>/custom_components/sun2/sensor.py`  
[`manifest.json`](custom_components/sun2/manifest.json) at `<config>/custom_components/sun2/manifest.json`

where `<config>` is your Home Assistant configuration directory.

>__NOTE__: Do not download the file by using the link above directly. Rather, click on it, then on the page that comes up use the `Raw` button.

### Versions

This custom integration supports HomeAssistant versions 2021.12 or newer, using Python 3.9 or newer.

## Sensors
### Configuration variables

- **`monitored_conditions`**: A list of sensor types to create. One or more of the following:

#### Point in Time Sensors
type | description
-|-
`solar_midnight` | The time when the sun is at its lowest point closest to 00:00:00 of the specified date; i.e. it may be a time that is on the previous day.
`astronomical_dawn` | The time in the morning when the sun is 18 degrees below the horizon.
`nautical_dawn` | The time in the morning when the sun is 12 degrees below the horizon.
`dawn` | The time in the morning when the sun is 6 degrees below the horizon.
`sunrise` | The time in the morning when the sun is 0.833 degrees below the horizon. This is to account for refraction.
`solar_noon` | The time when the sun is at its highest point.
`sunset` | The time in the evening when the sun is 0.833 degrees below the horizon. This is to account for refraction.
`dusk` | The time in the evening when the sun is a 6 degrees below the horizon.
`nautical_dusk` | The time in the evening when the sun is a 12 degrees below the horizon.
`astronomical_dusk` | The time in the evening when the sun is a 18 degrees below the horizon.

#### Length of Time Sensors (in hours)
type | description
-|-
`daylight` | The amount of time between sunrise and sunset.
`civil_daylight` | The amount of time between dawn and dusk.
`nautical_daylight` | The amount of time between nautical dawn and nautical dusk.
`astronomical_daylight` | The amount of time between astronomical dawn and astronomical dusk.
`night` | The amount of time between sunset and sunrise of the next day.
`civil_night` | The amount of time between dusk and dawn of the next day.
`nautical_night` | The amount of time between nautical dusk and nautical dawn of the next day.
`astronomical_night` | The amount of time between astronomical dusk and astronomical dawn of the next day.

#### Other Sensors
type | description
-|-
`elevation` | The sun's elevation (degrees).
`min_elevation` | The sun's elevation at solar midnight (degrees).
`max_elevation` | The sun's elevation at solar noon (degrees).
`deconz_daylight` | Emulation of [deCONZ Daylight Sensor](https://www.home-assistant.io/integrations/deconz/#deconz-daylight-sensor). Entity is `sensor.deconz_daylight` instead of `sensor.daylight`.
`sun_phase` | See [Sun Phase Sensor](#phase-sensor)

##### Sun Phase Sensor

###### Possible states
state | description
-|-
`Night` | Sun is below -18°
`Astronomical Twilight` | Sun is between -18° and -12°
`Nautical Twilight` | Sun is between -12° and -6°
`Civil Twilight` | Sun is between -6° and -0.833°
`Day` | Sun is above -0.833°

###### Attributes
attribute | description
-|-
`rising` | `True` if sun is rising.
`blue_hour` | `True` if sun is between -6° and -4°
`golden_hour` | `True` if sun is between -4° and 6°

## Binary Sensors
### Configuration variables

- **`monitored_conditions`**: A list of sensor types to create. One or more of the following:

#### `elevation`

`'on'` when sun's elevation is above threshold, `'off'` when at or below threshold. Can be specified in any of the following ways:

```yaml
elevation

elevation: THRESHOLD

elevation:
  above: THRESHOLD
  name: FRIENDLY_NAME
```

Default THRESHOLD (as with first format) is -0.833 (same as sunrise/sunset).

Default FRIENDLY_NAME is "Above Horizon" if THRESHOLD is -0.833, "Above minus THRESHOLD" if THRESHOLD is negative, otherwise "Above THRESHOLD".

`entity_id` will therefore be, for example, `binary_sensor.above_horizon` (-0.833), or `binary_sensor.above_minus_5_0` (-5) or `binary_sensor.above_10_5` (10.5).

## Optional Location

The following configuration parameters are optional, and can be used with all types of sensors. All four parameters are required, and should be specified once per platform entry. These can be used to create sensors that show sun data for another (or even multiple) location(s.) The default is to use Home Assistant's location configuration.

### Configuration variables

type | description
-|-
`latitude` | The location's latitude (in degrees.)
`longitude` | The location's longitude (in degrees.)
`time_zone` | The location's time zone. (See the "TZ database name" column at http://en.wikipedia.org/wiki/List_of_tz_database_time_zones.)
`elevation` | The location's elevation above sea level (in meters.)

## Entity Namespace

When using the optional [`entity_namespace`](https://www.home-assistant.io/docs/configuration/platform_options/#entity-namespace) configuration parameter, not only will this affect Entity IDs, but it will also be used in creating the entity's `friendly_name`. E.g., in the configuration show below, the sunrise and sunset entities for London will be named "London Sunrise" and "London Sunset".

## Example Full Configuration

```yaml
sensor:
  - platform: sun2
    monitored_conditions:
      - solar_midnight
      - astronomical_dawn
      - nautical_dawn
      - dawn
      - sunrise
      - solar_noon
      - sunset
      - dusk
      - nautical_dusk
      - astronomical_dusk
      - daylight
      - civil_daylight
      - nautical_daylight
      - astronomical_daylight
      - night
      - civil_night
      - nautical_night
      - astronomical_night
      - elevation
      - min_elevation
      - max_elevation
      - sun_phase
      - deconz_daylight
  - platform: sun2
    entity_namespace: London
    latitude: 51.50739529645933
    longitude: -0.12767666584664272
    time_zone: Europe/London
    elevation: 11
    monitored_conditions:
      - sunrise
      - sunset
binary_sensor:
  - platform: sun2
    monitored_conditions:
      - elevation
      - elevation: 3
      - elevation:
          above: -6
          name: Above Civil Dawn
```
