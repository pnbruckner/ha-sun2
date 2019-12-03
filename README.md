# Sun2 Sensor

Creates sensors that provide information about various sun related events.

## Installation

Follow either the HACS or manual installation instructions below.
Then add the desired configuration. Here is an example of a typical configuration:
```yaml
sensor:
  - platform: sun2
    monitored_conditions:
      - sunrise
      - sunset
```

### HACS

See [HACS](https://github.com/custom-components/hacs).

### Manual

Alternatively, place a copy of:

[`__init__.py`](custom_components/sun2/__init__.py) at `<config>/custom_components/sun2/__init__.py`  
[`binary_sensor.py`](custom_components/sun2/binary_sensor.py) at `<config>/custom_components/sun2/binary_sensor.py`  
[`helpers.py`](custom_components/sun2/helpers.py) at `<config>/custom_components/sun2/helpers.py`  
[`sensor.py`](custom_components/sun2/sensor.py) at `<config>/custom_components/sun2/sensor.py`  
[`manifest.json`](custom_components/sun2/manifest.json) at `<config>/custom_components/sun2/manifest.json`

where `<config>` is your Home Assistant configuration directory.

>__NOTE__: Do not download the file by using the link above directly. Rather, click on it, then on the page that comes up use the `Raw` button.

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
`max_elevation` | The sun's elevation at solar noon (degrees).

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
      - max_elevation
binary_sensor:
  - platform: sun2
    monitored_conditions:
      - elevation
      - elevation: 3
      - elevation:
          above: -6
          name: Above Civil Dawn
```
