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

See [HACS](https://github.com/custom-components/hacs), especially the **Add custom repositories** section on [this page](https://custom-components.github.io/hacs/usage/settings/).

### Manual

Alternatively, place a copy of:

[`__init__.py`](custom_components/sun2/__init__.py) at `<config>/custom_components/sun2/__init__.py`  
[`sensor.py`](custom_components/sun2/sensor.py) at `<config>/custom_components/sun2/sensor.py`  
[`manifest.json`](custom_components/sun2/manifest.json) at `<config>/custom_components/sun2/manifest.json`

where `<config>` is your Home Assistant configuration directory.

>__NOTE__: Do not download the file by using the link above directly. Rather, click on it, then on the page that comes up use the `Raw` button.

## Configuration variables

- **`monitored_conditions`**: A list of sensor types to create. One or more of the following:

type | description
-|-
`dawn` | The time in the morning when the sun is 6 degrees below the horizon.
`daylight` | The amount of time between sunrise and sunset, in hours.
`dusk` | The time in the evening when the sun is a 6 degrees below the horizon.
`night` | The amount of time between astronomical dusk and astronomical dawn of the next day, in hours.
`solar_noon` | The time when the sun is at its highest point.
`sunrise` | The time in the morning when the sun is 0.833 degrees below the horizon. This is to account for refraction.
`sunset` | The time in the evening when the sun is 0.833 degrees below the horizon. This is to account for refraction.

## Example Full Configuration

```yaml
sensor:
  - platform: sun2
    monitored_conditions:
      - dawn
      - daylight
      - dusk
      - night
      - solar_noon
      - sunrise
      - sunset
```
