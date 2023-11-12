# <img src="https://brands.home-assistant.io/sun2/icon.png" alt="Sun2 Sensor" width="50" height="50"/> Sun2 Sensor

Creates sensors that provide information about various sun related events.

Follow the installation instructions below.
Then add the desired configuration. Here is an example of a typical configuration:
```yaml
sun2:
  - unique_id: home
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

Place a copy of the files from [`custom_components/sun2`](custom_components/sun2)
in `<config>/custom_components/sun2`,
where `<config>` is your Home Assistant configuration directory.

>__NOTE__: When downloading, make sure to use the `Raw` button from each file's page.

### Versions

This custom integration supports HomeAssistant versions 2023.3 or newer.

## Configuration variables

A list of one or more dictionaries with the following options.

Key | Optional | Description
-|-|-
`unique_id` | no | Unique identifier for group of options.
`location` | yes | Name of location. Default is Home Assistant's current location name.
`latitude` | yes* | The location's latitude (in degrees.)
`longitude` | yes* | The location's longitude (in degrees.)
`time_zone` | yes* | The location's time zone. (See the "TZ database name" column at http://en.wikipedia.org/wiki/List_of_tz_database_time_zones.)
`elevation` | yes* | The location's elevation above sea level (in meters.)
`binary_sensors` | yes | Binary sensor configurations as defined [here](#binary-sensor-configurations).
`sensors` | yes | Sensor configurations as defined [here](#sensor-configurations).

\* These must all be used together. If not used, the default is Home Assistant's location configuration.

### Binary Sensor Configurations

A list of one or more of the following.

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

### Sensor Configurations

A list of one or more of the following.

#### Time at Elevation Sensor

Key | Optional | Description
-|-|-
`time_at_elevation` | no | Elevation
`direction` | yes | `rising` (default) or `setting`
`icon` | yes | default is `mdi:weather-sunny`
`name` | yes | default is "DIRECTION at [minus] ELEVATION °"

For example, this:

```yaml
- time_at_elevation: -0.833
```

Would be equivalent to:

```yaml
- time_at_elevation: -0.833
  direction: rising
  icon: mdi:weather-sunny
  name: Rising at minus 0.833 °
```

#### Elevation at Time Sensor

Key | Optional | Description
-|-|-
`elevation_at_time` | no | time string or `input_datetime` entity ID
`name` | yes | default is "Elevation at <value of `elevation_at_time`>"

When using an `input_datetime` entity it must have the time component. The date component is optional.
If the date is not present, the result will be the sun's elevation at the given time on the current date.
If the date is present, it will be used and the result will be the sun's elevation at the given time on the given date.
Also in this case, the `sensor` entity will not have `yesterday`, `today` and `tomorrow` attributes.

## Aditional Sensors

Besides any sensors specified in the configuration, the following will also be created.

### Point in Time Sensors

Some of these will be enabled by default. The rest will be disabled by default.

Type | Enabled | Description
-|-|-
Solar Midnight | yes | The time when the sun is at its lowest point closest to 00:00:00 of the specified date; i.e. it may be a time that is on the previous day.
Astronomical Dawn | no | The time in the morning when the sun is 18 degrees below the horizon.
Nautical Dawn | no | The time in the morning when the sun is 12 degrees below the horizon.
Dawn | yes | The time in the morning when the sun is 6 degrees below the horizon.
Rising | yes | The time in the morning when the sun is 0.833 degrees below the horizon. This is to account for refraction.
Solar Noon | yes | The time when the sun is at its highest point.
Setting | yes | The time in the evening when the sun is 0.833 degrees below the horizon. This is to account for refraction.
Dusk | yes | The time in the evening when the sun is a 6 degrees below the horizon.
Nautical Dusk | no | The time in the evening when the sun is a 12 degrees below the horizon.
Astronomical Dusk | no | The time in the evening when the sun is a 18 degrees below the horizon.

### Length of Time Sensors (in hours)

These are all disabled by default.

Type | Description
-|-
Daylight | The amount of time between sunrise and sunset.
Civil Daylight | The amount of time between dawn and dusk.
Nautical Daylight | The amount of time between nautical dawn and nautical dusk.
Astronomical Daylight | The amount of time between astronomical dawn and astronomical dusk.
Night | The amount of time between sunset and sunrise of the next day.
Civil Night | The amount of time between dusk and dawn of the next day.
Nautical Night | The amount of time between nautical dusk and nautical dawn of the next day.
Astronomical Night | The amount of time between astronomical dusk and astronomical dawn of the next day.

### Other Sensors

These are also all disabled by default.

Type | Description
-|-
Azimuth | The sun's azimuth (degrees).
Elevation | The sun's elevation (degrees).
Minimum Elevation | The sun's elevation at solar midnight (degrees).
maximum Elevation | The sun's elevation at solar noon (degrees).
deCONZ Daylight | Emulation of [deCONZ Daylight Sensor](https://www.home-assistant.io/integrations/deconz/#deconz-daylight-sensor).
Phase | See [Sun Phase Sensor](#sun-phase-sensor)

##### Sun Phase Sensor

###### Possible states

State | Description
-|-
Night | Sun is below -18°
Astronomical Twilight | Sun is between -18° and -12°
Nautical Twilight | Sun is between -12° and -6°
Civil Twilight | Sun is between -6° and -0.833°
Day | Sun is above -0.833°

###### Attributes

Attribute | Description
-|-
`rising` | `True` if sun is rising.
`blue_hour` | `True` if sun is between -6° and -4°
`golden_hour` | `True` if sun is between -4° and 6°

## Example Full Configuration

```yaml
sun2:
  - unique_id: home
    binary_sensors:
      - elevation
      - elevation: 3
      - elevation:
          above: -6
          name: Above Civil Dawn
    sensors:
      - time_at_elevation: 10
      - time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
      - elevation_at_time: '12:00'
        name: Elv @ noon
      - elevation_at_time: input_datetime.test
        name: Elv @ test var

  - unique_id: london
    location: London
    latitude: 51.50739529645933
    longitude: -0.12767666584664272
    time_zone: Europe/London
    elevation: 11
    binary_sensors:
      - elevation
      - elevation: 3
      - elevation:
          above: -6
          name: Above Civil Dawn
    sensors:
      - time_at_elevation: 10
      - time_at_elevation: -10
        direction: setting
        icon: mdi:weather-sunset-down
        name: Setting past 10 deg below horizon
      - elevation_at_time: '12:00'
        name: Elv @ noon
      - elevation_at_time: input_datetime.test
        name: Elv @ test var
```
